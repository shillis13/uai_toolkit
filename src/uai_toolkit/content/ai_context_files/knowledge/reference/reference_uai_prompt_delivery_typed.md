---
name: reference_uai_prompt_delivery_typed
description: 'UAI prompt delivery must use send-keys -l (typed), not a raw PTY burst,
  or Claude Code chips it as [Pasted text #N] and strips file paths'
status: active
---

Deliver prompts to a CLI session via the substrate's TYPED path — `session_ops write-to <session> --text-file <tmp> --delivery typed` (which is `tmux send-keys -l`) — NOT a raw-byte burst into the tmux client PTY.

Writing text bytes straight into the client PTY (`entry.process.write` / node-pty) arrives as one fast burst that Claude Code reads as a **paste**: it folds the prompt into a `[Pasted text #N]` chip AND strips file paths on submit. `send-keys -l` injects the characters as typed input instead: no chip, paths byte-exact, and a single **named** Enter submits cleanly (the old "2 Enters for Claude" workaround was only needed because the raw burst swallowed the CR as a newline).

Why send-keys -l is safe: the tmux substrate sets `assume-paste-time 0` at session creation (`lib_session_substrate.py`), disabling tmux's paste-detection heuristic. This resolves the old conflict — PianoMan recalled "even slow send-keys still bracket-pasted," but that predates the `assume-paste-time 0` fix; it's chip-free now.

UAI wiring: `prompt.send` in `app/main/command-handlers.ts` calls `deliverPromptTyped()` (spawns `python3 session_ops.py write-to … --delivery typed [--enter]`, text via temp file to dodge arg-length/escaping). Shipped v1.3.35 (`37286a534`). GUI-launched Electron needs the padded PATH (`/opt/homebrew/bin` etc.) to find python3/tmux — mirror the `brief-ops.ts` env. Verified end-to-end (real Claude session + deployed GUI via CDP). Related: [[reference_uai_multi_instance_testing]].
