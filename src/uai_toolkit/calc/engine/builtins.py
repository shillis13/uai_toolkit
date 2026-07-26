"""Curated function & constant catalog for the calculator.

Each builtin is ``fn(args, settings) -> number`` where ``args`` are already-
evaluated numeric values and ``settings`` carries the angle mode. Arity is
declared in :data:`BUILTINS` and enforced by the evaluator.

Type discipline (design doc B5): integer-preserving where it is exact
(``sqrt`` of a perfect square, ``abs`` of an int, ``floor``/``ceil``), float
otherwise.
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Dict, List, Tuple

from uai_toolkit.calc.engine.errors import EvalError

CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


# --- helpers ---------------------------------------------------------------

def _to_rad(x, settings):
    return math.radians(x) if settings.angle == "deg" else x


def _from_rad(x, settings):
    return math.degrees(x) if settings.angle == "deg" else x


def _as_nonneg_int(x, what):
    if isinstance(x, bool):  # bool is an int subclass; keep it out
        x = int(x)
    if isinstance(x, float):
        if not x.is_integer():
            raise EvalError("{} requires a whole number".format(what))
        x = int(x)
    if not isinstance(x, int) or x < 0:
        raise EvalError("{} requires a non-negative whole number".format(what))
    return x


def _require_ints(args, what):
    for a in args:
        if isinstance(a, float) and a.is_integer():
            continue
        if not isinstance(a, int):
            raise EvalError("{} requires whole numbers".format(what))
    return [int(a) for a in args]


# --- implementations -------------------------------------------------------

def _sqrt(args, s):
    x = args[0]
    if isinstance(x, int) and x >= 0:
        r = math.isqrt(x)
        if r * r == x:
            return r
    if x < 0:
        raise EvalError("sqrt of a negative number is not real")
    return math.sqrt(x)


def _cbrt(args, s):
    x = args[0]
    return math.copysign(abs(x) ** (1.0 / 3.0), x)


def _abs(args, s):
    return abs(args[0])


def _sin(args, s):
    return math.sin(_to_rad(args[0], s))


def _cos(args, s):
    return math.cos(_to_rad(args[0], s))


def _tan(args, s):
    return math.tan(_to_rad(args[0], s))


def _asin(args, s):
    x = args[0]
    if x < -1 or x > 1:
        raise EvalError("asin is defined on [-1, 1]")
    return _from_rad(math.asin(x), s)


def _acos(args, s):
    x = args[0]
    if x < -1 or x > 1:
        raise EvalError("acos is defined on [-1, 1]")
    return _from_rad(math.acos(x), s)


def _atan(args, s):
    return _from_rad(math.atan(args[0]), s)


def _ln(args, s):
    x = args[0]
    if x <= 0:
        raise EvalError("ln of a non-positive number")
    return math.log(x)


def _log(args, s):
    x = args[0]
    if x <= 0:
        raise EvalError("log of a non-positive number")
    if len(args) == 2:
        b = args[1]
        if b <= 0 or b == 1:
            raise EvalError("log base must be positive and not 1")
        return math.log(x, b)
    return math.log(x)


def _log2(args, s):
    if args[0] <= 0:
        raise EvalError("log2 of a non-positive number")
    return math.log2(args[0])


def _log10(args, s):
    if args[0] <= 0:
        raise EvalError("log10 of a non-positive number")
    return math.log10(args[0])


def _exp(args, s):
    return math.exp(args[0])


def _floor(args, s):
    return math.floor(args[0])


def _ceil(args, s):
    return math.ceil(args[0])


def _round(args, s):
    x = args[0]
    n = 0
    if len(args) == 2:
        n = _as_nonneg_int(args[1], "round digits") if args[1] >= 0 else int(args[1])
    q = Decimal(1).scaleb(-n)
    d = Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP)  # half away from zero
    return int(d) if n <= 0 else float(d)


def _sign(args, s):
    x = args[0]
    return (x > 0) - (x < 0)


def _min(args, s):
    return min(args)


def _max(args, s):
    return max(args)


def _gcd(args, s):
    return math.gcd(*_require_ints(args, "gcd"))


def _lcm(args, s):
    return math.lcm(*_require_ints(args, "lcm"))


def _factorial(args, s):
    return math.factorial(_as_nonneg_int(args[0], "factorial"))


def _hypot(args, s):
    return math.hypot(*args)


# name -> (min_arity, max_arity, fn). max_arity None means variadic.
BUILTINS: Dict[str, Tuple[int, "int | None", Callable]] = {
    "sqrt": (1, 1, _sqrt),
    "cbrt": (1, 1, _cbrt),
    "abs": (1, 1, _abs),
    "sin": (1, 1, _sin),
    "cos": (1, 1, _cos),
    "tan": (1, 1, _tan),
    "asin": (1, 1, _asin),
    "acos": (1, 1, _acos),
    "atan": (1, 1, _atan),
    "ln": (1, 1, _ln),
    "log": (1, 2, _log),
    "log2": (1, 1, _log2),
    "log10": (1, 1, _log10),
    "exp": (1, 1, _exp),
    "floor": (1, 1, _floor),
    "ceil": (1, 1, _ceil),
    "round": (1, 2, _round),
    "sign": (1, 1, _sign),
    "min": (1, None, _min),
    "max": (1, None, _max),
    "gcd": (2, None, _gcd),
    "lcm": (2, None, _lcm),
    "factorial": (1, 1, _factorial),
    "hypot": (2, 2, _hypot),
}
