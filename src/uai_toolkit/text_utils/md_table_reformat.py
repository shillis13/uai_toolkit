#!/usr/bin/env python3
"""
md_table_reformat.py — Reflow markdown or box-drawing tables.
(Imports logic from md_table_reformat_shared.py)
"""
import sys
import re
import math
import json
import hashlib
import os
import tempfile
import subprocess
import textwrap
from pathlib import Path

AI_UTILS = Path.home() / "bin" / "ai" / "utils"
if str(AI_UTILS) not in sys.path:
    sys.path.insert(0, str(AI_UTILS))

from uai_toolkit.common_utils.standard_colors import c, command_style, error, format_help, value

from uai_toolkit.text_utils.md_table_reformat_shared import (
    cell_natural_width, is_bold_cell, bold_cell_width, header_content_width,
    min_rendered_cell_width, wrap_cell
)

def print_help() -> None:
    """Print comprehensive, colorized command help."""
    default_width = _default_width()
    help_text = textwrap.dedent(f"""
    {command_style("md_table_reformat.py")} — reflow one markdown/box-drawing table

    Usage:
        md_table_reformat.py [options] [-w <cols>]
        md_table_reformat.py --stdin [-w <cols>]
        md_table_reformat.py --file <table.md> [-w <cols>]
        pbpaste | md_table_reformat.py --stdin --width 100 | pbcopy

    Description:
        Reformats a single markdown pipe table or existing box-drawing table into
        a Unicode box-drawing table. Headers are rendered bold, cells are wrapped
        to fit the target width where possible, and code/backtick tokens are kept
        atomic.

        This command processes one table block. To reformat every table in a
        mixed prose markdown file, use:
            md_file_table_reformat.py <file>

    Input source:
        Default source is the macOS clipboard via /usr/bin/pbpaste.

    Options:
        -h, --help              Show this help and exit.
        --stdin, -              Read table text from stdin instead of clipboard.
        --file <path>           Read table text from a file instead of clipboard.
        -w, --width <cols>      Target maximum table width in columns.
        --no-color              Disable ANSI colors in help/errors.

    Arguments:
        WIDTH                   Deprecated compatibility syntax for target width.
                                Prefer -w/--width. Equivalent to --width WIDTH
                                when used.

    Width behavior:
        CLI width wins:
            --width 100
            100

        If no CLI width is provided, TABLE_MAX_WIDTH is used when set.
        Otherwise the default is 100.

        Current effective default: {value(str(default_width))}

        Minimum atomic widths are respected. If headers/backtick tokens cannot
        fit inside the target, output may exceed the requested width rather than
        corrupting alignment.

    Examples:
        # Reformat table currently on clipboard, write to stdout
        md_table_reformat.py

        # Clipboard input, explicit width
        md_table_reformat.py --width 120
        md_table_reformat.py -w 120

        # Deprecated compatibility syntax
        md_table_reformat.py 120

        # Stdin input
        cat table.md | md_table_reformat.py --stdin --width 100

        # File input
        md_table_reformat.py --file table.md --width 100

        # Keyboard Maestro / clipboard pipeline
        /usr/bin/pbpaste | md_table_reformat.py --stdin "$TABLE_MAX_WIDTH" | /usr/bin/pbcopy

    Supported input:
        Markdown pipe table:
            | Name | Role |
            |------|------|
            | Ada  | Dev  |

        Existing box-drawing table:
            ┌──────┬──────┐
            │ Name │ Role │
            └──────┴──────┘

    Related:
        md_file_table_reformat.py    Reformat all tables in a mixed markdown file.
        Reformat MD Table.kmmacros   Keyboard Maestro clipboard macro.
    """).strip()
    print(format_help(help_text))

def _default_width() -> int:
    env_width = os.environ.get("TABLE_MAX_WIDTH")
    if env_width:
        try:
            return int(env_width)
        except ValueError:
            return 100
    return 100

def _die(message: str, code: int = 2) -> None:
    error(message)
    print(
        f"  {c('Hint:', 'label')} run {command_style('md_table_reformat.py --help')}",
        file=sys.stderr,
    )
    sys.exit(code)

