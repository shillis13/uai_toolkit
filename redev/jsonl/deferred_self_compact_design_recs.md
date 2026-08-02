# deferred_self_compact.py — recommendations

Companion to `deferred_self_compact_design.md`.

## 1. Defect — the path constants point at the source tree, so the rung is inert when installed

`:34-41` computes every collaborator path from `AI_ROOT / "ai_general" / "scripts" / …`:

```python
_SCHED_MGR   = _GEN / "scripts" / "scheduling"  / "scheduled_task_mgr.py"
_SELF        = _GEN / "scripts" / "jsonl"       / "deferred_self_compact.py"
_SEND_PROMPT = _GEN / "scripts" / "prompting"   / "send_prompt.py"
_PROMPT_FILE = _GEN / "ai_context_files" / "instructions" / "how_tos" / "instr_operational_handoff.md"
```

That is the live source-tree layout. On a machine where the toolkit was installed as a
package and `AI_ROOT` holds only config, logs and memories (`DESIGN.md` decision 1), none
of these exist:

- `_SEND_PROMPT.exists()` is checked (`:248`) ⇒ delivery logs `"send_prompt.py missing"`
  and returns `False` ⇒ RESCHEDULE forever.
- `_SCHED_MGR` is **not** checked ⇒ `subprocess.run` raises `FileNotFoundError` ⇒ caught
  and logged (`:132`, `:142`, `:161`) ⇒ **arming silently never happens**, while
  `_set_deferred(..., state="armed")` records that it did.
- `_SELF` is embedded in the scheduled command line, so even a successful arm would invoke
  a nonexistent path.
- `_PROMPT_FILE` is dead — unused since the instruction body moved into the
  `/self-compact` skill (`:241-244`).

**Fix.** Invoke collaborators as installed console scripts or as
`python -m uai_toolkit.<domain>.<module>` (the pattern `DESIGN.md` already uses for MCP
servers), and use `sys.executable` uniformly. Delete `_PROMPT_FILE`. This is the same class
of defect as `summarizer.SHADOW_LOG`; **audit every path constant in the package for
source-tree assumptions.**

## 2. Stop swallowing every failure while reporting success

Every side-effecting call is wrapped and swallowed — `_read_state` (`:68-80`),
`_set_deferred` (`:82-95`), `_reschedule` (`:121-134`), `cancel` (`:136-144`),
`sweep_orphans` (`:151-182`), `_live_idle` (`:229-238`), `_deliver` (`:247-261`) — and
`main` returns 0 on every path (`:321-406`). The combination means **there is no failure
signal anywhere**. A session can sit permanently over threshold with
`compact.deferred.state == "armed"` and no timer in existence, and nothing will ever say
so.

**Fix, keeping exit 0 (the plist is one-shot and a nonzero exit only makes launchd noise):**
- Record the outcome in session state, including failures — a `last_error` and a
  `last_fire_at` under `compact.deferred`.
- Only set `state="armed"` **after** the arm call actually succeeded. Today `_reschedule`
  swallows the error and the caller records `armed` unconditionally (`:383-384`,
  `:390-391`, `:404-405`).
- Have `reconcile_from_stop` treat "state says armed but the scheduler has no such job" as
  a re-arm condition. It already has a re-arm path for the analogous `triggered`-but-ignored
  case (`:201-216`).

## 3. Make `_set_deferred` failure not cause repeat deliveries

If `_set_deferred` fails after a successful delivery (`:400-401` — the write is swallowed
at `:94-95`), the state still reads `armed`, and the next Stop hook re-arms, producing
another `/self-compact` delivery. Compaction is the one irreversible rung; delivering it
twice is a real cost.

**Fix.** Write the `triggered` state **before** delivering, and reconcile afterwards. A
spurious `triggered` costs a 10-minute wait before re-arming (`:208`); a spurious repeat
delivery costs a second compaction.

## 4. Extract the one-shot skeleton — there are already two copies and a third planned

`session_bounce/deferred_offload_bounce.py` describes itself as *"the lossless sibling of
`deferred_self_compact`"*: identical shape — one-shot fire, three outcomes, idle gate,
reschedule, deterministic job id, orphan handling — and no shared code.
`hooks/handlers/Stop/09_auto_offload_sync.py:46` references a further planned
`deferred_auto_offload.py`.

**Fix.** One `IdleGatedOneShot` helper parameterized by: job-id prefix, threshold source,
idle minimum, the STOP predicate, and the TRIGGER action. Each rung then contributes only
its policy. Do this before a third copy exists.

## 5. Put the scheduler behind the platform boundary, with a capability flag

