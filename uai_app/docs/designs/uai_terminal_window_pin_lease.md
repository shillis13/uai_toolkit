# ① UAI terminal window-pin — the "lease" design (DRAFT, for review)

**Status:** DRAFT — **CHANGES REQUESTED** by Codex Review 2
(`uai_terminal_geometry.review2_codex.md`, findings #13–#17). Do NOT build as written.
The fire-and-forget acquire/maintain/release must become a **per-session serialized,
generation-checked, owner-marked lease** (tmux user-options recording owner pid/uuid +
generation + cols/rows), **coupled into ②'s apply/ack** (ack xterm only after BOTH the PTY
resize and tmux `resize-window` land), with **safety-gated acquire** (never `resize-window`
mid-response) and a **startup sweep that clears only UAI-owned STALE leases** (never a blanket
reset). This doc will be rewritten to that shape before any implementation. Original draft +
open questions retained below for reference. Pending Codex re-review + PianoMan sign-off. This is the
redesign of ① after the first attempt (`window-size manual` set durably in the substrate's
`attach()`) broke 4 live sessions (froze at a mismatched manual size → `···` padding + lost
CLI status line) and was reverted. Related: todo_0504. Pairs with ② (renderer lockstep
resize/ack, already implemented + deployed v1.3.280).

## Problem

UAI attaches each session as a full tmux client (a PTY running `tmux attach-session`). The
ai_root tmux server runs `window-size latest` + `aggressive-resize off`, so a session's
window follows the **most-recently-active client's** size. When a foreign client (the user's
iTerm, a monitoring TTY, tooling) attaches at a different — especially taller — size and
becomes latest-active, tmux repaints the window at that size; UAI's xterm clamps the cursor
to its last row and tmux's bottom content (statusline/prompt) superimposes onto UAI's final
rows. The user needs foreign clients to remain able to attach (emergency recovery), so
`attach-session -d` (sole client) is ruled out.

## Why the first attempt was wrong

`window-size manual` was written **durably, per-session, at attach**, applied only to whatever
subset happened to re-attach, and — critically — left behind when UAI stopped driving it.
`manual` is only safe while an authoritative resizer feeds it `resize-window`; the moment UAI
detaches/closes/crashes it's a frozen landmine. Two failure axes: non-uniform coverage, and
durable state that outlives its keeper.

## The redesign: a lease, not a setting

Treat the pin as a **lease UAI holds only while actively driving a session, and always
releases.** Lifecycle is owned by the **main process** (never baked into `attach()`):

1. **Acquire** — after attach, main sets `window-size manual` AND `resize-window` to xterm's
   exact size, together, atomically. Never `manual` without the companion resize (that was
   the bug).
2. **Maintain** — ② already issues `resize-window` on every applied resize, so the lease
   tracks UAI's size continuously while attached. (Must NOT fire mid-stream — see Open Q4.)
3. **Release** — on `detachTerminal` (tab unmount/close) and `detachAll` (app quit), main
   resets the session to `window-size latest`. **The `reset_window_size` substrate method
   already built (for incident recovery) IS the release primitive.**

## Crash safety

The weak point: a hard SIGKILL between acquire and release leaves `manual` stuck. Backstops:
- **Startup sweep** — on UAI launch, before attaching anything, reset every managed session
  to `latest` (reuse the `session_ops.py geometry` audit + `reset-window-size`). Any leftover
  lease from a prior crash self-heals on restart.
- **Manual recovery** — `session_ops.py reset-window-size <name>` / `--all` for the window
  between a crash and the next launch.

Residual, stated plainly: between a UAI crash and its next launch, a foreign client attaching
to a still-`manual` session sees it stuck until the sweep or a manual reset. Bounded, self-
healing, not silent.

## Coexistence

While UAI holds the lease, a foreign iTerm can still attach — it just can't drag the window
(it sees UAI's size, letterboxed if larger). On release (UAI detach), `latest` resumes and the
window follows whatever client remains. Emergency-recovery path intact.

## Concrete implementation points (for review — NOT yet built)

- **Substrate (`lib_session_substrate.py`, TmuxSubstrate):**
  - `set_window_pin(name, cols, rows)` — `set-option window-size manual` + `resize-window -x -y`
    (acquire/maintain). NEW method; sibling of the existing `reset_window_size` (release) and
    `get_window_geometry` (audit).
  - Release reuses existing `reset_window_size(name)`.
- **Main (`terminal.ts`):**
  - Store `terminalSession` on `PtyEntry` (needed to target the tmux session; today only
    `window` was added for ②).
  - `attachTerminal` → after spawning the attach PTY, acquire the lease (fire-and-forget
    spawn of `session_ops.py resize-window`-style op; see Open Q2/Q3).
  - `applyResize` (the ② apply path) → also drive `resize-window` (maintain).
  - `detachTerminal` / `detachAll` → release (`reset-window-size`).
  - Startup → sweep-reset all managed sessions before first attach.
- **All tmux calls go through the substrate** per `scripts/session_mgmt/DESIGN.md` (no raw
  tmux in main). Main shells `session_ops.py` (which owns server/substrate resolution), as it
  already does for `attach`.

## Open questions for Codex

1. **Eager vs reactive pin.** Eager = pin every attached session (simple, bounded crash
   residual). Reactive = pin only when the geometry audit detects a foreign client at a
   mismatched size, unpin when the threat clears (smaller durable-state footprint, more moving
   parts). Recommendation: ship eager + lifecycle + startup sweep first. Is reactive worth it?
2. **`resize-window` cost/timing.** Each acquire/maintain spawns a `session_ops.py` process
   (~100–300ms). Debounced/held resizes keep frequency low, and it's fire-and-forget so it
   doesn't block the UI — but a brief window where the tmux client size (set by
   `pty.resize`) ≠ the window size (set async by `resize-window`) exists. Acceptable during
   quiet? Better ordering?
3. **Startup sweep scope.** Reset ALL sessions on all servers, or only UAI-managed ones? A
   blanket reset-to-`latest` is the safe default (it's what healthy sessions have), but is
   there a session class that legitimately wants a non-`latest` window-size?
4. **Interaction with ②'s hold-during-output.** ② holds the pty resize while the CLI streams.
   The lease's `resize-window` must ride the SAME gate — never `resize-window` mid-stream (a
   window repaint mid-response is itself a corruption trigger). Confirm the maintain step hangs
   off `applyResize` (post-quiet) only, never off the request.
5. **Crash residual** — is the startup-sweep + manual-reset containment sufficient, or is a
   heartbeat/expiry worth the complexity?
