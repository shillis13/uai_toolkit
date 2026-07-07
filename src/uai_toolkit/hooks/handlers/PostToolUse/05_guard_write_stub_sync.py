#!/usr/bin/env python3
"""PostToolUse guard for Write|Edit|MultiEdit.

Catches the large-content stubbing bug: when the Write tool is given large
`content`, the harness can replace it on disk with an offload placeholder
(e.g. "[input archived: Write(content) ... resolve via read_jsonl ...]"),
silently losing the real content. Bash/heredoc writes are immune.

This guard reads the just-written file and, if its first non-blank line is an
offload stub, exits 2 (block) so the agent is told IMMEDIATELY — while the real
content is still in context — to re-write the file via a Bash heredoc instead of
the Write tool. Without this, the loss is silent and only discovered after the
content has been compacted away (which is exactly how meridian_instructions.md
and relationship_pianoman_bc.md were lost on 2026-06-30).
"""

import json
import sys
from pathlib import Path

# Offload stub prefixes (kept in sync with offload_tool_results.py STUB_PREFIXES).
STUB_PREFIXES = ("[archived:", "[tool result stripped:", "[input archived:", "[input stripped:")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("{}")
        return 0

    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit"):
        print("{}")
        return 0

    fp = data.get("tool_input", {}).get("file_path", "")
    if not fp:
        print("{}")
        return 0

    p = Path(fp)
    try:
        # Only need the head; corrupted files are stub-at-line-1.
        with p.open("r", errors="replace") as f:
            head = f.read(4096)
    except Exception:
        print("{}")
        return 0

    first = head.lstrip()
    if first.startswith(STUB_PREFIXES):
        msg = (
            f"WRITE CORRUPTED: {fp} now begins with an offload stub instead of the real "
            f"content. The Write tool silently replaced large `content` with a placeholder "
            f"on disk (the content is NOT recoverable from the stub). RE-WRITE this file NOW, "
            f"while the content is still in your context, using a Bash heredoc "
            f"(`cat > '{fp}' << 'EOF' ... EOF`) — heredoc/Bash writes are immune. "
            f"Do NOT use the Write tool for large files."
        )
        print(msg, file=sys.stderr)
        return 2

    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
