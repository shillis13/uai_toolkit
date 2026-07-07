#!/usr/bin/env python3
"""
CLI wrapper for task_coord_lib.py.

Provides argparse subcommands matching every operation the workflow MCP
tools expose, so MCP tools can call this via subprocess instead of
importing the library directly.

Output: JSON or text to stdout (matches MCP tool formatting).
Errors: stderr with non-zero exit code.

Usage:
    python3 task_coord_cli.py test
    python3 task_coord_cli.py list_tasks --platform claude_cli --status staged
    python3 task_coord_cli.py gen_task planning claude_cli --params '{"GOAL":"test"}'
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

# --- sys.path setup (mirrors workflow MCP server.py) ---
AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[3]))
SCRIPTS = AI_ROOT / "ai_general" / "scripts"
MCPS_DIR = AI_ROOT / "ai_general" / "apps" / "mcps"

sys.path.insert(0, str(SCRIPTS / "tasks"))
sys.path.insert(0, str(MCPS_DIR))  # for shared/

from uai_toolkit.tasks import task_coord_lib

# Callback URI parsing
CALLBACK_LIB = Path.home() / "bin/ai/callbacks"
if str(CALLBACK_LIB) not in sys.path:
    sys.path.insert(0, str(CALLBACK_LIB))


def _resolve_callback(args):
    """Resolve callback from --callback (JSON) or --callback-uri."""
    if getattr(args, 'callback_uri', None):
        from uai_toolkit.callbacks.callback_lib import parse_endpoint
        ep = parse_endpoint(args.callback_uri)
        cb = {"type": ep.scheme if ep.scheme != "fifo" else "file", "endpoint_uri": args.callback_uri}
        if ep.scheme in ("file", "fifo"):
            cb["output_path"] = ep.path
        elif ep.scheme == "prompt":
            cb["target"] = ep.path
            cb["session"] = ep.session
            cb["submit"] = ep.submit
            cb["force"] = ep.force
        if ep.template:
            cb["message_template"] = ep.template
        return cb
    if getattr(args, 'callback', None):
        return json.loads(args.callback)
    return None


# === Subcommand handlers ===
# Each returns the value to print (str or serializable object).
# Raise SystemExit for errors.

def _json_out(obj):
    """Print an object as indented JSON to stdout."""
    print(json.dumps(obj, indent=2))


def _text_out(text):
    """Print text to stdout."""
    print(text)


def _error(msg, code=1):
    """Print error to stderr and exit."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


def cmd_test(_args):
    result = task_coord_lib.test_server()
    _json_out(result)


def cmd_list_playbooks(_args):
    playbooks = task_coord_lib.get_playbooks()
    _json_out(playbooks)


def cmd_get_playbook(args):
    content = task_coord_lib.get_playbook_content(args.name)
    if content is None:
        _error(f"Playbook not found: {args.name}")
    _text_out(content)


def cmd_start_playbook(args):
    params = json.loads(args.params) if args.params else {}
    callback = _resolve_callback(args)
    result = task_coord_lib.start_playbook(
        name=args.name,
        params=params,
        callback=callback,
    )
    if "error" in result:
        _error(result["error"])
    _text_out(result.get("output", ""))


def cmd_stop_playbook(args):
    result = task_coord_lib.stop_playbook(args.task_id)
    if "error" in result:
        _error(result["error"])
    _text_out(result.get("output", ""))


def cmd_list_templates(_args):
    templates = task_coord_lib.get_templates()
    _json_out(templates)


def cmd_gen_task(args):
    params = json.loads(args.params) if args.params else {}
    callback = _resolve_callback(args)
    result = task_coord_lib.gen_task(
        template=args.template,
        platform=args.platform,
        params=params,
        execute=args.execute,
        callback=callback,
    )
    if "error" in result:
        _error(result["error"])
    _text_out(result.get("output", ""))


def cmd_list_tasks(args):
    tasks = task_coord_lib.find_tasks(
        platform=args.platform,
        status=args.status,
    )
    _json_out(tasks)


def cmd_get_task(args):
    result = task_coord_lib.get_task_content(args.task_id)
    if "error" in result:
        _error(result["error"])
    _text_out(result.get("content", ""))


def cmd_move_task(args):
    result = task_coord_lib.move_task(
        task_id=args.task_id,
        new_status=args.status,
        platform=args.platform,
    )
    if "error" in result:
        _error(result["error"])
    _text_out(result.get("output", ""))


