#!/usr/bin/env python3
"""session_mgr.py — Top-level CLI for session state operations.

Subcommands:
    state_get       Get a value by key
    state_set       Set a key-value pair
    state_delete    Delete a key
    state_increment Increment a numeric key
    state_decrement Decrement a numeric key
    state_list      List all keys (optional prefix filter)
    state_remove    Remove values from a list key
    state_seed      Seed env.* keys from environment variables
    get_footer      Assemble response footer
    get_ctx_used    Get context.* keys as JSON

Output: JSON to stdout for state_* and get_ctx_used.
        Formatted string for get_footer.
        Errors to stderr with non-zero exit.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path

# Bootstrap: ensure this script's directory is on sys.path so we can import store
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402


def _strip_uri(identifier):
    # type: (str) -> str
    """Extract session ID from a URI, or return as-is (centralized — see lib_uri)."""
    if '://' not in identifier:
        return identifier
    try:
        from uai_toolkit.session_mgmt.lib_uri import session_id_of
        return session_id_of(identifier)
    except Exception:
        return identifier


def _resolve_data_dir(tracking_id, data_dir_arg):
    # type: (str, str | None) -> str
    """Resolve the session data directory.

    Accepts any session identifier including URIs.
    1. If --data-dir was provided, use it directly.
    2. Otherwise, try SQLite lookup via session_store.py.
    3. If that fails, error with a clear message.
    """
    tracking_id = _strip_uri(tracking_id)
    if data_dir_arg:
        return data_dir_arg

    # Try SQLite resolution
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore as SQLiteStore
        sqlite_store = SQLiteStore()
        row = sqlite_store.resolve(tracking_id)
        if row and row.get("session_dir"):
            return row["session_dir"]
    except Exception:
        pass

    print(
        "Error: Cannot resolve session data directory for '{}'.\n"
        "Provide --data-dir explicitly, or ensure session_store.py SQLite "
        "is available.".format(tracking_id),
        file=sys.stderr,
    )
    sys.exit(1)


def _get_store(tracking_id, data_dir):
    # type: (str, str) -> Any
    """Create and return a SessionStore, ensuring the state file exists."""
    from uai_toolkit.session_mgmt.store import SessionStore
    store = SessionStore(tracking_id=tracking_id, session_data_dir=data_dir)
    # Ensure the state file exists (persist creates with defaults if missing)
    store.persist()
    return store


def _json_out(data):
    # type: (Any) -> None
    """Print data as JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def _parse_numeric(value_str):
    # type: (str) -> int | float
    """Parse a string as int or float."""
    try:
        return int(value_str)
    except ValueError:
        return float(value_str)


def _coerce_value(value_str):
    # type: (str) -> Any
    """Coerce a CLI string value to the appropriate Python type.

    - "true"/"false" -> bool
    - Integer strings -> int
    - Float strings -> float
    - Everything else -> str
    """
    lower = value_str.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(value_str)
    except ValueError:
        pass
    try:
        return float(value_str)
    except ValueError:
        pass
    return value_str


# --- Subcommand handlers ---

