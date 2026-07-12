#!/usr/bin/env python3
from __future__ import annotations
"""
destroy_dev_env.py — Tear down a dev environment.

Removes the worktree, branch, and directory.
Warns about uncommitted changes unless --force.

Usage:
  destroy_dev_env.py <uuid> [--force]
  destroy_dev_env.py --help
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


DEV_TREES = Path.home() / "AI/devTrees"
DEFAULT_AI_ROOT_MAIN = Path.home() / "AI/ai_root"


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=30,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Tear down a dev environment")
    parser.add_argument("dev_id", help="Dev env ID (the uuid part of AI_ROOT_<uuid>)")
    parser.add_argument("--force", action="store_true", help="Delete even with uncommitted changes")
    parser.add_argument("--ai-root-main", default=str(DEFAULT_AI_ROOT_MAIN))
    args = parser.parse_args()

    ai_root_main = Path(args.ai_root_main)
    dev_root = DEV_TREES / f"AI_ROOT_{args.dev_id}"

    if not dev_root.exists():
        print(f"Not found: {dev_root}", file=sys.stderr)
        sys.exit(1)

    ag_dev = dev_root / "ai_general"
    ag_main = ai_root_main / "ai_general"

    # Check for uncommitted changes
    if ag_dev.exists() and (ag_dev / ".git").exists():
        try:
            status = git("status", "--short", cwd=ag_dev, check=False)
            if status and not args.force:
                print(f"Uncommitted changes in {ag_dev}:", file=sys.stderr)
                print(status, file=sys.stderr)
                print(f"Use --force to delete anyway.", file=sys.stderr)
                sys.exit(1)
        except Exception:
            pass

        # Remove worktree
        try:
            git("worktree", "remove", str(ag_dev), "--force", cwd=ag_main, check=False)
        except Exception:
            pass

        # Delete branch
        try:
            git("branch", "-D", f"dev/{args.dev_id}", cwd=ag_main, check=False)
        except Exception:
            pass

    # Remove the dev root
    shutil.rmtree(str(dev_root))
    print(f"Destroyed dev environment: {args.dev_id}")


if __name__ == "__main__":
    main()