def cmd_list_platforms(_args):
    platforms = task_coord_lib.list_platforms()
    _json_out(platforms)


def cmd_start_watcher(args):
    watch_path = args.path
    if not Path(watch_path).exists():
        _error(f"Path does not exist: {watch_path}")
    if not task_coord_lib.WATCH_DIR_SCRIPT.exists():
        _error(f"watch_dir.sh not found at {task_coord_lib.WATCH_DIR_SCRIPT}")
    result = task_coord_lib.start_watcher(
        watch_path=watch_path,
        pattern=args.pattern,
        command=args.command or "",
        one_shot=args.one_shot,
        timeout=args.timeout,
        label=args.label or "",
    )
    _json_out(result)


def cmd_list_watchers(_args):
    watchers = task_coord_lib.list_watchers()
    _json_out(watchers)


def cmd_stop_watcher(args):
    result = task_coord_lib.stop_watcher(args.watcher_id)
    _json_out(result)


def cmd_cleanup_watchers(_args):
    count = task_coord_lib.cleanup_completed_watchers()
    _text_out(f"Cleaned up {count} completed watchers")


# === Dispatch table ===
# Maps subcommand name -> handler function (used by both one-shot CLI and REPL).

DISPATCH = {
    "test": cmd_test,
    "list_playbooks": cmd_list_playbooks,
    "get_playbook": cmd_get_playbook,
    "start_playbook": cmd_start_playbook,
    "stop_playbook": cmd_stop_playbook,
    "list_templates": cmd_list_templates,
    "gen_task": cmd_gen_task,
    "list_tasks": cmd_list_tasks,
    "get_task": cmd_get_task,
    "move_task": cmd_move_task,
    "list_platforms": cmd_list_platforms,
    "start_watcher": cmd_start_watcher,
    "list_watchers": cmd_list_watchers,
    "stop_watcher": cmd_stop_watcher,
    "cleanup_watchers": cmd_cleanup_watchers,
}


def build_parser():
    parser = argparse.ArgumentParser(
        description="CLI wrapper for task_coord_lib — task coordination operations.",
        prog="task_coord_cli.py",
    )
    subparsers = parser.add_subparsers(dest="command")

    # test
    subparsers.add_parser("test", help="Test server connectivity and configuration")

    # list_playbooks
    subparsers.add_parser("list_playbooks", help="List available playbooks")

    # get_playbook
    p = subparsers.add_parser("get_playbook", help="Get full playbook definition")
    p.add_argument("name", help="Playbook name")

    # start_playbook
    p = subparsers.add_parser("start_playbook", help="Start a playbook")
    p.add_argument("name", help="Playbook name")
    p.add_argument("--params", default=None, help="JSON object of parameters")
    p.add_argument("--callback", default=None, help="JSON callback config")
    p.add_argument("--callback-uri", default=None, help="Callback URI (e.g. prompt://claude-cli/session)")

    # stop_playbook
    p = subparsers.add_parser("stop_playbook", help="Stop/cancel a running playbook by task ID")
    p.add_argument("task_id", help="Task ID to cancel")

    # list_templates
    subparsers.add_parser("list_templates", help="List available task templates")

    # gen_task
    p = subparsers.add_parser("gen_task", help="Generate a task from template")
    p.add_argument("template", help="Template name")
    p.add_argument("platform", help="Target platform (claude_cli, codex_cli, etc)")
    p.add_argument("--params", default=None, help="JSON object of template parameters")
    p.add_argument("--execute", action="store_true", default=False,
                   help="Place in to_execute instead of staged")
    p.add_argument("--callback", default=None, help="JSON callback config")
    p.add_argument("--callback-uri", default=None, help="Callback URI (e.g. prompt://claude-cli/session)")

    # list_tasks
    p = subparsers.add_parser("list_tasks", help="List tasks, optionally filtered")
    p.add_argument("--platform", default=None, help="Filter by platform")
    p.add_argument("--status", default=None, help="Filter by status")

    # get_task
    p = subparsers.add_parser("get_task", help="Get task content by ID or path")
    p.add_argument("task_id", help="Task ID or full path")

    # move_task
    p = subparsers.add_parser("move_task", help="Move task to new status")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("status", help="New status (staged, to_execute, in_progress, completed, error, cancelled)")
    p.add_argument("--platform", default=None, help="Platform (if task_id is ambiguous)")

    # list_platforms
    subparsers.add_parser("list_platforms", help="List available task platforms")

    # start_watcher
    p = subparsers.add_parser("start_watcher", help="Start an fswatch-based file watcher")
    p.add_argument("path", help="Directory to watch")
    p.add_argument("pattern", help="Glob pattern to match")
    p.add_argument("--command", default=None, help="Command template ({filepath}, {filename}, {dir})")
    p.add_argument("--one-shot", dest="one_shot", action="store_true", default=True,
                   help="Exit after first match (default)")
    p.add_argument("--no-one-shot", dest="one_shot", action="store_false",
                   help="Continue watching after match")
    p.add_argument("--timeout", type=int, default=0, help="Timeout in seconds (0 = none)")
    p.add_argument("--label", default=None, help="Label for logs")

    # list_watchers
    subparsers.add_parser("list_watchers", help="List all active file watchers")

    # stop_watcher
    p = subparsers.add_parser("stop_watcher", help="Stop a running watcher")
    p.add_argument("watcher_id", help="Watcher ID to stop")

    # cleanup_watchers
    subparsers.add_parser("cleanup_watchers", help="Remove completed/stopped watchers from tracking")

    # repl (interactive mode)
    subparsers.add_parser("repl", help="Enter interactive REPL mode")

    return parser


