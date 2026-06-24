"""Lightweight session-file discovery (stdlib only).

Replaces the heavy file_utils.fsFind/fsFilters dependency (≈2,500 lines +
common_utils + yaml) for the one thing catjsonl needs: recursive discovery of
`.jsonl` / `logs.json` session transcripts with optional modified-time
windowing.

Dropped vs. the original: gitignore-respect. Session-transcript trees
(~/.claude/projects, ~/.codex, ...) aren't git working copies, so gitignore
filtering was effectively a no-op there.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

_REL = re.compile(r"(\d+)\s*([mhdw])")
_ABS_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_time_spec(spec: str | None) -> float | None:
    """Parse '7d'/'12h'/'30m'/'2w' relative or 'YYYY-MM-DD' absolute -> epoch.

    Returns None if spec is falsy or unparseable (treated as "no bound").
    """
    if not spec:
        return None
    spec = spec.strip()
    m = _REL.fullmatch(spec.lower())
    if m:
        return time.time() - int(m.group(1)) * _UNIT_SECONDS[m.group(2)]
    for fmt in _ABS_FORMATS:
        try:
            return datetime.strptime(spec, fmt).timestamp()
        except ValueError:
            continue
    return None


def _is_session_file(name: str) -> bool:
    # All .jsonl, plus Gemini's logs.json (matches the original's add_file_pattern).
    return name.endswith(".jsonl") or name == "logs.json"


def discover_files(
    directory: str,
    since: str | None = None,
    before: str | None = None,
    sort: str = "newest",
) -> list[Path]:
    """Recursively find session transcripts under `directory`.

    since/before window on modified-time. sort: 'newest' (default) or 'oldest'.
    """
    root = Path(directory).expanduser()
    if not root.is_dir():
        return []

    since_ts = parse_time_spec(since)
    before_ts = parse_time_spec(before)

    out: list[Path] = []
    for p in root.rglob("*"):
        if not _is_session_file(p.name):
            continue
        try:
            if not p.is_file():
                continue
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if since_ts is not None and mtime <= since_ts:
            continue
        if before_ts is not None and mtime >= before_ts:
            continue
        out.append(p)

    out.sort(key=lambda p: p.stat().st_mtime, reverse=(sort == "newest"))
    return out
