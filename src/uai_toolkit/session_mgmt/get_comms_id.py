#!/usr/bin/env python3
"""
get_comms_id.py -- Generate unique IDs for messaging infrastructure.

Usage:
    get_comms_id.py conversation    # prints conv_{YYYYMMDD_HHMMSS}_{random8}
    get_comms_id.py message         # prints msg_{YYYYMMDD_HHMMSS}_{random8}

Importable:
    from uai_toolkit.session_mgmt.get_comms_id import generate_conversation_id, generate_message_id
"""

import argparse
import random
import string
import sys
from datetime import datetime


def _generate_id(prefix: str) -> str:
    """Generate a unique ID: {prefix}_{YYYYMMDD_HHMMSS}_{random8}."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return "{}_{}_{}" .format(prefix, timestamp, suffix)


def generate_conversation_id() -> str:
    """Generate a new conversation ID."""
    return _generate_id("conv")


def generate_message_id() -> str:
    """Generate a new message ID."""
    return _generate_id("msg")


def main(argv=None):
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="get_comms_id",
        description="Generate unique IDs for messaging infrastructure.",
    )
    subs = parser.add_subparsers(dest="kind")
    subs.add_parser("conversation", help="Generate a conversation ID")
    subs.add_parser("message", help="Generate a message ID")

    args = parser.parse_args(argv)

    if args.kind == "conversation":
        print(generate_conversation_id())
        return 0
    elif args.kind == "message":
        print(generate_message_id())
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
