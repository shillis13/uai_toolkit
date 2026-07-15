# Session Management — Design Rules

## Substrate abstraction

- The substrate (lib_session_substrate.py) EXECUTES commands given to it. It does NOT construct CLI commands, select CLI flags, or make launch decisions.
- The substrate NEVER returns command strings, command arrays, or attach instructions for callers to execute. It performs the operation itself. No `--dry-run`, no `get_*_command()`, no `attach_cmd` return values.
- `create_session(name, command, cwd)` takes a pre-built command and runs it inside a new terminal session. The command comes from ai_launcher.py.
- The substrate handles multiplexer mechanics (tmux/zellij) only. It knows nothing about Claude, Codex, or Gemini.
- No code outside the substrate calls tmux or zellij commands directly. All terminal session operations go through the substrate.
- No code outside the substrate knows or constructs multiplexer-specific commands (e.g. `tmux attach-session -t X`). If you need to attach, call `substrate.attach(name)`. If you need it in a subprocess, call the substrate CLI: `python3 lib_session_substrate.py attach --session <name>`.

## session_store.py (SQLite)

- session_store.py is the authoritative source for session data. Direct JSON registry file reads are legacy.
- All session queries, writes, and updates go through session_store.py.

## session_ops.py

- session_ops.py is the only way to send text to sessions, read terminal content, or query session status.
- No raw tmux/zellij commands outside the substrate implementations.

## Session identity

- No time-based matching for session identity. Ever. No mtime, no timestamp proximity, no history scanning.
- Tracking IDs are opaque strings. Nothing parses their format or infers platform from the prefix.
- ai_launcher.py owns identity creation. session_store.py owns identity persistence. These are the only writers.
