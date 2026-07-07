#!/usr/bin/env python3
"""Derive a session's start/lifecycle history from its transcript JSONL markers.

The transcript already records every (re)instantiation of a session. Three
complementary markers (PianoMan, 2026-07-06) cover the lifecycle — none alone is
complete, so we union them:

  1. `<<<SESSION_IDENTITY>>>`  — injected at a fresh launch      → a genuine START
  2. `<<<SESSION RESUMED>>>`   — passive marker left by a Bounce → a RESUME
  3. parentUuid == null anchor — a chain root (post-compaction)  → a COMPACT/reset

Matching is STRUCTURAL (a record whose text *starts with* the marker), so echoes
of the literal string inside ordinary content or file diffs don't count. Anchors
are real conversation records (user/assistant/system with a timestamp), never the
metadata sub-records (last-prompt, custom-title, file-history-snapshot, …).

Output: a de-duplicated, ascending list of LOCAL-time ISO timestamps (matching the
`session.last_activity` convention). This is what the SessionStart hook writes into
`session.start_history`, and what the UAI app shows in the Details / Store Fields
panels ("most recent start, all prior on expand").

Usage:
    session_starts.py derive <transcript.jsonl> [<transcript2.jsonl> ...]
    session_starts.py backfill [--all]      # populate every session's state file
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Metadata sub-record types that also carry parentUuid == null but are NOT
# conversation chain anchors.
_META_TYPES = {
    "last-prompt", "custom-title", "agent-name", "mode", "permission-mode",
    "file-history-snapshot", "summary",
}
_ANCHOR_TYPES = {"user", "assistant", "system"}

# Dedup tolerance: two events within this many seconds are the same start (e.g.
# the identity marker and the first chain anchor of a fresh launch).
_DEDUP_SECONDS = 3


def _first_text(rec):
    """Best-effort leading text of a record (for structural marker matching)."""
    msg = rec.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
    return ""


def _to_local_iso(ts):
    """Normalize a transcript timestamp to a naive local-time ISO string.

    Transcript timestamps are UTC ('…Z'). We store local time to match
    session.last_activity and the workspace's local-time convention.
    """
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().replace(tzinfo=None).isoformat()
    except (ValueError, AttributeError):
        return None


def _events_from_transcript(path):
    """Yield (local_iso, kind) for every start/resume/anchor marker in a file."""
    p = Path(path)
    if not p.is_file():
        return
    try:
        fh = p.open()
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            ts = rec.get("timestamp")
            local = _to_local_iso(ts)
            if not local:
                continue
            text = _first_text(rec).lstrip()
            if text.startswith("<<<SESSION_IDENTITY>>>"):
                yield (local, "start")
            elif text.startswith("<<<SESSION RESUM"):  # RESUMED / RESUME
                yield (local, "resume")
            elif (
                rec.get("parentUuid") is None
                and rec.get("type") in _ANCHOR_TYPES
                and rec.get("type") not in _META_TYPES
            ):
                yield (local, "anchor")


def merge_starts(*timestamp_lists):
    """Flatten several local-ISO timestamp lists into one ascending, de-duplicated
    list (two entries within _DEDUP_SECONDS collapse to the earliest). Used to fold
    together prior history + transcript-derived markers + the current start."""
    seen = []
    for lst in timestamp_lists:
        for ts in (lst or []):
            if ts:
                seen.append(ts)
    seen.sort()
    kept = []
    last_dt = None
    for local in seen:
        try:
            dt = datetime.fromisoformat(local)
        except (ValueError, TypeError):
            continue
        if last_dt is not None and abs((dt - last_dt).total_seconds()) < _DEDUP_SECONDS:
            continue
        kept.append(local)
        last_dt = dt
    return kept


def derive_starts(transcript_paths):
    """Union the lifecycle markers across a session's transcript(s).

    Returns an ascending, de-duplicated list of local-time ISO timestamp strings.
    """
    if isinstance(transcript_paths, str):
        transcript_paths = [transcript_paths]

    events = []
    for path in transcript_paths or []:
        if path:
            events.extend(_events_from_transcript(path))
    return merge_starts([local for local, _kind in events])


# ── State-file write (shared with the SessionStart hook) ──────────────────────

def write_start_history(session_dir, tracking_id, history):
    """Read-modify-write session.start_history into the per-session state file,
    preserving every other key. Returns True on success."""
    path = Path(session_dir) / f"{tracking_id}_state.json"
    try:
        state = {}
        if path.exists():
            try:
                state = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                state = {}
        state["session.start_history"] = history
        state["updated_at"] = datetime.now().isoformat()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(path)
        return True
    except OSError:
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_derive(argv):
    starts = derive_starts(argv)
    print(json.dumps(starts, indent=2))
    return 0


def _cmd_backfill(argv):
    include_archived = "--all" in argv
    _here = Path(__file__).resolve().parent
    if str(_here) not in sys.path:
        sys.path.insert(0, str(_here))
    from uai_toolkit.session_mgmt.session_store import SessionStore

    store = SessionStore()
    rows = store.list()
    done = written = 0
    for r in rows:
        if not include_archived and (r.get("archived") in (1, True, "1", "true")):
            continue
        sdir, tid = r.get("session_dir"), r.get("tracking_id")
        tpaths = r.get("transcript_path") or []
        if isinstance(tpaths, str):
            tpaths = [tpaths]
        hist_file = r.get("history_file")
        if hist_file and hist_file not in tpaths:
            tpaths = [*tpaths, hist_file]
        if not (sdir and tid and tpaths):
            continue
        done += 1
        starts = derive_starts(tpaths)
        if starts and write_start_history(sdir, tid, starts):
            written += 1
    print(f"backfill: scanned {done} sessions, wrote start_history for {written}")
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "derive":
        return _cmd_derive(rest)
    if cmd == "backfill":
        return _cmd_backfill(rest)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
