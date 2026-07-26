#!/usr/bin/env python3
"""Clean text from clipboard, stdin, or a file.

Library usage:
    from text_utils.clean_text import clean_text
    cleaned = clean_text(raw_text)

CLI usage:
    clean_text                 # read clipboard, write cleaned text to stdout
    clean_text --stdin         # read stdin
    clean_text --file note.txt # read a file
    clean_text --copy          # copy cleaned output to clipboard as well as stdout

Default cleaning is intentionally conservative:
    - keep printable Unicode glyphs such as box drawing and bullets
    - preserve ANSI SGR color/style sequences so colored text can still render
    - convert common literal escaped controls ("\\n", "\\t", "\\u001b")
    - decode literal Unicode escapes such as "\\u2500" into printable glyphs
    - normalize CRLF/CR line endings to LF
    - normalize spacing characters such as no-break spaces to ordinary spaces
    - remove non-printable control characters while preserving newlines/tabs
    - trim trailing whitespace
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from uai_toolkit.file_utils.lib_fileInput import add_text_input_arguments, get_text_from_input

# Covers CSI, single-character ESC, and OSC escape sequences.
ANSI_ESCAPE_RE = re.compile(
    r"(?:"
    r"\x1B\][^\x07]*(?:\x07|\x1B\\)"  # OSC ... BEL/ST
    r"|\x1B\[[0-?]*[ -/]*[@-~]"          # CSI ... final byte
    r"|\x1B[@-Z\\-_]"                    # 2-byte ESC sequence
    r")"
)
ANSI_SGR_RE = re.compile(r"\x1B\[[0-9;:]*m")

TPUT_MARKER_RE = re.compile(
    r"(?:\$\(\s*(?:/usr/bin/)?tput\s+(?P<cmd1>setaf|setab|bold|sgr0|smul|rmul|dim)(?:\s+(?P<num1>\d+))?\s*\)"
    r"|`\s*(?:/usr/bin/)?tput\s+(?P<cmd2>setaf|setab|bold|sgr0|smul|rmul|dim)(?:\s+(?P<num2>\d+))?\s*`)"
)

ESCAPED_CONTROL_REPLACEMENTS = (
    ("\\r\\n", "\n"),
    ("\\n", "\n"),
    ("\\r", "\n"),
    ("\\t", "\t"),
    ("\\x1b", "\x1b"),
    ("\\x1B", "\x1b"),
    ("\\033", "\x1b"),
    ("\\u001b", "\x1b"),
    ("\\u001B", "\x1b"),
)

UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")

SPACE_REPLACEMENTS = {
    "\u00a0": " ",   # no-break space
    "\u1680": " ",
    "\u2000": " ",
    "\u2001": " ",
    "\u2002": " ",
    "\u2003": " ",
    "\u2004": " ",
    "\u2005": " ",
    "\u2006": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",
    "\u200a": " ",
    "\u202f": " ",
    "\u205f": " ",
    "\u3000": " ",
}

DECORATIVE_RANGES = (
    (0x2500, 0x257F),  # box drawing
    (0x2580, 0x259F),  # block elements
)

DECORATIVE_CHARS = {
    "●", "○", "◉", "◎", "◌", "◍", "◐", "◑", "◒", "◓",
    "•", "‣", "⁃", "◦",
    "⏺", "⏵", "⏸", "⏹", "⏭", "⏮",
    "⎿", "⏎", "↳", "↵",
}


def decode_literal_unicode_escapes(text: str) -> str:
    r"""Decode literal \uXXXX/\UXXXXXXXX escape text into Unicode characters."""
    def replace_match(match: re.Match[str]) -> str:
        hex_value = match.group(1) or match.group(2)
        try:
            return chr(int(hex_value, 16))
        except (TypeError, ValueError, OverflowError):
            return match.group(0)

    return UNICODE_ESCAPE_RE.sub(replace_match, text)


def decode_escaped_control_chars(text: str, *, decode_unicode: bool = True) -> str:
    """Decode common literal escaped control sequences without broad unicode_escape."""
    result = text
    if decode_unicode:
        result = decode_literal_unicode_escapes(result)
    for old, new in ESCAPED_CONTROL_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def _ansi_256_color(prefix: int, color_number: int) -> str:
    """Return ANSI SGR for tput setaf/setab color numbers."""
    if 0 <= color_number <= 7:
        return f"\x1b[{prefix + color_number}m"
    if 8 <= color_number <= 15:
        bright_prefix = 90 if prefix == 30 else 100
        return f"\x1b[{bright_prefix + color_number - 8}m"
    extended_prefix = 38 if prefix == 30 else 48
    return f"\x1b[{extended_prefix};5;{color_number}m"


def convert_tput_color_markers(text: str) -> str:
    """Convert command-substitution tput color markers into ANSI SGR sequences."""
    def replace_match(match: re.Match[str]) -> str:
        command = match.group("cmd1") or match.group("cmd2") or ""
        number_text = match.group("num1") or match.group("num2")

        if command == "setaf" and number_text is not None:
            return _ansi_256_color(30, int(number_text))
        if command == "setab" and number_text is not None:
            return _ansi_256_color(40, int(number_text))
        if command == "bold":
            return "\x1b[1m"
        if command == "dim":
            return "\x1b[2m"
        if command == "smul":
            return "\x1b[4m"
        if command == "rmul":
            return "\x1b[24m"
        if command == "sgr0":
            return "\x1b[0m"
        return match.group(0)

    return TPUT_MARKER_RE.sub(replace_match, text)


def strip_ansi(text: str) -> str:
    """Remove all ANSI and terminal escape sequences from text."""
    return ANSI_ESCAPE_RE.sub("", text)


def strip_non_color_ansi(text: str) -> str:
    """Remove terminal escapes except ANSI SGR color/style sequences."""
    def replace_match(match: re.Match[str]) -> str:
        sequence = match.group(0)
        if ANSI_SGR_RE.fullmatch(sequence):
            return sequence
        return ""

    return ANSI_ESCAPE_RE.sub(replace_match, text)


def normalize_newlines(text: str) -> str:
    """Normalize CRLF and CR line endings to LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_spacing_chars(text: str) -> str:
    """Replace unusual Unicode spaces with ordinary ASCII spaces."""
    return "".join(SPACE_REPLACEMENTS.get(char, char) for char in text)


