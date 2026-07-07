#!/usr/bin/env python3
"""
repl_base.py — shared interactive REPL base for the fleet's CLI managers.

This generalizes the per-manager readline REPL that several tools (e.g.
``scheduling/scheduled_task_mgr.py``, ``context_files/context_mgr.py``) each
hand-rolled: load a history file, install a tab completer, bind ``tab:
complete``, loop on ``input()`` dispatching each line, and write history on
exit. Rather than copy that loop into every manager, call :func:`run_repl` and
pass a ``dispatch`` callback plus optional ``completer_words``/``history_file``.

Design notes
------------
- **Stdlib only.** ``readline`` is optional: if it cannot be imported (or when a
  scripted ``input_lines`` iterable is supplied for TTY-free tests), the REPL
  still runs over plain ``input()`` with no history/completion side effects.
- **Errors never exit the loop.** Any exception raised by ``dispatch`` is caught,
  printed as ``error: <msg>`` to ``out``, and the loop continues. Only
  ``quit``/``exit``/``q``/EOF/Ctrl-C exit, returning 0.
- **All output goes through ``out``** (defaults to ``sys.stdout``) so tests can
  capture the banner, prompts, and error lines.

Terms
-----
- *dispatch*: a callable taking the stripped input line (str) and acting on it.
  Its return value is ignored; raising is how a command signals an error.
- *completer_words*: either a list of completion candidates (verbs/flags) or a
  zero-arg callable returning such a list (evaluated per completion request so
  dynamic candidates stay fresh).
"""

from __future__ import annotations

import sys
from typing import Callable, Iterable, List, Optional, Union

try:  # readline is optional; absent on some platforms / in scripted tests.
    import readline as _readline
    _HAS_READLINE = True
except ImportError:  # pragma: no cover - platform dependent
    _readline = None
    _HAS_READLINE = False

# Verbs that end the session.
_QUIT_WORDS = frozenset({"quit", "exit", "q"})

# Default cap on persisted history lines.
_HISTORY_MAX = 1000

WordsSource = Union[Iterable[str], Callable[[], Iterable[str]]]


def build_completer(words: WordsSource) -> Callable[[str, int], Optional[str]]:
    """Build a readline-style completer over ``words``.

    ``words`` may be an iterable of candidates or a zero-arg callable returning
    one (so dynamic candidate sets are recomputed per request). The returned
    function has the ``(text, state) -> match | None`` signature readline
    expects and is independently unit-testable without readline installed.
    """

    def completer(text: str, state: int) -> Optional[str]:
        candidates = list(words() if callable(words) else words)
        matches = [w for w in candidates if w.startswith(text)]
        try:
            return matches[state]
        except IndexError:
            return None

    return completer


def _setup_readline(history_file, completer_words: Optional[WordsSource]) -> bool:
    """Best-effort readline setup. Returns True if readline is active."""
    if not _HAS_READLINE:
        return False
    if history_file is not None:
        try:
            if history_file.exists():
                _readline.read_history_file(str(history_file))
        except Exception:  # pragma: no cover - history load is best-effort
            pass
    try:
        _readline.set_history_length(_HISTORY_MAX)
    except Exception:  # pragma: no cover
        pass
    if completer_words is not None:
        try:
            _readline.set_completer(build_completer(completer_words))
            _readline.parse_and_bind("tab: complete")
        except Exception:  # pragma: no cover
            pass
    return True


def run_repl(
    *,
    dispatch: Callable[[str], object],
    prompt: str = "> ",
    history_file=None,
    completer_words: Optional[WordsSource] = None,
    banner: Optional[str] = None,
    out=None,
    input_lines: Optional[Iterable[str]] = None,
) -> int:
    """Run a line-oriented interactive REPL.

    Args:
        dispatch: called with each non-empty, non-quit line (stripped). Any
            exception it raises is caught and reported; the loop continues.
        prompt: prompt string passed to ``input()`` in interactive mode.
        history_file: optional ``Path`` for readline history (load on start,
            write on exit). Ignored when readline is inactive or scripted.
        completer_words: candidates (or a callable returning them) for tab
            completion. See :func:`build_completer`.
        banner: printed once to ``out`` before the loop, if given.
        out: output stream for banner/prompts/errors (defaults to stdout).
        input_lines: when provided, lines are consumed from this iterable
            instead of stdin — readline/history are NOT touched (TTY-free tests).

    Returns 0 on clean exit.
    """
    out = out if out is not None else sys.stdout
    scripted = input_lines is not None

    readline_active = False
    if not scripted:
        readline_active = _setup_readline(history_file, completer_words)

    if banner is not None:
        print(banner, file=out)

    line_iter = iter(input_lines) if scripted else None

    def read_line() -> str:
        if scripted:
            return next(line_iter)  # StopIteration -> EOF below
        return input(prompt)

    while True:
        try:
            raw = read_line()
        except (EOFError, StopIteration, KeyboardInterrupt):
            print("", file=out)
            break

        line = (raw or "").strip()
        if not line:
            continue
        if line.lower() in _QUIT_WORDS:
            break

        try:
            dispatch(line)
        except Exception as exc:  # a command error never exits the loop
            print("error: {}".format(exc), file=out)
            continue

    if readline_active and history_file is not None:
        try:
            _readline.write_history_file(str(history_file))
        except Exception:  # pragma: no cover - history write is best-effort
            pass

    return 0
