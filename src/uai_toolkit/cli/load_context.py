#!/usr/bin/env python3
"""
load_context.py — Stage context files for delivery to a running session.

Places symlinks (or copies) in <session_dir>/context_to_load/. The
UserPromptSubmit hook handler picks them up on the next prompt and
injects their content as additionalContext.

Works with any text file: briefs, traits, roles, working memory, ad-hoc.

Usage:
  load_context.py --session <session-id> <file> [<file> ...]
  load_context.py --session self brief.yml trait.md
  load_context.py --session Relay brief.yml --copy
  load_context.py --session 20260510_d510 brief.yml --prefix 01 --dry-run

  # Legacy brief-loading interface (backward compat):
  load_context.py --session <id> --brief /path/to/brief.yml
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT
_AI_ROOT = AI_ROOT
_CLI_DIR = _AI_ROOT / "ai_general" / "scripts" / "cli"
if str(_CLI_DIR) not in sys.path:
    sys.path.insert(0, str(_CLI_DIR))

from uai_toolkit.cli.stage_context import _resolve_session_dir, stage_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage context files for delivery to a running CLI session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--session", required=True,
                        help="Tracking ID, terminal session name, CLI UUID, or 'self'")
    parser.add_argument("files", nargs="*", help="File paths to stage")
    parser.add_argument("--brief", help="(Legacy) Path to brief file — same as positional arg")
    parser.add_argument("--copy", action="store_true",
                        help="Copy files instead of symlinking (default: symlink)")
    parser.add_argument("--prefix", default=None,
                        help="Numeric prefix for sort ordering")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without staging")
    args = parser.parse_args()

    # Merge positional files and --brief
    all_files = list(args.files or [])
    if args.brief:
        all_files.append(args.brief)
    if not all_files:
        parser.error("No files specified. Provide file paths as arguments or use --brief.")

    # Validate files exist
    for f in all_files:
        p = Path(f)
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"File not found: {f}"}), file=sys.stderr)
            return 1
        if not os.access(p, os.R_OK):
            print(json.dumps({"ok": False, "error": f"File not readable: {f}"}), file=sys.stderr)
            return 1

    session_dir, tracking_id = _resolve_session_dir(args.session)
    if not session_dir:
        print(json.dumps({"ok": False, "error": f"Session not found: {args.session}"}), file=sys.stderr)
        return 1

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "session": tracking_id,
            "session_dir": session_dir,
            "files": [str(Path(f).resolve()) for f in all_files],
            "inbox": str(Path(session_dir) / "context_to_load"),
            "mode": "copy" if args.copy else "symlink",
        }, indent=2))
        return 0

    results = []
    errors = 0
    for f in all_files:
        staged_name, err = stage_file(session_dir, f, copy=args.copy, prefix=args.prefix)
        if err:
            results.append({"file": f, "error": err})
            errors += 1
        else:
            results.append({"file": f, "staged_as": staged_name})

    print(json.dumps({
        "ok": errors == 0,
        "session": tracking_id,
        "staged": [r for r in results if "staged_as" in r],
        "errors": [r for r in results if "error" in r],
        "inbox": str(Path(session_dir) / "context_to_load"),
    }, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
