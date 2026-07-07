#!/usr/bin/env python3
"""
CLI wrapper for lib_agent_ops.py — public subprocess boundary for CLI-agent tooling.

Subcommands mirror the 15 MCP tool operations in sessions_cli_agent.py.
Output: JSON to stdout. Errors: stderr + non-zero exit.

Usage:
    python3 agent_ops_cli.py list_sessions
    python3 agent_ops_cli.py launch_agent --platform claude_cli --role librarian --prompt "organize memories"
    python3 agent_ops_cli.py get_status --session-id claude_cli_librarian_20260430_120000
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


# --- sys.path setup (mirrors sessions/server.py) ---
AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[3]))
SCRIPTS = AI_ROOT / "ai_general" / "scripts"
sys.path.insert(0, str(SCRIPTS / "cli"))
sys.path.insert(0, str(SCRIPTS / "session_mgmt"))

from uai_toolkit.cli import lib_agent_ops as agent_ops


# === Subcommand handlers ===
# Each returns a dict (printed as JSON) or raises SystemExit on error.

def cmd_test(_args):
    """Test server connectivity and configuration."""
    result = agent_ops.test_server()
    result["sub_modules"] = {
        "cli_agent": "ok",
        "session": "loaded",
        "local_llm": "loaded",
    }
    return result


def cmd_launch_agent(args):
    """Launch a CLI agent with specified role and platform."""
    return agent_ops.launch_cli_agent(
        platform=args.platform,
        role=args.role,
        task_id=args.task_id,
        prompt=args.prompt,
        context_files=args.context_files,
        use_devtree=args.use_devtree,
    )


def _launch_role(role, args, default_platform="claude_cli"):
    """Shared launcher for role-specific subcommands."""
    platform = getattr(args, "platform", None) or default_platform
    return agent_ops.launch_cli_agent(
        platform=platform,
        role=role,
        task_id=getattr(args, "task_id", None),
        prompt=getattr(args, "prompt", None),
        context_files=getattr(args, "context_files", None),
        use_devtree=getattr(args, "use_devtree", False),
    )


def cmd_launch_librarian(args):
    return _launch_role("librarian", args)


def cmd_launch_dev_lead(args):
    return _launch_role("dev_lead", args)


def cmd_launch_custodian(args):
    return _launch_role("custodian", args)


def cmd_launch_peer_review(args):
    return _launch_role("peer_review", args)


def cmd_launch_tester(args):
    return _launch_role("tester", args)


def cmd_launch_researcher(args):
    """Launch researcher — hardcoded to claude_cli."""
    return agent_ops.launch_cli_agent(
        platform="claude_cli",
        role="researcher",
        task_id=getattr(args, "task_id", None),
        prompt=getattr(args, "prompt", None),
        context_files=getattr(args, "context_files", None),
        use_devtree=getattr(args, "use_devtree", False),
    )


def cmd_launch_validator(args):
    """Launch validator — defaults to codex_cli."""
    platform = getattr(args, "platform", None) or "codex_cli"
    return agent_ops.launch_cli_agent(
        platform=platform,
        role="validator",
        task_id=getattr(args, "task_id", None),
        prompt=getattr(args, "prompt", None),
        context_files=getattr(args, "context_files", None),
        use_devtree=getattr(args, "use_devtree", False),
    )


def cmd_kill(args):
    """Terminate a running agent session."""
    session_id = args.session_id
    if not agent_ops.session_exists(session_id):
        return {"success": False, "error": f"Session not found: {session_id}"}
    try:
        sub = agent_ops._get_substrate()
        sub.kill_session(session_id)
        return {"success": True, "message": f"Killed session: {session_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_attach(args):
    """Attach to an agent session (interactive)."""
    session_id = args.session_id
    if not agent_ops.session_exists(session_id):
        return {"success": False, "error": f"Session not found: {session_id}"}
    agent_ops.attach(session_id)
    return {"success": True}


def cmd_send_keys(args):
    """Send keystrokes to agent session."""
    session_id = args.session_id
    keys = args.keys
    enter = args.enter

    if not agent_ops.session_exists(session_id):
        return {"success": False, "error": f"Session not found: {session_id}"}
    try:
        script = agent_ops.AI_ROOT / "ai_general/scripts/prompting/lib_send_prompt.py"
        # lib_send_prompt.py `send` needs a platform target — infer from the session id
        if session_id.endswith("_cod") or session_id.startswith("codex_"):
            target = "codex-cli"
        elif session_id.endswith("_gem") or session_id.startswith("gemini_"):
            target = "gemini-cli"
        else:
            target = "claude-cli"
        cmd = [sys.executable, str(script), "send", target, keys, "--session", session_id]
        if enter:
            cmd.append("--submit")
        subprocess.run(cmd, capture_output=True, timeout=10)
        return {"success": True, "message": f"Sent keys to {session_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cmd_list_sessions(args):
    """List all active CLI agent sessions."""
    platform_filter = getattr(args, "platform", None)
    sessions = agent_ops.get_terminal_sessions()

    enriched = []
    for s in sessions:
        info = agent_ops.get_session_info(s["session_id"])
        if info:
            if platform_filter and info.get("platform") != platform_filter:
                continue
            enriched.append(info)

    return {"sessions": enriched, "count": len(enriched)}


def cmd_get_status(args):
    """Get detailed status of an agent session including recent output."""
    session_id = args.session_id
    output_lines = args.output_lines

    try:
        agent_ops._ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import get_ai_status, read_terminal

        registry_entry = agent_ops.resolve_registry_entry(session_id)
        platform_guess = registry_entry.get("platform") if registry_entry else "claude_cli"
        if platform_guess not in agent_ops.PLATFORMS:
            platform_guess = "claude_cli"

        ai_status = get_ai_status(session_id, platform=platform_guess)
        screen = read_terminal(session_id)
        last_lines = ""
        if screen:
            all_lines = screen.strip().split("\n")
            last_lines = "\n".join(all_lines[-output_lines:])

        status_result = {
            "session_status": ai_status,
            "last_output": last_lines,
        }

        info = agent_ops.get_session_info(session_id)
        if info:
            result = info
            ss = status_result.get("session_status", {})
            result["state"] = ss.get("state", "unknown")
            result["model"] = ss.get("model", "")
            result["context_pct"] = ss.get("context_pct", "")
            result["tokens"] = ss.get("tokens", 0)
            result["version"] = ss.get("version", "")
            result["permissions_mode"] = ss.get("permissions_mode", "")
            if ss.get("permission_detail"):
                result["permission_detail"] = ss["permission_detail"]
            result["last_output"] = status_result.get("last_output", "")
            return result
        else:
            return status_result

    except Exception:
        info = agent_ops.get_session_info(session_id)
        if not info:
            return {"success": False, "error": f"Session not found: {session_id}"}
        info["last_output"] = agent_ops.capture_pane_output(session_id, output_lines)
        return info


def cmd_read_session(args):
    """Read and parse terminal content from a CLI session."""
    session_id = args.session_id

    try:
        agent_ops._ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import read_terminal, get_ai_status

        if args.status_only:
            registry_entry = agent_ops.resolve_registry_entry(session_id)
            platform_guess = registry_entry.get("platform") if registry_entry else "claude_cli"
            if platform_guess not in agent_ops.PLATFORMS:
                platform_guess = "claude_cli"
            return get_ai_status(session_id, platform=platform_guess)

        screen = read_terminal(session_id)
        if not screen:
            return {"success": False, "error": f"No output from session: {session_id}"}

        fmt = args.format
        if fmt == "raw":
            return {"output": screen}
        elif fmt == "text":
            lines = [line for line in screen.split("\n") if line.strip()]
            return {"output": "\n".join(lines)}
        else:
            return {
                "session_id": session_id,
                "line_count": len(screen.split("\n")),
                "output": screen,
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


# === Argparse construction ===

def _add_common_launch_args(parser, include_platform=True, default_platform="claude_cli"):
    """Add arguments shared across all launch subcommands."""
    if include_platform:
        parser.add_argument(
            "--platform",
            choices=list(agent_ops.PLATFORMS.keys()),
            default=default_platform,
            help=f"Target platform (default: {default_platform})",
        )
    parser.add_argument("--task-id", dest="task_id", help="Task ID to execute (mutually exclusive with --prompt)")
    parser.add_argument("--prompt", help="Direct prompt for agent (mutually exclusive with --task-id)")
    parser.add_argument(
        "--context-files",
        dest="context_files",
        nargs="*",
        help="Additional files to load",
    )
    parser.add_argument(
        "--use-devtree",
        dest="use_devtree",
        action="store_true",
        default=False,
        help="Run in isolated devTree workspace",
    )


def build_parser():
    """Build the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="agent_ops_cli",
        description="CLI wrapper for lib_agent_ops — subprocess-callable interface for MCP tools.",
    )
    sub = parser.add_subparsers(dest="command")

    # --- test ---
    p = sub.add_parser("test", help="Test server connectivity and configuration")
    p.set_defaults(func=cmd_test)

    # --- launch_agent ---
    p = sub.add_parser("launch_agent", help="Launch a CLI agent with specified role and platform")
    p.add_argument("--platform", choices=list(agent_ops.PLATFORMS.keys()), required=True, help="Target platform")
    p.add_argument("--role", choices=agent_ops.ROLES, required=True, help="Agent role")
    p.add_argument("--task-id", dest="task_id", help="Task ID (mutually exclusive with --prompt)")
    p.add_argument("--prompt", help="Direct prompt (mutually exclusive with --task-id)")
    p.add_argument("--context-files", dest="context_files", nargs="*", help="Additional files to load")
    p.add_argument("--use-devtree", dest="use_devtree", action="store_true", default=False, help="Isolated devTree workspace")
    p.set_defaults(func=cmd_launch_agent)

    # --- role-specific launchers ---
    for role, handler, desc, default_plat in [
        ("launch_librarian", cmd_launch_librarian, "Launch librarian agent (memory system curator)", "claude_cli"),
        ("launch_dev_lead", cmd_launch_dev_lead, "Launch dev_lead agent (development coordinator)", "claude_cli"),
        ("launch_custodian", cmd_launch_custodian, "Launch custodian agent (repository maintainer)", "claude_cli"),
        ("launch_peer_review", cmd_launch_peer_review, "Launch peer_review agent (code/design reviewer)", "claude_cli"),
        ("launch_tester", cmd_launch_tester, "Launch tester agent (testing and validation)", "claude_cli"),
    ]:
        p = sub.add_parser(role, help=desc)
        _add_common_launch_args(p, include_platform=True, default_platform=default_plat)
        p.set_defaults(func=handler)

    # --- launch_researcher (no platform arg, hardcoded claude_cli) ---
    p = sub.add_parser("launch_researcher", help="Launch researcher agent (corpus search orchestrator)")
    p.add_argument("--task-id", dest="task_id", help="Existing task ID")
    p.add_argument("--prompt", help="Research query")
    p.add_argument("--context-files", dest="context_files", nargs="*", help="Additional files to load")
    p.add_argument("--use-devtree", dest="use_devtree", action="store_true", default=False, help="Isolated devTree workspace")
    p.set_defaults(func=cmd_launch_researcher)

    # --- launch_validator (defaults to codex_cli) ---
    p = sub.add_parser("launch_validator", help="Launch validator agent (adversarial I&T)")
    p.add_argument(
        "--platform",
        choices=["claude_cli", "codex_cli"],
        default="codex_cli",
        help="Target platform (default: codex_cli, must differ from synthesizer)",
    )
    p.add_argument("--task-id", dest="task_id", help="Query task ID containing synthesis to validate")
    p.add_argument("--prompt", help="Direct prompt")
    p.add_argument("--context-files", dest="context_files", nargs="*", help="Additional files to load")
    p.add_argument("--use-devtree", dest="use_devtree", action="store_true", default=False, help="Isolated devTree workspace")
    p.set_defaults(func=cmd_launch_validator)

    # --- kill ---
    p = sub.add_parser("kill", help="Terminate a running agent session")
    p.add_argument("--session-id", dest="session_id", required=True, help="Session ID to kill")
    p.set_defaults(func=cmd_kill)

    # --- attach ---
    p = sub.add_parser("attach", help="Get command to attach to agent session")
    p.add_argument("--session-id", dest="session_id", required=True, help="Session ID")
    p.set_defaults(func=cmd_attach)

    # --- send_keys ---
    p = sub.add_parser("send_keys", help="Send keystrokes to agent session")
    p.add_argument("--session-id", dest="session_id", required=True, help="Session ID")
    p.add_argument("--keys", required=True, help="Keys to send")
    p.add_argument("--no-enter", dest="enter", action="store_false", default=True, help="Do not press Enter after keys")
    p.set_defaults(func=cmd_send_keys)

    # --- list_sessions ---
    p = sub.add_parser("list_sessions", help="List all active CLI agent sessions")
    p.add_argument("--platform", choices=list(agent_ops.PLATFORMS.keys()), help="Filter by platform")
    p.set_defaults(func=cmd_list_sessions)

    # --- get_status ---
    p = sub.add_parser("get_status", help="Get detailed status of an agent session")
    p.add_argument("--session-id", dest="session_id", required=True, help="Session ID")
    p.add_argument("--output-lines", dest="output_lines", type=int, default=30, help="Lines of recent output (default: 30)")
    p.set_defaults(func=cmd_get_status)

    # --- read_session ---
    p = sub.add_parser("read_session", help="Read and parse terminal content from a CLI session")
    p.add_argument("--session-id", dest="session_id", required=True, help="Session ID")
    p.add_argument("--range", default="all", help="Line range: 'all', 'start:N', 'M:N', 'N:end'")
    p.add_argument("--format", choices=["json", "text", "raw"], default="json", help="Output format (default: json)")
    p.add_argument("--page-size", dest="page_size", type=int, default=500, help="Messages per page (default: 500)")
    p.add_argument("--page", type=int, default=1, help="Page number (default: 1)")
    p.add_argument("--platform-hint", dest="platform_hint", choices=["auto", "claude", "gemini", "codex"], default="auto", help="Platform override")
    p.add_argument("--status-only", dest="status_only", action="store_true", default=False, help="Return only session status")
    p.set_defaults(func=cmd_read_session)

    # --- repl ---
    p = sub.add_parser("repl", help="Enter interactive REPL mode")
    p.set_defaults(func=lambda _args: None)  # handled specially in main()

    return parser


