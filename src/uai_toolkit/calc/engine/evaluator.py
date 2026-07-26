"""Evaluate an AST to a numeric value.

Implements the integer-preserving numeric model (design doc B5), lexical scopes
for LET/LAMBDA/user functions, a recursion-depth guard, a size guard on integer
powers, and the arithmetic sign conventions from S8. Constants and the builtin
catalog come from :mod:`calc.engine.builtins`.
"""

from __future__ import annotations

import difflib
import math
from typing import Dict, List, Optional, Tuple

from uai_toolkit.calc.engine import ast_nodes as A
from uai_toolkit.calc.engine.builtins import BUILTINS, CONSTANTS, _as_nonneg_int
from uai_toolkit.calc.engine.errors import CalcError, EvalError
from uai_toolkit.calc.engine.settings import Settings
from uai_toolkit.calc.engine.tokenizer import T
from uai_toolkit.calc.reserved import is_reserved_name

# Sentinel returned by a statement that produces no displayable value (a bare
# assignment). Frontends print nothing for it.
NOTHING = object()

_MAX_DEPTH = 200
_MAX_POW_BITS = 350_000  # ~100k decimal digits


class Scope:
    """A lexical scope: a name->value map with an optional parent chain."""

    def __init__(self, parent: "Optional[Scope]" = None) -> None:
        self.vars: Dict[str, object] = {}
        self.parent = parent

    def define(self, name: str, value: object) -> None:
        self.vars[name] = value

    def lookup(self, name: str) -> object:
        scope: Optional[Scope] = self
        while scope is not None:
            if name in scope.vars:
                return scope.vars[name]
            scope = scope.parent
        raise KeyError(name)

    def lookup_opt(self, name: str) -> Optional[object]:
        try:
            return self.lookup(name)
        except KeyError:
            return None


class LambdaValue:
    """A user function: parameters, a body AST, and the scope it closed over."""

    __slots__ = ("params", "body", "closure")

    def __init__(self, params: List[str], body: A.Node, closure: Scope) -> None:
        self.params = params
        self.body = body
        self.closure = closure


class EvalContext:
    def __init__(self, settings: Settings, source: str) -> None:
        self.settings = settings
        self.source = source
        self.depth = 0


# --- public entry ----------------------------------------------------------

def evaluate_program(program: A.Program, scope: Scope, settings: Settings,
                     source: str = "") -> "Tuple[object, Optional[str]]":
    """Run a parsed program in ``scope``. Returns ``(value, base_override)``.

    ``value`` is ``NOTHING`` for a line whose last statement is an assignment.
    A multi-statement line runs in a child scope (LET locality); a single
    statement runs directly in ``scope`` so stream/REPL bindings persist.
    """
    ctx = EvalContext(settings, source)
    stmts = program.statements
    if len(stmts) == 1:
        return _eval_statement(stmts[0], scope, ctx)
    child = Scope(parent=scope)
    value: object = NOTHING
    base: Optional[str] = None
    for st in stmts:
        value, base = _eval_statement(st, child, ctx)
    return value, base


def _eval_statement(node: A.Node, scope: Scope,
                    ctx: EvalContext) -> "Tuple[object, Optional[str]]":
    if isinstance(node, A.AsBase):
        return _evaluate(node.expr, scope, ctx), node.base
    if isinstance(node, A.Assign):
        _exec_assign(node, scope, ctx)
        return NOTHING, None
    return _evaluate(node, scope, ctx), None


def _exec_assign(node: A.Assign, scope: Scope, ctx: EvalContext) -> None:
    if is_reserved_name(node.name):
        raise EvalError(
            "'{}' is a reserved word and can't be defined".format(node.name),
            pos=node.pos, source=ctx.source,
        )
    if node.params is None:
        scope.define(node.name, _evaluate(node.value, scope, ctx))
    else:
        for pnm in node.params:
            if is_reserved_name(pnm):
                raise EvalError(
                    "'{}' is a reserved word and can't be a parameter".format(pnm),
                    pos=node.pos, source=ctx.source,
                )
        scope.define(node.name, LambdaValue(node.params, node.value, scope))


