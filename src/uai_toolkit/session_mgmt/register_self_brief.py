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

    # Write through the shared bridge (todo_0495): enrolled sessions use the
    # locked canonical accessor, everyone else the legacy file. These are fixed
    # keys (no read-modify needed).
    _hook_common = Path(__file__).resolve().parents[2] / "data" / "hooks" / "common"
    if str(_hook_common) not in sys.path:
        sys.path.insert(0, str(_hook_common))
    from uai_toolkit.hooks.common.lib_session_state_union import write_session_state
    if not write_session_state(session_dir, tracking_id, {
        "compact.brief_file": str(brief_path),
        "compact.self": True,
        "updated_at": datetime.now().isoformat(),
    }):
        sys.stderr.write(f"register_self_brief.py: could not write session state for {tracking_id}\n")
        return 1

    # Stage the brief as a .ref into context_to_load/ NOW — at the moment we know
    # the path. The creator owns delivery staging: the .ref is a durable session-dir
    # artifact, drained on the next turn (UserPromptSubmit/06) or on resume
    # (SessionStart/02), so it does not depend on a compaction running PostCompact.
    # This also makes the catch-up flow's "the brief will load on your next turn"
    # actually true (a brief registered outside a compaction now gets delivered).
    try:
        inbox = Path(session_dir) / "context_to_load"
        inbox.mkdir(exist_ok=True)
        # pin_path: this brief is an EXACT file we just wrote — load it by path,
        # never re-resolve `name` through guidance. A session named e.g. "Prism"
        # collides with a guidance doc of the same name, which would shadow the
        # real handoff brief and load the wrong content. See lib_context_load.
        ref = {"type": "briefs", "name": brief_path.stem, "path": str(brief_path), "pin_path": True}
        # Clear any stale entry (incl. a legacy symlink of the same stem).
        for stale in (inbox / f"{brief_path.stem}.ref", inbox / brief_path.name):
            if stale.exists() or stale.is_symlink():
                stale.unlink()
        (inbox / f"{brief_path.stem}.ref").write_text(json.dumps(ref, indent=2))
    except OSError as e:
        # Non-fatal: the brief is registered; only its pre-staging failed.
        sys.stderr.write(f"register_self_brief.py: brief ref staging failed (non-fatal): {e}\n")

    print(f"registered self-brief: {brief_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
