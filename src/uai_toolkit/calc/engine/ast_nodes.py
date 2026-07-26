"""AST node definitions produced by the parser and consumed by the evaluator.

Nodes are plain dataclasses carrying a source ``pos`` for diagnostics. The set
is intentionally small: the whole "variables / user functions / local steps"
family collapses onto Assign + Lambda + Let (see the design doc, section 3.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


@dataclass
class Num:
    value: Union[int, float]
    pos: int


@dataclass
class Name:
    name: str
    pos: int


@dataclass
class BinOp:
    op: str          # token type: PLUS/MINUS/STAR/SLASH/DSLASH/PERCENT/CARET
    left: "Node"
    right: "Node"
    pos: int


@dataclass
class UnaryOp:
    op: str          # PLUS or MINUS (prefix)
    operand: "Node"
    pos: int


@dataclass
class Postfix:
    op: str          # BANG (factorial)
    operand: "Node"
    pos: int


@dataclass
class Call:
    func: "Node"     # usually a Name, but any expression yielding a lambda
    args: List["Node"]
    pos: int


@dataclass
class Lambda:
    params: List[str]
    body: "Node"
    pos: int


@dataclass
class Assign:
    """``name = value`` (params is None) or ``name(params) = value`` (function).

    ``local`` marks a binding introduced inside a ``;``/let sequence (line-scoped)
    versus a bare top-level definition (durable candidate). The parser sets it;
    the evaluator/frontends decide persistence.
    """

    name: str
    params: Optional[List[str]]
    value: "Node"
    pos: int
    local: bool = False


@dataclass
class Let:
    """A sequence of bindings followed by a result expression.

    Models both ``a = 1; b = a+2; a*b`` (semicolon steps) and the explicit
    ``let a = 1, b = a+2 : a*b`` form. Bindings are visible to later bindings and
    to ``body``, and are scoped to this Let.
    """

    bindings: List[Assign]
    body: "Node"
    pos: int


@dataclass
class AsBase:
    """``expr as hex`` — evaluate ``expr`` and render it in the named base."""

    expr: "Node"
    base: str
    pos: int


@dataclass
class Program:
    """Top-level parse result for one line/source: a list of statements.

    A statement is either an Assign (durable definition) or a bare expression.
    Most lines are a single statement; the multi-statement case supports a line
    like ``x = 5; x^2`` where the last statement is the value to print.
    """

    statements: List["Node"] = field(default_factory=list)
    pos: int = 0


# A Node is any of the above. Kept as a documentation alias; runtime code uses
# isinstance checks against the concrete classes.
Node = Union[Num, Name, BinOp, UnaryOp, Postfix, Call, Lambda, Assign, Let,
             AsBase, Program]
