#!/usr/bin/env python3
"""Reformat all markdown tables in a file while preserving surrounding prose.

Scans a mixed-content markdown file line by line, detects pipe-style and
box-drawing table blocks, reformats each via md_table_reformat.py, and
reassembles the file with non-table content unchanged.

Library usage:
    from text_utils.md_file_table_reformat import reformat_file_tables
    output = reformat_file_tables(text, width=120)

CLI usage:
    md_file_table_reformat.py notes.md                # file arg, stdout
    md_file_table_reformat.py notes.md -w 80          # custom width
    md_file_table_reformat.py notes.md -i             # modify file in place
    md_file_table_reformat.py -f file1.md file2.md -i # batch in-place
    cat notes.md | md_file_table_reformat.py           # stdin, stdout
    md_file_table_reformat.py --stdin                  # explicit stdin
    md_file_table_reformat.py -f notes.md              # --file flag
"""

from __future__ import annotations

import argparse
import glob
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uai_toolkit.file_utils.lib_fileInput import get_text_from_input

_REFORMAT_SCRIPT = Path(__file__).resolve().parent / "md_table_reformat.py"

# md_table_reformat.py uses Python 3.10+ type syntax (str | None, list[str]).
# Discover a suitable interpreter once at import time.
_PYTHON_CANDIDATES = [
    sys.executable,
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
]


