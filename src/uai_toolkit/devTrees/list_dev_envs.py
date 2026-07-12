#!/usr/bin/env python3
"""
list_dev_envs.py — List active dev environments with status.

Usage:
  list_dev_envs.py [--json]
"""

import argparse
import json
import subprocess
from pathlib import Path


DEV_TREES = Path.home() / "AI/devTrees"


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def get_env_info(dev_root: Path) -> dict:
    dev_id = dev_root.name.replace("AI_ROOT_", "")
    ag = dev_root / "ai_general"

    info = {
        "id": dev_id,
        "path": str(dev_root),
        "branch": "",
        "status": "unknown",
        "dirty_files": 0,
        "ahead": 0,
        "behind": 0,
    }

    if not ag.exists():
        info["status"] = "broken"
        return info

    info["branch"] = git("branch", "--show-current", cwd=ag)

    # Dirty check
    status = git("status", "--short", cwd=ag)
    if status:
        info["status"] = "dirty"
        info["dirty_files"] = len(status.split("\n"))
    else:
        info["status"] = "clean"

    # Ahead/behind
    ab = git("rev-list", "--left-right", "--count", "origin/main...HEAD", cwd=ag)
    if ab:
        parts = ab.split()
        if len(parts) == 2:
            info["behind"] = int(parts[0])
            info["ahead"] = int(parts[1])

    return info


def main():
    parser = argparse.ArgumentParser(description="List active dev environments")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not DEV_TREES.exists():
        if args.json:
            print("[]")
        else:
            print("No dev environments found.")
        return

    envs = []
    for d in sorted(DEV_TREES.iterdir()):
        if d.is_dir() and d.name.startswith("AI_ROOT_"):
            envs.append(get_env_info(d))

    if not envs:
        if args.json:
            print("[]")
        else:
            print("No dev environments found.")
        return

    if args.json:
        print(json.dumps(envs, indent=2))
    else:
        print(f"{'ID':<12}  {'Branch':<20}  {'Status':<8}  {'Ahead':<6}  {'Behind':<7}  Path")
        print(f"{'----':<12}  {'------':<20}  {'------':<8}  {'-----':<6}  {'------':<7}  ----")
        for e in envs:
            print(f"{e['id']:<12}  {e['branch']:<20}  {e['status']:<8}  {e['ahead']:<6}  {e['behind']:<7}  {e['path']}")


if __name__ == "__main__":
    main()
