"""Durable storage: the ``calcrc`` file, settings, and the ephemeral index.

``calcrc`` is written in the calculator's own grammar and is hand-editable. It
holds two kinds of lines: setting lines (``angle = deg``) whose keys are a known
set, and definition lines (``f(x) = x^2``, ``c = 3e8``) which are replayed
through the engine at startup. Writes are atomic (temp + rename). The only
module that touches persistent disk state.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import List, Optional, Tuple

from uai_toolkit.calc.engine import Scope, Settings, evaluate
from uai_toolkit.calc.engine.parser import parse
from uai_toolkit.calc.engine import ast_nodes as A
from uai_toolkit.calc.engine.formatter import _normalize_base

SETTINGS_KEYS = ("angle", "base", "precision", "full")


def config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "calc")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "calc")


def calcrc_path() -> str:
    return os.path.join(config_dir(), "calcrc")


def _index_path() -> str:
    return os.path.join(config_dir(), "index.snapshot")


class Entry:
    """One line of calcrc: kind is 'def', 'set', or 'raw'."""

    __slots__ = ("kind", "name", "text")

    def __init__(self, kind: str, name: Optional[str], text: str) -> None:
        self.kind = kind
        self.name = name
        self.text = text


class Store:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or calcrc_path()

    # -- parsing calcrc into entries ---------------------------------------
    def read_entries(self) -> List[Entry]:
        entries: List[Entry] = []
        if not os.path.exists(self.path):
            return entries
        with open(self.path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    entries.append(Entry("raw", None, line))
                    continue
                if "=" in line:
                    lhs = line.split("=", 1)[0].strip()
                    if lhs.lower() in SETTINGS_KEYS and "(" not in lhs:
                        entries.append(Entry("set", lhs.lower(), line))
                        continue
                    name = _def_name(line)
                    if name is not None:
                        entries.append(Entry("def", name, line))
                        continue
                entries.append(Entry("raw", None, line))
        return entries

    # -- building the live session state -----------------------------------
    def load(self) -> "Tuple[Scope, Settings]":
        """Return a (scope, settings) primed from calcrc."""
        scope = Scope()
        settings = Settings()
        import sys
        for e in self.read_entries():
            try:
                if e.kind == "set":
                    _apply_setting(settings, e.name, e.text.split("=", 1)[1].strip())
                elif e.kind == "def":
                    # replay the definition into the base scope
                    evaluate(e.text, scope, settings)
            except Exception as exc:  # a bad calcrc line must not break every call
                print("calc: skipping bad calcrc line {!r}: {}".format(e.text, exc),
                      file=sys.stderr)
        return scope, settings

    # -- mutations ----------------------------------------------------------
    def add_definition(self, text: str) -> str:
        """Persist a definition (``f(x)=…`` or ``c=…``); returns its name."""
        name = _def_name(text)
        if name is None:
            raise ValueError("not a definition: {!r}".format(text))
        entries = self.read_entries()
        replaced = False
        for i, e in enumerate(entries):
            if e.kind == "def" and e.name == name:
                entries[i] = Entry("def", name, text)
                replaced = True
                break
        if not replaced:
            entries.append(Entry("def", name, text))
        self._write(entries)
        self._invalidate_index()
        return name

    def set_setting(self, key: str, value: str) -> None:
        key = key.lower()
        if key not in SETTINGS_KEYS:
            raise ValueError("unknown setting '{}'".format(key))
        _apply_setting(Settings(), key, value)  # validate
        line = "{} = {}".format(key, value)
        entries = self.read_entries()
        for i, e in enumerate(entries):
            if e.kind == "set" and e.name == key:
                entries[i] = Entry("set", key, line)
                break
        else:
            entries.append(Entry("set", key, line))
        self._write(entries)

    def remove(self, ref: str) -> str:
        """Remove a definition by name or by ephemeral index; returns its name."""
        name = self._resolve_ref(ref)
        entries = self.read_entries()
        kept = [e for e in entries if not (e.kind == "def" and e.name == name)]
        if len(kept) == len(entries):
            raise KeyError(name)
        self._write(kept)
        self._invalidate_index()
        return name

    def clear(self) -> int:
        entries = self.read_entries()
        defs = [e for e in entries if e.kind == "def"]
        kept = [e for e in entries if e.kind != "def"]
        self._write(kept)
        self._invalidate_index()
        return len(defs)

    def definitions(self) -> List[Tuple[str, str]]:
        return [(e.name, e.text) for e in self.read_entries() if e.kind == "def"]

    def get_definition(self, ref: str) -> "Tuple[str, str]":
        """Resolve ``ref`` (name or ephemeral index) to (name, text)."""
        name = self._resolve_ref(ref)
        for n, txt in self.definitions():
            if n == name:
                return n, txt
        raise KeyError(name)

    def settings_lines(self) -> List[Tuple[str, str]]:
        out = []
        for e in self.read_entries():
            if e.kind == "set":
                out.append((e.name, e.text.split("=", 1)[1].strip()))
        return out

    # -- ephemeral index ----------------------------------------------------
    def write_index(self, names: List[str]) -> None:
        data = {"hash": self._content_hash(), "names": names}
        _atomic_write(_index_path(), json.dumps(data))

    def _resolve_ref(self, ref: str) -> str:
        if ref.isdigit():
            return self._resolve_index(int(ref))
        return ref

    def _resolve_index(self, idx: int) -> str:
        try:
            with open(_index_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            raise IndexStale("no active listing — run 'calc list' first")
        if data.get("hash") != self._content_hash():
            raise IndexStale("index is stale — run 'calc list' again")
        names = data.get("names", [])
        if idx < 1 or idx > len(names):
            raise KeyError(str(idx))
        return names[idx - 1]

    def _invalidate_index(self) -> None:
        try:
            os.remove(_index_path())
        except OSError:
            pass

    def _content_hash(self) -> str:
        try:
            with open(self.path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return ""

    # -- writing ------------------------------------------------------------
    def _write(self, entries: List[Entry]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        body = "\n".join(e.text for e in entries)
        if body and not body.endswith("\n"):
            body += "\n"
        _atomic_write(self.path, body)


class IndexStale(Exception):
    pass


def _def_name(text: str) -> Optional[str]:
    """Return the defined name for a definition line, or None if not a def."""
    try:
        program = parse(text)
    except Exception:
        return None
    if len(program.statements) != 1:
        return None
    st = program.statements[0]
    if isinstance(st, A.Assign):
        return st.name
    return None


def _apply_setting(settings: Settings, key: str, value: str) -> None:
    value = value.strip()
    if key == "angle":
        v = value.lower()
        if v not in ("rad", "deg"):
            raise ValueError("angle must be 'rad' or 'deg'")
        settings.angle = v
    elif key == "base":
        v = _normalize_base(value)
        if v not in ("dec", "hex", "bin", "oct"):
            raise ValueError("base must be dec/hex/bin/oct")
        settings.base = v
    elif key == "precision":
        try:
            p = int(value)
        except ValueError:
            raise ValueError("precision must be a whole number")
        if not (1 <= p <= 50):
            raise ValueError("precision must be between 1 and 50")
        settings.precision = p
    elif key == "full":
        settings.full = value.lower() in ("1", "true", "yes", "on")


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