# --- expression evaluation -------------------------------------------------

def _evaluate(node: A.Node, scope: Scope, ctx: EvalContext):
    if isinstance(node, A.Num):
        return node.value

    if isinstance(node, A.Name):
        return _eval_name(node, scope, ctx)

    if isinstance(node, A.BinOp):
        return _binop(node, scope, ctx)

    if isinstance(node, A.UnaryOp):
        return _unary(node, scope, ctx)

    if isinstance(node, A.Postfix):     # factorial
        x = _evaluate(node.operand, scope, ctx)
        return math.factorial(_as_nonneg_int(x, "factorial"))

    if isinstance(node, A.Call):
        return _eval_call(node, scope, ctx)

    if isinstance(node, A.Lambda):
        return LambdaValue(node.params, node.body, scope)

    if isinstance(node, A.Let):
        child = Scope(parent=scope)
        for b in node.bindings:
            _exec_assign(b, child, ctx)
        return _evaluate(node.body, child, ctx)

    raise EvalError("cannot evaluate {}".format(type(node).__name__),
                    pos=getattr(node, "pos", None), source=ctx.source)


def _eval_name(node: A.Name, scope: Scope, ctx: EvalContext):
    val = scope.lookup_opt(node.name)
    if val is not None:
        if isinstance(val, LambdaValue):
            raise EvalError(
                "'{}' is a function; call it like {}(…)".format(node.name, node.name),
                pos=node.pos, source=ctx.source,
            )
        return val
    key = node.name.lower()
    if key in CONSTANTS:
        return CONSTANTS[key]
    if key in BUILTINS:
        raise EvalError(
            "'{}' is a function; call it like {}(…)".format(node.name, node.name),
            pos=node.pos, source=ctx.source,
        )
    raise EvalError(_unknown(node.name, scope), pos=node.pos, source=ctx.source)


def _unknown(name: str, scope: Scope) -> str:
    pool = set(CONSTANTS) | set(BUILTINS)
    s = scope
    while s is not None:
        pool.update(s.vars.keys())
        s = s.parent
    near = difflib.get_close_matches(name.lower(), sorted(pool), n=1, cutoff=0.6)
    if near:
        return "unknown name '{}' — did you mean '{}'?".format(name, near[0])
    return "unknown name '{}'".format(name)


def _eval_call(node: A.Call, scope: Scope, ctx: EvalContext):
    args = [_evaluate(a, scope, ctx) for a in node.args]

    if isinstance(node.func, A.Name):
        name = node.func.name
        bound = scope.lookup_opt(name)
        if bound is not None:
            if isinstance(bound, LambdaValue):
                return _call_lambda(bound, args, node, ctx)
            raise EvalError("'{}' is not a function".format(name),
                            pos=node.pos, source=ctx.source)
        key = name.lower()
        if key in BUILTINS:
            return _call_builtin(key, name, args, node, ctx)
        raise EvalError(_unknown_fn(name, scope), pos=node.pos, source=ctx.source)

    fv = _evaluate(node.func, scope, ctx)
    if isinstance(fv, LambdaValue):
        return _call_lambda(fv, args, node, ctx)
    raise EvalError("this expression is not a function",
                    pos=node.pos, source=ctx.source)


def _unknown_fn(name: str, scope: Scope) -> str:
    near = difflib.get_close_matches(name.lower(), sorted(BUILTINS), n=1, cutoff=0.6)
    if near:
        return "unknown function '{}' — did you mean '{}'?".format(name, near[0])
    return "unknown function '{}'".format(name)


def _call_builtin(key: str, shown: str, args, node: A.Call, ctx: EvalContext):
    lo, hi, fn = BUILTINS[key]
    n = len(args)
    if n < lo or (hi is not None and n > hi):
        raise EvalError(_arity_msg(shown, lo, hi, n),
                        pos=node.pos, source=ctx.source)
    try:
        return fn(args, ctx.settings)
    except CalcError as e:
        if e.pos is None:
            e.pos = node.pos
        if e.source is None:
            e.source = ctx.source
        raise
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        raise EvalError("{}: {}".format(shown, e), pos=node.pos, source=ctx.source)