def is_decorative_terminal_char(char: str) -> bool:
    """Return whether char is a known terminal UI/decorative glyph."""
    codepoint = ord(char)
    for start, end in DECORATIVE_RANGES:
        if start <= codepoint <= end:
            return True
    return char in DECORATIVE_CHARS


def remove_decorative_terminal_glyphs(text: str) -> str:
    """Remove terminal UI glyphs while avoiding word concatenation."""
    chars: list[str] = []
    length = len(text)

    for index, char in enumerate(text):
        if not is_decorative_terminal_char(char):
            chars.append(char)
            continue

        previous = chars[-1] if chars else ""
        next_char = ""
        for lookahead_index in range(index + 1, length):
            candidate = text[lookahead_index]
            if not is_decorative_terminal_char(candidate):
                next_char = candidate
                break

        if (
            previous
            and next_char
            and not previous.isspace()
            and not next_char.isspace()
        ):
            chars.append(" ")

    return "".join(chars)


def _protect_ansi(text: str, *, keep_all: bool) -> tuple[str, list[str]]:
    """Replace ANSI sequences with printable placeholders during control cleanup."""
    protected: list[str] = []
    pattern = ANSI_ESCAPE_RE if keep_all else ANSI_SGR_RE

    def replace_match(match: re.Match[str]) -> str:
        index = len(protected)
        protected.append(match.group(0))
        return f"@@CLEAN_TEXT_ANSI_{index}@@"

    return pattern.sub(replace_match, text), protected


def _restore_ansi(text: str, protected: list[str]) -> str:
    """Restore ANSI placeholders after control cleanup."""
    for index, sequence in enumerate(protected):
        text = text.replace(f"@@CLEAN_TEXT_ANSI_{index}@@", sequence)
    return text


def remove_non_printable(text: str, *, keep_tabs: bool = True) -> str:
    """Remove non-printable/control characters while preserving useful whitespace."""
    allowed = {"\n"}
    if keep_tabs:
        allowed.add("\t")

    chars: list[str] = []
    for char in text:
        if char in allowed:
            chars.append(char)
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            continue
        chars.append(char)
    return "".join(chars)


def strip_trailing_whitespace(text: str) -> str:
    """Strip trailing spaces/tabs from each line."""
    lines = text.split("\n")
    return "\n".join(line.rstrip(" \t") for line in lines)


def compact_horizontal_whitespace(text: str) -> str:
    """Collapse repeated spaces/tabs and trim line-edge spaces."""
    lines = []
    for line in text.split("\n"):
        compacted = re.sub(r"[ \t]+", " ", line).strip(" ")
        lines.append(compacted)
    return "\n".join(lines)


def collapse_blank_lines(text: str, *, max_blank_lines: int = 1) -> str:
    """Limit runs of blank lines to max_blank_lines."""
    max_blank_lines = max(max_blank_lines, 0)
    output: list[str] = []
    blank_count = 0

    for line in text.split("\n"):
        if line.strip():
            blank_count = 0
            output.append(line)
            continue
        blank_count += 1
        if blank_count <= max_blank_lines:
            output.append(line)

    return "\n".join(output)


