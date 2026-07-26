#!/usr/bin/env python3
"""PreToolUse hook — require governed-doc read before editing files in governed directories.

If a governed doc (DESIGN.md, README.md, etc.) exists in the target file's directory
or any parent (up to AI_ROOT), and the current session hasn't read it yet, blocks the
edit. The session must read the doc first to prove it knows the rules.

Records each governed-doc read into the session state file so the UCI app's
Right Panel -> Context tab can display which directories the session has loaded
design rules for.

Uses file_access_tracker.get_last_read() which is populated by the PostToolUse
read-tracking hook whenever any file is read.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

sys.path.insert(0, '$AI_ROOT/ai_general/scripts/file_access')
from uai_toolkit.file_access.tracker import get_last_read

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))

# Governed doc types: filename -> state key prefix
# Add new types here to expand enforcement (e.g. "README.md": "context.readme")
GOVERNED_DOCS = {
    "DESIGN.md": "context.design_md",
}


def _find_governed_doc(file_path, doc_name):
    """Walk from the file's directory upward to AI_ROOT looking for doc_name."""
    target = Path(file_path).resolve()
    if target.is_file():
        target = target.parent

    ai_root_resolved = AI_ROOT.resolve()

    current = target
    while True:
        candidate = current / doc_name
        if candidate.is_file():
            return candidate

        # Stop at AI_ROOT boundary
        if current == ai_root_resolved or current == current.parent:
            break
        current = current.parent

    return None


def _record_governed_read(session_dir: str, tracking_id: str, state_prefix: str,
                          doc_path: Path, governed_dir: str) -> None:
    """Record a governed-doc read in the session state file.

    Writes two entries:
      {prefix}.dirs  -- list of directory paths where the doc was read
      {prefix}.reads -- list of {dir, file, read_at} objects
    """
    if not session_dir or not tracking_id:
        return

    from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state
    state = read_union(session_dir, tracking_id)

    reads_key = f"{state_prefix}.reads"
    dirs_key = f"{state_prefix}.dirs"

    reads = state.get(reads_key, [])
    if not isinstance(reads, list):
        reads = []

    # Add this read if the directory isn't already recorded
    existing_dirs = {r["dir"] for r in reads if isinstance(r, dict)}
    if governed_dir not in existing_dirs:
        reads.append({
            "dir": governed_dir,
            "file": str(doc_path),
            "read_at": datetime.now().isoformat(),
        })

    # Targeted write through the bridge (todo_0495).
    write_session_state(session_dir, tracking_id, {
        reads_key: reads,
        dirs_key: [r["dir"] for r in reads if isinstance(r, dict)],
        "updated_at": datetime.now().isoformat(),
    })


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        return HookResult.skip("not an edit/write")

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return HookResult.skip("no file_path")

    # Don't block edits to governed docs themselves
    if Path(file_path).name in GOVERNED_DOCS:
        return HookResult.skip(f"editing {Path(file_path).name} itself")

    # file_access_tracker logs reads by CLI session ID (UUID), not tracking ID
    session_id = os.environ.get("AI_CLI_SESSION_ID", context.tracking_id)
    if not session_id:
        return HookResult.allow()

    # Check each governed doc type
    for doc_name, state_prefix in GOVERNED_DOCS.items():
        doc_path = _find_governed_doc(file_path, doc_name)
        if doc_path is None:
            continue

        last_read = get_last_read(session_id, str(doc_path))
        if last_read is not None:
            # Session has read it -- record in session state for the app
            governed_dir = str(doc_path.parent.relative_to(AI_ROOT)) if str(doc_path).startswith(str(AI_ROOT)) else str(doc_path.parent)
            _record_governed_read(context.session_dir, context.tracking_id, state_prefix, doc_path, governed_dir)
            continue

        # Session hasn't read this governed doc -- block
        rel_doc = doc_path.relative_to(AI_ROOT) if str(doc_path).startswith(str(AI_ROOT)) else doc_path
        rel_target = Path(file_path).relative_to(AI_ROOT) if file_path.startswith(str(AI_ROOT)) else Path(file_path)

        return HookResult.block(
            f"{doc_name} exists at {rel_doc} but you haven't read it in this session.\n\n"
            f"Read it before editing files in this directory. It contains design rules "
            f"that constrain how this code works.\n\n"
            f"Run: Read {doc_path}",
            f"governed_doc_not_read: {rel_doc} (target: {rel_target})"
        )

    return HookResult.allow()


if __name__ == "__main__":
    sys.exit(run_hook("require_governed_doc_read", "PreToolUse", handler))
