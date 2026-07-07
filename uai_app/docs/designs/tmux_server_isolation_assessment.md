# Tmux Server Isolation Assessment

**Date:** 2026-05-14  
**Reviewer:** Codex (assessment only — no implementation)  
**Scope:** tmux server isolation per AI_ROOT context using `tmux -L "$(basename $AI_ROOT)"`

## Executive summary

This change is **feasible**, but it is not a one-line substrate tweak.

The core substrate file is the right center of gravity, but there are three important complications:

1. **`get_substrate()` currently selects only substrate type, not server identity.**  
   There is no way to say “tmux, but server X.”

2. **`session_store.py` and `broadcast.py` bypass the substrate and hardcode default-server tmux calls.**  
   Those will silently misclassify or miss sessions once production and devTree sessions live on different tmux servers.

3. **The shared session store does not persist tmux server identity.**  
   Once multiple tmux servers exist, `terminal_session` alone is not enough to know which server to query during resume, attach, liveness checks, or broadcasts.

If this is implemented, the minimum safe design is:
- add a tmux server concept to the substrate layer,
- persist `tmux_server` per session,
- make all direct tmux calls server-aware,
- and make cross-session/global code (especially `session_store.py` and `broadcast.py`) query **all relevant tmux servers**, not just the current AI_ROOT's server.

---

## Proposed naming rule

Requested convention:
- production: `tmux -L ai_root`
- devTree: `tmux -L AI_ROOT_uai-resurrection`

This is workable.

### Caveats
- It assumes `basename(AI_ROOT)` is stable enough to be the server identity.
- It can collide if two different roots share the same basename.
- It should be sanitized once in code rather than trusting arbitrary path basenames forever.

I would keep the requested basename rule as the default, but still normalize it through one helper.

---

## Cross-cutting findings

## 1. `get_substrate()` does not accept a tmux server name

Current signature:
- `lib_session_substrate.py:935-971`

It only accepts:
- `override`
- `config_path`

It returns `cls()` with no tmux-server context at all.

### Assessment
This is the first thing that must change.

### Recommended shape
Something like:
- `get_substrate(override=None, config_path=None, tmux_server_name=None)`

And for tmux specifically:
- `TmuxSubstrate(tmux_bin=None, server_name=None)`

Then every tmux command becomes either:
- `[tmux, "-L", server_name, ...]`
- or `[tmux, ...]` when no server name is set (legacy/default behavior)

## 2. There is no existing tmux-server env var or config field

I found:
- no `TMUX_SERVER_NAME`
- no `tmux_server`
- no `tmux -L ...` usage in the live code path

What does exist:
- `_SUBSTRATE_CONFIG_PATH` at `lib_session_substrate.py:911-914`
- but it is hardcoded to the **production ai_root path**, not the current AI_ROOT context

That means even the existing substrate config is effectively global, not per-context.

### Recommendation
Introduce one explicit driver variable, for example:
- `TMUX_SERVER_NAME`

or, better aligned with existing naming:
- `AI_TMUX_SERVER`

Then:
- `ai_launcher.py` derives it from `basename(AI_ROOT)`
- `build_launch_env()` exports it into launched sessions
- `get_substrate()` uses it when no explicit server name is passed

Important: **resume/attach operations should prefer the persisted per-session value over the current process env**.

## 3. The session store does not persist tmux server identity

Current schema only stores:
- `substrate` (`session_store.py:136-144`)

It does **not** store which tmux server the session belongs to.

### Should it?
**Yes.**

Without a `tmux_server` field, once multiple tmux servers exist:
- resume can hit the wrong server,
- liveness reconciliation can mark healthy sessions as stopped,
- attach/read/write can query the wrong tmux universe,
- and global tools cannot enumerate all tmux-backed sessions correctly.

### Minimum recommendation
Add a nullable `tmux_server` field to the sessions table.

Use it when:
- creating a tmux-backed session,
- resuming a tmux-backed session,
- reconciling liveness,
- broadcasting globally,
- attaching/reading/writing by session identity.

### Migration concern
Legacy rows will have no `tmux_server`. Those should temporarily mean:
- “use the legacy/default tmux server”

