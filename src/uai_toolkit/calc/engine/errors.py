"""Typed errors that carry a source position so frontends can render a caret.

No Python traceback should ever reach the user; every failure surfaces as one
of these, and :meth:`CalcError.render` turns it into a friendly, positioned
diagnostic.
"""

from __future__ import annotations

from typing import Optional


class CalcError(Exception):
    """Base class for all calculator errors.

    ``pos`` is a 0-based index into the source string marking where the problem
    is (or ``None`` if not positional). ``source`` is the original input, set by
    whoever has it when the error propagates out.
    """

    def __init__(self, message: str, pos: Optional[int] = None,
                 source: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.pos = pos
        self.source = source

    def render(self) -> str:
        """Return a human-facing diagnostic, with a caret line when possible."""
        if self.source is None or self.pos is None:
            return self.message
        # Clamp the caret to the line the position falls on. Sources are usually
        # single-line, but be safe about embedded newlines.
        src = self.source
        line_start = src.rfind("\n", 0, self.pos) + 1
        line_end = src.find("\n", self.pos)
        if line_end == -1:
            line_end = len(src)
        line = src[line_start:line_end]
        caret_col = self.pos - line_start
        indent = "  "
        caret = " " * caret_col + "^"
        return "{ind}{line}\n{ind}{caret}  {msg}".format(
            ind=indent, line=line, caret=caret, msg=self.message
        )


class LexError(CalcError):
    """Raised by the tokenizer for characters it cannot turn into a token."""


class ParseError(CalcError):
    """Raised by the parser for structurally invalid expressions."""


class EvalError(CalcError):
    """Raised by the evaluator for runtime problems (domain, arity, etc.)."""
