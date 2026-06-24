#!/usr/bin/env python3
"""Smoke test — validate an ai_toolkit install (esp. on a fresh Linux/WSL box).

Run after `pip install -e '.[mcp]'`:

    python tests/smoke_test.py

Checks, in order of dependency:
  1. Python >= 3.10
  2. core package + every CLI module imports
  3. CLI entry points run (read_jsonl --help)
  4. MCP servers import + list their tools (static — no content needed)
  5. (optional) if AI_ROOT has content, a real guidance/todo tool call

Exit 0 if all REQUIRED checks pass. Content-dependent checks are skipped (not
failed) when AI_ROOT isn't populated, so this is meaningful on a bare box.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PASS, FAIL, SKIP = "✅", "❌", "—"
failures = 0


def check(label: str, fn):
    global failures
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {e}"
    mark = PASS if ok is True else (SKIP if ok is None else FAIL)
    if ok is False:
        failures += 1
    print(f"  {mark} {label}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    print("ai_toolkit smoke test")
    print(f"  python {sys.version.split()[0]}  |  AI_ROOT={os.environ.get('AI_ROOT', '(unset)')}\n")

    check("python >= 3.10", lambda: (sys.version_info >= (3, 10), None))

    def imports():
        import ai_toolkit  # noqa: F401
        from ai_toolkit.jsonl import read_jsonl, catjsonl, discovery  # noqa: F401
        from ai_toolkit.file_access import tracker, hooks  # noqa: F401
        from ai_toolkit import install, paths  # noqa: F401
        from ai_toolkit.common_utils import lib_outputColors  # noqa: F401
        return True, "core + cli + file_access + common_utils"
    check("core package imports", imports)

    def cli_runs():
        exe = Path(sys.executable).with_name("read_jsonl")
        cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "ai_toolkit.jsonl.read_jsonl"]
        r = subprocess.run(cmd + ["--help"], capture_output=True, text=True, timeout=30)
        return (r.returncode == 0 and "read_jsonl" in r.stdout), "read_jsonl --help"
    check("read_jsonl runs", cli_runs)

    def mcp_imports():
        try:
            import mcp  # noqa: F401
        except ImportError:
            return None, "mcp extra not installed (pip install '.[mcp]')"
        from ai_toolkit.mcp.knowledge import server as k
        from ai_toolkit.mcp.workflow import server as w
        return True, f"knowledge {len(k.DISPATCH)} tools, workflow {len(w.DISPATCH)} tools"
    check("MCP servers import + list tools", mcp_imports)

    def guidance_content():
        root = os.environ.get("AI_ROOT")
        if not root:
            return None, "AI_ROOT unset — content checks skipped"
        db = Path(root) / "ai_general" / "data" / "context_files" / "context_files_registry.db"
        if not db.is_file():
            return None, "no guidance registry DB in AI_ROOT — content not materialized"
        r = subprocess.run(
            [sys.executable, "-m", "ai_toolkit.guidance.guidance_cli", "test"],
            capture_output=True, text=True, timeout=30,
        )
        return (r.returncode == 0 and "OK" in r.stdout), r.stdout.strip().split(chr(10))[0][:60]
    check("guidance tool vs real content", guidance_content)

    print()
    if failures:
        print(f"{FAIL} {failures} required check(s) failed.")
        return 1
    print(f"{PASS} all required checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