until migrated.

## 4. `new-session` definitely needs `-L`

Yes.

Creating the session on the right server happens at:
- `lib_session_substrate.py:304-309`

If `new-session` does not get `-L`, the whole isolation model fails at creation time.

But creation is not enough — **every** later tmux operation for that session must use the same `-L`.

---

## File-by-file assessment

## 1) `lib_session_substrate.py`

### Tmux invocation lines
These are the actual tmux command sites in `TmuxSubstrate`:

- `263` — resolves tmux binary (`_require_binary("tmux")`) [not an invocation, but part of tmux setup]
- `304-309` — `new-session`
- `311` — `set-option mouse on`
- `317` — `set-option assume-paste-time 0`
- `320-323` — `bind-key WheelUpPane ...`
- `327-330` — `bind-key` for copy-mode mouse handling
- `334-337` — `unbind-key` copy-mode drag bindings
- `348-349` — `list-panes`
- `361` — `has-session`
- `372` — `kill-session`
- `378-379` — `list-sessions`
- `415` — `send-keys Enter`
- `427` — `display-message #{pane_in_mode}`
- `432` — `send-keys -X cancel`
- `448` — `load-buffer`
- `455-457` — `paste-buffer`
- `483` — `send-keys -l`
- `491-494` — `capture-pane`
- `507` — `display-message #{session_name}`
- `516` — `attach-session`

Related selection/config lines:
- `911-914` — substrate config path is globally anchored to production ai_root
- `935-971` — `get_substrate()` has no server-name parameter and returns `cls()` blindly

### Uses substrate abstraction or hardcoded tmux?
This file **is** the substrate abstraction. That is good.

### Specific change needed
1. Add tmux server state to `TmuxSubstrate` itself.
2. Add a helper that prepends `-L <server_name>` to **every** tmux command.
3. Extend `get_substrate()` so callers can pass a server name.
4. Add env/config fallback resolution for tmux server name.
5. Revisit `_SUBSTRATE_CONFIG_PATH`: it is currently global to production and cannot represent per-AI_ROOT config cleanly.

### Risks / edge cases
- If even one tmux call site misses `-L`, behavior becomes partially cross-contaminated and very hard to debug.
- `TMUX` env in an attached shell can silently steer tmux calls to the current server; explicit `-L` is the only safe way to target another one.
- `get_current_session_name()` (`500-511`) currently relies on tmux without any server-awareness. That may be fine for “current attached client” semantics, but it should be reviewed carefully if cross-context tooling ever runs inside one tmux server while targeting another.

---

## 2) `session_store.py`

### Tmux invocation lines
Direct hardcoded tmux subprocess calls:
- `425-426` — `tmux list-sessions -F #{session_name}` inside `_get_live_terminal_sessions()`
- `988-989` — `tmux list-sessions -F #{session_name}` inside the reconciliation path

Schema line relevant to server identity:
- `142` — stores `substrate`, but not `tmux_server`

### Uses substrate abstraction or hardcoded tmux?
**Hardcoded tmux.** It bypasses the substrate entirely.

This also directly violates `session_mgmt/DESIGN.md`, which says tmux/zellij calls should not happen outside the substrate.

### Specific change needed
1. Add a `tmux_server` field to the sessions table.
2. Change liveness/reconciliation logic to query tmux **per server**, not once globally.
3. Preferably route tmux enumeration through substrate-aware helpers rather than raw `subprocess.run(["tmux", ...])`.
4. Change live-session data structures from just `set[str]` session names to something like:
   - `(tmux_server, session_name)` pairs, or
   - `dict[tmux_server, set[session_name]]`

### Risks / edge cases
- This file is **central**. If it only queries the current/default tmux server, all sessions on other servers will look dead.
- Right now it assumes session names are enough. With multiple tmux servers, the true identity for liveness is at least:
  - substrate
  - tmux_server
  - terminal_session
- If `tmux_server` is not persisted, background maintenance/reconciliation run from production ai_root cannot correctly assess devTree sessions.
- Legacy rows need fallback behavior, or the migration will falsely stop everything.

---

## 3) `session_ops.py`

