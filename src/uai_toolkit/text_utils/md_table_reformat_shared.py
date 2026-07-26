#!/usr/bin/env python3
import sys
import re
import math
import json
import hashlib
import tempfile
import subprocess
from pathlib import Path

# Common logic extracted from md_table_reformat.py
BOLD_MARKER_WIDTH = 4
LONG_WORD_SPLIT_THRESHOLD = 15

def strip_backticks(text: str) -> str:
    return text.replace('`', '')

def expand_cell_newlines(text: str) -> list[str]:
    normalized = re.sub(r'<br\s*/?>', '\n', text)
    normalized = normalized.replace('\\n', '\n')
    return normalized.split('\n')

def cell_natural_width(text: str) -> int:
    lines = expand_cell_newlines(text)
    max_line = max(len(line) for line in lines) if lines else 0
    # Backtick tokens are atomic — ensure width accommodates the widest one
    backtick_tokens = re.findall(r'`[^`]+`', text)
    max_token = max((len(t) for t in backtick_tokens), default=0)
    return max(max_line, max_token)

def is_bold_cell(text: str) -> bool:
    stripped = text.strip()
    return (
        len(stripped) >= BOLD_MARKER_WIDTH
        and stripped.startswith('**')
        and stripped.endswith('**')
    )

def bold_cell_width(text: str) -> int:
    return cell_natural_width(text) + (0 if is_bold_cell(text) else BOLD_MARKER_WIDTH)

def header_content_width(text: str, width: int) -> int:
    if is_bold_cell(text):
        return width
    return max(width - BOLD_MARKER_WIDTH, 1)

def preferred_token_split(token: str, width: int) -> int:
    split_limit = min(max(width, 1), len(token) - 1)
    for idx in range(split_limit, 0, -1):
        if not token[idx - 1].isalpha():
            return idx
    for idx in range(split_limit, 0, -1):
        if idx < len(token) and not token[idx].isalpha():
            return idx
    return split_limit

def min_rendered_cell_width(text: str, bold: bool = False) -> int:
    """Return the narrowest width that will not overflow rendered cell text.

    This is intentionally token-based rather than natural-line based because the
    renderer is allowed to wrap on whitespace.  When a header is rendered bold,
    every wrapped header line receives leading/trailing ``**`` markers, so the
    unsplittable width for each token must include those four marker characters.
    """
    stripped = text.strip()
    # Headers are rendered bold by the caller, but data cells may already be
    # markdown-bold.  wrap_cell() treats a whole-cell ``**...**`` value by
    # wrapping the inner text and then re-applying ``**`` to every rendered
    # line, so those cells need the same marker-aware minimum width even when
    # they are not in the header row.
    cell_is_bold = is_bold_cell(stripped)
    rendered_bold = (bold or cell_is_bold) and bool(stripped)
    inner = stripped
    marker_width = 0

    if rendered_bold:
        marker_width = BOLD_MARKER_WIDTH
        if cell_is_bold:
            inner = inner[2:-2]

    min_width = 1
    for line in expand_cell_newlines(inner):
        tokens = re.findall(r'`[^`]+`|\S+', line)
        if not tokens:
            continue
        for token in tokens:
            token_width = len(token) + marker_width
            min_width = max(min_width, token_width)
    return min_width

def split_long_token(token: str, width: int) -> list[str]:
    parts = []
    remaining = token
    width = max(width, 1)
    while len(remaining) > width:
        split_at = preferred_token_split(remaining, width)
        parts.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        parts.append(remaining)
    return parts if parts else ['']

def wrap_plain_line(line: str, width: int) -> list[str]:
    width = max(width, 1)
    # Preservation of backticks: treat backtick-wrapped text as single unit if possible
    # We use a regex that respects content within backticks
    tokens = re.findall(r'`[^`]+`|\S+', line)
    if not tokens:
        return ['']

    wrapped = []
    current = ''

    for token in tokens:
        is_code = token.startswith('`') and token.endswith('`')
        should_split = (not is_code and len(token) > LONG_WORD_SPLIT_THRESHOLD and len(token) > width)
        if should_split:
            if current:
                wrapped.append(current)
                current = ''
            pieces = split_long_token(token, width)
            wrapped.extend(pieces[:-1])
            current = pieces[-1]
            continue

        if not current:
            current = token
        elif len(current) + 1 + len(token) <= width:
            current = f'{current} {token}'
        else:
            wrapped.append(current)
            current = token
    if current:
        wrapped.append(current)
    return wrapped if wrapped else ['']

def wrap_cell(text: str, width: int) -> list[str]:
    width = max(width, 1)
    stripped = text.strip()

    # Single backtick-wrapped token (e.g., `UserPromptSubmit`) — never split
    if re.match(r'^`[^`]+`$', stripped):
        return [stripped]

    # Bold-wrapped cell (e.g., **Header**) — wrap inner content, re-apply markers
    bold_match = re.match(r'^(\*\*)(.+)(\*\*)$', stripped)
    if bold_match:
        content = bold_match.group(2)
        content_width = max(width - 4, 1)  # 4 chars for ** **
        lines = []
        for line in expand_cell_newlines(content):
            lines.extend(wrap_plain_line(line, content_width))
        if not lines:
            return [stripped]
        return [f"**{l}**" for l in lines]

    # Plain text or mixed content — wrap normally, preserving backtick tokens
    result = []
    for line in expand_cell_newlines(stripped):
        result.extend(wrap_plain_line(line, width))
    return result if result else ['']
