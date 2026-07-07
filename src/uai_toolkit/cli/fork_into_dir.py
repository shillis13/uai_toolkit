#!/usr/bin/env python3
from __future__ import annotations
"""
fork_into_dir.py — Fork a CLI session into a different project directory.

Copies the session transcript to a new project dir and optionally launches
there via ai_launch.py. Supports Claude, Codex, and Gemini.

Usage:
  fork_into_dir.py <uuid> <old_dir> <new_dir> --platform <platform> [--no-launch]

Args:
  uuid        Session UUID to fork
  old_dir     Original project directory (absolute path)
  new_dir     Target project directory (absolute path)
  --platform  claude_cli | codex_cli | gemini_cli
  --no-launch Copy the transcript but don't launch
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


# Platform-specific session file locations
PLATFORM_SESSION_DIRS = {
    "claude_cli": {
        "base": Path.home() / ".claude/projects",
        "slug_fn": "sanitize",  # uses sanitized project dir name
        "ext": ".jsonl",
    },
    "codex_cli": {
        "base": Path.home() / ".codex/sessions",
        "slug_fn": "date",  # uses date-based dirs
        "ext": ".jsonl",
    },
    "gemini_cli": {
        "base": Path.home() / ".gemini/tmp",
        "slug_fn": "sanitize",
        "ext": ".json",
    },
}

LAUNCHER = Path(__file__).parent / "ai_launch.py"


def sanitize_project_dir(dir_path: str) -> str:
    """Convert absolute path to Claude Code's project directory naming.
    Matches Claude Code's algorithm: replace all non-alphanumeric chars with '-'.
    /Users/foo/my_project → -Users-foo-my-project
    """
    import re
    normalized = os.path.realpath(os.path.expanduser(dir_path)).rstrip("/")
    return "-" + re.sub(r'[^a-zA-Z0-9]', '-', normalized.lstrip("/"))


def find_session_file(uuid: str, project_dir: str, platform: str) -> Path | None:
    """Find the session transcript file for a given platform."""
    config = PLATFORM_SESSION_DIRS.get(platform)
    if not config:
        return None

    base = config["base"]
    ext = config["ext"]

    if platform == "claude_cli":
        slug = sanitize_project_dir(project_dir)
        candidate = base / slug / f"{uuid}{ext}"
        if candidate.exists():
            return candidate
        # Search all project dirs as fallback
        for d in base.iterdir():
            f = d / f"{uuid}{ext}"
            if f.exists():
                return f

    elif platform == "codex_cli":
        # Codex stores in date-based dirs: ~/.codex/sessions/YYYY/MM/DD/
        import glob
        pattern = str(base / "**" / f"*{uuid}*{ext}")
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return Path(matches[0])

    elif platform == "gemini_cli":
        # Gemini: ~/.gemini/tmp/{project_slug}/chats/{session}.json
        for project_slug in base.iterdir():
            chats = project_slug / "chats"
            if chats.exists():
                f = chats / f"{uuid}{ext}"
                if f.exists():
                    return f

    return None


def compute_target_path(uuid: str, new_dir: str, platform: str, ext: str) -> Path:
    """Compute where the session file should go in the new project dir."""
    config = PLATFORM_SESSION_DIRS[platform]
    base = config["base"]

    if platform == "claude_cli":
        slug = sanitize_project_dir(new_dir)
        target_dir = base / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{uuid}{ext}"

    elif platform == "codex_cli":
        # Codex: keep in same date-based structure, just copy
        # The session file location doesn't change with project dir
        return None  # Codex doesn't need file relocation

    elif platform == "gemini_cli":
        slug = sanitize_project_dir(new_dir)
        target_dir = base / slug / "chats"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{uuid}{ext}"

    return None


def is_session_busy(session_file: Path) -> bool:
    """Check if a session is actively being written to."""
    if not session_file.exists():
        return False
    size1 = session_file.stat().st_size
    time.sleep(1)
    size2 = session_file.stat().st_size
    return size1 != size2


def main():
    parser = argparse.ArgumentParser(description="Fork a CLI session into a different project directory")
    parser.add_argument("uuid", help="Session UUID to fork")
    parser.add_argument("old_dir", help="Original project directory (absolute path)")
    parser.add_argument("new_dir", help="Target project directory (absolute path)")
    parser.add_argument("--platform", required=True, choices=["claude_cli", "codex_cli", "gemini_cli"],
                        help="CLI platform")
    parser.add_argument("--no-launch", action="store_true", help="Copy transcript but don't launch")
    args = parser.parse_args()

    # Validate
    new_dir_path = Path(os.path.realpath(os.path.expanduser(args.new_dir)))
    if not new_dir_path.exists():
        print(f"Error: target directory doesn't exist: {new_dir_path}", file=sys.stderr)
        sys.exit(1)

    if args.platform == "gemini_cli":
        print("Error: Gemini does not support fork/resume.", file=sys.stderr)
        sys.exit(1)

    # Find source session file
    source = find_session_file(args.uuid, args.old_dir, args.platform)
    if not source:
        print(f"Error: session file not found for UUID {args.uuid} ({args.platform})", file=sys.stderr)
        sys.exit(1)

    # Wait for source session to be idle
    if is_session_busy(source):
        print("Source session is actively writing. Waiting for idle...", file=sys.stderr)
        retries = 0
        while is_session_busy(source) and retries < 10:
            retries += 1
        if retries >= 10:
            print("Warning: source session still writing after 10s. Proceeding anyway.", file=sys.stderr)

    parent_uuid = args.uuid

    # Copy parent JSONL to the new project dir under the PARENT UUID filename.
    # Claude's --resume looks for {parent_uuid}.jsonl in the cwd's project dir.
    # ai_launch.py's fork path then uses --fork-session --session-id {new_uuid}
    # to branch from it.
    ext = PLATFORM_SESSION_DIRS[args.platform]["ext"]
    target = compute_target_path(parent_uuid, args.new_dir, args.platform, ext)

    if target is None and args.platform == "codex_cli":
        # Codex doesn't relocate session files — just resume in new dir
        print(f"Codex sessions don't need file relocation.")
        print(f"Session will resume in {new_dir_path}")
    else:
        if target.exists():
            print(f"Warning: parent JSONL already exists in target dir, skipping copy.", file=sys.stderr)
        else:
            shutil.copy2(str(source), str(target))
            print(f"Copied parent JSONL: {source.name}")
            print(f"  From: {source.parent}/")
            print(f"  To:   {target.parent}/")
            print(f"  Original: kept")

    if args.no_launch:
        print(f"\nTo launch fork: python3 {LAUNCHER} --platform {args.platform} --fork-from {parent_uuid} --workdir {new_dir_path}")
        return

    # Launch via ai_launch.py — it generates the child UUID and handles --fork-session
    print(f"\nLaunching {args.platform} fork in {new_dir_path}...")
    cmd = [
        sys.executable, str(LAUNCHER),
        "--platform", args.platform,
        "--fork-from", parent_uuid,
        "--workdir", str(new_dir_path),
    ]
    os.execvp(sys.executable, cmd)


if __name__ == "__main__":
    main()
