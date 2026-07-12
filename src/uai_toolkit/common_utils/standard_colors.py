#!/usr/bin/env python3
"""standard_colors — shared ANSI color library for ~/bin/ai/ scripts.

Zero dependencies. Respects NO_COLOR, --no-color, and non-TTY stdout.

Usage:
    from uai_toolkit.common_utils.standard_colors import c, success, error, warn, info, dim, bold, heading

    # Semantic helpers — print with prefix + color
    success("Server started")          # green checkmark
    error("File not found")            # red X
    warn("Disk 90% full")             # yellow warning
    info("Checking status...")         # cyan info

    # Inline styling — returns colored string
    print(f"Found {c('42', 'value')} results in {c('/tmp', 'path')}")
    print(f"{bold('Name:')} {dim('unknown')}")
    print(heading("Section Title"))

    # Raw colors
    print(c("hello", "red"))
    print(c("world", "green", "bold"))

    # Help formatting
    print(format_help('''
    Usage:
        mytool [options] <file>

    Options:
        -v, --verbose      Show detailed output
        -q, --quiet        Suppress all output
        --json             Output as JSON

    Examples:
        mytool status
        mytool --verbose /path/to/file
    '''))

Demo:
    python3 standard_colors.py
"""

from __future__ import annotations

import os
import sys

__all__ = [
    # Detection
    "colors_enabled", "set_color_mode",
    # Core
    "c", "strip_ansi",
    # Semantic print helpers
    "success", "error", "warn", "info",
    # Inline style functions (return strings)
    "bold", "dim", "heading", "value", "path_style", "command_style",
    # Help formatting
    "format_help",
    # Raw code access
    "CODES",
]


# =============================================================================
# Color detection
# =============================================================================

_color_override: bool | None = None  # None = auto-detect


def colors_enabled() -> bool:
    """Check if color output should be used.

    Respects (in priority order):
    1. Explicit override via set_color_mode()
    2. --no-color in sys.argv
    3. NO_COLOR env var (https://no-color.org/)
    4. TERM=dumb
    5. stdout.isatty()
    """
    if _color_override is not None:
        return _color_override
    if "--no-color" in sys.argv:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def set_color_mode(enabled: bool | None) -> None:
    """Force colors on/off, or None to restore auto-detection."""
    global _color_override
    _color_override = enabled


# =============================================================================
# ANSI escape codes — raw access
# =============================================================================

CODES: dict[str, str] = {
    # Reset
    "reset":          "\033[0m",

    # Modifiers
    "bold":           "\033[1m",
    "dim":            "\033[2m",
    "italic":         "\033[3m",
    "underline":      "\033[4m",

    # Standard colors
    "red":            "\033[31m",
    "green":          "\033[32m",
    "yellow":         "\033[33m",
    "blue":           "\033[34m",
    "magenta":        "\033[35m",
    "cyan":           "\033[36m",
    "white":          "\033[37m",
    "gray":           "\033[90m",

    # Bright colors
    "bright_red":     "\033[91m",
    "bright_green":   "\033[92m",
    "bright_yellow":  "\033[93m",
    "bright_blue":    "\033[94m",
    "bright_magenta": "\033[95m",
    "bright_cyan":    "\033[96m",
    "bright_white":   "\033[97m",

    # Background colors
    "bg_red":         "\033[41;97m",     # white text on red
    "bg_yellow":      "\033[43;30m",     # black text on yellow
    "bg_green":       "\033[42;30m",     # black text on green
    "bg_blue":        "\033[44;97m",     # white text on blue
    "bg_cyan":        "\033[46;30m",     # black text on cyan
    "bg_magenta":     "\033[45;97m",     # white text on magenta

    # Semantic aliases — map purpose to color
    "success":        "\033[32m",        # green
    "error":          "\033[31m",        # red
    "warning":        "\033[33m",        # yellow
    "info":           "\033[36m",        # cyan
    "heading":        "\033[1;36m",      # bold cyan
    "subheading":     "\033[33m",        # yellow
    "value":          "\033[37m",        # white
    "path":           "\033[35m",        # magenta
    "command":        "\033[1;32m",      # bold green
    "flag":           "\033[33m",        # yellow
    "label":          "\033[94m",        # bright blue
    "category":       "\033[96m",        # bright cyan
    "trait":          "\033[96m",        # bright cyan
    "role":           "\033[94m",        # bright blue
    "skill":          "\033[95m",        # bright magenta
    "profile":        "\033[93m",        # bright yellow
    "platform":       "\033[92m",        # bright green
    "global":         "\033[97m",        # bright white
    "team":           "\033[92m",        # bright green
    "project":        "\033[93m",        # bright yellow
    "family_instr":   "\033[94m",        # bright blue
    "family_protocol":"\033[92m",        # bright green
    "family_playbook":"\033[95m",        # bright magenta
    "family_workflow":"\033[93m",        # bright yellow
    "family_spec":    "\033[96m",        # bright cyan
    "family_schema":  "\033[33m",        # yellow
    "family_know":    "\033[32m",        # green
    "family_arch":    "\033[35m",        # magenta
    "family_task":    "\033[97m",        # bright white
    "family_cli":     "\033[36m",        # cyan
    "family_other":   "\033[37m",        # white
    "muted":          "\033[90m",        # gray
    "ok":             "\033[32m",        # green
    "critical":       "\033[41;97m",     # bg_red
}


