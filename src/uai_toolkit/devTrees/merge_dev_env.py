#!/usr/bin/env python3
"""
merge_dev_env.py — Merge a dev branch back to main.

Usage:
  merge_dev_env.py [--ai-root PATH] [--no-delete] [--squash]

Merges from the dev branch into main (in the main worktree).
By default, suggests running destroy_dev_env.py afterward to clean up.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_AI_ROOT_MAIN = Path.home() / "AI/ai_root"


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )


def main():
    parser = argparse.ArgumentParser(description="Merge dev branch back to main")
    parser.add_argument("--ai-root", help="Dev env root (default: $AI_ROOT)")
    parser.add_argument("--ai-root-main", default=str(DEFAULT_AI_ROOT_MAIN),
                        help="Production ai_root path")
    parser.add_argument("--no-delete", action="store_true", help="Keep dev branch after merge")
    parser.add_argument("--squash", action="store_true", help="Squash merge into single commit")
    args = parser.parse_args()

    ai_root_str = args.ai_root or os.environ.get("AI_ROOT", "")
    ai_root = Path(ai_root_str) if ai_root_str else Path()
    ai_root_main = Path(args.ai_root_main)

    if not ai_root or not ai_root.exists():
        print("Error: AI_ROOT not set or doesn't exist.", file=sys.stderr)
        sys.exit(1)

    ag_dev = ai_root / "ai_general"
    ag_main = ai_root_main / "ai_general"

    # Get dev branch name
    branch_result = git("branch", "--show-current", cwd=ag_dev)
    branch = branch_result.stdout.strip()

    if not branch.startswith("dev/"):
        print(f"Error: current branch '{branch}' doesn't look like a dev branch", file=sys.stderr)
        sys.exit(1)

    # Verify main worktree is actually on main
    main_branch = git("branch", "--show-current", cwd=ag_main).stdout.strip()
    if main_branch != "main":
        print(f"Error: main worktree is on '{main_branch}', not 'main'. Cannot merge.", file=sys.stderr)
        sys.exit(1)

    # Check for uncommitted changes in dev
    dirty = git("diff", "--quiet", cwd=ag_dev)
    if dirty.returncode != 0:
        print("Error: uncommitted changes in dev env. Commit first.", file=sys.stderr)
        sys.exit(1)

    # Check for uncommitted changes in main
    dirty_main = git("diff", "--quiet", cwd=ag_main)
    if dirty_main.returncode != 0:
        print("Error: uncommitted changes in main worktree. Commit or stash first.", file=sys.stderr)
        sys.exit(1)

    # Show what will be merged
    log = git("log", "main..HEAD", "--oneline", cwd=ag_dev)
    commits = log.stdout.strip().splitlines() if log.stdout.strip() else []
    print(f"Branch: {branch}")
    print(f"Commits to merge: {len(commits)}")
    for c in commits[:10]:
        print(f"  {c}")
    if len(commits) > 10:
        print(f"  ... and {len(commits) - 10} more")

    # Merge into main
    print(f"\nMerging {branch} into main...")
    if args.squash:
        result = git("merge", "--squash", branch, cwd=ag_main)
        if result.returncode != 0:
            print(f"Squash merge failed: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        # Squash merge needs an explicit commit
        commit_result = git("commit", "-m", f"squash: merge {branch} into main", cwd=ag_main)
        if commit_result.returncode != 0:
            print(f"Commit failed: {commit_result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
        print("Squash merged and committed")
    else:
        result = git("merge", branch, cwd=ag_main)
        if result.returncode != 0:
            print(f"Merge failed: {result.stderr.strip()}", file=sys.stderr)
            print("\nTo abort: git -C ai_general merge --abort", file=sys.stderr)
            sys.exit(1)
        print("Merged successfully")

    # Check for changes in copied (non-symlinked) dirs that won't auto-merge
    copied_dirs = ["data"]
    for d in copied_dirs:
        dev_dir = ag_dev / d
        prod_dir = ag_main / d
        if dev_dir.exists() and prod_dir.exists():
            diff_result = subprocess.run(
                ["diff", "-rq", str(dev_dir), str(prod_dir)],
                capture_output=True, text=True,
            )
            if diff_result.stdout.strip():
                print(f"\nWarning: {d}/ was copied (not branched). These files differ from production:")
                for line in diff_result.stdout.strip().splitlines()[:15]:
                    # Simplify diff output
                    line = line.replace(str(dev_dir), f"dev:{d}").replace(str(prod_dir), f"prod:{d}")
                    print(f"  {line}")
                if len(diff_result.stdout.strip().splitlines()) > 15:
                    print(f"  ... and {len(diff_result.stdout.strip().splitlines()) - 15} more")
                print(f"  Copy manually if needed: cp -r {dev_dir}/* {prod_dir}/")

    dev_id = branch.replace("dev/", "")
    if args.no_delete:
        print(f"\nDev branch '{branch}' kept. Run destroy_dev_env.py {dev_id} when done.")
    else:
        print(f"\nTo clean up: python3 ~/bin/ai/devTrees/destroy_dev_env.py {dev_id}")


if __name__ == "__main__":
    main()
