#!/usr/bin/env python3
"""Temporary debug handler — dumps raw stdin JSON to a file for inspection.

Writes to: ai_general/data/hooks/data/stdin_dumps/{platform}_{event}_{timestamp}.json

Install in any hook type directory to capture what that platform sends.
Remove after inspection.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
DUMP_DIR = AI_ROOT / "ai_general" / "data" / "hooks" / "data" / "stdin_dumps"


def main():
    raw = ""
    try:
        raw = sys.stdin.read()
    except (IOError, OSError):
        pass

    if not raw.strip():
        return 0

    DUMP_DIR.mkdir(parents=True, exist_ok=True)

    platform = os.environ.get("AI_SESSION_PLATFORM", "unknown")
    tracking_id = os.environ.get("AI_TRACKING_ID", "unknown")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Try to extract event name from the JSON
    event = "unknown"
    try:
        data = json.loads(raw)
        event = data.get("hook_event_name", "unknown")
    except json.JSONDecodeError:
        pass

    filename = f"{platform}_{event}_{ts}_{tracking_id[:20]}.json"
    dump_path = DUMP_DIR / filename

    try:
        # Pretty-print if valid JSON, raw otherwise
        try:
            parsed = json.loads(raw)
            dump_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            dump_path.write_text(raw)
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
