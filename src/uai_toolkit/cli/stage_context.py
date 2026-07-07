#!/usr/bin/env python3
"""
stage_context.py — Stage context files for delivery to a running session.

Places files (as symlinks or copies) into <session_dir>/context_to_load/.
The UserPromptSubmit hook handler picks them up on the next prompt and
injects them as additionalContext.

Usage:
    stage_context.py <session> <file> [<file> ...]
    stage_context.py <session> <file> --copy          # copy instead of symlink
    stage_context.py <session> <file> --prefix 01     # explicit sort prefix
    stage_context.py --self <file>                     # stage for own session

Session identifiers: tracking ID, display name, CLI UUID prefix, 'self'.

Exit codes:
    0  All files staged
    1  Session not found or no files provided
    2  File error (not found, not readable)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
_SESSION_MGMT = _AI_ROOT / "ai_general" / "scripts" / "session_mgmt"
if str(_SESSION_MGMT) not in sys.path:
    sys.path.insert(0, str(_SESSION_MGMT))

from uai_toolkit.session_mgmt.session_store import SessionStore


def _resolve_session_dir(identifier):
    """Resolve session identifier to session_dir path."""
    if identifier.lower() == "self":
        sd = os.environ.get("AI_SESSION_DIR", "")
        if sd:
            return sd, os.environ.get("AI_TRACKING_ID", "self")
        identifier = os.environ.get("AI_TRACKING_ID", "")
        if not identifier:
            return None, None

    store = SessionStore()
    session = store.resolve(identifier)
    if session and session.get("session_dir"):
        return session["session_dir"], session["tracking_id"]
    return None, None


def stage_file(session_dir, file_path, copy=False, prefix=None):
    """Stage a single file into context_to_load/.

    Returns (staged_name, error_or_None).
    """
    inbox = Path(session_dir) / "context_to_load"
    inbox.mkdir(exist_ok=True)

    src = Path(file_path).resolve()
    if not src.exists():
        return None, f"File not found: {file_path}"
    if not src.is_file():
        return None, f"Not a file: {file_path}"

    # Build destination name with optional prefix
    stem = src.name
    if prefix is not None:
        stem = f"{prefix}_{stem}"

    dest = inbox / stem

    # Dedup: if already staged (same name), skip
    if dest.exists() or dest.is_symlink():
        # Check if it points to the same source
        if dest.is_symlink() and dest.resolve() == src:
            return stem, None  # already staged
        # Different source, same name — add suffix
        i = 2
        while dest.exists() or dest.is_symlink():
            dest = inbox / f"{Path(stem).stem}_{i}{Path(stem).suffix}"
            i += 1
        stem = dest.name

    if copy:
        shutil.copy2(str(src), str(dest))
    else:
        dest.symlink_to(src)

    return stem, None


def stage_ref(session_dir, item_type, name, prefix=None, path=None):
    """Stage a .ref file for a registered context item.

    The delivery hook resolves .ref files through the guidance pipeline
    for types it knows (traits, roles, profiles, skills). For other types
    (briefs, mslots), or if guidance fails, the hook falls back to reading
    the file at 'path' directly.

    Returns (staged_name, error_or_None).
    """
    inbox = Path(session_dir) / "context_to_load"
    inbox.mkdir(exist_ok=True)

    ref_name = f"{item_type}__{name}.ref"
    if prefix is not None:
        ref_name = f"{prefix}_{ref_name}"

    dest = inbox / ref_name

    if dest.exists():
        return ref_name, None  # already staged

    ref_data = {"type": item_type, "name": name}
    if path:
        ref_data["path"] = str(path)
    dest.write_text(json.dumps(ref_data))
    return ref_name, None


def main():
    parser = argparse.ArgumentParser(
        description="Stage context files for delivery to a running session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("session", help="Session identifier or 'self'")
    parser.add_argument("files", nargs="+", help="File paths to stage")
    parser.add_argument("--copy", action="store_true",
                        help="Copy files instead of symlinking (default: symlink)")
    parser.add_argument("--prefix", default=None,
                        help="Numeric prefix for sort ordering (e.g., '01')")
    args = parser.parse_args()

    session_dir, tracking_id = _resolve_session_dir(args.session)
    if not session_dir:
        print(json.dumps({"ok": False, "error": f"Session not found: {args.session}"}))
        return 1

    results = []
    errors = 0
    for f in args.files:
        name, err = stage_file(session_dir, f, copy=args.copy, prefix=args.prefix)
        if err:
            results.append({"file": f, "error": err})
            errors += 1
        else:
            results.append({"file": f, "staged_as": name})

    output = {
        "ok": errors == 0,
        "session": tracking_id,
        "session_dir": session_dir,
        "staged": [r for r in results if "staged_as" in r],
        "errors": [r for r in results if "error" in r],
    }
    print(json.dumps(output, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
