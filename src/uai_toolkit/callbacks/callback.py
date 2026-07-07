#!/usr/bin/env python3
"""
Callback CLI — deliver a response to an endpoint URI.

The responder doesn't need to know what kind of endpoint it is.
Pass the URI you were given, pass the message. Done.

Usage:
    callback.py --endpoint "file:///tmp/resp.fifo" --msg "approved"
    callback.py --endpoint "prompt://claude-cli/session_name" --msg "review complete"
    callback.py --endpoint "fifo:///tmp/pipe" --msg "42"

    # Generate a URI (for originators)
    callback.py make-uri --scheme file --path /tmp/resp.txt
    callback.py make-uri --scheme fifo --path /tmp/resp.fifo
    callback.py make-uri --scheme prompt --target claude-cli --session abc123

    # Parse a URI into its component fields
    callback.py parse-uri "prompt://claude-cli/abc123?submit=true"

Exit codes:
    0 = delivered successfully
    1 = delivery failed
"""

import argparse
import json
import sys
from pathlib import Path

# Allow import from same directory
sys.path.insert(0, str(Path(__file__).parent))

from uai_toolkit.callbacks.callback_lib import execute_uri, make_endpoint_uri, parse_endpoint, CallbackResult


def cmd_deliver(args) -> int:
    """Deliver a message to an endpoint."""
    result: CallbackResult = execute_uri(args.endpoint, args.msg)
    if getattr(args, 'json_output', False):
        output = {
            "success": result.success,
            "message": result.message,
            "endpoint_type": result.endpoint_type,
        }
        print(json.dumps(output))
        return 0 if result.success else 1
    if result.success:
        print(f"OK: {result.message}")
        return 0
    print(f"FAIL: {result.message}", file=sys.stderr)
    return 1


def cmd_make_uri(args) -> int:
    """Generate an endpoint URI from parameters."""
    try:
        uri = make_endpoint_uri(
            scheme=args.scheme,
            path=args.path or args.target or "",
            session=args.session or "",
            template=args.template or "",
            submit=not args.no_submit,
            force=args.force,
        )
        print(uri)
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_parse_uri(args) -> int:
    """Parse an endpoint URI into its component fields."""
    try:
        ep = parse_endpoint(args.uri)
        result = {
            "scheme": ep.scheme,
            "path": ep.path,
            "session": ep.session,
            "template": ep.template,
            "submit": ep.submit,
            "force": ep.force,
        }
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description="Callback endpoint delivery")
    sub = parser.add_subparsers(dest="command")

    # Default: deliver (no subcommand needed if --endpoint is present)
    parser.add_argument("--endpoint", help="Callback endpoint URI")
    parser.add_argument("--msg", help="Message to deliver")
    parser.add_argument("--reply-to", help="This caller's endpoint URI (for bidirectional)")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        default=False, help="Output structured JSON instead of human text")

    # make-uri subcommand
    p_make = sub.add_parser("make-uri", help="Generate an endpoint URI")
    p_make.add_argument("--scheme", required=True, choices=["file", "fifo", "prompt", "none"])
    p_make.add_argument("--path", help="File/FIFO path")
    p_make.add_argument("--target", help="Prompt target (for prompt://)")
    p_make.add_argument("--session", help="Session ID (for prompt://)")
    p_make.add_argument("--template", help="Message template")
    p_make.add_argument("--no-submit", action="store_true", help="Don't press Enter (prompt://)")
    p_make.add_argument("--force", action="store_true", help="Force delivery (prompt://)")
    p_make.set_defaults(func=cmd_make_uri)

    # parse-uri subcommand
    p_parse = sub.add_parser("parse-uri", help="Parse an endpoint URI into components")
    p_parse.add_argument("uri", help="Callback endpoint URI to parse")
    p_parse.set_defaults(func=cmd_parse_uri)

    args = parser.parse_args()

    if args.command in ("make-uri", "parse-uri"):
        return args.func(args)

    # Default: deliver mode
    if not args.endpoint or not args.msg:
        parser.print_help()
        return 1

    return cmd_deliver(args)


if __name__ == "__main__":
    sys.exit(main())
