# deferred_self_compact.py — redevelopment design

**File:** `src/uai_toolkit/jsonl/deferred_self_compact.py` (410 lines; CLI + library)
**Read at:** 2026-08-01. Packaged copy differs from the live source only in import
rewrites (`:29-32`, `:64`, `:168`, `:234`) — but two of those rewrites left behind
**stale path constants**; see §5.

## Terms used here

- **One-shot** — a scheduled task that fires once and removes itself. Implemented on macOS
  with `launchd` via `scheduled_task_mgr.py once --remove`.
- **Tracking id** — a session's primary identifier, `YYYYMMDD_HHMMSS_<uuid8>_<plat3>`.
- **Session state** — a per-session JSON document holding context percentage, compaction
  flags, and thresholds.
- **Idle** — the session is not mid-turn, per `activity_state.json` and a live re-check.
- **Self-compact** — the session writes (or has a subagent write) a brief of its own
  conversation, then runs `/compact`.
- **Fire** — one execution of this script by its one-shot timer.

## 1. What it is for

This is the **arming and firing mechanism for the self-compact rung**. When a session
crosses its context threshold, the Stop hook arms a one-shot timer. On each fire this
script decides exactly one of three outcomes:

- **STOP** — nothing to do (a compact is already in flight this cycle, the session dropped
  below threshold, or the session is gone).
- **RESCHEDULE** — the session is still over threshold but not idle enough: arm another
  one-shot in five minutes.
- **TRIGGER** — over threshold **and** idle ≥ 5 minutes **and** verifiably idle at send
  time: deliver `/self-compact` to the session as a submitted prompt, then stop.

It also owns the reconciliation the Stop hook calls on every response
(`reconcile_from_stop`) and an orphan sweep (`sweep_orphans`).

It does **not** parse JSONL, does not compact anything, and does not write to a
transcript.

## 2. Where this sits on the reclaim ladder

Ladder: offload < bounce < summarize < **self-compact** < compact. Full description in
`lib_engram_design.md` §2. This file's own usage text (`:268-270`) states the position and
the two properties that distinguish this rung:

1. **It is the terminal, lossy rung.** A self-compact is a whole-context summary with **no
   bring-back**. There is no archive, no stub, no rehydrate. Everything not in the brief is
   gone from the session's view. It is the last resort *after* the lossless and reversible
   rungs have been exhausted.
2. **It is the only deliberate, model-facing prompt in the entire ladder.** Every other
   rung is silent disk surgery a session need never notice. This one hands the model an
   instruction and asks it to act. The reason is structural and is stated at `:15`: *a
   hook or script cannot run an AI.* Compaction requires a model in the loop, so the
   mechanism has to be a delivered prompt.

Because of (2), it carries a gate the other rungs do not need: **fail-closed on
idleness.** Interrupting a working session to make it summarize itself is the worst
possible time to do it, so delivery is refused unless the session is provably idle twice —
once from recorded state, once live immediately before the send.

## 3. Interface

```
deferred_self_compact.py <tracking_id>
deferred_self_compact.py -h | --help
```

**Exit codes** (`:321-406`): `0` for every normal outcome — STOP, RESCHEDULE and TRIGGER
alike — because the plist is one-shot and has already removed itself, so a nonzero exit
would only produce launchd noise. `2` is reachable only from the original usage-error path
(`:327`), which is now unreachable in practice because the `--help`/no-args branch at
`:322` returns 0 first. `--help` returns 0.

**Output**: diagnostics only, on **stderr**, prefixed `[deferred_self_compact]` (`:55-56`).
Nothing is written to stdout except the usage text. There is no JSON output; callers that
need the outcome read the session state instead.

**Library API** (this is how the hooks use it):

| Symbol | Signature | Used by |
|---|---|---|
| `reconcile_from_stop(session_dir, tid, ctx_pct, threshold) -> str` (`:185`) | arms/cancels/re-arms on transitions; returns a short status string for the log | `hooks/handlers/Stop/08_auto_self_compact_sync.py:91` |
| `cancel(tid) -> None` (`:136`) | cancel this session's one-shot | `hooks/handlers/Stop/08_auto_self_compact_sync.py:123` |
| `arm(tid)` (`:148`) | **alias of `_reschedule`** — arming and rescheduling are the same operation because the job id is deterministic and replaces | internal + hooks |
| `sweep_orphans() -> str` (`:151`) | cancel one-shots whose session is gone | `hooks/handlers/SessionStart/02_sweep_deferred_compact_async.py:21` |
| `main() -> int` (`:321`) | the fire body | the one-shot itself |

