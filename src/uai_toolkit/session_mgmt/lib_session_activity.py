"""Shared writer for a session's live activity_state.

The UAI app (and any consumer) reads `session.activity_state` from the per-session
state file ({session_dir}/{tracking_id}_state.json) — the same file it already reads
`session.last_activity` from. This module is the single, change-guarded writer of that
field, used by THREE scaffolding callers:

  - UserPromptSubmit hook → "responding"  (fast, event-driven onset)
  - Stop hook             → "idle"         (fast, event-driven normal end)
  - session_ops.get_ai_status (get-status) → reconciled ground-truth state
        (idle / prompt_occupied / responding / blocked / permission_prompt / exited)
        — catches prompt_occupied, permission/blocked, AND interrupt-idle (it reads
        the terminal, which is correct even when no Stop hook fired).

The store stays fed only by scaffolding; the app is a pure reader.

Design notes:
- CHANGE-GUARDED: writes (and signals) only when the value actually changes, so the
  frequently-called get-status path never storms the signal file.
- Touches ai_general/data/sessions.changed so the app's fs.watch re-reads the store.
- Lightweight (json/os/datetime/pathlib only) — safe to import from async hooks.
- Best-effort: never raises; activity tracking must not break a hook or a status read.
"""

import json
import os
from datetime import datetime
from pathlib import Path

# States we accept as a real, persistable activity_state. "unknown" is intentionally
# excluded — we never overwrite a known state with "unknown".
VALID_STATES = {
    "idle", "responding", "working", "prompt_occupied",
    "blocked", "permission_prompt", "exited",
}


def _ai_root() -> Path:
    return Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))


def set_activity_state(session_dir: str, tracking_id: str, state: str, *, signal: bool = True) -> bool:
    """Change-guarded write of `session.activity_state` to the per-session state file.

    Returns True if the value changed (was written + signalled), False otherwise.
    Never raises.
    """
    if not session_dir or not tracking_id or state not in VALID_STATES:
        return False
    try:
        path = Path(session_dir) / f"{tracking_id}_state.json"
        cur = {}
        if path.exists():
            try:
                cur = json.loads(path.read_text())
            except (ValueError, OSError):
                cur = {}

        if cur.get("session.activity_state") == state:
            return False  # change-guard: no write, no signal

        now = datetime.now().isoformat()
        cur["session.activity_state"] = state
        cur["session.activity_state_at"] = now
        cur["updated_at"] = now

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, indent=2))
        tmp.rename(path)

        if signal:
            try:
                (_ai_root() / "ai_general" / "data" / "sessions.changed").touch()
            except OSError:
                pass
        return True
    except Exception:
        return False
