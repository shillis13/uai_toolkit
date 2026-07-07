#!/usr/bin/env python3
"""PostToolUse hook for Read — tracks the read in file access state."""

import json
import sys
from pathlib import Path

sys.path.insert(0, '$AI_ROOT/ai_general/scripts/file_access')
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
