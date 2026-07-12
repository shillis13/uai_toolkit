#!/usr/bin/env python3
"""
push_dev_env.py — Push a dev environment's branch to remote.

Usage:
  push_dev_env.py [--ai-root PATH]
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )


def main():
    parser = argparse.ArgumentParser(description="Push dev branch to remote")
    parser.add_argument("--ai-root", help="Dev env root (default: $AI_ROOT)")
    args = parser.parse_args()

    ai_root_str = args.ai_root or os.environ.get("AI_ROOT", "")
    ai_root = Path(ai_root_str) if ai_root_str else Path()
    if not ai_root or not ai_root.exists():
        print("Error: AI_ROOT not set or doesn't exist.", file=sys.stderr)
        sys.exit(1)

    ag = ai_root / "ai_general"
    branch_result = git("branch", "--show-current", cwd=ag)
    branch = branch_result.stdout.strip()

    if not branch:
        print("Error: could not determine current branch", file=sys.stderr)
        sys.exit(1)

    if not branch.startswith("dev/"):
        print(f"Error: branch '{branch}' is not a dev branch. Refusing to push.", file=sys.stderr)
        sys.exit(1)

    print(f"Pushing {branch} to origin...")
    result = git("push", "-u", "origin", branch, cwd=ag)

    if result.returncode != 0:
        print(f"Push failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"Pushed {branch} to origin")
    if result.stdout.strip():
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
