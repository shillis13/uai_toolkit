"""Reserved words: names that may not be used as user definitions.

Grammar keywords (``let lambda mod as xor``) are already handled at the lexer
level, so they can never arrive as identifiers. This module covers the command
verbs and special variables, which *can* appear as identifiers and so must be
rejected explicitly when someone tries to define them.
"""

from __future__ import annotations

# CLI / REPL management verbs (dispatch, and cannot be definition names).
COMMAND_VERBS = frozenset({
    "list", "show", "del", "clear", "edit", "path", "set", "help", "def",
    "shell-init",
})

# Grammar keywords — reserved at the tokenizer, listed here for documentation
# and for help/error messages.
GRAMMAR_KEYWORDS = frozenset({"let", "lambda", "mod", "as", "xor"})

# Special identifiers the engine manages itself.
SPECIAL_VARS = frozenset({"ans", "_"})

# Names (identifier-shaped) that a user definition may not use.
_HARD_RESERVED = {v for v in COMMAND_VERBS if v.isidentifier()} | set(SPECIAL_VARS)


def is_reserved_name(name: str) -> bool:
    """True if ``name`` (case-insensitive) may not be defined by a user."""
    return name.lower() in _HARD_RESERVED
