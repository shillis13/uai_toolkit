#!/usr/bin/env python3
"""PostToolUse hook for Edit|Write — tracks the write in file access state."""

import json
import os
import sys
from pathlib import Path

# Locate ai_general/scripts/file_access: honor $AI_SCRIPTS override, else derive
# from this hook's location (…/data/hooks/PostToolUse/ -> parents[3] = ai_general).
_scripts = os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[3] / "scripts")
sys.path.insert(0, str(Path(_scripts) / "file_access"))
import random
from uai_toolkit.file_access.tracker import log_write, prune

def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
    file_path = data.get("tool_input", {}).get("file_path", "")

    if file_path:
        log_write(session_id, file_path)

    # Auto-prune ~1% of the time to keep log manageable
    if random.random() < 0.01:
        prune()

    print("{}")

if __name__ == "__main__":
    main()