def clean_text(
    text: str,
    *,
    decode_escapes: bool = True,
    decode_unicode_escapes: bool = True,
    convert_tput_colors: bool = True,
    preserve_colors: bool = True,
    keep_all_ansi: bool = False,
    remove_ansi: bool | None = None,
    normalize_spaces: bool = True,
    remove_decorative_glyphs: bool = False,
    compact_spaces: bool = False,
    remove_controls: bool = True,
    keep_tabs: bool = True,
    strip_trailing: bool = True,
    collapse_blanks: bool = False,
    max_blank_lines: int = 1,
) -> str:
    """Return cleaned text with printable glyphs and colors preserved by default.

    ``remove_ansi`` is retained as a compatibility alias. When set, it overrides
    ``preserve_colors``; ``remove_ansi=True`` strips colors too.
    """
    if remove_ansi is not None:
        preserve_colors = not remove_ansi

    result = text
    if decode_escapes:
        result = decode_escaped_control_chars(result, decode_unicode=decode_unicode_escapes)
    result = normalize_newlines(result)
    if normalize_spaces:
        result = normalize_spacing_chars(result)
    if convert_tput_colors:
        result = convert_tput_color_markers(result)

    protected_ansi: list[str] = []
    if keep_all_ansi:
        result, protected_ansi = _protect_ansi(result, keep_all=True)
    elif preserve_colors:
        result = strip_non_color_ansi(result)
        result, protected_ansi = _protect_ansi(result, keep_all=False)
    else:
        result = strip_ansi(result)

    if remove_decorative_glyphs:
        result = remove_decorative_terminal_glyphs(result)
    if remove_controls:
        result = remove_non_printable(result, keep_tabs=keep_tabs)
    if compact_spaces:
        result = compact_horizontal_whitespace(result)
    if strip_trailing:
        result = strip_trailing_whitespace(result)
    if collapse_blanks:
        result = collapse_blank_lines(result, max_blank_lines=max_blank_lines)
    if protected_ansi:
        result = _restore_ansi(result, protected_ansi)
    return result


def copy_to_clipboard(text: str) -> None:
    """Copy text to macOS clipboard if pbcopy is available."""
    subprocess.run(["/usr/bin/pbcopy"], input=text, text=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean text from stdin, a file, or the clipboard.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  clean_text\n"
               "  clean_text --stdin < raw.txt\n"
               "  clean_text --file raw.txt --no-colors\n"
               "  pbpaste | clean_text --stdin | pbcopy",
    )
    add_text_input_arguments(parser)
    parser.add_argument("--no-colors", action="store_true", help="Strip ANSI/tput color and style sequences.")
    parser.add_argument("--keep-ansi", action="store_true", help="Keep all ANSI escape sequences, not just color/style sequences.")
    parser.add_argument("--no-tput-colorize", action="store_true", help="Do not convert $(tput ...) color markers to ANSI colors.")
    parser.add_argument("--no-decode-escapes", action="store_true", help="Do not convert literal \\n/\\t escape text.")
    parser.add_argument("--no-decode-unicode", action="store_true", help="Do not decode literal \\uXXXX / \\UXXXXXXXX escape text.")
    parser.add_argument("--keep-unicode-spaces", action="store_true", help="Keep non-ASCII Unicode space characters such as no-break spaces.")
    parser.add_argument("--strip-decorative-glyphs", action="store_true", help="Remove box-drawing/status glyphs such as ─, ⏺, ⎿, and ●.")
    parser.add_argument("--keep-decorative-glyphs", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--compact-spacing", action="store_true", help="Collapse repeated horizontal spaces and trim line-edge spaces.")
    parser.add_argument("--keep-spacing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--keep-controls", action="store_true", help="Do not remove non-printable control characters.")
    parser.add_argument("--spaces-for-tabs", type=int, default=None, metavar="N", help="Expand tabs to N spaces after cleaning.")
    parser.add_argument("--keep-trailing", action="store_true", help="Keep trailing whitespace on each line.")
    parser.add_argument("--collapse-blank-lines", action="store_true", help="Collapse repeated blank lines.")
    parser.add_argument("--max-blank-lines", type=int, default=1, help="Blank lines to keep when collapsing; default 1.")
    parser.add_argument("--copy", action="store_true", help="Also copy cleaned output to the clipboard.")
    parser.add_argument("-o", "--output", help="Write cleaned text to a file instead of stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    raw_text = get_text_from_input(args, default_to_clipboard=True)

    cleaned = clean_text(
        raw_text,
        decode_escapes=not args.no_decode_escapes,
        decode_unicode_escapes=not args.no_decode_unicode,
        convert_tput_colors=not args.no_tput_colorize,
        preserve_colors=not args.no_colors,
        keep_all_ansi=args.keep_ansi,
        normalize_spaces=not args.keep_unicode_spaces,
        remove_decorative_glyphs=args.strip_decorative_glyphs,
        compact_spaces=args.compact_spacing,
        remove_controls=not args.keep_controls,
        strip_trailing=not args.keep_trailing,
        collapse_blanks=args.collapse_blank_lines,
        max_blank_lines=args.max_blank_lines,
    )
    if args.spaces_for_tabs is not None:
        cleaned = cleaned.expandtabs(args.spaces_for_tabs)

    if args.output:
        Path(args.output).expanduser().write_text(cleaned, encoding="utf-8")
    else:
        print(cleaned, end="")

    if args.copy:
        copy_to_clipboard(cleaned)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
