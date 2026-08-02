#!/usr/bin/env python3
"""Incremental tail of an append-mostly JSONL transcript.

For the Transcript->Memorex pipeline: read only the records appended since the
last read, without rescanning the whole file. A CURSOR (small JSON blob) tracks
the resume position; the caller round-trips it.

The transcript is NOT purely append-only — offload/compaction can REWRITE it:
  * the live Offload (offload_tool_results / offload_session) writes ATOMICALLY
    via temp + os.replace, so the file's INODE changes;
  * an in-place rewrite / truncation shrinks the file below the cursor offset.
Either way a naive "read from byte B" would silently miss in-place edits (a
tool_result you already displayed getting stubbed) or read stale bytes. So the
cursor carries inode+size and we DETECT those cases and tell the caller to
`reset` (full rescan) instead. Cheap: one os.stat per tick.

Reset triggers:
  - cursor is None (first read)
  - inode changed        -> atomic offload replaced the file
  - size < cursor.size   -> truncation / in-place shrink (e.g. stub rewrite)
  - malformed cursor     -> safe full rescan
Otherwise seek to cursor.byte and read the newly-appended COMPLETE lines; a torn
final line (no trailing newline yet) is left for the next tick.

Cursor shape (opaque to callers; pass it back verbatim):
  {"inode": int, "byte": int, "line": int, "size": int}
    byte = offset to resume reading from (just past the last consumed newline)
    line = 1-indexed file line number of the last consumed complete line
"""
from __future__ import annotations

import json
import os


def _read_complete_lines(path: str, start_byte: int, start_line: int):
    """Read complete (newline-terminated) lines from start_byte to EOF.

    Returns (records, end_byte, end_line) where records is a list of
    (line_number, parsed_dict). A trailing partial line is NOT consumed;
    end_byte stops just past the last newline so the next tick resumes there.
    Malformed JSON lines still advance the line counter (so source_line stays a
    true file line number) but are skipped as records.
    """
    with open(path, "rb") as f:
        f.seek(start_byte)
        data = f.read()
    nl = data.rfind(b"\n")
    if nl == -1:
        return [], start_byte, start_line          # no complete line yet
    complete = data[: nl + 1]
    end_byte = start_byte + len(complete)
    line = start_line
    records = []
    # split on \n; the segment after the final \n is "" and is not a line
    for raw in complete.split(b"\n")[:-1]:
        line += 1
        s = raw.strip()
        if not s:
            continue                                 # blank physical line
        try:
            records.append((line, json.loads(raw.decode("utf-8", "replace"))))
        except Exception:
            pass                                     # skip malformed, keep counting
    return records, end_byte, line


def tail_records(path, cursor: dict | None = None) -> dict:
    """Return records appended since `cursor`, plus the updated cursor.

    Result:
      {
        "reset":   bool,          # True => `records` is a FULL rescan; drop old state
        "records": [(line, dict)],# new (or all, on reset) parsed records
        "cursor":  {inode,byte,line,size},  # cache this; pass back next call
      }
    """
    st = os.stat(path)
    inode, size = st.st_ino, st.st_size

    valid_cursor = isinstance(cursor, dict)
    if valid_cursor:
        try:
            cursor_byte = int(cursor["byte"])
            cursor_line = int(cursor["line"])
            cursor_size = int(cursor.get("size", cursor_byte))
            valid_cursor = cursor_byte >= 0 and cursor_line >= 0 and cursor_size >= 0
        except (KeyError, TypeError, ValueError):
            valid_cursor = False
    if not valid_cursor:
        cursor_byte = cursor_line = cursor_size = 0

    reset = (not valid_cursor
             or cursor.get("inode") != inode
             or size < cursor_size
             or size < cursor_byte)

    if reset:
        start_byte, start_line = 0, 0
    else:
        start_byte, start_line = cursor_byte, cursor_line

    records, end_byte, end_line = _read_complete_lines(path, start_byte, start_line)
    return {
        "reset": reset,
        "records": records,
        "cursor": {"inode": inode, "byte": end_byte, "line": end_line, "size": size},
    }


def cursor_at_line(path, line_no: int) -> dict:
    """Build a cursor positioned just after file line `line_no` (1-indexed).

    Convenience for callers that only have a line number (`--since-line N`): scans
    the file once (O(file)) to find the byte offset; subsequent calls should
    round-trip the returned cursor for O(new-bytes) reads.
    """
    if line_no < 0:
        raise ValueError("line_no must be >= 0")
    st = os.stat(path)
    byte = 0
    line = 0
    if line_no > 0:
        with open(path, "rb") as f:
            for _ in range(line_no):
                chunk = f.readline()
                if not chunk:
                    break
                byte += len(chunk)
                line += 1
    return {"inode": st.st_ino, "byte": byte, "line": line, "size": st.st_size}
