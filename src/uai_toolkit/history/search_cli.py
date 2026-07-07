#!/usr/bin/env python3
"""
CLI wrapper for search_lib.py — knowledge base search operations.

Subcommands:
    search      Search the knowledge base (topics, chat history, chunks)
    grep        Grep search across chunk files
    stats       Get search index statistics
    test        Test server connectivity and configuration

Output: JSON to stdout. Errors to stderr with non-zero exit.

Usage:
    python3 search_cli.py search "query text" [--max-results N] [--mode search|answer]
    python3 search_cli.py grep "pattern" [--max-results N]
    python3 search_cli.py stats
    python3 search_cli.py test
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure search_lib is importable
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from uai_toolkit.history import search_lib


def cmd_search(args):
    result = search_lib.search_knowledge_base(
        query=args.query,
        max_results=args.max_results,
        mode=args.mode,
        use_synonyms=not args.no_synonyms,
        max_tokens=args.max_tokens,
        output_file=args.output_file,
        retrieve_artifacts_flag=args.retrieve_artifacts,
    )
    print(json.dumps(result, indent=2, default=str))


def cmd_grep(args):
    result = search_lib.grep_search(
        query=args.query,
        max_results=args.max_results,
        use_synonyms=not args.no_synonyms,
        return_format=args.format,
        output_file=args.output_file,
    )
    print(json.dumps(result, indent=2, default=str))


def cmd_stats(_args):
    result = search_lib.get_search_stats()
    print(json.dumps(result, indent=2, default=str))


def cmd_test(_args):
    result = search_lib.test_server()
    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        prog="search_cli",
        description="Knowledge base search operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  search QUERY     Search knowledge base [--max-results N]
  grep PATTERN     Grep search across chunk files [--max-results N]
  stats            Get search index statistics
  test             Test connectivity and configuration

Use 'search_cli <command> --help' for full details.""",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("search", help="Search the knowledge base")
    p.add_argument("query", help="Search query text")
    p.add_argument("--max-results", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--mode", choices=["search", "answer", "auto"], default="auto",
                   help="Response mode (default: auto)")
    p.add_argument("--no-synonyms", action="store_true", help="Disable synonym expansion")
    p.add_argument("--max-tokens", type=int, default=None, help="Token budget constraint")
    p.add_argument("--output-file", action="store_true", help="Write results to .md file")
    p.add_argument("--retrieve-artifacts", action="store_true", help="Copy matching files to retrieval dir")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("grep", help="Grep search across chunk files")
    p.add_argument("query", help="Grep pattern")
    p.add_argument("--max-results", type=int, default=10, help="Max results (default: 10)")
    p.add_argument("--no-synonyms", action="store_true", help="Disable synonym expansion")
    p.add_argument("--format", choices=["condensed", "full"], default="condensed",
                   help="Return format (default: condensed)")
    p.add_argument("--output-file", action="store_true", help="Write results to .md file")
    p.set_defaults(func=cmd_grep)

    p = sub.add_parser("stats", help="Get search index statistics")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("test", help="Test connectivity and configuration")
    p.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        sys.exit(2)

    try:
        args.func(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