# =============================================================================
# Core colorize function
# =============================================================================

def c(text: str, *styles: str) -> str:
    """Apply one or more named styles to text.

    Args:
        text: The string to colorize.
        *styles: Style names from CODES (e.g., "red", "bold", "heading").

    Returns:
        Styled string if colors enabled, plain text otherwise.

    Examples:
        c("hello", "red")
        c("world", "green", "bold")
        c("Error!", "error")
        c("/path/to/file", "path")
    """
    if not colors_enabled():
        return text
    codes = []
    for style in styles:
        code = CODES.get(style)
        if code:
            codes.append(code)
    if not codes:
        return text
    return f"{''.join(codes)}{text}\033[0m"


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text."""
    import re
    return re.sub(r"\033\[[0-?]*[ -/]*[@-~]", "", text)


# =============================================================================
# Inline style functions (return colored strings)
# =============================================================================

def bold(text: str) -> str:
    """Return text in bold."""
    return c(text, "bold")


def dim(text: str) -> str:
    """Return text in dim/muted style."""
    return c(text, "dim")


def heading(text: str) -> str:
    """Return text styled as a heading (bold cyan)."""
    return c(text, "heading")


def value(text: str) -> str:
    """Return text styled as a value (white)."""
    return c(text, "value")


def path_style(text: str) -> str:
    """Return text styled as a file path (magenta)."""
    return c(text, "path")


def command_style(text: str) -> str:
    """Return text styled as a command name (bold green)."""
    return c(text, "command")


# =============================================================================
# Print helpers — print with prefix and color
# =============================================================================

def success(msg: str, **kwargs) -> None:
    """Print a success message with green checkmark prefix."""
    prefix = c("OK", "green", "bold")
    print(f"  {prefix}  {msg}", **kwargs)


def error(msg: str, file=None, **kwargs) -> None:
    """Print an error message with red prefix to stderr."""
    prefix = c("ERR", "red", "bold")
    print(f"  {prefix} {msg}", file=file or sys.stderr, **kwargs)


def warn(msg: str, **kwargs) -> None:
    """Print a warning message with yellow prefix."""
    prefix = c("WARN", "yellow", "bold")
    print(f"  {prefix} {msg}", **kwargs)


def info(msg: str, **kwargs) -> None:
    """Print an info message with cyan prefix."""
    prefix = c("--", "cyan")
    print(f"  {prefix} {msg}", **kwargs)


# =============================================================================
# Help text formatting
# =============================================================================

def format_help(text: str) -> str:
    """Apply consistent ANSI coloring to --help text.

    Conventions:
        - Section headers (lines ending with :) -> bold cyan
        - Flags (-x, --flag) -> yellow, descriptions -> dim
        - Command names (indented words) -> bold green
        - Example comments (# ...) -> dim
        - Descriptive text -> unchanged

    Args:
        text: Raw help text (typically a triple-quoted string).

    Returns:
        Colorized help text.
    """
    import re

    if not colors_enabled():
        return text

    lines = text.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()

        # Empty lines
        if not stripped:
            result.append(line)
            continue

        # Section headers: "Options:", "Usage:", "Examples:" etc.
        if stripped.endswith(":") and not stripped.startswith("-") and not stripped.startswith("#"):
            result.append(c(line, "heading"))
            continue

        # Flag lines: "  -v, --verbose  Some description"
        if stripped.startswith("-"):
            match = re.match(
                r"^(\s*)(-\S+(?:,\s*--?\S+)?(?:\s+\S+)?)"  # indent + flags
                r"(\s{2,})"                                   # gap
                r"(.*)$",                                      # description
                line,
            )
            if match:
                indent, flag, spacing, desc = match.groups()
                result.append(
                    f"{indent}{c(flag, 'flag')}{spacing}{c(desc, 'dim')}"
                )
            else:
                result.append(c(line, "flag"))
            continue

        # Comment lines in examples: "  # some comment"
        if stripped.startswith("#"):
            result.append(c(line, "dim"))
            continue

        # Command examples: indented lines starting with a word (not inside a description block)
        if re.match(r"^\s{2,}[a-z_][\w.-]*(\s|$)", line) and not stripped.startswith("#"):
            match = re.match(r"^(\s+)([\w.-]+)(.*)$", line)
            if match:
                indent, cmd, rest = match.groups()
                # Check if rest has a comment part
                comment_match = re.match(r"^(.*?)(#.*)$", rest)
                if comment_match:
                    before_comment, comment = comment_match.groups()
                    result.append(
                        f"{indent}{c(cmd, 'command')}{before_comment}{c(comment, 'dim')}"
                    )
                else:
                    result.append(f"{indent}{c(cmd, 'command')}{rest}")
            else:
                result.append(line)
            continue

        # Default: leave as-is
        result.append(line)

    return "\n".join(result)


def format_usage(prog: str, usage_line: str) -> str:
    """Format a usage line: bold program name, flags in yellow.

    Args:
        prog: Program name (e.g., "sysmon").
        usage_line: The rest of the usage (e.g., "[options] <command>").

    Returns:
        Formatted usage string.
    """
    return f"{c(prog, 'command')} {usage_line}"


# =============================================================================
# Pressure/severity coloring (from sysmon pattern)
# =============================================================================

def pressure_color(level: str, text: str | None = None) -> str:
    """Color text based on severity/pressure level.

    Args:
        level: One of "critical", "warn"/"warning", "ok"/"normal"/"good", or anything else (muted).
        text: Text to color. Defaults to the level name.

    Returns:
        Colored text. Critical gets background color for visibility.
    """
    text = text or level
    if level == "critical":
        return c(f" {text} ", "bg_red")
    elif level in ("warn", "warning"):
        return c(f" {text} ", "bg_yellow")
    elif level in ("ok", "normal", "good"):
        return c(text, "green")
    return c(text, "dim")


def value_color(val: float, warn_threshold: float, crit_threshold: float, text: str) -> str:
    """Color a value based on warning/critical thresholds.

    Assumes higher values are worse (e.g., CPU%, memory%).
    """
    if val >= crit_threshold:
        return c(text, "red")
    elif val >= warn_threshold:
        return c(text, "yellow")
    return c(text, "green")


# =============================================================================
# Demo
# =============================================================================

def _demo() -> None:
    """Print a visual demonstration of all available styles and helpers."""
    set_color_mode(True)  # Force colors on for demo

    print()
    print(c("standard_colors.py", "heading") + c(" — shared ANSI color library", "dim"))
    print(c("=" * 60, "dim"))
    print()

    # --- Raw colors ---
    print(c("Raw Colors:", "heading"))
    raw_colors = [
        "red", "green", "yellow", "blue", "magenta", "cyan", "white", "gray",
    ]
    for name in raw_colors:
        print(f"  {c(name.ljust(12), name)} c('text', '{name}')")

    print()
    print(c("Bright Colors:", "heading"))
    bright_colors = [
        "bright_red", "bright_green", "bright_yellow", "bright_blue",
        "bright_magenta", "bright_cyan", "bright_white",
    ]
    for name in bright_colors:
        print(f"  {c(name.ljust(18), name)} c('text', '{name}')")

    print()
    print(c("Modifiers:", "heading"))
    modifiers = ["bold", "dim", "italic", "underline"]
    for name in modifiers:
        print(f"  {c(name.ljust(12), name)} c('text', '{name}')")

    print()
    print(c("Combinations:", "heading"))
    combos = [
        ("bold + red",     "bold", "red"),
        ("bold + green",   "bold", "green"),
        ("bold + cyan",    "bold", "cyan"),
        ("dim + yellow",   "dim", "yellow"),
        ("italic + blue",  "italic", "blue"),
    ]
    for label, *styles in combos:
        print(f"  {c(label.ljust(18), *styles)} c('text', {', '.join(repr(s) for s in styles)})")

    print()
    print(c("Background Colors:", "heading"))
    bg_colors = ["bg_red", "bg_yellow", "bg_green", "bg_blue", "bg_cyan", "bg_magenta"]
    for name in bg_colors:
        print(f"  {c(f' {name} ', name)}  c(' text ', '{name}')")

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Semantic styles ---
    print(c("Semantic Styles:", "heading"))
    semantic = [
        ("success",    "Completed successfully"),
        ("error",      "Something went wrong"),
        ("warning",    "Proceed with caution"),
        ("info",       "Here is some information"),
        ("heading",    "Section Heading"),
        ("subheading", "Sub-section"),
        ("value",      "42"),
        ("path",       "/Users/you/project/file.py"),
        ("command",    "sysmon status"),
        ("flag",       "--verbose"),
        ("label",      "Status:"),
        ("muted",      "Not important right now"),
        ("ok",         "All systems nominal"),
        ("critical",   "SYSTEM DOWN"),
    ]
    for name, example in semantic:
        print(f"  {c(name.ljust(14), 'dim')} {c(example, name)}")

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Print helpers ---
    print(c("Print Helpers:", "heading"))
    print(c("  These print directly to stdout/stderr:", "dim"))
    print()
    success("Operation completed successfully")
    error("Could not open file: permission denied")
    warn("Disk usage at 89%, approaching threshold")
    info("Checking remote server status...")

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Inline style functions ---
    print(c("Inline Style Functions:", "heading"))
    print(f"  {bold('bold(text)')}     — {bold('Makes text bold')}")
    print(f"  {dim('dim(text)')}      — {dim('Makes text dim/muted')}")
    print(f"  {heading('heading(text)')} — {heading('Bold cyan heading')}")
    print(f"  {value('value(text)')}    — {value('White value')}")
    print(f"  {path_style('path_style(text)')}      — {path_style('/some/file/path.py')}")
    print(f"  {command_style('command_style(text)')}  — {command_style('my_command --flag')}")

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Pressure coloring ---
    print(c("Pressure/Severity Colors:", "heading"))
    print(f"  pressure_color('critical'):  {pressure_color('critical')}")
    print(f"  pressure_color('warn'):      {pressure_color('warn')}")
    print(f"  pressure_color('ok'):        {pressure_color('ok')}")
    print(f"  pressure_color('unknown'):   {pressure_color('unknown')}")
    print()
    print(f"  value_color(95, 80, 95, '95%'):  {value_color(95, 80, 95, '95%')}")
    print(f"  value_color(85, 80, 95, '85%'):  {value_color(85, 80, 95, '85%')}")
    print(f"  value_color(50, 80, 95, '50%'):  {value_color(50, 80, 95, '50%')}")

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Help formatting ---
    print(c("Help Text Formatting:", "heading"))
    print(c("  format_help() colorizes --help output consistently:", "dim"))
    print()

    sample_help = """\
Usage:
    sysmon [options] <command>

Commands:
    status              Show current system state
    dashboard           Live auto-refreshing dashboard
    collect --group G   Run collectors for group G
    history M H         Show metric M for last H hours

Options:
    -v, --verbose       Show detailed output
    -q, --quiet         Suppress non-error output
    --json              Output as JSON
    --no-color          Disable color output

Examples:
    sysmon status
    sysmon dashboard
    sysmon collect --group host
    sysmon history memory.app_gb 24   # last 24 hours"""

    print(format_help(sample_help))

    print()
    print(c("=" * 60, "dim"))
    print()

    # --- Color detection ---
    print(c("Color Detection:", "heading"))
    print(f"  colors_enabled():  {colors_enabled()}")
    print(f"  NO_COLOR env:      {os.environ.get('NO_COLOR', '(not set)')}")
    print(f"  TERM env:          {os.environ.get('TERM', '(not set)')}")
    print(f"  stdout.isatty():   {sys.stdout.isatty()}")
    print(f"  --no-color in argv: {'--no-color' in sys.argv}")
    print()


if __name__ == "__main__":
    _demo()
