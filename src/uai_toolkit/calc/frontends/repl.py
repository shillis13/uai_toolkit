"""The interactive REPL — the opt-in "build up a formula" mode.

Uses ``prompt_toolkit`` when available for the non-destructive help that
motivated it: a completion menu of function/constant names as you type, and a
live bottom toolbar showing the current result / parse status and mode without
disturbing your in-progress line. Degrades to a plain ``input()`` loop when
``prompt_toolkit`` is not installed. The engine itself never imports it.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from uai_toolkit.calc.engine import evaluate, Scope, Settings, CalcError, NOTHING
from uai_toolkit.calc.engine.builtins import BUILTINS, CONSTANTS
from uai_toolkit.calc.engine.settings import Settings as _S
from uai_toolkit.calc.store import Store
from uai_toolkit.calc.commands import run_command
from uai_toolkit.calc.reserved import COMMAND_VERBS, GRAMMAR_KEYWORDS
from uai_toolkit.calc.helptext import help_text

_MUTATING = {"def", "set", "del", "clear", "edit"}
_QUIT = {"quit", "exit", ":q", "\\q"}


def _completions() -> List[str]:
    words = sorted(set(BUILTINS) | set(CONSTANTS) | set(GRAMMAR_KEYWORDS)
                   | set(COMMAND_VERBS))
    return words


def _prompt_str(settings: Settings) -> str:
    tags = []
    if settings.angle != "rad":
        tags.append(settings.angle)
    if settings.base != "dec":
        tags.append(settings.base)
    return "calc[{}]> ".format(",".join(tags)) if tags else "calc> "


def run_repl(scope: Scope, settings: Settings, store: Store) -> int:
    import sys
    print("calc — type an expression, '?' for help, 'quit' to exit")
    # prompt_toolkit needs a real terminal; a forced REPL over a pipe uses plain.
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit import PromptSession  # noqa: F401
            return _ptk_repl(scope, settings, store)
        except ImportError:
            pass
    return _plain_repl(scope, settings, store)


# --- shared line handling --------------------------------------------------

def _handle(line: str, scope: Scope, settings: Settings,
            store: Store) -> "Tuple[bool, Scope, Settings]":
    """Process one input line. Returns (should_exit, scope, settings)."""
    s = line.strip()
    if not s:
        return False, scope, settings
    if s.lower() in _QUIT:
        return True, scope, settings
    if s == "?":
        print(help_text())
        return False, scope, settings
    if s.startswith("?"):
        print(help_text(s[1:].strip() or None))
        return False, scope, settings

    first = s.split(None, 1)
    verb = first[0].lower()
    if verb in COMMAND_VERBS:
        remainder = first[1] if len(first) > 1 else ""
        remainder = _unquote(remainder)   # no shell in the REPL; quotes optional
        args = [remainder] if verb == "def" else (remainder.split() if remainder else [])
        run_command(verb, args, store, assume_yes=False)
        if verb in _MUTATING:
            scope, settings = _resync(scope, settings, store)
        return False, scope, settings

    # otherwise: an expression
    try:
        r = evaluate(line, scope, settings)
    except CalcError as e:
        print(e.render())
        return False, scope, settings
    if r.warning:
        print(r.warning)
    if not r.is_nothing and r.text is not None:
        print(r.text)
        scope.define("ans", r.value)
        scope.define("_", r.value)
    return False, scope, settings


def _unquote(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


def _resync(scope: Scope, settings: Settings,
            store: Store) -> "Tuple[Scope, Settings]":
    """Reload persisted defs/settings while preserving in-session bindings."""
    session_vars = dict(scope.vars)
    new_scope, new_settings = store.load()
    new_scope.vars.update(session_vars)
    return new_scope, new_settings


# --- plain fallback --------------------------------------------------------

def _plain_repl(scope: Scope, settings: Settings, store: Store) -> int:
    while True:
        try:
            line = input(_prompt_str(settings))
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("^C")
            continue
        should_exit, scope, settings = _handle(line, scope, settings, store)
        if should_exit:
            return 0


# --- prompt_toolkit path ---------------------------------------------------

def _ptk_repl(scope: Scope, settings: Settings, store: Store) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.application.current import get_app

    completer = WordCompleter(_completions(), ignore_case=True, sentence=False)
    history = InMemoryHistory()

    # A live status line: previews the current line's value / parse status and
    # shows the mode, without disturbing the buffer.
    state = {"scope": scope, "settings": settings}

    def bottom_toolbar():
        try:
            text = get_app().current_buffer.text
        except Exception:
            text = ""
        st = state["settings"]
        mode = "{} · {}".format(st.angle, st.base)
        preview = _preview(text, state["scope"], st)
        return " {} │ {} │ Tab complete · ? help · ↑ history".format(preview, mode)

    session = PromptSession(history=history, completer=completer,
                            bottom_toolbar=bottom_toolbar,
                            complete_while_typing=True)

    while True:
        try:
            line = session.prompt(_prompt_str(state["settings"]))
        except EOFError:
            return 0
        except KeyboardInterrupt:
            continue
        should_exit, new_scope, new_settings = _handle(
            line, state["scope"], state["settings"], store)
        state["scope"], state["settings"] = new_scope, new_settings
        if should_exit:
            return 0


def _preview(text: str, scope: Scope, settings: Settings) -> str:
    s = text.strip()
    if not s or s.split(None, 1)[0].lower() in COMMAND_VERBS or s.startswith("?"):
        return "…"
    # paren balance hint
    bal = s.count("(") - s.count(")")
    if bal > 0:
        return "{} unclosed '('".format(bal)
    if bal < 0:
        return "{} extra ')'".format(-bal)
    try:
        # preview must not mutate the live scope
        r = evaluate(text, Scope(parent=scope), settings)
    except CalcError:
        return "…"
    except Exception:
        return "…"
    if r.is_nothing or r.text is None:
        return "…"
    return "= {}".format(r.text)