def _find_python() -> str:
    """Return the first Python >= 3.10 that is available.

    Falls back to sys.executable if nothing better is found.

    Returns:
        Path string for a suitable Python interpreter.
    """
    for candidate in _PYTHON_CANDIDATES:
        try:
            proc = subprocess.run(
                [candidate, "-c", "import sys; print(sys.version_info >= (3, 10))"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0 and proc.stdout.strip() == "True":
            return candidate
    return sys.executable


_PYTHON = _find_python()

# ---------------------------------------------------------------------------
# Table block detection
# ---------------------------------------------------------------------------

PIPE_LINE_RE = re.compile(r"^\s*\|")
PIPE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
BOX_TOP_RE = re.compile(r"[┌╔]")
BOX_BOTTOM_RE = re.compile(r"[┘╝]")
BOX_INTERIOR_RE = re.compile(r"^[│┃║├┤┼┬┴─═┌┐└┘╔╗╚╝╠╣╦╩╬]")


def _is_pipe_table_line(line: str) -> bool:
    """Return True if a line looks like part of a pipe-style markdown table."""
    result = bool(PIPE_LINE_RE.match(line))
    return result


def _is_pipe_separator_line(line: str) -> bool:
    """Return True if a line is a markdown pipe-table separator row."""
    result = bool(PIPE_SEPARATOR_RE.match(line))
    return result


def _looks_like_pipe_table_row(line: str) -> bool:
    """Return True if a line can be a pipe-table row without edge pipes."""
    stripped = line.strip()
    result = bool(stripped) and "|" in stripped
    return result


def _starts_pipe_table(line: str, next_line: str) -> bool:
    """Return True if a line starts a pipe table.

    Leading-pipe tables keep the historical permissive behavior.  Tables without
    leading/trailing pipes are only recognized when followed by a separator row,
    so prose containing an incidental pipe is not treated as a table.
    """
    if _is_pipe_table_line(line):
        return True
    result = _looks_like_pipe_table_row(line) and _is_pipe_separator_line(next_line)
    return result


def _is_box_drawing_line(line: str) -> bool:
    """Return True if a line appears to be part of a box-drawing table."""
    stripped = line.strip()
    if not stripped:
        return False
    result = bool(BOX_INTERIOR_RE.match(stripped))
    return result


def _starts_box_table(line: str) -> bool:
    """Return True if a line starts a box-drawing table (top border)."""
    result = bool(BOX_TOP_RE.search(line))
    return result


def _ends_box_table(line: str) -> bool:
    """Return True if a line ends a box-drawing table (bottom border)."""
    result = bool(BOX_BOTTOM_RE.search(line))
    return result


# ---------------------------------------------------------------------------
# Block extraction
# ---------------------------------------------------------------------------

def _extract_blocks(text: str) -> List[Tuple[str, str]]:
    """Split text into tagged blocks of ('prose', text) or ('table', text).

    Correctly handles fenced code blocks so that pipe characters inside
    code fences are not mistaken for table rows.

    Args:
        text: The full file content to scan.

    Returns:
        A list of (tag, content) tuples where tag is 'prose' or 'table'.
    """
    lines = text.split("\n")
    blocks: List[Tuple[str, str]] = []
    prose_lines: List[str] = []
    table_lines: List[str] = []
    in_fence = False
    in_box_table = False

    def flush_prose() -> None:
        if prose_lines:
            blocks.append(("prose", "\n".join(prose_lines)))
            prose_lines.clear()

    def flush_table() -> None:
        if table_lines:
            blocks.append(("table", "\n".join(table_lines)))
            table_lines.clear()

    for idx, line in enumerate(lines):
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""

        # -- fenced code block tracking --
        if FENCE_RE.match(line):
            if in_fence:
                in_fence = False
                prose_lines.append(line)
                continue
            in_fence = True
            # If we were accumulating a table, that's an error in the
            # source -- flush whatever we have as prose.
            if table_lines:
                prose_lines.extend(table_lines)
                table_lines.clear()
            prose_lines.append(line)
            continue

        if in_fence:
            prose_lines.append(line)
            continue

        # -- box-drawing table --
        if not in_box_table and _starts_box_table(line) and _is_box_drawing_line(line):
            flush_prose()
            in_box_table = True
            table_lines.append(line)
            continue

        if in_box_table:
            table_lines.append(line)
            if _ends_box_table(line):
                in_box_table = False
                flush_table()
            continue

        # -- pipe-style table --
        if _starts_pipe_table(line, next_line):
            if not table_lines:
                flush_prose()
            table_lines.append(line)
            continue

        # Continuation rows for an already-started pipe table.  This supports
        # GitHub-style tables without leading/trailing pipes while avoiding prose
        # after a blank line (trailing blanks are trimmed/flushed below).
        if (
            table_lines
            and table_lines[-1].strip() != ""
            and _looks_like_pipe_table_row(line)
        ):
            table_lines.append(line)
            continue

        # A blank line while inside a pipe table: could be a gap between
        # sections of the same table, so tentatively include it.
        if table_lines and line.strip() == "":
            table_lines.append(line)
            continue

        # Non-table line encountered while we had a table accumulating.
        if table_lines:
            # Trim any trailing blank lines -- they belong to prose.
            trailing_blanks: List[str] = []
            while table_lines and table_lines[-1].strip() == "":
                trailing_blanks.append(table_lines.pop())
            flush_table()
            trailing_blanks.reverse()
            prose_lines.extend(trailing_blanks)

        prose_lines.append(line)

    # End of file: flush whatever remains.
    if table_lines:
        flush_table()
    if prose_lines:
        flush_prose()

    return blocks


# ---------------------------------------------------------------------------
# Reformatting
# ---------------------------------------------------------------------------

def _reformat_table_block(table_text: str, width: int) -> str:
    """Reformat a single table block by piping it through md_table_reformat.py.

    Args:
        table_text: Raw text of one table (pipe-style or box-drawing).
        width: Target table width (0 = auto-fit).

    Returns:
        Reformatted table as a string, or the original text if the
        subprocess fails or produces no output.
    """
    cmd = [_PYTHON, str(_REFORMAT_SCRIPT), "--stdin", str(width)]
    try:
        proc = subprocess.run(
            cmd,
            input=table_text,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return table_text

    if proc.returncode != 0 or not proc.stdout.strip():
        return table_text

    result = proc.stdout.rstrip("\n")
    return result


def reformat_file_tables(text: str, width: int = 120) -> str:
    """Reformat every table in a mixed-content markdown string.

    Args:
        text: Full file content (prose + tables).
        width: Target width for tables (0 = auto-fit, default 120).

    Returns:
        The file content with all tables reformatted.
    """
    blocks = _extract_blocks(text)
    parts: List[str] = []

    for tag, content in blocks:
        if tag == "table":
            reformatted = _reformat_table_block(content, width)
            parts.append(reformatted)
        else:
            parts.append(content)

    result = "\n".join(parts)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        description="Reformat all markdown tables in a file, preserving prose.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  md_file_table_reformat.py notes.md\n"
            "  md_file_table_reformat.py notes.md -w 80\n"
            "  md_file_table_reformat.py notes.md -i\n"
            "  md_file_table_reformat.py -f file1.md -f file2.md -i\n"
            "  md_file_table_reformat.py -f *.md -i\n"
            "  cat notes.md | md_file_table_reformat.py\n"
            "  md_file_table_reformat.py --stdin -w 100\n"
        ),
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Markdown file to process (reads stdin if omitted).",
    )
    parser.add_argument(
        "-w", "--width",
        type=int,
        default=120,
        help="Target table width (0 = auto-fit). Default: 120.",
    )
    parser.add_argument(
        "-i", "--in-place",
        action="store_true",
        help="Modify the file in place instead of writing to stdout.",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "-f", "--input-file",
        dest="input_files",
        action="append",
        nargs="+",
        metavar="FILE",
        help=(
            "Read input from one or more files. Can be repeated. "
            "Examples: -f file1.md -f file2.md, or -f *.md"
        ),
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read input text from stdin.",
    )
    source_group.add_argument(
        "-p",
        "--paste",
        action="store_true",
        help="Read input text from the clipboard.",
    )
    source_group.add_argument(
        "-v",
        "--clipboard",
        action="store_true",
        help="Read input text from the clipboard (alias for --paste).",
    )
    return parser


def _expand_input_file_args(raw_groups: Optional[List[List[str]]]) -> List[Path]:
    """Expand repeated/nargs input-file arguments into concrete paths.

    Args:
        raw_groups: argparse value for ``-f/--input-file``.

    Returns:
        Ordered list of resolved paths. Quoted glob patterns are expanded here;
        shell-expanded globs already arrive as multiple paths.
    """
    if not raw_groups:
        return []

    paths: List[Path] = []
    for group in raw_groups:
        for raw_item in group:
            expanded = Path(raw_item).expanduser()
            matches = glob.glob(str(expanded))
            if matches:
                for match in sorted(matches):
                    paths.append(Path(match).expanduser().resolve())
            else:
                paths.append(expanded.resolve())
    return paths


def _read_input(args: argparse.Namespace) -> Tuple[str, Optional[str]]:
    """Determine the input text and source path from parsed arguments.

    Args:
        args: Parsed CLI arguments.

    Returns:
        A (text, filepath) tuple. filepath is None when reading from stdin
        or clipboard.
    """
    # Positional file argument takes priority.
    if args.file is not None:
        filepath = Path(args.file).expanduser().resolve()
        text = filepath.read_text(encoding="utf-8")
        return text, str(filepath)

    input_files = _expand_input_file_args(getattr(args, "input_files", None))
    if input_files:
        if len(input_files) > 1:
            raise ValueError("_read_input only supports one file; use batch path")
        filepath = input_files[0]
        text = filepath.read_text(encoding="utf-8")
        return text, str(filepath)

    # Fall back to shared input helpers (--stdin, --paste).
    text = get_text_from_input(args, default_to_clipboard=False)

    return text, None


def _process_file(path: Path, width: int, in_place: bool) -> str:
    """Reformat tables in one file and optionally write the result in place."""
    text = path.read_text(encoding="utf-8")
    output = reformat_file_tables(text, width=width)
    if in_place:
        path.write_text(output, encoding="utf-8")
    return output


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for CLI invocation.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 on success, 1 on error).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    input_files = _expand_input_file_args(getattr(args, "input_files", None))
    if args.file is not None and input_files:
        print("Error: use either positional file or -f/--input-file, not both.", file=sys.stderr)
        return 1

    if input_files:
        failed = False
        for index, path in enumerate(input_files):
            try:
                output = _process_file(path, width=args.width, in_place=args.in_place)
            except OSError as exc:
                print(f"Error processing {path}: {exc}", file=sys.stderr)
                failed = True
                continue

            if args.in_place:
                print(f"Reformatted {path}", file=sys.stderr)
                continue

            if index > 0:
                sys.stdout.write("\n")
            sys.stdout.write(output)
            if output and not output.endswith("\n"):
                sys.stdout.write("\n")

        return 1 if failed else 0

    text, filepath = _read_input(args)
    if not text:
        print("Error: no input text provided.", file=sys.stderr)
        return 1

    output = reformat_file_tables(text, width=args.width)

    if args.in_place:
        if filepath is None:
            print("Error: --in-place requires a file path.", file=sys.stderr)
            return 1
        target = Path(filepath)
        target.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
        # Ensure a trailing newline if the output doesn't end with one.
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