## 4. Integration

**Who calls it**
- The **launchd one-shot** it schedules for itself (`:126-131`): `python3 <SELF> <tid>`.
- **Stop hook `08_auto_self_compact_sync.py`** — every response, via
  `reconcile_from_stop` and `cancel`.
- **SessionStart hook `02_sweep_deferred_compact_async.py`** — opportunistic orphan sweep.

**What it calls**
- `scheduled_task_mgr.py once --in / --cancel / --list` (`:126`, `:140`, `:158`) — the
  scheduler backend. **Subprocess, by path.**
- `send_prompt.py --endpoint prompt://<target>/<terminal>?submit=true --message /self-compact
  --fb_queue` (`:254-256`) — **subprocess, by path.**
- `SessionStore().resolve(tid)` (`:168`, `:331`) — session identity, `session_dir`,
  `platform`, `terminal_session`, `status`.
- `lib_send_prompt.is_busy_cli(target, terminal, double_check=True)` (`:234`) — the live
  idle re-check.
- `lib_session_state_union.read_union` / `write_session_state` (`:64`) — the canonical
  session-state accessor (cited as todo_0495), with a legacy direct-file fallback
  (`:75-80`).

**Its sibling.** `session_bounce/deferred_offload_bounce.py` is described in its own
docstring as *"the lossless sibling of `deferred_self_compact`"* — same one-shot / idle /
reschedule skeleton, but it realizes an already-staged offload with a bounce instead of
delivering a compact prompt. The two share a shape and share nothing in code. A re-design
should extract the common "idle-gated one-shot with three outcomes" machinery once.

## 5. Data & config

| Artifact | Path | R/W | Notes |
|---|---|---|---|
| Session state | via `read_union(session_dir, tid)`; legacy fallback `<session_dir>/<tid>_state.json` | read + targeted write | keys read: `compact.self`, `compact.self_triggered`, `compact.auto_self_pct`, `context.used_pct`; key written: `compact.deferred` (a dict with `state`, `armed_at`, `triggered_at`) plus `updated_at` |
| Activity state | `<session_dir>/activity_state.json` | read (`:101`) | `{state: "idle"|…, at: <isoformat>}` |
| One-shot log | `$AI_ROOT/ai_general/logs/oneshot/compact_deferred_<tid>.log` (`:123`) | written by the scheduler | |
| Scheduler jobs | `compact_deferred_<tid>` — a **deterministic id** so re-arming replaces rather than duplicating (`:122`) | create/cancel/list | |
| The prompt delivered | the literal string `"/self-compact"` (`:398`) | — | expands to the skill body at `~/.claude/commands/self-compact.md` |

**Environment**: `AI_SCRIPTS` (optional, prepended to `sys.path` at `:29-31`),
and `AI_ROOT` indirectly through `uai_toolkit.paths.AI_ROOT` (`:32`).

### Stale paths — a port defect

Constants at `:34-41` are all computed from `AI_ROOT / "ai_general" / "scripts" / …`:

```python
_SCHED_MGR   = _GEN / "scripts" / "scheduling"   / "scheduled_task_mgr.py"
_SELF        = _GEN / "scripts" / "jsonl"        / "deferred_self_compact.py"
_SEND_PROMPT = _GEN / "scripts" / "prompting"    / "send_prompt.py"
_PROMPT_FILE = _GEN / "ai_context_files" / "instructions" / "how_tos" / "instr_operational_handoff.md"
```

These point at the **live source tree layout**, not at the installed package. On a machine
where the toolkit was installed with `pipx` and `AI_ROOT` holds only config, logs and
memories (per `DESIGN.md` decision 1), none of these paths exist:

- `_SEND_PROMPT.exists()` is checked (`:248`) so delivery fails cleanly with
  `"send_prompt.py missing"` — the whole rung silently never fires.
- `_SCHED_MGR` is **not** checked; `subprocess.run` raises `FileNotFoundError`, which is
  caught (`:132`, `:142`, `:161`) and logged — so arming silently never happens.
