"""Render an evaluated value into legible text (design doc section 4).

Defaults favor readability: integers print exactly (Python bigints, never
lossy), floats are cleaned of representation noise via significant-figure
formatting, and base output (hex/bin/oct) applies to integers with signed
magnitude. ``settings.full`` shows full float precision on demand.
"""

from __future__ import annotations

import math
import re
from typing import Optional, Tuple

from uai_toolkit.calc.engine.settings import Settings
from uai_toolkit.calc.engine.evaluator import LambdaValue

_PREFIX = {"hex": "0x", "bin": "0b", "oct": "0o"}
_BASESPEC = {"hex": "x", "bin": "b", "oct": "o"}
# accept a few friendly aliases for base names
_BASE_ALIAS = {
    "hex": "hex", "hexadecimal": "hex", "x": "hex", "16": "hex",
    "bin": "bin", "binary": "bin", "b": "bin", "2": "bin",
    "oct": "oct", "octal": "oct", "o": "oct", "8": "oct",
    "dec": "dec", "decimal": "dec", "d": "dec", "10": "dec",
}


def format_value(value, settings: Settings,
                 base_override: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Return ``(text, warning_or_None)`` for ``value``."""
    if isinstance(value, LambdaValue):
        return "lambda({}, …)".format(", ".join(value.params)), None

    base = _normalize_base(base_override) if base_override else settings.base
    if base and base != "dec":
        iv = _as_integral(value)
        if iv is None:
            return (_format_decimal(value, settings),
                    "note: {} output applies to whole numbers; showing decimal"
                    .format(base))
        return _format_int_base(iv, base), None

    return _format_decimal(value, settings), None


def _normalize_base(name: str) -> str:
    return _BASE_ALIAS.get(name.lower(), name.lower())


def _as_integral(value) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer() and math.isfinite(value):
        return int(value)
    return None


def _format_int_base(n: int, base: str) -> str:
    sign = "-" if n < 0 else ""
    body = format(abs(n), _BASESPEC[base])
    return "{}{}{}".format(sign, _PREFIX[base], body)


def _format_decimal(value, settings: Settings) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return _format_float(value, settings)


def _format_float(x: float, settings: Settings) -> str:
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"

    if settings.full:
        text = repr(x)
    else:
        prec = max(1, settings.precision)
        text = "{:.{p}g}".format(x, p=prec)

    # An integral float renders without a trailing '.0' via %g already, but
    # repr(2.0) == '2.0'; normalize that for the full-precision path too.
    if text.endswith(".0"):
        text = text[:-2]
    return _tidy_exponent(text)


def _tidy_exponent(text: str) -> str:
    # '1e-05' -> '1e-5', '6.02e+23' -> '6.02e23'
    m = re.match(r"^(-?[0-9.]+)e([+-]?)0*(\d+)$", text)
    if not m:
        return text
    mant, sign, exp = m.group(1), m.group(2), m.group(3)
    sign = "-" if sign == "-" else ""
    return "{}e{}{}".format(mant, sign, exp)
