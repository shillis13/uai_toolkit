#!/usr/bin/env python3
"""
field_reorder.py — reorder fields/columns in delimited text.

Reads delimited text from a file, stdin/pipe, or the clipboard and writes the
reordered data to stdout.

Input sources:
    field_reorder.py --file data.csv --order id,name,status
    cat data.tsv | field_reorder.py --stdin -d tab --order 3,1,2
    field_reorder.py -p -d '|' --swap first:last
    field_reorder.py -v -d comma --header --order status,id

Ordering:
    --order SPEC       Comma-separated field refs. Refs are 1-based indexes by
                       default, or header names when --header is used.
                       Partial order is allowed: omitted fields are appended in
                       their original relative order unless --only is passed.

Swapping:
    --swap A:B         Swap two field refs. Can be repeated.
                       Swaps are applied after --order when both are provided.

Delimiter examples:
    -d comma           ,
    -d tab             tab character
    -d pipe            |
    -d ';'             semicolon
    -d '\t'            tab character

Examples:
    # Put Status and ID first, keep remaining columns after them
    field_reorder.py -f input.csv --header --order Status,ID

    # Output only selected fields, in order
    field_reorder.py -f input.csv --header --order Status,ID --only

    # Swap columns 1 and 3 in tab-delimited stdin
    pbpaste | field_reorder.py --stdin -d tab --swap 1:3

    # Clipboard in, pipe output back to clipboard
    field_reorder.py -p -d comma --header --order Email,Name | pbcopy
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

# Allow direct execution from the text_utils directory without requiring the
# caller to set PYTHONPATH.
PY_SRC = Path(__file__).resolve().parents[1]
if str(PY_SRC) not in sys.path:
    sys.path.insert(0, str(PY_SRC))

from uai_toolkit.file_utils.lib_fileInput import add_text_input_arguments, get_text_from_input


DELIMITER_ALIASES = {
    "comma": ",",
    "csv": ",",
    ",": ",",
    "tab": "\t",
    "tsv": "\t",
    "\\t": "\t",
    "pipe": "|",
    "bar": "|",
    "|": "|",
    "semi": ";",
    "semicolon": ";",
    ";": ";",
    "space": " ",
    "sp": " ",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Reorder fields/columns in delimited text.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(__doc__ or "").strip(),
    )
    add_text_input_arguments(parser)
    parser.add_argument(
        "-d",
        "--delimiter",
        default=",",
        help="Input delimiter: comma, tab, pipe, semicolon, space, or a literal char. Default: comma.",
    )
    parser.add_argument(
        "--output-delimiter",
        help="Output delimiter. Defaults to the input delimiter.",
    )
    parser.add_argument(
        "--header",
        action="store_true",
        help="Treat the first row as a header and allow header names in --order/--swap.",
    )
    parser.add_argument(
        "--order",
        help="Comma-separated new field order. Partial order allowed; unspecified fields are appended unless --only is used.",
    )
    parser.add_argument(
        "--only",
        action="store_true",
        help="Output only fields listed in --order instead of appending unspecified fields.",
    )
    parser.add_argument(
        "--swap",
        action="append",
        default=[],
        metavar="A:B",
        help="Swap two fields by 1-based index or header name. Can be repeated.",
    )
    parser.add_argument(
        "--no-trim-field-refs",
        action="store_true",
        help="Do not trim whitespace around names in --order or --swap specs.",
    )
    parser.add_argument(
        "--strict-width",
        action="store_true",
        help="Fail if a data row has a different field count than the reference row.",
    )
    return parser.parse_args(argv)


def parse_delimiter(value: str) -> str:
    """Resolve a delimiter alias or escaped delimiter into one character."""
    if value is None:
        return ","

    lowered = value.lower()
    if lowered in DELIMITER_ALIASES:
        delimiter = DELIMITER_ALIASES[lowered]
    else:
        delimiter = bytes(value, "utf-8").decode("unicode_escape")

    if len(delimiter) != 1:
        raise ValueError(f"Delimiter must resolve to exactly one character, got {value!r}.")

    return delimiter


def split_spec(spec: str | None, *, trim: bool = True) -> list[str]:
    """Split a comma-separated CLI spec into non-empty tokens."""
    if not spec:
        return []

    tokens = spec.split(",")
    if trim:
        tokens = [token.strip() for token in tokens]

    return [token for token in tokens if token]


def read_rows(text: str, delimiter: str) -> list[list[str]]:
    """Parse delimited text using Python's CSV reader."""
    if text == "":
        return []

    stream = io.StringIO(text)
    reader = csv.reader(stream, delimiter=delimiter)
    rows = [row for row in reader]
    return rows


