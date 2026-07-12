#!/usr/bin/env python3
from __future__ import annotations
"""
refresh_dev_env.py — Update dev branch and/or data from production.

Usage:
  refresh_dev_env.py [--rebase|--merge] [--data [FILE ...]] [--ai-root PATH]

Modes:
  (default)     Rebase/merge git branch from origin/main
  --data        Re-copy all of data/ from production
  --data FILE   Re-copy specific files (relative to ai_general/data/)

Both can be combined: refresh_dev_env.py --merge --data sessions.db
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_AI_ROOT_MAIN = Path.home() / "AI/ai_root"


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=120,
    )


def refresh_data(ai_root: Path, ai_root_main: Path, files: list[str] | None) -> None:
    """Re-copy data/ (or specific files within it) from production."""
    src_data = ai_root_main / "ai_general" / "data"
    dst_data = ai_root / "ai_general" / "data"

    if not src_data.exists():
        print(f"Error: production data/ not found at {src_data}", file=sys.stderr)
        sys.exit(1)

    if files:
        # Copy specific files
        for rel_path in files:
            src = src_data / rel_path
            dst = dst_data / rel_path
            if not src.exists():
                print(f"  Warning: {rel_path} not found in production, skipping", file=sys.stderr)
                continue
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(str(dst))
                shutil.copytree(str(src), str(dst),
                                symlinks=True, ignore_dangling_symlinks=True,
                                copy_function=shutil.copy2)
                print(f"  Refreshed: data/{rel_path}/ (directory)")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                print(f"  Refreshed: data/{rel_path}")
    else:
        # Copy entire data/ directory
        if dst_data.exists():
            shutil.rmtree(str(dst_data))
        shutil.copytree(str(src_data), str(dst_data),
                        symlinks=True, ignore_dangling_symlinks=True,
                        copy_function=shutil.copy2)
        print(f"  Refreshed: entire data/ directory")


def refresh_branch(ai_root: Path, strategy: str) -> None:
    """Rebase or merge latest main into dev branch."""
    ag = ai_root / "ai_general"
    branch = git("branch", "--show-current", cwd=ag).stdout.strip()
    if not branch.startswith("dev/"):
        print(f"Error: branch '{branch}' is not a dev branch. Refusing to {strategy}.", file=sys.stderr)
        sys.exit(1)
    print(f"Branch: {branch}")
    print(f"Strategy: {strategy}")

    # Check for uncommitted changes
    dirty = git("diff", "--quiet", cwd=ag)
    if dirty.returncode != 0:
        print("Error: uncommitted changes. Commit or stash first.", file=sys.stderr)
        git("status", "--short", cwd=ag)
        sys.exit(1)

    # Fetch latest
    print("Fetching origin/main...")
    fetch = git("fetch", "origin", "main", cwd=ag)
    if fetch.returncode != 0:
        print(f"Fetch failed: {fetch.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Apply strategy
    if strategy == "rebase":
        print("Rebasing on origin/main...")
        result = git("rebase", "origin/main", cwd=ag)
        if result.returncode != 0:
            print(f"Rebase failed — likely conflicts:", file=sys.stderr)
            print(result.stderr.strip(), file=sys.stderr)
            print("\nTo abort: git -C ai_general rebase --abort", file=sys.stderr)
            sys.exit(1)
    else:
        print("Merging origin/main...")
        result = git("merge", "origin/main", "-m", f"Merge main into {branch}", cwd=ag)
        if result.returncode != 0:
            print(f"Merge failed — likely conflicts:", file=sys.stderr)
            print(result.stderr.strip(), file=sys.stderr)
            print("\nTo abort: git -C ai_general merge --abort", file=sys.stderr)
            sys.exit(1)

    print(f"\nRefreshed {branch} via {strategy} from origin/main")

    # Show ahead/behind
    ab = git("rev-list", "--left-right", "--count", "origin/main...HEAD", cwd=ag)
    if ab.stdout.strip():
        parts = ab.stdout.strip().split()
        if len(parts) == 2:
            print(f"  {parts[1]} ahead, {parts[0]} behind main")


def main():
    parser = argparse.ArgumentParser(description="Update dev branch and/or data from production")
    parser.add_argument("--rebase", action="store_true", default=True, help="Rebase on main (default)")
    parser.add_argument("--merge", action="store_true", help="Merge main instead of rebase")
    parser.add_argument("--data", nargs="*", default=None, metavar="FILE",
                        help="Re-copy data/ from production. No args = all. With args = specific files (relative to data/)")
    parser.add_argument("--data-only", action="store_true",
                        help="Only refresh data, skip branch refresh")
    parser.add_argument("--ai-root", help="Dev env root (default: $AI_ROOT)")
    parser.add_argument("--ai-root-main", default=None,
                        help="Production ai_root path (default: $AI_ROOT_MAIN or ~/AI/ai_root)")
    args = parser.parse_args()

    ai_root_str = args.ai_root or os.environ.get("AI_ROOT", "")
    ai_root = Path(ai_root_str) if ai_root_str else Path()
    if not ai_root or not ai_root.exists():
        print("Error: AI_ROOT not set or doesn't exist.", file=sys.stderr)
        sys.exit(1)

    ai_root_main_str = args.ai_root_main or os.environ.get("AI_ROOT_MAIN", "")
    ai_root_main = Path(ai_root_main_str) if ai_root_main_str else DEFAULT_AI_ROOT_MAIN

    strategy = "merge" if args.merge else "rebase"

    # Refresh data if requested
    if args.data is not None:
        print("Refreshing data from production...")
        files = args.data if args.data else None
        refresh_data(ai_root, ai_root_main, files)

    # Refresh branch unless --data-only
    if not args.data_only:
        refresh_branch(ai_root, strategy)
    elif args.data is None:
        print("Error: --data-only requires --data", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