`launchd` via `scheduled_task_mgr.py once --in 5m --remove` (`:126-131`) is macOS-only.
`DESIGN.md` marks `scheduling/` as "port deferred; `schtasks` backend later". The reality
per target:

- **WSL** — no `launchd`, no `schtasks`. systemd user timers need systemd enabled in WSL2;
  `at` needs `atd` running. **Neither is guaranteed.**
- **Native Windows** — `schtasks` has no clean self-removing relative-delay one-shot; the
  usual approximation is a one-time trigger plus `/Z`, at coarser granularity.

**Fix.** A `platform_compat/scheduler` backend behind an interface of roughly
`arm_once(job_id, delay, command)` / `cancel(job_id)` / `list(prefix)`, **plus a
capability flag**. Where no backend exists, arming must degrade to an explicit
"self-compact automation unavailable on this platform" — surfaced once, not swallowed. This
is a **Tier C** feature per `DESIGN.md`: it may genuinely not exist on some targets, and it
must not import-and-crash or silently pretend.

While doing this: make `list` return structured data. `sweep_orphans` currently scrapes
`compact_deferred_(\S+)` out of CLI stdout with a regex (`:164`), which will not survive a
backend swap.

## 6. Fix the scheduled command line's quoting and interpreter

```python
"--command", f'python3 "{_SELF}" {tid}'          # :129
```

Two problems: `python3` is hard-coded (the adjacent call uses `sys.executable` at `:126`,
and `python3` is frequently absent on Windows), and the quoting is manual — a path
containing a double quote or backslashes breaks it. Build the command as an argument list
and let the scheduler backend quote for its platform.

## 7. Decide whether an automatic timer may fire the irreversible rung

`PLAN_EVICTION_RANGE_REVIEW.md` (2026-07-30) withdrew **automatic** authorization for the
bounce path, on the grounds that no positive lower bound on realized reclaim is licensed.
The analogous question for this rung — may an unattended timer trigger the one lever with
no undo? — is not answered in any document I found. Today the answer is *yes, at 85%
context, gated only on idleness*, with **no authorization token** (`:243-244`: "compaction
is unguarded (no token)").

**Rationale for that posture is not determinable from the code — needs an owner's answer.**
Whatever the decision, record it, and consider adding a precondition that the reversible
rungs were attempted first. Today nothing checks the ladder ordering; this rung fires on
context percentage and idleness alone, and the ordering survives only as a convention in
prose.

This matters more given `FINDING_never_bounced.md`: if the reversible rungs report success
while reclaiming nothing live, pressure keeps rising and **this rung absorbs their
failure** — the irreversible lever firing because the reversible ones did not work.

## 8. Re-examine the threshold in light of the overhead floor

`DEFAULT_THRESHOLD = 85` (`:48`) predates `FINDING_overhead_floor.md`, which measured
non-transcript overhead (system prompt, MCP tool schemas, skill descriptions, injected
instructions) at ~254,000 tokens, *tripling* across a bounce as the deferred-tool catalog
reloaded. A session at 85% may have very little reclaimable transcript mass. Thresholding
on total context percentage conflates mass the ladder can move with mass it cannot.

**Fix.** Threshold on something the levers can act on — e.g. reclaimable on-chain mass, or
total percentage **and** a minimum reclaimable estimate — rather than percentage alone.
Note the estimate itself is disputed (`DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md`), so a
conservative floor is appropriate here, not a point estimate.

## 9. Smaller items

- **Delete the vestigial `sys.path` work:** `AI_SCRIPTS` insertion (`:29-31`) and
  `_bridge`'s `parents[2]/"data"/"hooks"/"common"` computation (`:61-63`), which resolves to
  a nonexistent `src/data/hooks/common` in the package. Both are inert because the imports
  beneath them were rewritten to absolute module paths.
- **`_SUBAGENT_PLATFORMS` (`:51`) is declared and never read.** Either use it or drop it —
  the routing decision now lives inside the `/self-compact` skill.
- **Update the usage text.** `:286-287` still describes a "self-write the brief when there
  is ≥ 10% context room, else route through a subagent" decision that no longer lives in
  this file (`:241-244` records the move into the skill).
- **Reduce state reads on the hot path.** `reconcile_from_stop` reads state at `:186` and
  again inside `_set_deferred` (`:83`), on every Stop hook.
- **Make `sweep_orphans` fail safe.** An unresolvable tracking id is treated as dead and
  its timer cancelled (`:178-181`); a transient `SessionStore` failure therefore disarms
  live sessions. Distinguish "resolved and terminal" from "could not resolve".
