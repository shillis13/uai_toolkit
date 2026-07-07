"""
Dynamic handler-dispatch discovery for MCP servers.

Builds the {tool_name: call_tool} dispatch map by DISCOVERING every module in a
server's ``tools/`` package that exposes the handler contract — a ``tools()``
function and a ``call_tool`` coroutine — instead of a hardcoded ``modules = [..]``
list bound at import time.

Why this exists (todo_0378, PianoMan's long-standing pet peeve): the schema side
(``tool_registry.ToolRegistry`` reading ``tools.yml``) already loads dynamically,
so a NEW TOOL in an EXISTING module went live via reload-on-miss with no restart.
But a brand-new ``tools/<x>.py`` MODULE was never picked up, because the running
process's ``modules`` global was bound at import and reload-on-miss only re-imported
what was already in it — so adding a tool module needed a server restart. Globbing
the package on every (re)build closes that gap: drop a new ``tools/<x>.py`` exposing
``tools()`` + ``call_tool`` and the next dispatch-miss auto-registers it, zero restart.

Usage in a server:

    from pathlib import Path
    from uai_toolkit.mcp.shared.handler_dispatch import build_dispatch

    TOOLS_DIR = Path(__file__).resolve().parent / "tools"
    HANDLER_DISPATCH = build_dispatch(TOOLS_DIR)                       # startup: strict
    ...
    # reload-on-miss inside call_tool:
    HANDLER_DISPATCH = build_dispatch(TOOLS_DIR, reload=True, strict=False)

``strict`` controls import/reload failure handling: True (startup) fails loud so a
broken module is caught immediately; False (runtime reload-on-miss) skips a broken
drop-in with a stderr warning so one bad file never bricks a running server.
Duplicate tool names across modules are ALWAYS a hard error (fail loud), matching
the original hardcoded-list guard.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def discover_modules(tools_dir: Path, package: str = "tools", *,
                     reload: bool = False, strict: bool = False) -> list:
    """Import every tool module in ``tools_dir`` exposing ``tools()`` + ``call_tool``.

    New files are ``import_module``'d; already-imported ones are ``reload``'d when
    ``reload=True`` (so edited handler code goes live). Files named ``__init__`` or
    prefixed with ``_`` are skipped (package internals / helpers), as is any module
    that doesn't expose the full handler contract — so shared helper modules dropped
    in ``tools/`` are ignored rather than mis-registered. Discovery is deterministic
    (sorted glob) so duplicate-name reporting is stable.
    """
    mods = []
    for py in sorted(tools_dir.glob("*.py")):
        stem = py.stem
        if stem == "__init__" or stem.startswith("_"):
            continue
        qualname = f"{package}.{stem}"
        try:
            mod = sys.modules.get(qualname)
            if mod is None:
                mod = importlib.import_module(qualname)
            elif reload:
                mod = importlib.reload(mod)
        except Exception as e:
            if strict:
                raise
            print(f"[handler_dispatch] skipping {qualname}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue
        if callable(getattr(mod, "tools", None)) and callable(getattr(mod, "call_tool", None)):
            mods.append(mod)
    return mods


def build_dispatch(tools_dir: Path, package: str = "tools", *,
                   reload: bool = False, strict: bool = True) -> dict:
    """{tool_name: module.call_tool} over all discovered tool modules.

    Duplicate tool names across modules are a hard error (fail loud) — the same
    guard as the original hardcoded-list dispatch. ``strict`` is forwarded to
    :func:`discover_modules` for import/reload failures.
    """
    dispatch: dict = {}
    for module in discover_modules(tools_dir, package, reload=reload, strict=strict):
        for tool in module.tools():
            if tool.name in dispatch:
                raise RuntimeError(
                    f"Duplicate handler: {tool.name} (module {module.__name__})")
            dispatch[tool.name] = module.call_tool
    return dispatch