### Tmux invocation lines
Via substrate:
- `295` — `get_substrate()` in `list_sessions()`
- `317` — `get_substrate()` in `read_terminal()`
- `456` — `get_substrate()` in `write_to()`
- `492` — `get_substrate()` in `discover_uuid()`
- `663` — `get_substrate()` in CLI `attach`

Direct hardcoded tmux subprocess:
- `546` — `tmux send-keys -t <session> Escape` in `_send_escape()`

### Uses substrate abstraction or hardcoded tmux?
Mostly **uses the substrate abstraction**, except `_send_escape()`, which hardcodes both zellij and tmux.

### Specific change needed
1. Add tmux server propagation through the public `session_ops` API, not just substrate override.
   - likely new optional param such as `tmux_server_name`
2. Update CLI arguments for relevant commands if manual override is needed.
3. Replace `_send_escape()`’s raw tmux call with a substrate method, or at minimum make it server-aware.

### Risks / edge cases
- `discover_uuid()` depends on `_send_escape()` after `/status`; if that call hits the wrong tmux server, overlays remain on-screen and later parsing gets noisy.
- `list_sessions()` and `read_terminal()` currently only know substrate type, not server identity. After isolation, “list sessions” must be clearly defined as either:
  - current context's server only, or
  - an explicitly named server.
- If callers keep using `get_substrate()` implicitly with no server parameter, the code will appear to work in some interactive shells and fail in background/electron contexts.

---

## 4) `ai_launcher.py`

### Tmux invocation lines
No raw tmux subprocess calls in this file.

Substrate-based call sites:
- `1189` — dry-run reports substrate name via `get_substrate()`
- `1201` — resume path obtains substrate
- `1290` — fork path checks name collision via substrate
- `1373` — fork dry-run obtains substrate name
- `1405` — fork path creates session via substrate
- `1481` — new-session collision check via substrate
- `1548` — new-session dry-run obtains substrate name
- `1581` — new-session path creates session via substrate

Also relevant env construction:
- `120-134` — `build_launch_env()` currently exports no tmux-server variable

### Uses substrate abstraction or hardcoded tmux?
**Uses substrate abstraction only.** That is good.

### Specific change needed
1. Add a single helper to derive tmux server name from current AI_ROOT context.
2. Export that into launch env (`build_launch_env()`), so child processes inherit it.
3. Pass the server name to every `get_substrate()` call.
4. Persist `tmux_server` when writing session records.
5. In **resume paths**, do **not** derive from current AI_ROOT if the session already has a stored `tmux_server`; use the stored value.

### Risks / edge cases
- **Resume is the critical case.** The app may be running in production ai_root while resuming a devTree session. If launcher code derives server name from current AI_ROOT instead of the session record, it will target the wrong tmux server.
- Dry-run output should include server name or debugging this later will be miserable.
- `build_launch_env()` is the cleanest place to introduce an env override like `TMUX_SERVER_NAME` / `AI_TMUX_SERVER`.

---

## 5) `broadcast.py`

### Tmux invocation lines
Direct hardcoded tmux call:
- `54-55` — `tmux list-sessions -F #{session_name}`

### Uses substrate abstraction or hardcoded tmux?
**Hardcoded tmux.** No substrate abstraction here.

### Specific change needed
This file needs a design decision first:

### Option A — global broadcast stays global
Then `broadcast.py` must enumerate **all tmux servers in use**, not just the current/default one.
That likely means:
- read sessions from store,
- collect distinct `tmux_server` values for tmux-backed sessions,
- union `list-sessions` across each server.

### Option B — broadcast becomes context-local
Then it should explicitly target only the current AI_ROOT's tmux server.

Given existing semantics (“all active sessions across the ecosystem”), **Option A** is more consistent.

### Risks / edge cases
- If left unchanged, broadcast will silently miss every session on non-default tmux servers.
- This is not just a local bug; it changes system-wide coordination semantics.
- If two servers both have a session with the same name, current enrichment by session name alone is ambiguous.

---

## 6) `lib_agent_ops.py`

### Tmux invocation lines
No raw tmux subprocess calls.