def build_name_index(header: list[str]) -> dict[str, int]:
    """Build a case-sensitive header-name index and fail on duplicates."""
    name_index: dict[str, int] = {}
    duplicates: set[str] = set()

    for index, name in enumerate(header):
        if name in name_index:
            duplicates.add(name)
        name_index[name] = index

    if duplicates:
        dup_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate header names cannot be referenced safely: {dup_list}")

    return name_index


def resolve_field_ref(ref: str, field_count: int, name_index: dict[str, int] | None) -> int:
    """Resolve a 1-based index or header name to a zero-based index."""
    try:
        parsed = int(ref)
    except ValueError:
        parsed = None

    if parsed is not None:
        if parsed == 0:
            raise ValueError("Field indexes are 1-based; index 0 is invalid.")
        if parsed < 0:
            index = field_count + parsed
        else:
            index = parsed - 1
    else:
        if name_index is None:
            raise ValueError(f"Field ref {ref!r} is not numeric. Use --header for named refs.")
        if ref not in name_index:
            available = ", ".join(name_index.keys())
            raise ValueError(f"Unknown field name {ref!r}. Available names: {available}")
        index = name_index[ref]

    if index < 0 or index >= field_count:
        raise ValueError(f"Field ref {ref!r} resolves outside 1..{field_count}.")

    return index


def build_order(
    field_count: int,
    order_refs: list[str],
    swaps: list[str],
    *,
    only: bool,
    name_index: dict[str, int] | None,
) -> list[int]:
    """Build the output field order as zero-based indexes."""
    base_order = list(range(field_count))

    if order_refs:
        requested = [resolve_field_ref(ref, field_count, name_index) for ref in order_refs]
        seen: set[int] = set()
        deduped: list[int] = []
        for index in requested:
            if index in seen:
                raise ValueError(f"Field {index + 1} appears more than once in --order.")
            seen.add(index)
            deduped.append(index)

        if only:
            base_order = deduped
        else:
            base_order = deduped + [index for index in range(field_count) if index not in seen]

    for swap_spec in swaps:
        parts = split_spec(swap_spec.replace(":", ",", 1), trim=True)
        if len(parts) != 2:
            raise ValueError(f"Invalid --swap {swap_spec!r}; expected A:B.")
        left = resolve_field_ref(parts[0], field_count, name_index)
        right = resolve_field_ref(parts[1], field_count, name_index)

        try:
            left_pos = base_order.index(left)
            right_pos = base_order.index(right)
        except ValueError as exc:
            raise ValueError(
                f"Cannot swap {swap_spec!r} because one side is not present in the output order."
            ) from exc

        base_order[left_pos], base_order[right_pos] = base_order[right_pos], base_order[left_pos]

    return base_order


def reorder_row(row: list[str], order: list[int], reference_width: int, *, strict_width: bool) -> list[str]:
    """Return row fields in the requested order."""
    if strict_width and len(row) != reference_width:
        raise ValueError(
            f"Row has {len(row)} fields but expected {reference_width}: {row!r}"
        )

    output_row = []
    for index in order:
        if index < len(row):
            output_row.append(row[index])
        else:
            output_row.append("")

    return output_row


def write_rows(rows: list[list[str]], delimiter: str) -> str:
    """Serialize rows with CSV quoting and a stable newline terminator."""
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue()


def reorder_text(text: str, args: argparse.Namespace) -> str:
    """Reorder delimited text based on parsed args."""
    input_delimiter = parse_delimiter(args.delimiter)
    output_delimiter = parse_delimiter(args.output_delimiter or args.delimiter)
    rows = read_rows(text, input_delimiter)

    if not rows:
        return ""

    reference_row = rows[0]
    field_count = len(reference_row)
    trim_refs = not args.no_trim_field_refs
    name_index = build_name_index(reference_row) if args.header else None
    order_refs = split_spec(args.order, trim=trim_refs)
    output_order = build_order(
        field_count,
        order_refs,
        args.swap,
        only=args.only,
        name_index=name_index,
    )

    reordered_rows = [
        reorder_row(row, output_order, field_count, strict_width=args.strict_width)
        for row in rows
    ]
    return write_rows(reordered_rows, output_delimiter)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parsed_args = parse_args(argv if argv is not None else sys.argv[1:])

    try:
        input_text = get_text_from_input(parsed_args, default_to_clipboard=True)
        output_text = reorder_text(input_text, parsed_args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
