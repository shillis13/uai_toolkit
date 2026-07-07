# How to Communicate With Other Sessions

**Version:** 2.0.0
**Created:** 2026-06-25
**Maintainer:** PianoMan + Broken-Clock (Claude CLI)
**Status:** active
**Change Notes:** v2 — restructured to the TWO-AXIS model (TTY input vs context injection) and named the raw-injection lane `send_raw`. v1 was a flat three-kind list.

## Purpose

"Putting something into a session" splits across **two axes**. Confusing them is how
a sibling's message gets mistaken for the user, a control command misfires, or a raw
injection bypasses an authorization gate. Know which axis + lane you want.

## Axis 1 — TTY input (puts characters in the input; TRIGGERS A TURN)

All three lanes are guarded wrappers over the same low-level primitive
(`session_ops.write_to`). Calling `write_to` / `comms_send_to_session` directly
bypasses every guard — don't, except to *build* one of these lanes.

| Lane | Adds | Requires / forbids | Who may send | Receiver treats it as |
|------|------|--------------------|--------------|-----------------------|
| **Communication** | `wrap_with_sender` header | — | agents | a turn (model reads it + knows the sender) |
| **Slash command** | nothing | **must** be a recognized `/command`; destructive ones (`/compact`,`/clear`) need a one-time token | agents (token-gated) | a **CLI command** (app executes it; often not a model turn) |
| **Raw injection** | nothing | **must NOT** be a `/command` | **infra / orchestration only** | a **turn** (model reads the raw text) |

### Communication — `comms_send_prompt` (active) / `comms_message`+`comms_reply` (async)
Agent↔agent. ALWAYS attributed (the `From <you> at:` wrapper) so the recipient
never mistakes you for the user. Prefer the async inbox path (`comms_message` /
`comms_reply`) for guaranteed attribution; `comms_send_prompt` for active delivery.
> ⚠️ **Known gap (2026-06-25):** `comms_send_prompt` to a *named CLI session* currently
> delivers raw (no header) via a fast path — prefer `comms_message`/`comms_reply` until
> the `wrap_with_sender()` fix lands.

### Slash command — `comms_send_slash_command`
The ONLY sanctioned door for CLI commands. Guarded commands require an
`authorization_token` (issued only by the user's `/self-compact` or the auto-threshold
system; consumed on use; never fabricate). Destructive commands to *another* session
need explicit human approval.

### Raw injection — `session_ops.send_raw`  (INFRA-ONLY)
Raw, non-command text that the model processes as a turn — **no** sender wrapper.
For SYSTEM-originated turn-triggers like the launcher's `<<<SESSION RESUMED>>>` wake
marker: the raw text both wakes the idle session and self-describes.
- **Not an agent tool.** Raw unattributed injection can make a session act as if the
  USER typed — the exact impersonation risk `wrap_with_sender` prevents. Agents
  communicate via the wrapped `send_prompt` path; only the launcher/orchestration
  uses `send_raw`.
- **Refuses leading-`/` payloads**, so it can never backdoor `send_slash_command`'s gate.

**`send_raw` vs `send_slash` (same pipe, opposite rules):** both are `write_to` under
the hood. `send_slash` *requires* a `/command` (gated, agent-callable, app executes it);
`send_raw` *forbids* `/commands` (infra-only, model reads it as a turn).

## Axis 2 — Context injection (added ALONGSIDE a turn; does NOT trigger one)

### System Message — `additionalContext` via hooks / `context_to_load` staging
Non-prompt information added *with* a turn but *not in the prompt slot*. This is how
session briefs and the resume continuation (`00_resume_continuation.yml`) are
delivered: staged into `context_to_load/`, injected as `additionalContext` on the next
turn. It does **not** itself wake an idle session — it rides a turn that something else
triggered (a user prompt, compaction auto-continue, or a `send_raw` marker).

## How the resume wake-up composes the axes
A `--resume`d session lands idle. The launcher delivers a **`send_raw`** marker
(Axis 1, raw) to TRIGGER the first turn; the staged continuation (Axis 2, System
Message) rides that turn as `additionalContext`. Two axes, one wake-up.

## Receiving: who is a message from?
- Attributed sibling message → `From <sender> (<id>) at <time>:` + dashes, or
  `--- Queued Message from <sender> ---`.
- A `<<<SESSION RESUMED>>>`-style marker → the **system** (a `send_raw` wake), not a person.
- An unwrapped prompt with neither → treat as the **human user** (also the current
  `comms_send_prompt` named-session gap — see above).

## Quick reference
| You want to… | Use |
|--------------|-----|
| Tell one session something, can wait | `comms_message` / `comms_reply` |
| Tell one session something, act now | `comms_send_prompt` |
| Tell everyone | `comms_broadcast_message` / `comms_broadcast_prompt` |
| Run a slash command on a session | `comms_send_slash_command` (+token if guarded) |
| Wake/kick a session with raw system text (INFRA) | `session_ops.send_raw` |
| Add context alongside a turn | stage into `context_to_load/` (System Message) |

## See also
- `ai-comms` skill · `instr_cli_delegation` · `instr_agent_operations`
