# Hook Framework Design

## Overview

A single dispatcher (`dispatch.py`) routes hook events from all three AI CLI platforms (Claude Code, Codex, Gemini) to a shared set of handler scripts organized by event type.

```
Platform config (settings.json / hooks.json)
  └─ one entry per event type
       └─ dispatch.py <EventName>
            ├─ scans data/hooks/{EventType}/
            ├─ runs *_sync* handlers sequentially (by numeric prefix)
            ├─ runs *_async* handlers concurrently (fire-and-forget)
            └─ propagates exit codes (2 = block, 1 = error, 0 = allow)
```

## Dispatcher (`dispatch.py`)

Single entry point. Takes the hook event name as its first argument.

**Event alias mapping:** Gemini uses different event names than Claude/Codex. The dispatcher maps them before scanning directories:

```
BeforeAgent  → UserPromptSubmit
AfterAgent   → Stop
BeforeTool   → PreToolUse
AfterTool    → PostToolUse
PreCompress  → PreCompact
```

**Handler discovery:** Scans `data/hooks/{EventType}/` for executable files (`.py`, `.sh`). Ignores files starting with `.` or `__`. Sorts by filename (numeric prefix controls order).

**Sync vs async:**
- Filenames containing `_sync` run sequentially in order. If any returns exit 2 (block), the dispatcher stops immediately and propagates the block.
- Filenames containing `_async` run concurrently via `subprocess.Popen` — stdin is written and the process is released. Exit codes are not waited on.
- Files without either suffix are treated as sync.

**Stdin passthrough:** Stdin is read once by the dispatcher and passed to each handler as `subprocess.run(input=stdin_data)`.

**Exit code propagation:** Most significant wins: 2 (block) > 1 (error) > 0 (allow). For sync handlers, exit 2 short-circuits — remaining handlers are skipped.

**CWD safety:** Platform configs prefix the command with `cd ~ &&` because Claude Code sets hook CWD to the session's project_dir, which may not exist (deleted devTrees).

## Handler Conventions

### Naming

```
{NN}_{descriptive_name}_{sync|async}.{py|sh}
```

- `NN` — two-digit numeric prefix for execution order
- `_sync` — runs sequentially, can block (exit 2)
- `_async` — runs concurrently, fire-and-forget
- Use `.py` for Python, `.sh` for bash

### Base class (Python)

All Python handlers use `lib_hook_base.run_hook()`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from lib_hook_base import run_hook, HookResult

def handler(hook_input, context):
    # hook_input = parsed JSON from stdin
    # context = HookContext with tracking_id, session_dir, etc.
    return HookResult.allow()
    return HookResult.skip("reason")
    return HookResult.block("message to AI", "log reason")
    return HookResult.output(json_string, "log reason")

if __name__ == "__main__":
    sys.exit(run_hook("handler_name", "EventType", handler))
```

`run_hook()` handles stdin parsing, logging, timing, and exit code mapping.

### Base class (Bash)

Bash handlers source `lib_hook_log.sh`:

```bash
source "$(dirname "$0")/../common/lib_hook_log.sh"
# ... do work ...
hook_log "allow" "reason"
exit 0
```

### Logging

Every handler automatically logs to `{session_dir}/hook_events.jsonl`:

```json
{"ts":"...","tracking_id":"...","hook_type":"Stop","handler":"block_permission_seeking","action":"block","reason":"matched: Would you like me to","exit_code":2,"duration_ms":1}
```

Fallback log: `/tmp/hook_events_{tracking_id}.jsonl` if session_dir unavailable.

**Dispatcher invocation log (per-event, authoritative).** Beyond the opt-in per-handler
lines above, the dispatcher itself records one summary per hook firing — independent of
whether each handler opted into `run_hook()`. Written to BOTH `{session_dir}/hook_events.jsonl`
(co-located, `kind:"dispatch"`) and the central stream `ai_general/data/audit/hook_invocations.jsonl`:

```json
{"ts":"2026-06-19T16:17:48-04:00","tracking_id":"…","hook_type":"PreToolUse","kind":"dispatch",
 "handlers":[
   {"handler":"check_file_conflict","mode":"sync","exit_code":0,"action":"allow","duration_ms":36},
   {"handler":"some_excluded","mode":"sync","excluded":true},
   {"handler":"later_one","mode":"sync","skipped":true},
   {"handler":"store_session_data","mode":"async","launched":true}],
 "final":{"exit_code":0,"blocked":false,"blocking_handler":null,"merged_context":true},
 "duration_ms":350}
