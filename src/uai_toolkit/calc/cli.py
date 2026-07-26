#!/usr/bin/env python3
"""Command-line entry point: parse argv, dispatch, and drive the frontends.

Dispatch rule: the first non-flag token, if it is a management verb, runs a
command; otherwise all non-flag tokens join into one expression. The REPL is
entered only at an interactive terminal with no expression, or via ``-i``.
"""

from __future__ import annotations

import sys
from typing import List, Optional

# Allow running this file directly (./cli.py) — put the package root (…/src) on
# sys.path so `import calc` resolves even without an editable install.
if __package__ in (None, ""):
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uai_toolkit.calc import __version__
from uai_toolkit.calc.engine import evaluate, Scope, Settings, CalcError, NOTHING
from uai_toolkit.calc.engine.formatter import _normalize_base
from uai_toolkit.calc.store import Store
from uai_toolkit.calc.commands import run_command
from uai_toolkit.calc.reserved import COMMAND_VERBS
from uai_toolkit.calc.helptext import help_text


class _Opts:
    def __init__(self) -> None:
        self.out_base: Optional[str] = None
        self.angle: Optional[str] = None
        self.full: bool = False
        self.precision: Optional[int] = None
        self.repl: bool = False
        self.assume_yes: bool = False
        self.help: bool = False
        self.examples: bool = False
        self.version: bool = False


def _parse_argv(argv: List[str]) -> "tuple[_Opts, List[str], Optional[str]]":
    opts = _Opts()
    positionals: List[str] = []
    i, n = 0, len(argv)
    rest_positional = False
    while i < n:
        a = argv[i]
        if rest_positional:
            positionals.append(a)
            i += 1
            continue
        if a == "--":
            rest_positional = True
        elif a in ("-h", "--help"):
            opts.help = True
        elif a in ("--examples", "--help-examples"):
            opts.examples = True
        elif a == "--version":
            opts.version = True
        elif a in ("-i", "--repl"):
            opts.repl = True
        elif a == "--deg":
            opts.angle = "deg"
        elif a == "--rad":
            opts.angle = "rad"
        elif a == "--full":
            opts.full = True
        elif a in ("-y", "--yes"):
            opts.assume_yes = True
        elif a in ("-o", "--out"):
            i += 1
            if i >= n:
                return opts, positionals, "option {} needs a base".format(a)
            opts.out_base = argv[i]
        elif a.startswith("--out="):
            opts.out_base = a.split("=", 1)[1]
        elif a.startswith("-o") and len(a) > 2:
            opts.out_base = a[2:]
        elif a in ("-p", "--precision"):
            i += 1
            if i >= n:
                return opts, positionals, "option {} needs a number".format(a)
            opts.precision = _int_or(argv[i])
        elif a.startswith("--precision="):
            opts.precision = _int_or(a.split("=", 1)[1])
        elif a.startswith("--"):
            return opts, positionals, "unknown option '{}'".format(a)
        elif a != "-" and a.startswith("-") and not (a[1].isdigit() or a[1] == "."):
            return opts, positionals, "unknown option '{}' (use -- for a leading minus)".format(a)
        else:
            positionals.append(a)
        i += 1
    return opts, positionals, None


def _int_or(s: str) -> Optional[int]:
    try:
        return int(s)
    except ValueError:
        return None


def _apply_overrides(settings: Settings, opts: _Opts) -> Optional[str]:
    if opts.angle:
        settings.angle = opts.angle
    if opts.full:
        settings.full = True
    if opts.precision is not None:
        settings.precision = opts.precision
    if opts.out_base is not None:
        b = _normalize_base(opts.out_base)
        if b not in ("dec", "hex", "bin", "oct"):
            return "unknown base '{}' (use dec/hex/bin/oct)".format(opts.out_base)
        settings.base = b
    return None


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    opts, positionals, err = _parse_argv(argv)
    if err:
        print("calc: {}".format(err), file=sys.stderr)
        return 2

    if opts.version:
        print("calc {}".format(__version__))
        return 0
    if opts.help:
        print(help_text())
        return 0
    if opts.examples:
        print(help_text("examples"))
        return 0

    store = Store()

    # management command?
    if positionals and positionals[0].lower() in COMMAND_VERBS:
        return run_command(positionals[0], positionals[1:], store, opts.assume_yes)

    scope, settings = store.load()
    oerr = _apply_overrides(settings, opts)
    if oerr:
        print("calc: {}".format(oerr), file=sys.stderr)
        return 2

    expr = " ".join(positionals).strip()
    stdin_is_tty = sys.stdin.isatty()

    if opts.repl or (not expr and stdin_is_tty):
        from uai_toolkit.calc.frontends.repl import run_repl
        return run_repl(scope, settings, store)

    if expr:
        if not stdin_is_tty:
            code = _bind_stdin_ans(scope, settings)
            if code:
                return code
        return _run_oneshot(expr, scope, settings)

    if not stdin_is_tty:
        return _run_filter(scope, settings)

    # no expression, at a tty
    from uai_toolkit.calc.frontends.repl import run_repl
    return run_repl(scope, settings, store)


# --- frontends: oneshot & filter (REPL lives in frontends/repl.py) ---------

def _emit_error(e: CalcError) -> None:
    print(e.render(), file=sys.stderr)


def _run_oneshot(expr: str, scope: Scope, settings: Settings) -> int:
    try:
        r = evaluate(expr, scope, settings)
    except CalcError as e:
        _emit_error(e)
        return 1
    if r.warning:
        print(r.warning, file=sys.stderr)
    if not r.is_nothing and r.text is not None:
        print(r.text)
    return 0


def _run_filter(scope: Scope, settings: Settings) -> int:
    status = 0
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            r = evaluate(line, scope, settings)
        except CalcError as e:
            _emit_error(e)
            status = 1
            continue
        if r.warning:
            print(r.warning, file=sys.stderr)
        if not r.is_nothing and r.text is not None:
            print(r.text)
            scope.define("ans", r.value)
            scope.define("_", r.value)
    return status


def _bind_stdin_ans(scope: Scope, settings: Settings) -> int:
    """Evaluate piped stdin (shared scope); bind its last value to ans/_."""
    last = None
    for raw in sys.stdin.read().splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            r = evaluate(raw, scope, settings)
        except CalcError as e:
            _emit_error(e)
            return 1
        if not r.is_nothing:
            last = r.value
    if last is not None and last is not NOTHING:
        scope.define("ans", last)
        scope.define("_", last)
    return 0


if __name__ == "__main__":
    sys.exit(main())