def repl():
    """Interactive REPL for task coordination commands."""
    import readline  # noqa: F401 — enables arrow keys and history in input()

    parser = build_parser()

    # Build help text from parser subcommands
    cmd_help = {}
    for action in parser._subparsers._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                if name == "repl":
                    continue
                # Use the help= kwarg from add_parser()
                help_text = action._name_parser_map[name].format_usage().strip() if name in action._name_parser_map else ""
                # Try to get the help string directly
                for choice_action in action._choices_actions:
                    if choice_action.dest == name:
                        help_text = choice_action.help or help_text
                        break
                cmd_help[name] = help_text

    # Welcome message
    print("Task Coordination REPL — type 'help' for commands, 'q' to quit")
    print(f"Available commands: {', '.join(sorted(DISPATCH.keys()))}")
    print()

    while True:
        try:
            line = input("task> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue

        if not line:
            continue

        # Exit commands
        if line.lower() in ("quit", "exit", "q"):
            break

        # Help command
        if line.lower() == "help":
            print("\nAvailable commands:")
            # Find longest command name for alignment
            max_len = max(len(name) for name in DISPATCH)
            for name in sorted(DISPATCH):
                desc = cmd_help.get(name, "")
                print(f"  {name:<{max_len + 2}} {desc}")
            print(f"\n  {'help':<{max_len + 2}} Show this help message")
            print(f"  {'quit':<{max_len + 2}} Exit REPL (also: exit, q, Ctrl-D)")
            print()
            continue

        # Parse the input line
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            continue

        if not tokens:
            continue

        # Reject 'repl' inside repl
        if tokens[0] == "repl":
            print("Already in REPL mode.", file=sys.stderr)
            continue

        # Route through argparse + DISPATCH
        try:
            args = parser.parse_args(tokens)
        except SystemExit:
            # argparse calls sys.exit on error/--help; catch and continue
            continue

        handler = DISPATCH.get(args.command)
        if handler is None:
            print(f"Unknown command: {tokens[0]}", file=sys.stderr)
            print("Type 'help' for available commands.", file=sys.stderr)
            continue

        try:
            handler(args)
        except SystemExit as e:
            # _error() calls sys.exit; in REPL mode, catch it and continue
            if e.code and e.code != 0:
                pass  # error message already printed to stderr by _error()
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)


def main():
    # No arguments: enter REPL mode
    if len(sys.argv) == 1:
        repl()
        return

    parser = build_parser()
    args = parser.parse_args()

    # 'repl' subcommand: enter REPL mode
    if args.command == "repl":
        repl()
        return

    # No command provided (shouldn't happen with argv > 1, but be safe)
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    handler = DISPATCH.get(args.command)
    if handler is None:
        _error(f"Unknown command: {args.command}")

    try:
        handler(args)
    except SystemExit:
        raise
    except Exception as e:
        _error(str(e))


if __name__ == "__main__":
    main()