def _arity_msg(name: str, lo: int, hi: Optional[int], got: int) -> str:
    if hi is None:
        want = "at least {}".format(lo)
    elif lo == hi:
        want = "exactly {}".format(lo)
    else:
        want = "{} to {}".format(lo, hi)
    return "{} takes {} argument(s), got {}".format(name, want, got)


def _call_lambda(lam: LambdaValue, args, node: A.Call, ctx: EvalContext):
    if len(args) != len(lam.params):
        raise EvalError(
            "function takes {} argument(s), got {}".format(len(lam.params), len(args)),
            pos=node.pos, source=ctx.source,
        )
    if ctx.depth >= _MAX_DEPTH:
        raise EvalError("maximum expression depth exceeded (possible infinite "
                        "recursion)", pos=node.pos, source=ctx.source)
    child = Scope(parent=lam.closure)
    for pname, aval in zip(lam.params, args):
        child.define(pname, aval)
    ctx.depth += 1
    try:
        return _evaluate(lam.body, child, ctx)
    finally:
        ctx.depth -= 1


# --- operators -------------------------------------------------------------

def _unary(node: A.UnaryOp, scope: Scope, ctx: EvalContext):
    x = _evaluate(node.operand, scope, ctx)
    if node.op == T.MINUS:
        return -x
    if node.op == T.PLUS:
        return +x
    if node.op == T.TILDE:
        return ~_as_int(x, "bitwise ~", node.pos, ctx)
    raise EvalError("bad unary operator", pos=node.pos, source=ctx.source)  # pragma: no cover


def _binop(node: A.BinOp, scope: Scope, ctx: EvalContext):
    op = node.op
    a = _evaluate(node.left, scope, ctx)
    b = _evaluate(node.right, scope, ctx)
    pos, src = node.pos, ctx.source

    if op == T.PLUS:
        return a + b
    if op == T.MINUS:
        return a - b
    if op == T.STAR:
        return a * b
    if op == T.SLASH:
        if b == 0:
            raise EvalError("division by zero", pos=pos, source=src)
        if isinstance(a, int) and isinstance(b, int) and a % b == 0:
            return a // b
        return a / b
    if op == T.DSLASH:
        if b == 0:
            raise EvalError("floor division by zero", pos=pos, source=src)
        return a // b
    if op == T.PERCENT:
        if b == 0:
            raise EvalError("modulo by zero", pos=pos, source=src)
        return a % b
    if op == T.CARET:
        return _checked_pow(a, b, pos, src)
    if op in (T.AMP, T.PIPE, T.XOR, T.LSHIFT, T.RSHIFT):
        ai = _as_int(a, "bitwise operation", pos, ctx)
        bi = _as_int(b, "bitwise operation", pos, ctx)
        if op == T.AMP:
            return ai & bi
        if op == T.PIPE:
            return ai | bi
        if op == T.XOR:
            return ai ^ bi
        if bi < 0:
            raise EvalError("negative shift count", pos=pos, source=src)
        return ai << bi if op == T.LSHIFT else ai >> bi
    raise EvalError("bad operator", pos=pos, source=src)  # pragma: no cover


def _as_int(x, what: str, pos, ctx: EvalContext) -> int:
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    raise EvalError("{} requires whole numbers".format(what), pos=pos, source=ctx.source)


def _checked_pow(a, b, pos, src):
    if isinstance(a, int) and isinstance(b, int) and b >= 0:
        if a not in (0, 1, -1) and b > 0:
            if b * max(1, a.bit_length()) > _MAX_POW_BITS:
                raise EvalError("result too large to compute", pos=pos, source=src)
        return a ** b
    if a == 0 and isinstance(b, (int, float)) and b < 0:
        raise EvalError("division by zero (zero to a negative power)",
                        pos=pos, source=src)
    try:
        r = a ** b
    except (OverflowError, ValueError) as e:
        raise EvalError("power overflow: {}".format(e), pos=pos, source=src)
    if isinstance(r, complex):
        raise EvalError("result is not real (fractional power of a negative number)",
                        pos=pos, source=src)
    return r
