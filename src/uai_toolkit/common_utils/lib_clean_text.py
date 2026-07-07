"""Clean text utilities — strip ANSI, control chars, normalize whitespace.

Copied from ~/bin/all_languages/python/src/text_utils/clean_text.py
for use in ~/bin/ai/ scripts without the file_utils dependency.

Library usage:
    from uai_toolkit.common_utils.lib_clean_text import clean_text
    cleaned = clean_text(raw_text)
    cleaned = clean_text(raw_text, remove_ansi=True, collapse_blanks=True)
"""

from __future__ import annotations

import re
import unicodedata

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
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ",
    "\u2004": " ", "\u2005": " ", "\u2006": " ", "\u2007": " ",
    "\u2008": " ", "\u2009": " ", "\u200a": " ",
    "\u202f": " ", "\u205f": " ", "\u3000": " ",
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
    """Decode common literal escaped control sequences."""
    result = text
    if decode_unicode:
        result = decode_literal_unicode_escapes(result)
    for old, new in ESCAPED_CONTROL_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def _ansi_256_color(prefix: int, color_number: int) -> str:
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
        if command == "bold": return "\x1b[1m"
        if command == "dim": return "\x1b[2m"
        if command == "smul": return "\x1b[4m"
        if command == "rmul": return "\x1b[24m"
        if command == "sgr0": return "\x1b[0m"
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
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_spacing_chars(text: str) -> str:
    return "".join(SPACE_REPLACEMENTS.get(char, char) for char in text)


def is_decorative_terminal_char(char: str) -> bool:
    codepoint = ord(char)
    for start, end in DECORATIVE_RANGES:
        if start <= codepoint <= end:
            return True
    return char in DECORATIVE_CHARS


def remove_decorative_terminal_glyphs(text: str) -> str:
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
        if previous and next_char and not previous.isspace() and not next_char.isspace():
            chars.append(" ")
    return "".join(chars)


def _protect_ansi(text: str, *, keep_all: bool) -> tuple[str, list[str]]:
    protected: list[str] = []
    pattern = ANSI_ESCAPE_RE if keep_all else ANSI_SGR_RE
    def replace_match(match: re.Match[str]) -> str:
        index = len(protected)
        protected.append(match.group(0))
        return f"@@CLEAN_TEXT_ANSI_{index}@@"
    return pattern.sub(replace_match, text), protected


def _restore_ansi(text: str, protected: list[str]) -> str:
    for index, sequence in enumerate(protected):
        text = text.replace(f"@@CLEAN_TEXT_ANSI_{index}@@", sequence)
    return text


def remove_non_printable(text: str, *, keep_tabs: bool = True) -> str:
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
    lines = text.split("\n")
    return "\n".join(line.rstrip(" \t") for line in lines)


def compact_horizontal_whitespace(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        compacted = re.sub(r"[ \t]+", " ", line).strip(" ")
        lines.append(compacted)
    return "\n".join(lines)


def collapse_blank_lines(text: str, *, max_blank_lines: int = 1) -> str:
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
    """Return cleaned text with printable glyphs and colors preserved by default."""
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
