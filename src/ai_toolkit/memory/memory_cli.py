#!/usr/bin/env python3
"""
Memory CLI — Thin subprocess-friendly wrapper around memory_lib.py.

Usage:
    python3 memory_cli.py get_manifest [--ai NAME]
    python3 memory_cli.py read SLOT [--since TS] [--limit N] [--oldest-first] [--ai NAME]
    python3 memory_cli.py append SLOT CONTENT [--ai NAME]
    python3 memory_cli.py update SLOT INDEX CONTENT [--ai NAME]
    python3 memory_cli.py delete SLOT [--index N] [--before TS] [--ai NAME]
    python3 memory_cli.py search QUERY [--slot N ...] [--regex] [--since TS] [--content-only] [--ai NAME]
    python3 memory_cli.py set_config SLOT [--name N] [--purpose P] [--load L] [--tags T ...] [--ai NAME]
    python3 memory_cli.py stats [--ai NAME]
"""

import argparse
import json
import os
import sys
from pathlib import Path

# --- Path setup (mirrors knowledge/server.py) ---
AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[3]))
SCRIPTS = AI_ROOT / "ai_general" / "scripts"
from ai_toolkit.memory import memory_lib


# === Subcommand handlers ===
# Each returns a dict (or raises). The dispatch table maps name -> handler.

def cmd_get_manifest(args):
    return memory_lib.op_get_manifest(ai=args.ai)


def cmd_read(args):
    return memory_lib.op_read(
        slot=args.slot,
        ai=args.ai,
        limit=args.limit,
        since=args.since,
        oldest_first=args.oldest_first,
    )


def cmd_append(args):
    return memory_lib.op_append(
        slot=args.slot,
        content=args.content,
        ai=args.ai,
    )


def cmd_update(args):
    return memory_lib.op_update(
        slot=args.slot,
        index=args.index,
        content=args.content,
        ai=args.ai,
    )


def cmd_delete(args):
    return memory_lib.op_delete(
        slot=args.slot,
        ai=args.ai,
        index=args.index,
        before=args.before,
    )


def cmd_search(args):
    return memory_lib.op_search(
        query=args.query,
        ai=args.ai,
        slots=args.slot if args.slot else None,
        regex=args.regex,
        since=args.since,
        content_only=args.content_only,
    )


def cmd_set_config(args):
    return memory_lib.op_set_slot_config(
        slot=args.slot,
        ai=args.ai,
        name=args.name,
        purpose=args.purpose,
        load=args.load,
        tags=args.tags if args.tags else None,
    )


def cmd_stats(args):
    return memory_lib.op_stats(ai=args.ai)


# === Argument parser ===

def build_parser():
    parser = argparse.ArgumentParser(
        prog="memory_cli",
        description="CLI wrapper for memory_lib slot operations",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- get_manifest --
    p = sub.add_parser("get_manifest", help="Get the working memory manifest")
    p.add_argument("--ai", default=None, help="AI instance name")
    p.set_defaults(func=cmd_get_manifest)

    # -- read --
    p = sub.add_parser("read", help="Read slot contents")
    p.add_argument("slot", type=int, help="Slot number")
    p.add_argument("--since", default=None, help="ISO timestamp — entries after this time")
    p.add_argument("--limit", type=int, default=None, help="Max entries to return")
    p.add_argument("--oldest-first", action="store_true", default=False,
                   help="Chronological order (default: newest first)")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_read)

    # -- append --
    p = sub.add_parser("append", help="Append a timestamped entry to a slot")
    p.add_argument("slot", type=int, help="Slot number")
    p.add_argument("content", help="Observation text to record")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_append)

    # -- update --
    p = sub.add_parser("update", help="Update entry at index (preserves timestamp)")
    p.add_argument("slot", type=int, help="Slot number")
    p.add_argument("index", type=int, help="Entry index (0-based)")
    p.add_argument("content", help="New content")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_update)

    # -- delete --
    p = sub.add_parser("delete", help="Delete entry by index or entries before a date")
    p.add_argument("slot", type=int, help="Slot number")
    p.add_argument("--index", type=int, default=None, help="Entry index to delete")
    p.add_argument("--before", default=None, help="ISO timestamp — delete entries before this")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_delete)

    # -- search --
    p = sub.add_parser("search", help="Search content across slots")
    p.add_argument("query", help="Search term or regex pattern")
    p.add_argument("--slot", type=int, action="append", default=None,
                   help="Slot(s) to search (repeatable; default: all)")
    p.add_argument("--regex", action="store_true", default=False,
                   help="Treat query as regex")
    p.add_argument("--since", default=None, help="ISO timestamp filter")
    p.add_argument("--content-only", action="store_true", default=True,
                   help="Match content field only (default: true)")
    p.add_argument("--all-fields", action="store_true", default=False,
                   help="Match against entire entry, not just content")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_search)

    # -- set_config --
    p = sub.add_parser("set_config", help="Update or create slot definition in manifest")
    p.add_argument("slot", type=int, help="Slot number")
    p.add_argument("--name", default=None, help="Slot name")
    p.add_argument("--purpose", default=None, help="Slot purpose description")
    p.add_argument("--load", default=None, choices=["AUTO", "TOPIC", "DEMAND"],
                   help="Load behavior")
    p.add_argument("--tags", nargs="+", default=None, help="Slot tags")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_set_config)

    # -- stats --
    p = sub.add_parser("stats", help="Get entry counts and sizes for all slots")
    p.add_argument("--ai", default=None)
    p.set_defaults(func=cmd_stats)

    return parser


# === Main ===

def main(argv=None):
    """Parse args, dispatch to handler, print JSON result. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # Handle --all-fields flipping content_only for search
    if args.command == "search" and args.all_fields:
        args.content_only = False

    try:
        result = args.func(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2, default=str), file=sys.stderr)
        return 1

    # Check for library-level errors (some ops return {"error": ...} without raising)
    if isinstance(result, dict) and "error" in result and result.get("success") is not True:
        print(json.dumps(result, indent=2, default=str), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
