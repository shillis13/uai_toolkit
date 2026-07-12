#!/usr/bin/env python3
"""
status_dev_env.py — Show detailed status of a dev environment.

Usage:
  status_dev_env.py [--ai-root PATH]
  status_dev_env.py <uuid>
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEV_TREES = Path.home() / "AI/devTrees"


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def du(path: Path) -> str:
    result = subprocess.run(
        ["du", "-sh", str(path)],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.split()[0] if result.returncode == 0 else "?"


def main():
    parser = argparse.ArgumentParser(description="Show dev environment status")
    parser.add_argument("dev_id", nargs="?", help="Dev env ID")
    parser.add_argument("--ai-root", help="Dev env path (alternative to ID)")
    args = parser.parse_args()

    if args.ai_root:
        dev_root = Path(args.ai_root)
    elif args.dev_id:
        dev_root = DEV_TREES / f"AI_ROOT_{args.dev_id}"
    else:
        # Try current AI_ROOT
        ai_root = os.environ.get("AI_ROOT", "")
        if "devTrees/AI_ROOT_" in ai_root:
            dev_root = Path(ai_root)
        else:
            print("Usage: status_dev_env.py <uuid> or --ai-root PATH", file=sys.stderr)
            sys.exit(1)

    if not dev_root.exists():
        print(f"Not found: {dev_root}", file=sys.stderr)
        sys.exit(1)

    ag = dev_root / "ai_general"
    dev_id = dev_root.name.replace("AI_ROOT_", "")

    print(f"Dev Environment: {dev_id}")
    print(f"  Path:       {dev_root}")
    print(f"  Disk:       {du(dev_root)}")
    print()

    if not ag.exists():
        print("  ai_general: MISSING")
        return

    # Git info
    branch = git("branch", "--show-current", cwd=ag)
    last_commit = git("log", "-1", "--oneline", cwd=ag)
    print(f"  Branch:     {branch}")
    print(f"  Last commit: {last_commit}")

    # Ahead/behind
    ab = git("rev-list", "--left-right", "--count", "origin/main...HEAD", cwd=ag)
    if ab:
        parts = ab.split()
        if len(parts) == 2:
            print(f"  vs main:    {parts[1]} ahead, {parts[0]} behind")

    # Dirty files
    status = git("status", "--short", cwd=ag)
    if status:
        lines = status.split("\n")
        print(f"  Dirty:      {len(lines)} files")
        for line in lines[:10]:
            print(f"    {line}")
        if len(lines) > 10:
            print(f"    ... and {len(lines) - 10} more")
    else:
        print(f"  Working tree: clean")

    print()

    # Symlink health
    print("  Symlinks:")
    for item in sorted(dev_root.iterdir()):
        if item.is_symlink():
            target = item.resolve()
            ok = target.exists()
            status_char = "OK" if ok else "BROKEN"
            print(f"    [{status_char}] {item.name} → {os.readlink(str(item))}")

    # ai_general internal symlinks
    print()
    print("  ai_general shared dirs:")
    for item in sorted(ag.iterdir()):
        if item.is_symlink():
            target = item.resolve()
            ok = target.exists()
            status_char = "OK" if ok else "BROKEN"
            print(f"    [{status_char}] {item.name}")

    # Editable dirs
    print()
    print("  ai_general editable dirs:")
    for d in ["scripts", "apps", "projects", "docs"]:
        p = ag / d
        if p.exists() and not p.is_symlink():
            print(f"    [REAL] {d}/")
        elif p.is_symlink():
            print(f"    [LINK] {d}/ (should be real!)")
        else:
            print(f"    [MISSING] {d}/")


if __name__ == "__main__":
    main()