Indirect substrate / session enumeration call sites:
- `68` — `_get_substrate()` returns `get_substrate()` with no server parameter
- `138` — `test_server()` instantiates substrate
- `166` — `get_terminal_sessions()` calls `session_ops.list_sessions()`
- `185` — `get_session_info()` calls `session_ops.list_sessions()`
- `284` — `capture_pane_output()` calls `session_ops.read_terminal()`
- `300` — `session_exists()` calls `session_ops.list_sessions()`

### Uses substrate abstraction or hardcoded tmux?
No direct tmux, but it is **implicitly tied to current/default server selection** because all the lower-level calls are server-unaware.

### Specific change needed
1. `_get_substrate()` needs a way to pass server name, or callers need to stop using it directly for anything session-specific.
2. `get_session_info()` / `session_exists()` should prefer deriving the tmux server from the resolved registry entry when available.
3. `get_terminal_sessions()` needs explicit semantics: current-context server only, or all known servers.

### Risks / edge cases
- Today it will silently under-report once sessions are split across tmux servers.
- Since this is agent/control-plane code, “session not found” failures here may look like orchestration bugs rather than tmux-scope bugs.

---

## Recommended design changes

## 1. Add tmux server identity to the substrate API

Recommended direction:
- `TmuxSubstrate(server_name: str | None = None)`
- `get_substrate(..., tmux_server_name: str | None = None)`

And centralize tmux command construction in one helper so `-L` cannot be forgotten.

## 2. Add `tmux_server` to session persistence

Recommended minimum:
- sessions table field: `tmux_server TEXT NULL`

Persist it on create/fork/resume for tmux-backed sessions.

Why it matters:
- shared session store spans production + devTrees
- AI_ROOT at runtime is not always the same context as the session being operated on
- current-context derivation is not enough for resume, reconciliation, or global broadcast

## 3. Add an env override for child processes

Suggested env var:
- `AI_TMUX_SERVER`

or if you want a more generic name:
- `TMUX_SERVER_NAME`

Populate it in `ai_launcher.build_launch_env()`.
Then `get_substrate()` can use:
1. explicit parameter
2. env var
3. config
4. legacy default

## 4. Make the substrate config path context-aware if you keep config-driven server selection

Current path:
- `lib_session_substrate.py:913`
- hardcoded to `~/Documents/AI/ai_root/...`

That cannot represent separate devTree contexts cleanly.

If config is used for tmux server selection, it should be AI_ROOT-relative, not globally anchored to production.

## 5. Fix direct tmux bypasses before shipping isolation

At minimum:
- `session_store.py` — both `list-sessions` calls
- `session_ops.py` — `_send_escape()`
- `broadcast.py` — `list-sessions`

If those remain unchanged, server isolation will be only partially implemented and will fail in non-obvious ways.

---

## Suggested migration / rollout concerns

## 1. Legacy sessions on the default server

Existing sessions were created without `-L`.
So after rollout you need a compatibility story:
- legacy rows with `tmux_server = NULL` mean “default/legacy server”
- new rows get explicit `tmux_server`

## 2. Cross-server liveness reconciliation

`session_store.py` must not assume one tmux world.
It should query liveness per server and compare against `(tmux_server, session_name)`.

## 3. Debuggability

Once isolation is introduced, every relevant status/dry-run/log output should surface:
- substrate
- tmux_server
- terminal_session

Without that, diagnosis becomes guesswork.

## 4. Basename collisions

Using `basename(AI_ROOT)` is okay as requested, but it is only safe if basenames are unique.
If not, two contexts can land on the same tmux server name.

That is probably acceptable as a documented assumption, but it should be called out.

---

## Bottom line

**Yes, do it — but treat it as a substrate + persistence + liveness change, not just a `tmux -L` flag patch.**

The key implementation requirement is this:

> once tmux servers are isolated by AI_ROOT, any code that wants to find, attach, read, write, or reconcile a session must know not just “tmux” but “which tmux server.”

Today the codebase does not model that.

So the safe implementation order is:
1. extend substrate API with tmux-server awareness,
2. persist `tmux_server` in session store,
3. eliminate direct raw tmux calls or make them server-aware,
4. update launch/resume code to pass the correct server name,
5. only then rely on isolated tmux servers in production.
