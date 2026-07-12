#!/usr/bin/env python3
"""
launch_from_brief.py -- Launch a new CLI session pre-loaded with a session brief file.

Creates a new session of the specified platform type, injecting the brief
file as initial context via --pre-prompt.

Usage:
  launch_from_brief.py --platform claude --brief /path/to/brief.yml
  launch_from_brief.py --platform codex --brief /path/to/brief.yml --name "successor session"

The brief file is read and prepended to the session's bootstrap prompt so the
successor AI has full context before receiving any user instructions.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT
_AI_ROOT = AI_ROOT
_LAUNCHER = _AI_ROOT / "ai_general" / "scripts" / "cli" / "ai_launch.py"
_CLI_DIR = _AI_ROOT / "ai_general" / "scripts" / "cli"
if str(_CLI_DIR) not in sys.path:
    sys.path.insert(0, str(_CLI_DIR))

from uai_toolkit.cli.lib_brief_loading import build_brief_load_prompt

PLATFORM_COMMANDS = {
    "claude": "claudeCli",
    "codex": "codexCli",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch a new CLI session with session brief context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--platform", required=True, choices=["claude", "codex"],
                        help="Platform to launch (claude, codex)")
    parser.add_argument("--brief", required=True,
                        help="Path to session brief YAML file to inject as context")
    parser.add_argument("--display-name", "--name", dest="display_name",
                        help="Display name for the new session")
    parser.add_argument("--workdir", "-w", help="Working directory for the session")
    parser.add_argument("--model", "-m", help="Model override")
    parser.add_argument("--ask-permissions", action="store_true",
                        help="Require permission prompts (launcher defaults to auto-approve)")
    parser.add_argument("--parent", help="Parent tracking ID (for lineage)")
    parser.add_argument("--prompt", help="Initial prompt to send after brief loads. If omitted, no initial prompt is sent.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the command that would be run, don't execute")

    args = parser.parse_args()

    # Validate brief file
    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"[error] Brief file not found: {brief_path}", file=sys.stderr)
        return 1

    # Build launcher command
    cmd_name = PLATFORM_COMMANDS[args.platform]

    # Resolve the symlink to get the actual launcher path
    # ai_launch.py is called via symlinks: claudeCli, codexCli
    symlink_dir = _AI_ROOT / "ai_general" / "scripts" / "cli"
    symlink_path = symlink_dir / cmd_name

    if symlink_path.exists():
        cmd = [sys.executable, str(symlink_path)]
    elif _LAUNCHER.exists():
        cmd = [sys.executable, str(_LAUNCHER)]
    else:
        print(f"[error] ai_launch.py not found at {_LAUNCHER}", file=sys.stderr)
        return 1

    # Brief files can be 50KB+ which exceeds command-line argument limits.
    # Use --pre-prompt with a read instruction so the launched session loads
    # the brief from disk as background context before user interaction.
    pre_prompt_text = build_brief_load_prompt(brief_path)
    cmd.extend(["--pre-prompt", pre_prompt_text])

    if args.display_name:
        cmd.extend(["--display-name", args.display_name])
    if args.workdir:
        cmd.extend(["--workdir", args.workdir])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.ask_permissions:
        cmd.append("--ask-permissions")
    if args.parent:
        cmd.extend(["--parent", args.parent])

    # Optional initial prompt
    if args.prompt:
        cmd.append(args.prompt)

    if args.dry_run:
        import shlex
        print(" ".join(shlex.quote(c) for c in cmd))
        return 0

    print(f"[launch] Platform: {args.platform}", file=sys.stderr)
    print(f"[launch] Brief: {brief_path}", file=sys.stderr)
    if args.display_name:
        print(f"[launch] Name: {args.display_name}", file=sys.stderr)

    result = subprocess.run(cmd, timeout=60)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
