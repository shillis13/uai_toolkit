#!/usr/bin/env python3
from __future__ import annotations
"""
create_dev_env.py — Create an isolated dev environment.

Creates ~/AI/devTrees/AI_ROOT_<uuid>/ with:
- Git worktree of ai_general on branch dev/<uuid>
- Symlinks to production for shared dirs (ai_comms, ai_memories, ai_platforms, etc.)
- Real copies of data/ (not symlinked) for runtime isolation
- .envrc (direnv) with AI_ROOT — platform-agnostic, works for all CLI agents
- .claude/settings.local.json with AI_ROOT set

Usage:
  create_dev_env.py [--id UUID]
  create_dev_env.py --help

Output (last line, machine-readable):
  AI_ROOT=<path>
"""

import argparse
import json
import shutil
import subprocess
import sys
import uuid as _uuid
from pathlib import Path


DEV_TREES = Path.home() / "AI/devTrees"
DEFAULT_AI_ROOT_MAIN = Path.home() / "AI/ai_root"


def git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command, return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Create an isolated dev environment")
    parser.add_argument("--id", dest="dev_id", help="Dev env ID (default: auto-generate 8-char UUID)")
    parser.add_argument("--ai-root-main", default=str(DEFAULT_AI_ROOT_MAIN),
                        help="Production ai_root path")
    args = parser.parse_args()

    ai_root_main = Path(args.ai_root_main)
    dev_id = args.dev_id or str(_uuid.uuid4())[:8]
    dev_root = DEV_TREES / f"AI_ROOT_{dev_id}"

    # Idempotent — if already exists, just return
    if dev_root.exists():
        print(f"Dev environment already exists: {dev_root}", file=sys.stderr)
        print(f"AI_ROOT={dev_root}")
        return

    print(f"Creating dev environment: {dev_id}", file=sys.stderr)

    # Define paths upfront so cleanup handler can access them
    ag_main = ai_root_main / "ai_general"
    ag_dev = dev_root / "ai_general"

    # Create dirs
    DEV_TREES.mkdir(exist_ok=True)
    dev_root.mkdir()

    try:
        # --- Shared top-level dirs (symlinks to production) ---
        shared_dirs = [
            "ai_comms", "ai_memories", "ai_chat_artifacts",
            "ai_models", "ai_platforms",
        ]
        for d in shared_dirs:
            src = ai_root_main / d
            if src.exists():
                (dev_root / d).symlink_to(src)

        # --- Config files (symlinks) ---
        config_files = [
            "CLAUDE.md", "CLAUDE.local.md", "AGENTS.md",
            ".mcp.json", "ai_root.yml",
        ]
        for f in config_files:
            src = ai_root_main / f
            if src.exists():
                (dev_root / f).symlink_to(src)

        # --- ai_general: sparse checkout worktree (editable dirs only) ---
        editable_dirs = ["scripts", "apps", "projects", "docs"]
        shared_ag_dirs = [
            "config", "data", "logs", "prompts", "references",
            "research_and_reports", "roles", "templates", "todos", "workstate",
        ]

        # Create worktree without checking out files
        git("worktree", "add", "--no-checkout", "-b", f"dev/{dev_id}", str(ag_dev), "HEAD", cwd=ag_main)

        # Enable sparse checkout and set editable dirs only
        git("sparse-checkout", "init", "--cone", cwd=ag_dev)
        git("sparse-checkout", "set", *editable_dirs, cwd=ag_dev)
        git("checkout", cwd=ag_dev)

        # Dirs with mutable runtime state — copy instead of symlink
        copied_dirs = ["data"]

        # Symlink shared dirs, copy mutable dirs
        gitignore_entries = []
        for d in shared_ag_dirs:
            src = ag_main / d
            if not src.exists():
                continue
            if d in copied_dirs:
                shutil.copytree(str(src), str(ag_dev / d),
                                symlinks=True, ignore_dangling_symlinks=True,
                                copy_function=shutil.copy2)
            else:
                (ag_dev / d).symlink_to(src)
            gitignore_entries.append(f"/{d}")

        # Also symlink top-level ai_general files that aren't checked out
        # (e.g., .obsidian, .gitignore — things outside editable dirs)
        for item in ag_main.iterdir():
            target = ag_dev / item.name
            if item.name.startswith(".") and item.name not in [".git"]:
                if not target.exists():
                    target.symlink_to(item)
                    gitignore_entries.append(f"/{item.name}")
            elif item.is_file() and not target.exists():
                target.symlink_to(item)
                gitignore_entries.append(f"/{item.name}")

        # Write .gitignore so `git add -A` ignores symlinked shared dirs
        with open(ag_dev / ".gitignore", "w") as f:
            f.write("# DevTree: symlinked shared dirs — do not stage\n")
            for entry in gitignore_entries:
                f.write(entry + "\n")

        # --- .claude dir (real, not symlinked — project-scoped settings) ---
        claude_dir = dev_root / ".claude"
        claude_dir.mkdir(exist_ok=True)

        # Write settings.local.json with AI_ROOT
        settings = {
            "env": {
                "AI_ROOT": str(dev_root),
                "AI_ROOT_MAIN": str(ai_root_main),
            }
        }
        (claude_dir / "settings.local.json").write_text(json.dumps(settings, indent=2))

        # --- .envrc (direnv) — platform-agnostic AI_ROOT for all CLI agents ---
        envrc_path = dev_root / ".envrc"
        envrc_path.write_text(
            f'# DevTree environment — auto-loaded by direnv\n'
            f'export AI_ROOT="{dev_root}"\n'
            f'export AI_ROOT_MAIN="{ai_root_main}"\n'
        )
        # Auto-allow so direnv activates without manual intervention
        subprocess.run(["direnv", "allow", str(dev_root)],
                        capture_output=True, timeout=10)

        # Copy CLAUDE.md instructions from production .claude if they exist
        prod_claude = ai_root_main / ".claude"
        for f in ["settings.json"]:
            src = prod_claude / f
            if src.exists():
                shutil.copy2(str(src), str(claude_dir / f))

        print(f"", file=sys.stderr)
        print(f"Dev environment ready:", file=sys.stderr)
        print(f"  ID:       {dev_id}", file=sys.stderr)
        print(f"  Path:     {dev_root}", file=sys.stderr)
        print(f"  Branch:   dev/{dev_id}", file=sys.stderr)
        print(f"  Editable: ai_general/{{scripts,apps,projects,docs}}", file=sys.stderr)
        print(f"", file=sys.stderr)

    except Exception as e:
        # Cleanup on failure
        print(f"Error: {e}", file=sys.stderr)
        if ag_dev.exists():
            try:
                git("worktree", "remove", str(ag_dev), "--force", cwd=ag_main)
            except Exception:
                pass
            try:
                git("branch", "-D", f"dev/{dev_id}", cwd=ag_main)
            except Exception:
                pass
        if dev_root.exists():
            shutil.rmtree(str(dev_root))
        sys.exit(1)

    # Machine-readable output (last line)
    print(f"AI_ROOT={dev_root}")


if __name__ == "__main__":
    main()
