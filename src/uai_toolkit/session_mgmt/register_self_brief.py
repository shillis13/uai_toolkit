#!/usr/bin/env python3
"""Register a self-written handoff brief so it auto-loads post-compaction.

The /self-compact flow has the AI write its own brief, then trigger /compact.
PostCompact only stages a brief for delivery if `compact.brief_file` points at a
real file (see ai_general/data/hooks/PostCompact/02_auto_brief_postcompact_sync.py).
Nothing on the self-compact path used to set that field — so self-written briefs
were orphaned and never re-loaded. This script is the authoritative registration
step: the AI knows exactly which file it wrote, so it records the path here.

Writes two keys into the canonical session state file
({session_dir}/{tracking_id}_state.json — the same file the hooks read/write):
  - compact.brief_file : absolute path to the brief
  - compact.self       : True (marks this as a self-compaction so PreCompact
                         preserves the registered brief instead of clearing it)

Usage:
  register_self_brief.py <brief_path>
  register_self_brief.py ai_general/data/session_briefs/auto_briefs/Relay.yml

Resolves session_dir / tracking_id from $AI_SESSION_DIR / $AI_TRACKING_ID.
Exit 0 on success (prints the resolved path); non-zero with a clear message
otherwise — the error must be visible, never silently swallowed.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("register_self_brief.py: exactly one argument required — the brief path.\n")
        return 2

    brief_path = Path(sys.argv[1]).expanduser().resolve()
    if not brief_path.exists():
        sys.stderr.write(f"register_self_brief.py: brief not found: {brief_path}\n")
        return 2

    session_dir = os.environ.get("AI_SESSION_DIR", "")
    tracking_id = os.environ.get("AI_TRACKING_ID", "")
    if not session_dir or not tracking_id:
        sys.stderr.write(
            "register_self_brief.py: AI_SESSION_DIR and AI_TRACKING_ID must be set "
            "(they identify the session state file to update).\n"
        )
        return 2

    state_path = Path(session_dir) / f"{tracking_id}_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            sys.stderr.write(f"register_self_brief.py: could not read state {state_path}: {e}\n")
            return 1

    state["compact.brief_file"] = str(brief_path)
    state["compact.self"] = True
    state["updated_at"] = datetime.now().isoformat()

    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except OSError as e:
        sys.stderr.write(f"register_self_brief.py: could not write state {state_path}: {e}\n")
        return 1

    print(f"registered self-brief: {brief_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
