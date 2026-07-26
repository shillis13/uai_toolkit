"""Handlers for the non-calculation management commands.

Each returns a process exit code. They operate on a :class:`calc.store.Store`
and print to stdout/stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List

from uai_toolkit.calc.store import Store, IndexStale, SETTINGS_KEYS
from uai_toolkit.calc.helptext import help_text


def run_command(verb: str, args: List[str], store: Store,
                assume_yes: bool = False) -> int:
    verb = verb.lower()
    handler = {
        "list": cmd_list,
        "show": cmd_show,
        "del": cmd_del,
        "clear": cmd_clear,
        "edit": cmd_edit,
        "path": cmd_path,
        "set": cmd_set,
        "def": cmd_def,
        "help": cmd_help,
        "shell-init": cmd_shell_init,
    }.get(verb)
    if handler is None:
        print("calc: unknown command '{}'".format(verb), file=sys.stderr)
        return 2
    try:
        return handler(args, store, assume_yes)
    except IndexStale as e:
        print("calc: {}".format(e), file=sys.stderr)
        return 1


def cmd_list(args, store: Store, assume_yes: bool) -> int:
    defs = store.definitions()
    settings = store.settings_lines()
    if not defs and not settings:
        print("no saved definitions or settings. Add one with: calc def \"f(x)=x^2\"")
        return 0
    if defs:
        width = len(str(len(defs)))
        print("DEFINITIONS")
        for i, (_name, text) in enumerate(defs, 1):
            print("  {:>{w}}) {}".format(i, text, w=width))
        store.write_index([name for name, _ in defs])
    if settings:
        print("SETTINGS")
        for key, val in settings:
            print("  {} = {}".format(key, val))
    return 0


def cmd_show(args, store: Store, assume_yes: bool) -> int:
    if not args:
        print("calc: show needs a name or index", file=sys.stderr)
        return 2
    try:
        name, text = store.get_definition(args[0])
    except KeyError:
        print("calc: no definition '{}'".format(args[0]), file=sys.stderr)
        return 1
    print(text)
    return 0


def cmd_del(args, store: Store, assume_yes: bool) -> int:
    if not args:
        print("calc: del needs a name or index", file=sys.stderr)
        return 2
    try:
        name = store.remove(args[0])
    except KeyError:
        print("calc: no definition '{}'".format(args[0]), file=sys.stderr)
        return 1
    print("deleted {}".format(name))
    return 0


def cmd_clear(args, store: Store, assume_yes: bool) -> int:
    if not store.definitions():
        print("nothing to clear")
        return 0
    if not assume_yes:
        if not sys.stdin.isatty():
            print("calc: refusing to clear without --yes (non-interactive)",
                  file=sys.stderr)
            return 1
        reply = input("Remove all saved definitions? [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            print("cancelled")
            return 0
    n = store.clear()
    print("cleared {} definition(s)".format(n))
    return 0


def cmd_edit(args, store: Store, assume_yes: bool) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("calc: 'edit' needs an interactive terminal; file is at {}"
              .format(store.path), file=sys.stderr)
        return 1
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    if not os.path.exists(store.path):
        open(store.path, "a", encoding="utf-8").close()
    try:
        return subprocess.call([editor, store.path])
    except OSError as e:
        print("calc: could not launch editor '{}': {}".format(editor, e),
              file=sys.stderr)
        return 1


def cmd_path(args, store: Store, assume_yes: bool) -> int:
    print(store.path)
    return 0


def cmd_set(args, store: Store, assume_yes: bool) -> int:
    if len(args) < 2:
        print("calc: set needs a key and a value (keys: {})"
              .format(", ".join(SETTINGS_KEYS)), file=sys.stderr)
        return 2
    key, value = args[0], " ".join(args[1:])
    try:
        store.set_setting(key, value)
    except ValueError as e:
        print("calc: {}".format(e), file=sys.stderr)
        return 1
    print("set {} = {}".format(key.lower(), value))
    return 0


def cmd_def(args, store: Store, assume_yes: bool) -> int:
    if not args:
        print("calc: def needs a definition, e.g. calc def \"f(x)=x^2+1\"",
              file=sys.stderr)
        return 2
    text = " ".join(args)
    try:
        name = store.add_definition(text)
    except ValueError as e:
        print("calc: {}".format(e), file=sys.stderr)
        return 1
    print("defined {}".format(name))
    return 0


def cmd_help(args, store: Store, assume_yes: bool) -> int:
    print(help_text(args[0] if args else None))
    return 0


def cmd_shell_init(args, store: Store, assume_yes: bool) -> int:
    shell = (args[0] if args else "bash").lower()
    snippet = SHELL_INIT.get(shell)
    if snippet is None:
        print("calc: unknown shell '{}' (try: bash zsh fish powershell)"
              .format(shell), file=sys.stderr)
        return 2
    print(snippet)
    return 0


# Sourced wrappers that capture calc's output into a shell variable `$ans`
# (per-shell-session; no state file, no cross-terminal races). Only $ans is
# exported — bash clobbers $_ on every command, so it is not shipped.
SHELL_INIT = {
    "bash": (
        "# calc: add to ~/.bashrc  ->  eval \"$(calc shell-init bash)\"\n"
        "calc() {\n"
        "  local out\n"
        "  out=$(command calc \"$@\") || return\n"
        "  export ans=\"$out\"\n"
        "  printf '%s\\n' \"$out\"\n"
        "}"
    ),
    "zsh": (
        "# calc: add to ~/.zshrc  ->  eval \"$(calc shell-init zsh)\"\n"
        "calc() {\n"
        "  local out\n"
        "  out=$(command calc \"$@\") || return\n"
        "  export ans=\"$out\"\n"
        "  printf '%s\\n' \"$out\"\n"
        "}"
    ),
    "fish": (
        "# calc: add to config.fish  ->  calc shell-init fish | source\n"
        "function calc\n"
        "  set -l out (command calc $argv); or return\n"
        "  set -gx ans $out\n"
        "  printf '%s\\n' $out\n"
        "end"
    ),
    "powershell": (
        "# calc: add to $PROFILE  ->  calc shell-init powershell | Out-String | iex\n"
        "function calc {\n"
        "  $out = & (Get-Command -CommandType Application calc) @args\n"
        "  if ($LASTEXITCODE -ne 0) { return }\n"
        "  $env:ans = $out\n"
        "  $out\n"
        "}"
    ),
}
