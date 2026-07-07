#!/usr/bin/env python3
"""
fork_session.py — Fork a CLI session with optional one-shot mode and callbacks.

Resolves the parent session, cds to its project directory, and calls the CLI
wrapper with --fork-from. Supports one-shot execution with response file or
prompt-forwarding callbacks.

Absorbs fork_task.py's callback features. fork_into_dir.py's JSONL-copy
behavior is handled by the wrapper's --targetDir + --fork-from combination.

Usage:
  fork_session.py --from <id> --prompt "task" [options]

Examples:
  # Interactive fork
  fork_session.py --from devEnvs_HUD --prompt "implement the HUD feature"

  # One-shot with file output
  fork_session.py --from abc12345 --prompt "review this code" \\
      --oneshot --response-file /tmp/review.md

  # One-shot forwarding output as prompt to another session
  fork_session.py --from abc12345 --prompt "analyze the logs" \\
      --oneshot --prompt-target claude_cli_95993

  # With model override and timeout
  fork_session.py --from abc12345 --prompt "quick task" \\
      --model claude-sonnet-4-6 --oneshot --timeout 300

Spec reference: spec_session_identity_v3.md section 9
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure cli/ and session_mgmt/ are in path
_cli_scripts = Path(__file__).resolve().parent
_session_mgmt = _cli_scripts.parent / "session_mgmt"
for _d in (_cli_scripts, _session_mgmt):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.session_mgmt.lib_session import get_session_info, resolve_identifier, get_project_dir
from uai_toolkit.cli.lib_paths import AI_ROOT

SEND_PROMPT = Path.home() / "bin/ai/prompting/send_prompt.py"


def _get_wrapper(platform: str) -> Path:
    wrappers = {
        "claude": AI_ROOT / "ai_general/scripts/cli/claudeCli",
        "codex": AI_ROOT / "ai_general/scripts/cli/codexCli",
        "gemini": AI_ROOT / "ai_general/scripts/cli/geminiCli",
    }
    wrapper = wrappers.get(platform)
    if not wrapper or not wrapper.exists():
        print(f"Error: wrapper not found for '{platform}': {wrapper}", file=sys.stderr)
        sys.exit(1)
    return wrapper


def resolve_parent(identifier: str) -> tuple[str, str | None, str | None]:
    """Resolve parent identifier to (cli_uuid, project_dir, platform).

    Uses lib_session for v3 registry resolution, with fallback.
    """
    info = get_session_info(identifier)
    if info:
        project_dir = None
        if info.cli_session_id:
            proj = get_project_dir(info.platform, info.cli_session_id)
            if proj:
                project_dir = str(proj)
        # Normalize platform for wrapper lookup (claude_cli -> claude)
        platform = info.platform.replace("_cli", "") if info.platform else None
        return info.cli_session_id or identifier, project_dir, platform

    # Fallback: treat as raw UUID
    return identifier, None, None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fork a CLI session with optional one-shot mode and callbacks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required
    parser.add_argument(
        "--from", dest="session_id", required=True,
        help="Session to fork from (terminal session name, CLI UUID, or partial match)",
    )
    parser.add_argument(
        "--prompt", required=True,
        help="Prompt for the forked session",
    )

    # Platform and identity
    parser.add_argument(
        "--platform", choices=["claude", "codex", "gemini"],
        default="claude",
        help="AI platform (default: claude)",
    )
    parser.add_argument(
        "-s", "--session-name",
        help="Terminal session name (auto-generated if omitted)",
    )
    parser.add_argument("--model", help="Model override")

    # Execution mode
    parser.add_argument(
        "--oneshot", action="store_true",
        help="One-shot pipe mode: run prompt, capture output, exit",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Timeout in seconds for oneshot mode (default: 600)",
    )

    # Callbacks (oneshot mode)
    parser.add_argument(
        "--response-file", metavar="PATH",
        help="Write output to file on completion",
    )
    parser.add_argument(
        "--prompt-target", metavar="SESSION",
        help="Send output as prompt to target session on completion",
    )

    # Control
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print command without executing",
    )

    args = parser.parse_args(argv)

    # Validation
    if args.response_file and not args.oneshot:
        parser.error("--response-file requires --oneshot")
    if args.prompt_target and not args.oneshot:
        parser.error("--prompt-target requires --oneshot")

    return args


def build_command(args: argparse.Namespace, cli_uuid: str) -> list[str]:
    """Build the CLI wrapper command."""
    wrapper = _get_wrapper(args.platform)
    cmd = [sys.executable, str(wrapper), "--fork-from", cli_uuid]

    if args.oneshot:
        cmd.append("--oneshot")
        cmd.append("--direct")

    if args.session_name:
        cmd.extend(["-s", args.session_name])
    if args.model:
        cmd.extend(["--model", args.model])

    cmd.append("--")
    cmd.append(args.prompt)
    return cmd


def handle_response_file(output: str, path: str) -> str:
    """Write output to a file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output)
    return f"Response written to {path} ({len(output)} chars)"


