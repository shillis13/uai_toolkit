#!/usr/bin/env python3
"""PostToolUse guard for Write|Edit|MultiEdit.

Catches the large-content stubbing bug: when Write/Edit/MultiEdit is given a large
`content`/`new_string`, the input can be archived to an offload placeholder
(e.g. "[input archived: Edit(new_string) · 3,700 chars (~925 tok) · ac06e0c1 → ref
offload.<id>/<toolu>.input.new_string.txt (resolve via read_jsonl) …]") and that STUB
can land on disk as the actual write — silently losing the real content. The tool_result
still reports success and a follow-up Read returns the same stub, so the AI has NO in-band
way to notice: only raw bytes are ground truth. That is why this out-of-band hook exists.

Two corruption shapes, two detection rules (Anvil, 2026-07-15, 4 incidents / 3 files):
  • Whole-file Write  → stub at line 1. Caught for EVERY file (incl. .md/.txt): a doc whose
    entire content was replaced starts with the stub. (This is how meridian_instructions.md
    and relationship_pianoman_bc.md were lost on 2026-06-30.)
  • Mid-file Edit      → a single new_string block replaced by the stub, deep in the file
    (Anvil saw lines 244 / 3267 / 698). The old line-1-only check MISSED all of these.
    We now scan ALL lines — but only for SOURCE files, and only for the FULL stub shape
    (`… · N chars (~N tok) · <sha8>`), so a .md/design doc that legitimately QUOTES a stub
    prefix mid-prose does not false-positive.

On detection: exit 2 (block) so the agent is told IMMEDIATELY — while the real content is
still in context — to re-write via a Bash heredoc (heredoc/Bash writes are immune).
"""

import json
import re
import sys
from pathlib import Path

# Offload stub prefixes (kept in sync with offload_tool_results.py STUB_PREFIXES).
STUB_PREFIXES = ("[archived:", "[tool result stripped:", "[input archived:", "[input stripped:")

# Full-shape stub: the label + the distinctive `· N chars (~N tok) · <sha8>` spine that
# offload_tool_results._stub() always emits. The mid-file scan requires BOTH this full
# shape AND that the stub STARTS the line (re.match on the l-stripped line): a real
# corruption's written value IS the stub, whereas docs/source that merely document a stub
# embed it after prose (e.g. `(e.g. "[input archived: …`), so it won't be at line-start.
STUB_LINE_RE = re.compile(
    r"\[(?:input archived|input stripped|archived|tool result stripped|"
    r"attachment archived|attachment stripped): "
    r".+? · [\d,]+ chars \(~[\d,]+ tok\) · [0-9a-f]{6,}"
)

# Extensions where a stub line is NEVER legitimate content, so the all-lines mid-file scan
# is safe. Everything else (.md, .txt, docs) uses line-1-only detection.
SOURCE_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".scss", ".less",
    ".py", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".hpp",
    ".rb", ".php", ".swift", ".sh", ".bash", ".zsh", ".sql", ".html", ".vue",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
}


def find_stub_corruption(path: Path):
    """Return (lineno, text) of the corrupting stub, or None if the file looks clean.

    Rule 1 (all files): line 1 begins with a stub prefix  -> whole-file Write loss.
    Rule 2 (source exts only): any line matches the full stub shape -> mid-file Edit loss.
    lineno is 1-indexed; text is the offending line stripped of trailing newline.
    """
    is_source = path.suffix.lower() in SOURCE_EXTS
    saw_first_nonblank = False
    try:
        with path.open("r", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                # Rule 1 — whole-file replacement: first non-blank line is a stub
                # (any file type).
                if not saw_first_nonblank and line.strip():
                    saw_first_nonblank = True
                    if line.lstrip().startswith(STUB_PREFIXES):
                        return (i, line.rstrip("\n"))
                    if not is_source:
                        return None

                # Rule 2 — mid-file Edit replacement: full-shape stub anywhere in
                # source files. Stream the whole file: real incidents have appeared
                # thousands of lines in, past any fixed-size head read.
                if is_source and STUB_LINE_RE.match(line.lstrip()):
                    return (i, line.rstrip("\n"))
    except Exception:
        return None

    return None


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

    hit = find_stub_corruption(Path(fp))
    if hit:
        lineno, _ = hit
        where = "begins with" if lineno == 1 else f"contains at line {lineno}"
        msg = (
            f"WRITE CORRUPTED: {fp} {where} an offload stub instead of the real content. "
            f"The write silently replaced large `content`/`new_string` with a placeholder on "
            f"disk (the content is NOT recoverable from the stub, and a Read will show you the "
            f"SAME stub — only raw bytes are ground truth). RE-WRITE the real content NOW, while "
            f"it is still in your context. For a whole-file loss use a Bash heredoc "
            f"(`cat > '{fp}' << 'EOF' … EOF`); for a single mid-file block, splice the real text "
            f"over line {lineno} with a Python one-liner. Do NOT use the Write/Edit tool for the "
            f"large payload — heredoc/Bash writes are immune."
        )
        print(msg, file=sys.stderr)
        return 2

    print("{}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