- `_SELF` is embedded in the scheduled command line, so even a successfully armed timer
  would invoke a path that does not exist.
- `_PROMPT_FILE` (`:41`) is **never used** — dead since the instruction body moved into the
  `/self-compact` skill (`:241-244`).

Same class of defect as `summarizer.SHADOW_LOG`: a source-tree-relative constant that
survived materialization unchanged. Related: `_bridge()` (`:59-66`) computes
`Path(__file__).parents[2] / "data" / "hooks" / "common"` — in the package that is
`src/data/hooks/common`, which does not exist — but the import beneath it was rewritten to
the absolute `uai_toolkit.hooks.common.lib_session_state_union`, so the `sys.path` insert
is merely vestigial rather than broken.

## 6. How it works

### 6.1 Arming — `reconcile_from_stop` (`:185-226`)

Called by the Stop hook on **every response**, so it must be cheap and must not churn the
scheduler. It touches launchd **only on transitions** (`:189`):

- `ctx_pct >= threshold`:
  - already `armed` ⇒ return, do nothing;
  - `triggered` ⇒ leave it, **unless it clearly never took**: no compact in flight and the
    trigger was delivered more than 10 minutes ago ⇒ re-arm (`:201-216`);
  - otherwise ⇒ arm once.
- below threshold and `armed` ⇒ cancel and clear.

Threshold comes from `compact.auto_self_pct` in session state, default 85 (`:48`, `:359`).

### 6.2 Firing — `main` (`:321-406`)

1. Resolve the tracking id through `SessionStore`. Unresolvable, missing, or no
   `session_dir` ⇒ STOP with exit 0 (`:330-342`).
2. **STOP if a compact is already in flight this cycle** (`:354`) — checked via the
   *cycle flags* `compact.self` / `compact.self_triggered`, deliberately **not** by
   looking for a brief file, so a stale brief from a previous cycle is not mistaken for a
   fresh one (`:350-353`, credited to a Codex review).
3. STOP if `context.used_pct` is missing or below threshold (`:369`).
4. STOP if the session's status is `exited`/`ended`/`archived`/`deleted` (`:374`).
5. **Idle gate** (`:380`): `_activity_idle_secs` returns `None` unless
   `activity_state.json` exists, parses, says `state == "idle"`, and carries a parseable
   `at` timestamp. `None` or `< 300s` ⇒ RESCHEDULE. **Anything ambiguous counts as not
   idle.**
6. **Live re-check** (`:388`): `is_busy_cli(..., double_check=True)`. Any exception ⇒
   treat as busy (`:236-238`). Busy ⇒ RESCHEDULE.
7. **TRIGGER**: deliver `/self-compact` with `--fb_queue` so it **queues rather than
   interrupts** if the session went busy between the check and the send (`:255`). On
   success, record `state="triggered"` with a timestamp; on failure, RESCHEDULE.

### 6.3 Why the payload is a slash command

`:241-244` records the change: the compact instruction body used to be assembled here
(`_build_instruction`) and delivered inline. It now lives **solely** in the
`/self-compact` skill, and the trigger delivers the literal string `"/self-compact"`.
Single source of truth. The comment also notes *"compaction is unguarded (no token)"* —
i.e. there is no authorization token on this path; anything that can deliver a prompt to
the session can trigger a compact.