def parse_args(argv: list[str]) -> tuple[str, str | None, int]:
    source = 'clipboard'
    filepath = None
    max_width = _default_width()
    args = argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('--stdin', '-'):
            source = 'stdin'
        elif arg == '--file':
            source = 'file'
            i += 1
            if i >= len(args):
                _die("--file requires a path argument.")
            filepath = args[i]
        elif arg in ('--width', '-w'):
            i += 1
            if i >= len(args):
                _die(f"{arg} requires an integer width.")
            try:
                max_width = int(args[i])
            except ValueError:
                _die(f"Invalid width for {arg}: {args[i]!r}")
        elif arg == '--no-color':
            pass
        elif arg in ('--help', '-h'):
            print_help()
            sys.exit(0)
        else:
            try:
                max_width = int(arg)
            except ValueError:
                _die(f"Unknown option or invalid width: {arg!r}")
        i += 1
    return source, filepath, max_width

def get_input_text(source: str, filepath: str | None) -> str:
    if source == 'stdin': return sys.stdin.read()
    elif source == 'file': 
        with open(filepath, 'r') as f: return f.read()
    return subprocess.run(['/usr/bin/pbpaste'], capture_output=True, text=True).stdout

def _is_box_drawing(text: str) -> bool:
    """Check if text contains box-drawing characters."""
    return bool(re.search(r'[┌┐└┘├┤┬┴┼│─╔╗╚╝╠╣╦╩╬║═]', text))

def _parse_box_table(text: str) -> tuple[list[str], list[list[str]], set[int]]:
    """Parse a box-drawing table into headers, data rows, and separator positions."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    all_rows = []
    separator_after: set[int] = set()
    header_sep_seen = False
    data_row_index = -1

    for line in lines:
        stripped = line.strip()
        # Border/separator lines (contain ─ or ═ but no content cells)
        is_border = bool(re.match(r'^[┌┐└┘├┤┬┴┼─╔╗╚╝╠╣╦╩╬║═\s]+$', stripped))
        if is_border:
            if not header_sep_seen and all_rows:
                header_sep_seen = True
            elif header_sep_seen and data_row_index >= 0:
                separator_after.add(data_row_index)
            continue
        # Data row: split on │ or ║
        cells = re.split(r'[│║]', stripped)
        cells = [c.strip() for c in cells]
        if cells and cells[0] == '': cells = cells[1:]
        if cells and cells[-1] == '': cells = cells[:-1]
        # Strip bold markers from headers for re-processing
        cells = [re.sub(r'^\*\*(.+)\*\*$', r'\1', c) for c in cells]
        if cells:
            all_rows.append(cells)
            if header_sep_seen: data_row_index += 1

    if not all_rows: return [], [], set()
    return all_rows[0], all_rows[1:], separator_after

def _parse_pipe_table(text: str) -> tuple[list[str], list[list[str]], set[int]]:
    """Parse a pipe-style markdown table."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    all_rows = []
    separator_after: set[int] = set()
    header_sep_seen = False
    data_row_index = -1
    for line in lines:
        is_sep = bool(re.match(r'^\|?\s*[:\-]+\s*(\|?\s*[:\-]+\s*)*\|?$', line))
        if is_sep:
            if not header_sep_seen: header_sep_seen = True
            elif data_row_index >= 0: separator_after.add(data_row_index)
            continue
        cells = [c.strip() for c in line.split('|')]
        if cells and cells[0] == '': cells = cells[1:]
        if cells and cells[-1] == '': cells = cells[:-1]
        if cells:
            all_rows.append(cells)
            if header_sep_seen: data_row_index += 1
    if not all_rows: return [], [], set()
    return all_rows[0], all_rows[1:], separator_after

def parse_markdown_table(text: str) -> tuple[list[str], list[list[str]], set[int]]:
    if _is_box_drawing(text):
        return _parse_box_table(text)
    return _parse_pipe_table(text)

