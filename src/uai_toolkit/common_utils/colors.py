#!/usr/bin/env python3
"""
DEPRECATED — use standard_colors.py instead.

    Old:  from uai_toolkit.common_utils.colors import C, G, c
          print(c(C, "text"))

    New:  from uai_toolkit.common_utils.standard_colors import c, success, error
          print(c("text", "cyan"))

Migration notes:
    - c(CODE, text) → c(text, "style_name")  (args reversed, named styles)
    - cp(CODE, text) → not yet in standard_colors (add if needed)
    - Raw codes (C, G, RED) → use c("text", "cyan"), c("text", "green"), etc.

This file is kept for backwards compatibility with existing scripts.
New code should use standard_colors.py exclusively.
"""

import sys
import warnings
warnings.warn(
    "colors.py is deprecated. Use 'from uai_toolkit.common_utils.standard_colors import c' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Raw ANSI codes
R = '\033[0m'        # reset
B = '\033[1m'        # bold
U = '\033[4m'        # underline
C = '\033[36m'       # cyan — names, commands, identifiers
G = '\033[32m'       # green — labels, success, field names
Y = '\033[33m'       # yellow — warnings, counts, urgency=prompt
M = '\033[35m'       # magenta — special values, scopes
DIM = '\033[2m'      # dim — secondary info, descriptions
W = '\033[97m'       # bright white — values, content
RED = '\033[31m'     # red — errors, danger, urgency=interrupt

# TTY detection — disable color when piped
USE_COLOR = sys.stdout.isatty()


def c(code: str, text: str) -> str:
    """Wrap text in ANSI color for print() output."""
    if USE_COLOR:
        return "{}{}{}".format(code, text, R)
    return text


def cp(code: str, text: str) -> str:
    """Wrap text in ANSI color for input() prompts (readline-safe)."""
    if USE_COLOR:
        return "\001{}\002{}\001{}\002".format(code, text, R)
    return text