def handle_prompt_target(output: str, target_session: str) -> str:
    """Send output as a prompt to a target session."""
    if not SEND_PROMPT.exists():
        return f"send_prompt.py not found at {SEND_PROMPT}"

    max_len = 4096
    prompt_text = output[:max_len]
    if len(output) > max_len:
        prompt_text += f"\n\n[Truncated — {len(output)} total chars, showing first {max_len}]"

    try:
        result = subprocess.run(
            [str(SEND_PROMPT), "--target", "claude-cli",
             "--session", target_session, "--message", prompt_text,
             "--submit", "--force"],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode == 0:
            return f"Prompt sent to {target_session}"
        return f"send_prompt.py failed (rc={result.returncode}): {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"send_prompt.py timed out sending to {target_session}"
    except Exception as e:
        return f"send_prompt.py error: {e}"


def run(args: argparse.Namespace) -> int:
    """Execute the fork."""
    cli_uuid, project_dir, detected_platform = resolve_parent(args.session_id)

    # Use detected platform if not explicitly specified
    if detected_platform and args.platform == "claude":
        args.platform = detected_platform

    project_dir = project_dir or str(AI_ROOT)
    if not Path(project_dir).exists():
        print(f"Warning: project_dir '{project_dir}' not found, using AI_ROOT", file=sys.stderr)
        project_dir = str(AI_ROOT)

    cmd = build_command(args, cli_uuid)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[fork_session] {now}")
    print(f"[fork_session] Parent: {cli_uuid[:12]}..." if len(cli_uuid) > 12 else f"[fork_session] Parent: {cli_uuid}")
    print(f"[fork_session] Platform: {args.platform}")
    print(f"[fork_session] Project: {project_dir}")
    print(f"[fork_session] Mode: {'oneshot' if args.oneshot else 'interactive'}")

    if args.dry_run:
        print(f"[fork_session] Command: {' '.join(cmd)}")
        return 0

    os.chdir(project_dir)

    if not args.oneshot:
        # Interactive mode
        try:
            result = subprocess.run(cmd)
            return result.returncode
        except KeyboardInterrupt:
            print(f"\n[fork_session] Interrupted")
            return 130

    # One-shot mode: capture output, apply timeout, handle callbacks
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=args.timeout, cwd=project_dir,
        )
        elapsed = time.time() - start_time
        output = result.stdout
        exit_code = result.returncode

        print(f"[fork_session] Completed in {elapsed:.1f}s (exit code: {exit_code})")
        print(f"[fork_session] Output: {len(output)} chars")

        if result.stderr:
            print(f"[fork_session] Stderr: {result.stderr[:200]}")

    except subprocess.TimeoutExpired:
        print(f"[fork_session] TIMEOUT after {args.timeout}s")
        return 1
    except Exception as e:
        print(f"[fork_session] ERROR: {e}")
        return 1

    # Handle callbacks
    if args.response_file:
        cb_result = handle_response_file(output, args.response_file)
        print(f"[fork_session] {cb_result}")

    if args.prompt_target:
        cb_result = handle_prompt_target(output, args.prompt_target)
        print(f"[fork_session] {cb_result}")

    if not args.response_file and not args.prompt_target and output.strip():
        print(f"\n--- Output ---")
        print(output)
        print(f"--- End ---")

    return exit_code


def main() -> int:
    args = parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