```

- Captures the FULL roster: each sync handler's `exit_code`/`action`/`duration_ms`, `excluded:true`
  for session-excluded handlers, `skipped:true` for sync handlers not reached after a block, and
  `launched:true` for async (fire-and-forget — their *outcome* still comes from their own `run_hook`
  line, since the dispatcher doesn't wait on async).
- Logged at every exit path (including block via exit 2). Best-effort: wrapped so logging can never
  break the hook; directories are not auto-created.
- This central stream is the intended basis for **triggers / event subscriptions** (e.g. driving
  session `activity_state` from `SessionStart`/`Stop`/`UserPromptSubmit` events) — one event source,
  no per-consumer polling or fswatcher proliferation.
- **Volume note:** `PreToolUse`/`PostToolUse` fire per tool call, so `hook_invocations.jsonl` grows
  quickly — it needs a rotation/retention policy (not yet implemented).

### Exit codes

| Code | Meaning | Dispatcher behavior |
|---|---|---|
| 0 | Allow | Continue to next handler. Optional JSON on stdout for context injection. |
| 1 | Error | Non-blocking. Logged, processing continues. |
| 2 | Block | **Stops execution.** Stderr message is shown to the AI. For Stop hooks, forces a retry turn. |

### Failure signaling (both channels)

When a handler hits an error, surface it through **both** channels — they serve different
consumers and neither substitutes for the other. (Same principle as
`ai_general/scripts/DESIGN.md` § Failure Signaling; origin: note_0031 / todo_0458.)

1. **Indicator — exit code / `HookResult`.** An internal error is **exit 1** (`HookResult.error(reason)`):
   non-blocking, but *recorded as an error* in the roll-up. Do **not** swallow a caught exception
   into `HookResult.allow()` (exit 0) — that logs the firing as a clean allow and hides the
   failure from `final.exit_code` and anything consuming `hook_invocations.jsonl`. Either let the
   exception propagate (`run_hook()` maps an uncaught handler exception to `HookResult.error(str(e))`
   → exit 1, logged) or return an explicit `HookResult.error(...)`. Exit **2** stays reserved for an
   intentional *block*, never an internal error.
2. **Evidence — the hook log.** `run_hook()` already records the **where** (`handler`, `hook_type`),
   **what** (`reason` / message), and **when** (`ts`) to `{session_dir}/hook_events.jsonl` — so pass a
   **meaningful** `reason`, not a generic one. That line is the diagnosable record and the basis for
   any error surfacing.

A handler that catches its own failure and returns allow/exit 0 is the hook-framework version of a
script that prints `ERROR` but exits 0: invisible to every automated consumer. Signal it (exit 1)
**and** log the where/what/when.

### Output formats by event type

| Event | Stdout format for context injection |
|---|---|
| UserPromptSubmit | `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}` |
| PostToolUse | `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}` |
| PreToolUse (block) | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` |
| Stop | `{"systemMessage": "..."}` for non-blocking context, or exit 2 + stderr for blocking |

## Platform Configuration

| Platform | Config file | Matcher syntax | Timeout unit |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | glob (`*`) | seconds |
| Codex | `~/.codex/hooks.json` | regex (`.*`) | seconds |
| Gemini | `~/.gemini/settings.json` | regex (`.*`) | milliseconds |