# === Dispatch ===

def _resolve_session_arg(args):
    """Resolve session_id through session_store if present (handles URIs, display names)."""
    sid = getattr(args, "session_id", None)
    if not sid:
        return
    try:
        agent_ops._ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
        row = store.resolve(sid)
        if row:
            args.session_id = row.get("terminal_session") or row.get("tracking_id") or sid
    except Exception:
        pass


def dispatch(args):
    """Run the handler for the parsed subcommand and print result as JSON."""
    _resolve_session_arg(args)
    result = args.func(args)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")

    # Non-zero exit when the result signals failure
    if isinstance(result, dict) and result.get("success") is False:
        sys.exit(1)


# === REPL ===

# Subcommand names that are valid in the REPL (with descriptions for help).
# Kept in definition order for display. Populated lazily from the parser.
_REPL_COMMANDS = None


def _get_repl_commands(parser):
    """Extract subcommand names and help strings from the parser."""
    global _REPL_COMMANDS
    if _REPL_COMMANDS is not None:
        return _REPL_COMMANDS
    commands = []
    # Walk the subparsers action to get names + help text
    for action in parser._subparsers._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                if name == "repl":
                    continue  # don't list repl inside the repl
                desc = subparser.description or subparser.format_usage().strip()
                # Prefer the short help string from add_parser(help=...)
                for choice_action in action._choices_actions:
                    if choice_action.dest == name:
                        desc = choice_action.help or desc
                        break
                commands.append((name, desc))
    _REPL_COMMANDS = commands
    return _REPL_COMMANDS


