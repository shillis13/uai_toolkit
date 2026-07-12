#!/usr/bin/env python3
"""
commit_dev_env.py — Stage and commit changes in a dev environment's branch.

Usage:
  commit_dev_env.py -m MESSAGE [--all] [--ai-root PATH]

  -m MESSAGE    Commit message (required)
  --all         Stage all changes including untracked (default: tracked only)
  --ai-root     Dev env root (default: $AI_ROOT)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=30,
    )


def main():
    parser = argparse.ArgumentParser(description="Commit changes in a dev environment")
    parser.add_argument("-m", "--message", required=True, help="Commit message")
    parser.add_argument("--all", action="store_true", help="Stage all changes including untracked")
    parser.add_argument("--ai-root", help="Dev env root (default: $AI_ROOT)")
    args = parser.parse_args()

    ai_root_str = args.ai_root or os.environ.get("AI_ROOT", "")
    ai_root = Path(ai_root_str) if ai_root_str else Path()
    if not ai_root or not ai_root.exists():
        print("Error: AI_ROOT not set or doesn't exist. Use --ai-root or set $AI_ROOT.", file=sys.stderr)
        sys.exit(1)

    ag = ai_root / "ai_general"
    if not (ag / ".git").exists():
        print(f"Error: {ag} is not a git worktree/repo", file=sys.stderr)
        sys.exit(1)

    # Verify we're on a dev branch
    branch = git("branch", "--show-current", cwd=ag).stdout.strip()
    if not branch.startswith("dev/"):
        print(f"Error: branch '{branch}' is not a dev branch. Refusing to commit on main.", file=sys.stderr)
        sys.exit(1)
    print(f"Branch: {branch}")

    # Stage only editable dirs (never shared/symlinked dirs)
    editable_dirs = ["scripts", "apps", "projects", "docs"]
    if args.all:
        result = git("add", "-A", *editable_dirs, cwd=ag)
    else:
        result = git("add", "-u", *editable_dirs, cwd=ag)

    if result.returncode != 0:
        print(f"Error staging: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Check if anything to commit
    check = git("diff", "--cached", "--quiet", cwd=ag)
    if check.returncode == 0:
        print("Nothing to commit (working tree clean)")
        return

    # Show what's staged
    stat = git("diff", "--cached", "--stat", cwd=ag)
    print(stat.stdout.strip())

    # Commit
    result = git("commit", "-m", args.message, cwd=ag)
    if result.returncode != 0:
        print(f"Error committing: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"\nCommitted: {result.stdout.strip().splitlines()[0]}")


if __name__ == "__main__":
    main()
