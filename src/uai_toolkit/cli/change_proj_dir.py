#!/usr/bin/env python3
"""
change_proj_dir.py — Move a CLI session to a different project directory.

Moves the session transcript and resumes in the new dir via ai_launch.py.
Session must be stopped first. Supports Claude and Codex.

Usage:
  change_proj_dir.py <uuid> <old_dir> <new_dir> --platform <platform> [--no-launch]
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Import from sibling fork_into_dir for shared helpers
sys.path.insert(0, str(Path(__file__).parent))
from uai_toolkit.cli.fork_into_dir import (
    find_session_file,
    compute_target_path,
    PLATFORM_SESSION_DIRS,
    LAUNCHER,
)


def main():
    parser = argparse.ArgumentParser(description="Move a CLI session to a different project directory")
    parser.add_argument("uuid", help="Session UUID")
    parser.add_argument("old_dir", help="Original project directory (absolute path)")
    parser.add_argument("new_dir", help="Target project directory (absolute path)")
    parser.add_argument("--platform", required=True, choices=["claude_cli", "codex_cli"],
                        help="CLI platform")
    parser.add_argument("--no-launch", action="store_true", help="Move transcript but don't launch")
    args = parser.parse_args()

    # Validate target dir exists
    new_dir_path = Path(os.path.realpath(os.path.expanduser(args.new_dir)))
    if not args.no_launch and not new_dir_path.exists():
        print(f"Error: target directory doesn't exist: {new_dir_path}", file=sys.stderr)
        sys.exit(1)

    # Find source session file
    source = find_session_file(args.uuid, args.old_dir, args.platform)
    if not source:
        print(f"Error: session file not found for UUID {args.uuid} ({args.platform})", file=sys.stderr)
        sys.exit(1)

    # Compute target
    ext = PLATFORM_SESSION_DIRS[args.platform]["ext"]
    target = compute_target_path(args.uuid, args.new_dir, args.platform, ext)

    if target is None and args.platform == "codex_cli":
        print("Codex sessions don't need file relocation.")
        print(f"Session will resume in {new_dir_path}")
    else:
        if target.exists():
            print(f"Error: target already exists: {target}", file=sys.stderr)
            print(f"Use fork_into_dir.py to create a copy, or remove the existing file.", file=sys.stderr)
            sys.exit(1)

        # Move (not copy)
        shutil.move(str(source), str(target))
        print(f"Moved: {source.name}")
        print(f"  From: {source.parent}/")
        print(f"  To:   {target.parent}/")

    if args.no_launch:
        print(f"\nTo resume: python3 {LAUNCHER} --platform {args.platform} --resume {args.uuid} --workdir {new_dir_path}")
        return

    # Launch via ai_launch.py
    print(f"\nLaunching {args.platform} in {new_dir_path}...")
    cmd = [
        sys.executable, str(LAUNCHER),
        "--platform", args.platform,
        "--resume", args.uuid,
        "--workdir", str(new_dir_path),
    ]
    os.execvp(sys.executable, cmd)


if __name__ == "__main__":
    main()