def repl():
    """Interactive REPL for agent_ops_cli.

    Builds the parser once, then loops reading commands from stdin.
    Uses shlex.split() for shell-like tokenisation and routes everything
    through the standard argparse parser + dispatch().
    """
    import readline  # noqa: F401 — enables arrow keys and history in input()

    parser = build_parser()
    commands = _get_repl_commands(parser)

    # Derive the max command-name width for aligned help
    max_name = max(len(c[0]) for c in commands) if commands else 12

    def print_help():
        print("\nAvailable commands:")
        for name, desc in commands:
            print(f"  {name:<{max_name}}  {desc}")
        print(f"  {'help':<{max_name}}  Show this help message")
        print(f"  {'quit':<{max_name}}  Exit the REPL (also: exit, q)")
        print()

    print("agent_ops REPL — type 'help' for commands, 'q' to quit\n")

    while True:
        try:
            line = input("agent> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue

        if not line:
            continue

        # Built-in REPL-only commands
        if line.lower() in ("quit", "exit", "q"):
            break

        if line.lower() == "help":
            print_help()
            continue

        # Tokenise like a shell
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            continue

        # Parse through argparse — catch SystemExit so bad input doesn't kill the REPL
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse already printed its error message to stderr
            continue

        if not args.command:
            print("No command given. Type 'help' for available commands.", file=sys.stderr)
            continue

        # Dispatch — catch SystemExit (from dispatch failure exit codes) and exceptions
        try:
            dispatch(args)
        except SystemExit:
            # dispatch() calls sys.exit(1) on result failure — absorb it in REPL mode
            pass
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)


def main():
    # No arguments → enter REPL mode
    if len(sys.argv) == 1:
        repl()
        return

    parser = build_parser()
    args = parser.parse_args()

    # Explicit 'repl' subcommand
    if args.command == "repl":
        repl()
        return

    # One-shot mode requires a valid subcommand
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        dispatch(args)
    except Exception as exc:
        error = {"success": False, "error": str(exc)}
        json.dump(error, sys.stderr, indent=2)
        sys.stderr.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
