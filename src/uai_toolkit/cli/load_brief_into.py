#!/usr/bin/env python3
"""
load_brief_into.py — Legacy wrapper. Use load_context.py instead.

Translates --session/--brief args to load_context.py's interface.
"""
import os
import sys
from pathlib import Path

_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
_CLI_DIR = _AI_ROOT / "ai_general" / "scripts" / "cli"

if __name__ == "__main__":
    load_context = _CLI_DIR / "load_context.py"
    os.execv(sys.executable, [sys.executable, str(load_context)] + sys.argv[1:])
