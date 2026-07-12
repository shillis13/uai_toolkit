#!/usr/bin/env python3
"""
pr_dev_env.py — Create a GitHub PR from a dev environment's branch.

Usage:
  pr_dev_env.py [--title TITLE] [--body BODY] [--ai-root PATH] [--draft]
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


def gh(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )


def main():
    parser = argparse.ArgumentParser(description="Create a PR from dev branch")
    parser.add_argument("--title", help="PR title (default: auto from branch name)")
    parser.add_argument("--body", help="PR body/description")
    parser.add_argument("--draft", action="store_true", help="Create as draft PR")
    parser.add_argument("--ai-root", help="Dev env root (default: $AI_ROOT)")
    args = parser.parse_args()

    ai_root_str = args.ai_root or os.environ.get("AI_ROOT", "")
    ai_root = Path(ai_root_str) if ai_root_str else None
    if not ai_root or not ai_root.exists():
        print("Error: AI_ROOT not set or doesn't exist.", file=sys.stderr)
        sys.exit(1)

    ag = ai_root / "ai_general"
    branch = git("branch", "--show-current", cwd=ag).stdout.strip()

    if not branch.startswith("dev/"):
        print(f"Error: branch '{branch}' is not a dev branch.", file=sys.stderr)
        sys.exit(1)

    # Ensure branch is pushed
    remote_check = git("rev-parse", "--verify", f"origin/{branch}", cwd=ag)
    if remote_check.returncode != 0:
        print(f"Pushing {branch} to origin first...")
        push = git("push", "-u", "origin", branch, cwd=ag)
        if push.returncode != 0:
            print(f"Push failed: {push.stderr.strip()}", file=sys.stderr)
            sys.exit(1)

    # Build title from branch name if not provided
    dev_id = branch.replace("dev/", "")
    title = args.title or f"dev: {dev_id.replace('_', ' ').replace('-', ' ')}"

    # Build body
    log = git("log", "main..HEAD", "--oneline", cwd=ag)
    commits = log.stdout.strip().splitlines() if log.stdout.strip() else []

    body_parts = []
    if args.body:
        body_parts.append(args.body)
    body_parts.append("\n## Commits")
    for c in commits[:20]:
        body_parts.append(f"- {c}")
    if len(commits) > 20:
        body_parts.append(f"- ... and {len(commits) - 20} more")
    body = "\n".join(body_parts)

    # Create PR
    pr_args = ["pr", "create", "--title", title, "--body", body, "--base", "main"]
    if args.draft:
        pr_args.append("--draft")

    print(f"Creating PR: {title}")
    result = gh(*pr_args, cwd=ag)

    if result.returncode != 0:
        print(f"PR creation failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    pr_url = result.stdout.strip()
    print(f"PR created: {pr_url}")


if __name__ == "__main__":
    main()
