"""Source string -> list of tokens.

The tokenizer handles number literals (all bases, digit separators, scientific
notation), operator recognition (including multi-character and unicode
synonyms), names, and grouping punctuation. It deliberately does NOT decide
whether a name is a function, constant, or variable, nor does it insert
implicit-multiplication markers -- those are the parser's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Union

from uai_toolkit.calc.engine.errors import LexError


class T:
    """Token type tags (string constants for cheap equality + readable repr)."""

    NUMBER = "NUMBER"
    NAME = "NAME"
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    DSLASH = "DSLASH"     # //  (integer / floor division)
    PERCENT = "PERCENT"   # %   (modulo)  -- also the word 'mod'
    CARET = "CARET"       # ^   (power)   -- also **
    BANG = "BANG"         # !   (factorial, postfix)
    AMP = "AMP"           # &   (bitwise and)
    PIPE = "PIPE"         # |   (bitwise or)
    TILDE = "TILDE"       # ~   (bitwise not, prefix)
    LSHIFT = "LSHIFT"     # <<
    RSHIFT = "RSHIFT"     # >>
    XOR = "XOR"           # bitwise xor (the word 'xor'; ^ is power)
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    SEMI = "SEMI"         # ;   (step separator)
    ASSIGN = "ASSIGN"     # =
    COLON = "COLON"       # :   (let ... : body)
    AS = "AS"             # as  (output-base directive)
    LET = "LET"           # let (local bindings)
    LAMBDA = "LAMBDA"     # lambda (anonymous function)
    EOF = "EOF"


@dataclass
class Token:
    type: str
    value: Union[int, float, str, None]
    pos: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Token({}, {!r}, @{})".format(self.type, self.value, self.pos)


# Single-character operators/punctuation with no multi-char prefix ambiguity.
_SINGLE = {
    "+": T.PLUS,
    "-": T.MINUS,
    "!": T.BANG,
    "(": T.LPAREN,
    ")": T.RPAREN,
    ",": T.COMMA,
    ";": T.SEMI,
    "=": T.ASSIGN,
    ":": T.COLON,
    "^": T.CARET,
    "%": T.PERCENT,
    "&": T.AMP,
    "|": T.PIPE,
    "~": T.TILDE,
}

# Words that are grammar keywords, not identifiers. Tokenizing them here keeps
# them out of the NAME space so they can never be shadowed as variable names
# (design doc S5) and are not mistaken for implicit-multiplication operands.
_KEYWORDS = {
    "mod": T.PERCENT,
    "xor": T.XOR,
    "as": T.AS,
    "let": T.LET,
    "lambda": T.LAMBDA,
}

# Unicode operator synonyms normalized to their ASCII token type.
_UNICODE_OPS = {
    "×": T.STAR,    # × multiplication sign
    "·": T.STAR,    # · middle dot
    "∗": T.STAR,    # ∗ asterisk operator
    "÷": T.SLASH,   # ÷ division sign
    "−": T.MINUS,   # − minus sign
}


def _is_name_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_"


def _is_name_part(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def tokenize(source: str) -> List[Token]:
    """Turn ``source`` into a list of tokens terminated by an EOF token.

    Raises :class:`LexError` (carrying ``pos`` and ``source``) on any character
    that cannot begin a token.
    """
    tokens: List[Token] = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        # whitespace
        if ch in " \t\r\n\f\v":
            i += 1
            continue

        # comment: '#' to end of line (or end of input)
        if ch == "#":
            nl = source.find("\n", i)
            i = n if nl == -1 else nl
            continue

        start = i

        # numbers: a digit, or a leading dot immediately followed by a digit
        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            tok, i = _read_number(source, i)
            tokens.append(tok)
            continue

        # names (identifiers) -- also catches the operator-word 'mod'
        if _is_name_start(ch):
            j = i + 1
            while j < n and _is_name_part(source[j]):
                j += 1
            text = source[start:j]
            kw = _KEYWORDS.get(text.lower())
            if kw is not None:
                tokens.append(Token(kw, text.lower(), start))
            else:
                tokens.append(Token(T.NAME, text, start))
            i = j
            continue

        # two-character operators before their one-character prefixes
        two = source[i:i + 2]
        if two == "//":
            tokens.append(Token(T.DSLASH, "//", start))
            i += 2
            continue
        if two == "**":
            tokens.append(Token(T.CARET, "**", start))
            i += 2
            continue
        if two == "<<":
            tokens.append(Token(T.LSHIFT, "<<", start))
            i += 2
            continue
        if two == ">>":
            tokens.append(Token(T.RSHIFT, ">>", start))
            i += 2
            continue

        # single '/'  (must come after '//')
        if ch == "/":
            tokens.append(Token(T.SLASH, "/", start))
            i += 1
            continue

        # single '*'  (must come after '**')
        if ch == "*":
            tokens.append(Token(T.STAR, "*", start))
            i += 1
            continue

        # other single-char operators / punctuation
        if ch in _SINGLE:
            tokens.append(Token(_SINGLE[ch], ch, start))
            i += 1
            continue

        # unicode operator synonyms
        if ch in _UNICODE_OPS:
            tokens.append(Token(_UNICODE_OPS[ch], ch, start))
            i += 1
            continue

        raise LexError(
            "unexpected character {!r}".format(ch), pos=i, source=source
        )

    tokens.append(Token(T.EOF, None, n))
    return tokens


def _read_number(source: str, i: int) -> "tuple[Token, int]":
    """Read one numeric literal starting at ``i``. Returns (token, next_index)."""
    n = len(source)
    start = i

    # based integer literals: 0x / 0b / 0o
    if source[i] == "0" and i + 1 < n and source[i + 1] in "xXbBoO":
        prefix = source[i + 1].lower()
        base = {"x": 16, "b": 2, "o": 8}[prefix]
        digits = _base_digits(base)
        j = i + 2
        k = j
        while k < n and (source[k] in digits or source[k] == "_"):
            k += 1
        body = source[j:k].replace("_", "")
        if not body:
            raise LexError(
                "malformed base-{} literal".format(base), pos=start, source=source
            )
        try:
            value = int(body, base)
        except ValueError:
            raise LexError(
                "malformed base-{} literal".format(base), pos=start, source=source
            )
        return Token(T.NUMBER, value, start), k

    # decimal: integer part, optional fraction, optional exponent
    j = i
    is_float = False

    def consume_digits(pos: int) -> int:
        while pos < n and (source[pos].isdigit() or source[pos] == "_"):
            pos += 1
        return pos

    j = consume_digits(j)

    # thousands separators: a comma is part of the number only when it is
    # immediately followed by exactly three digits (e.g. 1,234,567). A comma
    # followed by a space or by other than three digits stays an argument
    # separator, so f(1, 234) is two arguments while f(1,234) is 1234.
    while (j < n and source[j] == "," and j + 3 < n + 1
           and source[j + 1:j + 4].isdigit() and len(source[j + 1:j + 4]) == 3
           and (j + 4 >= n or not source[j + 4].isdigit())):
        j += 4

    if j < n and source[j] == ".":
        is_float = True
        j = consume_digits(j + 1)

    if j < n and source[j] in "eE":
        # exponent, with optional sign, requires at least one digit
        k = j + 1
        if k < n and source[k] in "+-":
            k += 1
        if k < n and source[k].isdigit():
            is_float = True
            j = consume_digits(k)
        # else: not an exponent (e.g. a trailing name like '2e'); leave 'e' for
        # the name/implicit-mult path by not consuming it here.

    text = source[start:j].replace("_", "").replace(",", "")
    if is_float:
        value: Union[int, float] = float(text)
    else:
        value = int(text)
    return Token(T.NUMBER, value, start), j


def _base_digits(base: int) -> str:
    if base == 16:
        return "0123456789abcdefABCDEF"
    if base == 8:
        return "01234567"
    if base == 2:
        return "01"
    raise ValueError(base)  # pragma: no cover