def cmd_state_get(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    value = store.get(args.key)
    _json_out({"key": args.key, "value": value})


def cmd_state_set(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    value = _coerce_value(args.value)
    try:
        result = store.set(args.key, value)
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    _json_out(result)


def cmd_state_delete(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    result = store.delete(args.key)
    _json_out(result)


def cmd_state_increment(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    try:
        result = store.increment(args.key, args.amount)
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    _json_out(result)


def cmd_state_decrement(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    try:
        result = store.decrement(args.key, args.amount)
    except ValueError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)
    _json_out(result)


def cmd_state_list(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    result = store.list_all(prefix=args.prefix)
    _json_out(result)


def cmd_state_remove(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    result = store.remove(args.key, args.values)
    if "error" in result:
        print("Error: {}".format(result["error"]), file=sys.stderr)
        sys.exit(1)
    _json_out(result)


def cmd_state_seed(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    var_names = [v.strip() for v in args.vars.split(",") if v.strip()]
    result = store.seed_from_env(var_names)
    _json_out(result)


def cmd_state_persist(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    path = store.persist()
    _json_out({"persisted": str(path)})


def cmd_state_load(args):
    # type: (argparse.Namespace) -> None
    # State is auto-loaded from state.{uuid8}.json on store init; "load" here means
    # "read back the full persisted state". (Was: store.load() — a method that never
    # existed on store.py's SessionStore, so this subcommand crashed with AttributeError.)
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    result = store.list_all()
    _json_out(result)


def cmd_get_ai_root(_args):
    # type: (argparse.Namespace) -> None
    ai_root = str(AI_ROOT)
    _json_out({"ai_root": ai_root, "exists": Path(ai_root).exists()})


def cmd_get_footer(args):
    # type: (argparse.Namespace) -> None
    from uai_toolkit.session_mgmt.build_footer import build_footer
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    result = build_footer(
        tracking_id=args.tracking_id,
        tags=args.tags,
        mode=args.mode,
        session_data_dir=data_dir,
    )
    print(result)


def cmd_get_ctx_used(args):
    # type: (argparse.Namespace) -> None
    data_dir = _resolve_data_dir(args.tracking_id, args.data_dir)
    store = _get_store(args.tracking_id, data_dir)
    all_state = store.list_all(prefix="context.")
    _json_out(all_state)


# --- Argument parsing ---

def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(
        prog="session_mgr.py",
        description="Session state management CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Common arguments for all subcommands
    def add_common_args(sub):
        # type: (argparse.ArgumentParser) -> None
        sub.add_argument("tracking_id", help="Session tracking ID")
        sub.add_argument("--data-dir", default=None, help="Session data directory (bypasses SQLite lookup)")

    # state_get
    p = subparsers.add_parser("state_get", help="Get a value by key")
    add_common_args(p)
    p.add_argument("key", help="Key to get")
    p.set_defaults(func=cmd_state_get)

    # state_set
    p = subparsers.add_parser("state_set", help="Set a key-value pair")
    add_common_args(p)
    p.add_argument("key", help="Key to set")
    p.add_argument("value", help="Value to set")
    p.set_defaults(func=cmd_state_set)

    # state_delete
    p = subparsers.add_parser("state_delete", help="Delete a key")
    add_common_args(p)
    p.add_argument("key", help="Key to delete")
    p.set_defaults(func=cmd_state_delete)

    # state_increment
    p = subparsers.add_parser("state_increment", help="Increment a numeric key")
    add_common_args(p)
    p.add_argument("key", help="Key to increment")
    p.add_argument("--amount", type=float, default=1, help="Amount to increment (default: 1)")
    p.set_defaults(func=cmd_state_increment)

    # state_decrement
    p = subparsers.add_parser("state_decrement", help="Decrement a numeric key")
    add_common_args(p)
    p.add_argument("key", help="Key to decrement")
    p.add_argument("--amount", type=float, default=1, help="Amount to decrement (default: 1)")
    p.set_defaults(func=cmd_state_decrement)

    # state_list
    p = subparsers.add_parser("state_list", help="List all keys (optional prefix filter)")
    add_common_args(p)
    p.add_argument("--prefix", default=None, help="Filter keys by prefix")
    p.set_defaults(func=cmd_state_list)

    # state_remove
    p = subparsers.add_parser("state_remove", help="Remove values from a list key")
    add_common_args(p)
    p.add_argument("key", help="List key to remove from")
    p.add_argument("values", help="Comma-separated values to remove")
    p.set_defaults(func=cmd_state_remove)

    # state_seed
    p = subparsers.add_parser("state_seed", help="Seed env.* keys from environment variables")
    add_common_args(p)
    p.add_argument("--vars", required=True, help="Comma-separated env var names to seed")
    p.set_defaults(func=cmd_state_seed)

    # state_persist
    p = subparsers.add_parser("state_persist", help="Save current session state to disk")
    add_common_args(p)
    p.set_defaults(func=cmd_state_persist)

    # state_load
    p = subparsers.add_parser("state_load", help="Show all persisted session state (key-values)")
    add_common_args(p)
    p.add_argument("--session-id", default=None, help="Session ID to load (defaults to tracking_id)")
    p.set_defaults(func=cmd_state_load)

    # get_ai_root
    p = subparsers.add_parser("get_ai_root", help="Resolve current AI_ROOT path")
    p.set_defaults(func=cmd_get_ai_root)

    # get_footer (stub)
    p = subparsers.add_parser("get_footer", help="Assemble response footer")
    add_common_args(p)
    p.add_argument("--tags", default="", help="Tags for footer")
    p.add_argument("--mode", choices=["brief", "full"], default=None, help="Footer mode")
    p.set_defaults(func=cmd_get_footer)

    # get_ctx_used
    p = subparsers.add_parser("get_ctx_used", help="Get context.* keys as JSON")
    add_common_args(p)
    p.set_defaults(func=cmd_get_ctx_used)

    return parser


def main():
    # type: () -> None
    parser = build_parser()
    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        sys.exit(2)

    args.func(args)


if __name__ == "__main__":
    main()
