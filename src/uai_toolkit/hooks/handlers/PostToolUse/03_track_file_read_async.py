#!/usr/bin/env python3
"""PostToolUse hook for Read — tracks the read in file access state."""

import json
import os
import sys
from pathlib import Path

# Locate ai_general/scripts/file_access: honor $AI_SCRIPTS override, else derive
# from this hook's location (…/data/hooks/PostToolUse/ -> parents[3] = ai_general).
_scripts = os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[3] / "scripts")
sys.path.insert(0, str(Path(_scripts) / "file_access"))
from uai_toolkit.file_access.tracker import log_read

def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id", "unknown")
    file_path = data.get("tool_input", {}).get("file_path", "")

    if file_path:
        log_read(session_id, file_path)

    # Allow — no output needed for PostToolUse
    print("{}")

if __name__ == "__main__":
    main()