def render_table(headers, data_rows, max_width, separator_after):
    num_cols = max(len(headers), max((len(row) for row in data_rows), default=0))

    # Pad rows to uniform column count
    def pad(row):
        return row + [''] * (num_cols - len(row))

    all_rows = [pad(headers)] + [pad(r) for r in data_rows]

    # Calculate natural column widths (max content width per column)
    # Headers get bold markers added, so account for that extra width
    col_widths = []
    for c in range(num_cols):
        data_max = max((cell_natural_width(all_rows[r][c]) for r in range(1, len(all_rows))), default=0)
        header_text = all_rows[0][c].strip()
        header_w = bold_cell_width(header_text)  # accounts for ** markers if not already bold
        col_widths.append(max(data_max, header_w, 3))

    # Calculate minimum column widths (widest rendered atomic/unsplittable token
    # per column).  Headers are rendered with **bold markers**, so their minimum
    # widths must include those markers too; otherwise shrink-to-max-width can make
    # columns narrower than the actual header text and the box borders drift.
    min_widths = []
    for c in range(num_cols):
        min_w = 3
        for r in range(len(all_rows)):
            cell = all_rows[r][c]
            min_w = max(min_w, min_rendered_cell_width(cell, bold=(r == 0)))
        min_widths.append(min_w)

    # Shrink columns if total exceeds max_width
    overhead = 3 * num_cols + 1
    total_content = sum(col_widths)
    if total_content + overhead > max_width and max_width > overhead + num_cols:
        available = max_width - overhead
        # Proportional shrink, but never below minimum atomic width
        ratio = available / total_content
        col_widths = [max(int(w * ratio), min_widths[i]) for i, w in enumerate(col_widths)]
        # Proportional shrink plus min-width clamping can overshoot the target
        # when one or more columns have large atomic rendered tokens (notably
        # markdown-bold data cells: each wrapped line gets ** markers).  Pull
        # that excess back out of columns that are still above their minimums
        # so the rendered table honors max_width whenever the atomic minima
        # make that possible.
        excess = sum(col_widths) - available
        while excess > 0:
            shrinkable = [i for i, w in enumerate(col_widths) if w > min_widths[i]]
            if not shrinkable:
                break
            # Prefer shrinking the widest / most flexible column first.
            i = max(shrinkable, key=lambda idx: (col_widths[idx] - min_widths[idx], col_widths[idx]))
            col_widths[i] -= 1
            excess -= 1

        # Distribute rounding remainder to widest columns
        diff = available - sum(col_widths)
        if diff > 0:
            sorted_cols = sorted(range(num_cols), key=lambda i: -col_widths[i])
            for i in range(diff):
                col_widths[sorted_cols[i % num_cols]] += 1

    def hline(left, mid, right, fill='─'):
        segs = [fill * (w + 2) for w in col_widths]
        return left + mid.join(segs) + right

    def render_row(cells):
        # Wrap each cell and build multi-line output
        wrapped = [wrap_cell(cells[c], col_widths[c]) for c in range(num_cols)]
        max_lines = max(len(w) for w in wrapped)
        lines = []
        for ln in range(max_lines):
            parts = []
            for c in range(num_cols):
                cell_lines = wrapped[c]
                text = cell_lines[ln] if ln < len(cell_lines) else ''
                parts.append(text.ljust(col_widths[c]))
            lines.append('│ ' + ' │ '.join(parts) + ' │')
        return lines

    output = []
    output.append(hline('┌', '┬', '┐'))

    # Header row (bold)
    bold_headers = []
    for h in all_rows[0]:
        h = h.strip()
        if not is_bold_cell(h) and h:
            h = f'**{h}**'
        bold_headers.append(h)
    output.extend(render_row(bold_headers))
    output.append(hline('├', '┼', '┤'))

    # Data rows
    last_data = len(all_rows) - 2  # index of last data row
    for i, row in enumerate(all_rows[1:]):
        output.extend(render_row(row))
        if i < last_data:
            output.append(hline('├', '┼', '┤'))
        elif i in separator_after and i < last_data:
            output.append(hline('├', '┼', '┤'))

    output.append(hline('└', '┴', '┘'))
    return "\n".join(output)

def main():
    source, filepath, max_width = parse_args(sys.argv)
    text = get_input_text(source, filepath)
    headers, data_rows, separator_after = parse_markdown_table(text)
    print(render_table(headers, data_rows, max_width, separator_after))

if __name__ == '__main__':
    main()