Each config has one entry per event type, all pointing at `dispatch.py` with the event name as argument.

## Handler exclusions

Each event-type directory may contain an optional `exclusions.yml` that lets
specific sessions skip specific handlers. The dispatcher loads it once per
event and filters handlers **before** running them — handlers themselves stay
unaware of exclusions.

```yaml
# <EventType>/exclusions.yml
# key = handler name (NN_ prefix and _sync/_async suffix stripped);
#       "*" / "*sync" / "*async" = handler-set wildcards (see below).
# value = tracking IDs; trailing comment is the display name (auto-regenerated).
"*sync":
  - 20260423_045650_app3020c_cla   # Meridian — skips blocking Stop handlers, keeps telemetry
auto_self_compact:
  - 20260511_160359_bd191353_cla   # Cadence — never auto-self-compacts
```

- **Handler key** = `normalize_handler_name()` (strips `NN_` and `_sync/_async.{py,sh}`),
  so it matches the `run_hook("name", …)` value and survives renumbering.
- **Session key** = tracking ID (authoritative; resolved from `$AI_TRACKING_ID`).
- **Wildcard keys** (any starting with `*`; must be quoted in YAML so they aren't
  parsed as aliases):
  - **`"*"`** — exclude the session from *every* handler in that directory.
  - **`"*sync"`** — exclude from every *sync* handler. Sync handlers run inline and
    are allowed to block/inject/compact (gates, `auto_self_compact`, `auto_offload`,
    reminders, `todo_audit`). This silences the intrusive/behavioral handlers while
    leaving the passive async handlers — `store_session_data` (telemetry incl.
    `last_activity`), `mark_idle` (activity state) — running. Prefer this over `"*"`
    for a "leave-me-alone" session: `"*"` also freezes the telemetry the UAI app
    reads, which makes the session sort/display as stale.
  - **`"*async"`** — exclude from every *async* (fire-and-forget) handler.
  - Convention (documented so it isn't quietly broken): sync == may block/modify the
    turn; async == passive side-effect. The mode wildcards lean on that alignment, so
    a *new* intrusive handler should be `_sync` and a *new* passive one `_async`.
- **Fail-open**: a missing/malformed `exclusions.yml` means no exclusions — all
  handlers run. Exclusions are a convenience, not a security boundary.

Manage with `ai_general/scripts/hooks/hook_exclusions.py {add,remove,list}`
(accepts display names, resolves to tracking IDs, regenerates name comments).

## Adding a new handler

1. Create the script in the appropriate `{EventType}/` directory
2. Name it `NN_descriptive_name_sync.py` or `NN_descriptive_name_async.py`
3. Use `lib_hook_base.run_hook()` for automatic stdin parsing and logging
4. Make it executable (`chmod +x`)
5. The dispatcher picks it up automatically — no config changes needed
6. Update the directory's `README.md`

## Adding a new event type

1. Create the directory under `data/hooks/`
2. Add a `README.md`
3. Register in all three platform configs pointing at `dispatch.py <EventName>`
4. If Gemini uses a different event name, add the alias to `EVENT_ALIASES` in dispatch.py

## Dependencies

- `ai_general/scripts/file_access/file_access_tracker.py` — cross-session file read/write tracking (used by anti-clobbering handlers)
- `ai_general/scripts/session_mgmt/session_store.py` — session metadata lookups
- `~/bin/ai/messages/messaging.py` — unread message checks
- `~/bin/ai/notifications/send_user_notification.py` — user notifications from compaction handlers
- `~/bin/ai/jsonl/read_jsonl.py` — JSONL transcript stats
- `~/bin/ai/jsonl/auto_brief.py` — auto-brief creation on compaction
- `ai_general/scripts/cli/stage_context.py` — stage files into session context_to_load/ inbox
- `ai_general/scripts/cli/load_context.py` — CLI for staging context files (replaces load_brief_into.py)
