"""The public engine surface: parse -> evaluate -> format, in one call.

Every frontend and test uses :func:`evaluate`. It is pure: no I/O, no globals.
Callers own the :class:`Scope` (so bindings persist across a stream/REPL) and
the :class:`Settings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from uai_toolkit.calc.engine.parser import parse
from uai_toolkit.calc.engine.evaluator import Scope, evaluate_program, NOTHING
from uai_toolkit.calc.engine.formatter import format_value
from uai_toolkit.calc.engine.settings import Settings


@dataclass
class Result:
    value: object                 # numeric value, a LambdaValue, or NOTHING
    text: Optional[str]           # display text, or None when there is nothing to show
    warning: Optional[str] = None # non-fatal note (e.g. base fallback)

    @property
    def is_nothing(self) -> bool:
        return self.value is NOTHING


def evaluate(source: str, scope: Optional[Scope] = None,
             settings: Optional[Settings] = None) -> Result:
    """Evaluate ``source`` and return a :class:`Result`.

    ``scope`` carries variable/function bindings (create one and reuse it to
    chain a stream or REPL). ``settings`` carries angle mode, precision, and
    default output base.
    """
    if scope is None:
        scope = Scope()
    if settings is None:
        settings = Settings()

    program = parse(source)
    value, base = evaluate_program(program, scope, settings, source)
    if value is NOTHING:
        return Result(NOTHING, None, None)
    text, warning = format_value(value, settings, base)
    return Result(value, text, warning)
