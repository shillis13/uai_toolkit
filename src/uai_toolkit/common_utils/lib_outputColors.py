#!/usr/bin/env python3
"""
Unified ANSI color output for all Python tools.

Zero external dependencies. Platform-agnostic (macOS, Linux, Windows 10+).
Respects NO_COLOR (https://no-color.org/), TERM=dumb, and pipe detection.

Usage:
    from uai_toolkit.common_utils.lib_outputColors import Colors

    # Direct attribute usage
    print(f"{Colors.GREEN}success{Colors.RESET}")

    # Auto-reset helper (respects terminal detection)
    print(Colors.colorize("success", Colors.GREEN, Colors.BOLD))

    # Backward-compat named-string API
    print(colorize_string("warning", fore_color="yellow", style="bright"))
"""

import os
import sys
from typing import Optional


class Colors:
    """ANSI color codes with terminal detection."""

    _enabled: Optional[bool] = None

    # Styles
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground — basic (30-37)
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Foreground — bright (90-97)
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Aliases
    GRAY = "\033[90m"
    GREY = "\033[90m"

    # Background (41-47)
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"

    @classmethod
    def enabled(cls) -> bool:
        """Check whether color output is appropriate for current terminal."""
        if cls._enabled is None:
            cls._enabled = cls._detect()
        return cls._enabled

    @classmethod
    def disable(cls):
        """Force colors off."""
        cls._enabled = False

    @classmethod
    def enable(cls):
        """Force colors on."""
        cls._enabled = True

    @classmethod
    def _detect(cls) -> bool:
        if os.environ.get("NO_COLOR") is not None:
            return False
        if os.environ.get("TERM", "") == "dumb":
            return False
        if not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
            return False
        if os.name == "nt":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                return False
        return True

    @classmethod
    def colorize(cls, text: str, *codes: str) -> str:
        """Apply color codes to text. Returns plain text when colors disabled."""
        if not cls.enabled():
            return text
        prefix = "".join(codes)
        return f"{prefix}{text}{cls.RESET}" if prefix else text


# --- Backward-compatible API (used by fsFormat, treePrint, renameFiles, etc.) ---

_FORE_MAP = {
    "black": Colors.BLACK, "red": Colors.RED, "green": Colors.GREEN,
    "yellow": Colors.YELLOW, "blue": Colors.BLUE, "magenta": Colors.MAGENTA,
    "cyan": Colors.CYAN, "white": Colors.WHITE,
    "gray": Colors.GRAY, "grey": Colors.GREY,
}

_BACK_MAP = {
    "red": Colors.BG_RED, "green": Colors.BG_GREEN,
    "yellow": Colors.BG_YELLOW, "blue": Colors.BG_BLUE,
    "magenta": Colors.BG_MAGENTA, "cyan": Colors.BG_CYAN, "white": Colors.BG_WHITE,
}

_STYLE_MAP = {
    "bright": Colors.BOLD, "bold": Colors.BOLD,
    "dim": Colors.DIM, "italic": Colors.ITALIC,
    "underline": Colors.UNDERLINE, "reset_all": Colors.RESET,
}


def colorize_string(text, fore_color=None, back_color=None, style=None):
    """Return colorized string using named colors. No-op when colors disabled."""
    if not Colors.enabled():
        return str(text)
    codes = []
    if style:
        codes.append(_STYLE_MAP.get(style.lower(), ""))
    if back_color:
        codes.append(_BACK_MAP.get(back_color.lower(), ""))
    if fore_color:
        codes.append(_FORE_MAP.get(fore_color.lower(), ""))
    if not any(codes):
        return str(text)
    return f"{''.join(codes)}{text}{Colors.RESET}"


def print_colored(text, fore_color=None, back_color=None, style=None):
    """Print colorized text. No-op coloring when colors disabled."""
    print(colorize_string(text, fore_color=fore_color, back_color=back_color, style=style))