The skill itself (per the toolkit's skill listing) spawns a condenser subagent that writes
the session brief from the durable transcript, registers it, then compacts — so the brief
is written **from disk by a fresh agent**, not from the depleted context of the session
being compacted. `_SUBAGENT_PLATFORMS` (`:51`) records that Claude and Codex both have a
subagent tool and should always delegate. The usage text (`:286-287`) still describes a
self-write-if-there-is-room path — **that no longer lives in this file**; the routing
decision is inside the skill. Doc/code mismatch, minor.

### 6.4 Orphan sweep (`:151-182`)

Lists one-shots, extracts tracking ids with the regex `compact_deferred_(\S+)`, resolves
each through `SessionStore`, and cancels those whose session is missing or terminal.
Deliberately bounded to `compact_deferred.*` jobs so it can never cancel something else.

## 7. Essential vs incidental

### Essential

- **The three-outcome decision** (STOP / RESCHEDULE / TRIGGER) and the ordering of its
  guards. Cheap state checks before the expensive live check.
- **Fail-closed idleness, checked twice**: recorded state, then a live re-check
  immediately before the send. Ambiguity counts as busy.
- **Queue, never interrupt** (`--fb_queue`).
- **Deterministic job id so arming is idempotent** and re-arming replaces.
- **Transition-only scheduler contact.** This runs on every Stop hook; touching the
  scheduler each time would be untenable.
- **Cycle flags, not artifact existence**, as the "already in flight" signal.
- **The re-arm-if-ignored rule** (10 minutes, `:208`). Without it a delivered-and-dropped
  trigger leaves a session permanently over threshold with no timer.
- **Exit 0 on every normal outcome.**
- **A hook cannot run a model, so this rung must be a delivered prompt.** Any replacement
  that tries to make self-compaction synchronous inside a hook is fighting the harness.
- **The orphan sweep, bounded to its own job namespace.**
- **The instruction body lives in exactly one place** (the skill), not duplicated here.

### Incidental

- `IDLE_MIN_S = 300`, `RESCHEDULE_IN = "5m"`, `DEFAULT_THRESHOLD = 85`, the 10-minute
  re-arm window.
- `launchd`/`scheduled_task_mgr.py` as *the* scheduler. This is a backend choice.
- Subprocess-by-path invocation of the scheduler and the prompt sender. Both would be
  better as imports or console-script entry points (`DESIGN.md` decision 2 already moves
  the toolkit that way).
- The `prompt://<target>/<terminal>?submit=true` endpoint URI shape.
- `_PLATFORM_TARGET`'s underscore-to-hyphen mapping (`:52`).
- `_PROMPT_FILE` (`:41`) — dead constant.
- The `AI_SCRIPTS` `sys.path` insertion (`:29-31`) and `_bridge()`'s path computation
  (`:61-63`) — both vestigial after the import rewrite.
- `_SUBAGENT_PLATFORMS` (`:51`) — declared, never read in this file.
- The stderr log prefix and message wording.

## 8. Platform notes (Tier A / B / C per `DESIGN.md`)

This is the **most platform-bound file of the five**.

- **Tier B / C — the scheduler.** `scheduled_task_mgr.py once --in 5m --remove` is macOS
  `launchd`. `DESIGN.md` marks `scheduling/` as "port deferred; `schtasks` backend later".
  Native Windows `schtasks` has no direct equivalent of a self-removing one-shot with a
  relative delay — the usual pattern is a one-time trigger plus `/Z` (delete after
  expiry), with coarser granularity. WSL has neither `launchd` nor `schtasks` by default;
  systemd user timers require systemd enabled in WSL2, and `at` requires `atd` running.
  **This rung genuinely may not exist on some targets — it needs a capability flag, and
  the arming call must degrade to "self-compact automation unavailable" rather than
  logging a `FileNotFoundError` and pretending it armed.**
- **Tier B — prompt delivery.** `send_prompt.py` writes into a terminal multiplexer
  session (tmux/zellij per `DESIGN.md`). Works on WSL; on native Windows this is the
  substrate problem the `SessionSubstrate` ABC exists for.
- **Tier B — liveness.** `is_busy_cli` inspects the terminal session. Same substrate
  dependency.
- **Tier A — paths.** Everything is `pathlib`, but the *constants* are source-tree-shaped
  (§5). Must be rebased on the package or on `AI_ROOT` explicitly.
- **Tier A — the scheduled command line** is built by string interpolation with manual
  quoting: `f'python3 "{_SELF}" {tid}'` (`:129`). A path containing a double quote or a
  backslash (routine on Windows) breaks this. Also `python3` is hard-coded there while the
  same call uses `sys.executable` for the scheduler itself (`:126`) — inconsistent, and
  `python3` is frequently absent on Windows.
- **Tier A — timestamps.** `datetime.now().isoformat()` naive local (`:214`, `:401`), and
  `_activity_idle_secs` (`:113-117`) carefully handles both aware and naive `at` values by
  matching the parsed value's tzinfo. That care is correct; keep it.
- **Tier A — regex over CLI text.** `sweep_orphans` (`:164`) scrapes
  `compact_deferred_(\S+)` out of `--list` stdout. A structured listing (JSON) would
  survive a scheduler backend swap; this will not.
- **No file locking, no signals, no fork.** Portable in that respect.

## 9. Risks & sharp edges

1. **Stale source-tree paths (§5)** mean the whole rung is inert in a packaged install,
   and inert *quietly* — every failure path logs to stderr and returns success.
2. **Everything is best-effort and swallowed.** `_set_deferred` (`:82-95`), `_read_state`
   (`:68-80`), `_reschedule`, `cancel`, `_deliver` and `_live_idle` all catch broadly and
   continue. Combined with exit 0 on every path, **there is no failure signal anywhere**.
   A session can sit permanently over threshold with a `compact.deferred` state that says
   `armed` and no timer in existence.
3. **State-write failure is invisible** (`:94-95`). If `_set_deferred` fails after a
   successful delivery, the state still says `armed`, and `reconcile_from_stop` will
   re-arm — producing repeated `/self-compact` deliveries.
4. **Race between the idle check and the send.** Mitigated by `--fb_queue` (queue rather
   than interrupt) but not eliminated: a queued `/self-compact` lands whenever the session
   next drains its queue, which may be long after it stopped being idle.
5. **No authorization on the delivered command** (`:243-244`, "compaction is unguarded (no
   token)"). Anything with prompt-delivery access can trigger the terminal, lossy rung.
6. **`_activity_idle_secs` trusts a file another component writes.** A component that
   stops updating `activity_state.json` leaves it permanently "idle" and this will trigger
   into a busy session (the live re-check is the only remaining guard).
7. **The ladder ordering is not enforced here.** Nothing in this file checks whether the
   lossless rungs were tried first. It fires on context percentage and idleness alone. The
   ordering is a *convention* carried in documentation and in the operator's head — a
   re-design should consider making it a precondition, since this rung is the one with no
   undo.
8. **`sweep_orphans` treats an unresolvable tracking id as dead** (`:178-181`) and cancels
   its timer. A transient `SessionStore` failure therefore disarms live sessions.
9. **`reconcile_from_stop` reads state twice per call** (`:186` and `:83` inside
   `_set_deferred`) — three file reads on a hot path.

## 10. Work in flight — **do not read this file as settled design**

Active work lives in `ai_root/ai_general/work/experiments/t2_context_agency/`. Less of it
touches this file directly than the other four, but the surrounding decisions move it:

1. **The ladder below this rung was rebuilt on 2026-07-27 (todo_0692).** Offload and
   Summarize no longer archive-and-stub; they re-point `parentUuid` (`chain_skip.py`, not
   in this package). Since self-compact is defined as the rung of last resort *after* the
   reversible ones, its trigger policy depends on rungs whose economics just changed.
2. **`FINDING_never_bounced.md`** showed that a full run of correct Summarize acts
   reclaimed nothing live, because the realizing bounce never happened. If the reversible
   rungs do not actually reduce live context, **context pressure keeps rising and this
   rung fires more often than it should** — the lossy fallback absorbing the failure of
   the lossless ones. Any threshold tuning here is meaningless until that is fixed.
3. **`FINDING_gate_notice_mismatch.md`** (notice at 60%, planner gate at 75%) and
   **`FINDING_overhead_floor.md`** (non-transcript overhead measured at ~254k tokens and
   *growing* across a bounce) both mean the context percentage this file thresholds on is
   dominated by mass no reclaim lever can touch. `DEFAULT_THRESHOLD = 85` is a number
   chosen before those measurements.
4. **`PLAN_EVICTION_RANGE_REVIEW.md` (2026-07-30)** withdrew automatic authorization for
   the bounce path. The analogous question for this rung — *should an automatic timer be
   allowed to trigger the one irreversible lever?* — is not settled in any document I
   found. Rationale for the current answer (yes, at 85%, gated only on idleness) is not
   determinable from the code: **rationale unknown, needs an owner's answer.**
5. **`hooks/handlers/Stop/09_auto_offload_sync.py:46`** references a planned
   `deferred_auto_offload.py` modeled on this file; `session_bounce/deferred_offload_bounce.py`
   is the realized version. The "idle-gated one-shot with three outcomes" pattern is being
   copied rather than shared — worth resolving in the re-design before a third copy exists.
