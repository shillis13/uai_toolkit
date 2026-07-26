#!/usr/bin/env python3
"""
notes_mgr - Filesystem-based Notes manager for the Unified Work Tracking System.

Notes are globally-accessible capture objects with their own micro-conversation
threads (Component 6 of the Unified Work Tracking design). This is the
backend/data-layer only — no UI. It mirrors todo_mgr's conventions:

  - filesystem-is-the-database (human-readable, git-friendly, greppable)
  - condensed YAML metadata
  - atomic NNNN allocation + directory creation (no race)
  - append-only message numbering
  - one active ".status" file is NOT used here (notes carry status in meta.yml,
    paralleling the lightweight todo "summary"-style objects); status is a small
    enum {open, resolved, archived}
  - LOCAL-time timestamps (never UTC)
  - --json / --no-color / --root flags so an MCP wrapper can shell out exactly
    like workflow_todo.py does for todo_mgr.

Storage layout (parallels ai_general/work/todos/):

    ai_general/work/notes/
    └── note_NNNN_short_slug/
        ├── content.md              # note body + captured-content references
        ├── meta.yml                # id, created_by, created_at, recipients, ...
        ├── captures/
        │   └── capture_NNN.yml     # structured component-tree capture
        └── messages/
            ├── 001_user.md         # header + markdown body
            └── 002_hamilton.md     # may carry reply_to: {type, id} or, for a
                                    #   turn, {type: turn, session, transcript, turn}

Usage:
    notes_mgr <command> [args...]        # one-shot CLI mode
    notes_mgr --json <command> [args...] # structured JSON for MCP/scripts
    notes_mgr --help

Commands:
    create       Create a new note (allocates note_NNNN atomically)
    add-message  Append a message to a note's thread
    list         List notes, optionally filtered by status/recipient
    read         Show a note's meta + messages
    edit         Rewrite a note's body (content.md)
    set-status   Set note status (open|resolved|archived)
    link-todo    Append a todo id to a note's resulted_in[]
    add-capture  Attach a structured component-tree capture to a note
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# === Configuration ===

# Derive the notes root from the single canonical AI_ROOT (default ~/AI/ai_root),
# mirroring todo_mgr. NOTES_ROOT stays an optional override for non-standard
# layouts; when unset (MCP servers don't inherit it) fall back to the
# AI_ROOT-derived location.
_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT as _AI_ROOT
_FALLBACK_ROOT = _AI_ROOT / "ai_general" / "work" / "notes"
DEFAULT_ROOT = Path(os.environ.get("NOTES_ROOT") or _FALLBACK_ROOT)
CURRENT_ROOT = DEFAULT_ROOT

VERSION = "1.0.0"

VALID_STATUSES = ("open", "resolved", "archived", "draft")

# Generalized target-reference types for a message's reply_to / target.
# Most are a small {type, id} pointer (prior note message, todo, artifact).
# A `turn` is special: it is NOT addressable by a bare number, so it carries
# the richer {type: turn, session, transcript, turn} shape (validated at write
# time by _validate_target).
VALID_TARGET_TYPES = ("note_message", "turn", "todo", "artifact")

# ANSI colors (cheap; mirrors todo_mgr's --no-color contract).
_COLOR_ENABLED = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(t: str) -> str:
    return _c(t, "1")


def _dim(t: str) -> str:
    return _c(t, "2")


def _red(t: str) -> str:
    return _c(t, "31")


def _green(t: str) -> str:
    return _c(t, "32")


def _cyan(t: str) -> str:
    return _c(t, "36")


# === Time ===

def now_local_iso() -> str:
    """Local-time ISO-8601 with offset, e.g. 2026-06-15T16:40:00-04:00.

    Per workspace convention timestamps are ALWAYS local time, never UTC.
    """
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# === Slug / numbering ===

def slugify(name: str) -> str:
    """Lowercase, collapse non [a-z0-9_] runs to single underscore, trim."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def get_next_note_number() -> int:
    """Highest existing note_NNNN across active + archive + trash, plus one.

    Scans every place a note dir could live so numbers are never reused even
    after a note is archived/trashed (parallels todo_mgr.get_next_todo_number).
    """
    max_num = 0
    scan_dirs = [CURRENT_ROOT, CURRENT_ROOT / "archived", CURRENT_ROOT / "trash"]
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for item in scan_dir.rglob("note_*"):
            if not item.is_dir():
                continue
            m = re.match(r"note_(\d{4})_", item.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return max_num + 1


def allocate_note_dir(name: str) -> Path:
    """Atomically allocate the next note_NNNN_slug dir.

    Uses os.mkdir (O_EXCL semantics on the dir) inside a bounded retry loop so
    two concurrent writers never collide on the same number: if the computed
    dir already exists we bump and retry rather than clobber.
    """
    slug = slugify(name)
    if not slug:
        raise ValueError("Invalid note name — no usable characters")

    CURRENT_ROOT.mkdir(parents=True, exist_ok=True)

    last_err: OSError | None = None
    for _ in range(50):
        num = get_next_note_number()
        prefix = f"note_{num:04d}_"
        max_slug_len = 255 - len(prefix)
        dir_slug = slug[:max_slug_len].rstrip("_") if len(slug) > max_slug_len else slug
        target = CURRENT_ROOT / f"{prefix}{dir_slug}"
        try:
            # os.mkdir is the atomic claim — fails if another writer won the race.
            os.mkdir(target)
            return target
        except FileExistsError as e:
            last_err = e
            continue
    raise OSError(f"Could not allocate a free note number after retries: {last_err}")


# === YAML (minimal, no external deps) ===
#
# We keep a tiny hand-rolled emitter/parser so the script has zero third-party
# dependencies (same posture as set_status being a plain bash script). The
# schema is flat enough that this is safe and keeps the files human-editable.

def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "":
        return '""'
    # Quote anything with structural characters or leading/trailing space.
    if re.search(r'[:#\[\]{}",]|^\s|\s$', s) or s in ("null", "true", "false"):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def dump_yaml(data: dict, indent: int = 0) -> str:
    """Emit a small, flat-ish YAML doc. Supports nested dicts/lists of scalars
    and lists of dicts (used by captures[] and resulted_in[])."""
    pad = "  " * indent
    lines: list[str] = []
    for key, val in data.items():
        if isinstance(val, dict):
            lines.append(f"{pad}{key}:")
            lines.append(dump_yaml(val, indent + 1).rstrip("\n"))
        elif isinstance(val, list):
            if not val:
                lines.append(f"{pad}{key}: []")
                continue
            lines.append(f"{pad}{key}:")
            for item in val:
                if isinstance(item, dict):
                    # dump_yaml already indents the item's lines at (indent+2)
                    # levels = len(pad)+4 spaces. Convert the FIRST line's leading
                    # indent into the "- " marker and keep every other line
                    # VERBATIM — re-stripping/re-padding them (the old bug) flattened
                    # any deeper nesting (dicts/lists inside a list item), silently
                    # corrupting nested structures like a captured component tree.
                    inner = dump_yaml(item, indent + 2).rstrip("\n").split("\n")
                    prefix_len = len(pad) + 4  # width of "  " * (indent + 2)
                    first_content = inner[0][prefix_len:]
                    lines.append(f"{pad}  - {first_content}")
                    for extra in inner[1:]:
                        lines.append(extra)
                else:
                    lines.append(f"{pad}  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(val)}")
    return "\n".join(lines) + "\n"


def _yaml_unscalar(s: str):
    s = s.strip()
    if s in ("null", "~", ""):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "[]":
        return []
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1].replace('\\"', '"')
    # Integer — but NOT zero-padded values like "001". Those are identifiers
    # (message ids, target ids) and must keep their padding to stay addressable;
    # a real integer never carries a leading zero (except the literal "0").
    if re.fullmatch(r"-?\d+", s) and not re.fullmatch(r"-?0\d+", s):
        return int(s)
    return s


def _split_lines(text: str) -> list[tuple[int, str]]:
    """Return (indent, content) for each significant line (no blanks/comments)."""
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        out.append((indent, raw.strip()))
    return out


def _parse_block(lines: list[tuple[int, str]], pos: int, indent: int):
    """Recursively parse a block at the given indent. Returns (value, next_pos).

    A block is a list if its first line starts with '- ', otherwise a map.
    Handles nested maps, lists of scalars, and lists of inline dict items
    (`- key: val` with aligned continuation keys). This is a small, predictable
    parser for the YAML subset dump_yaml emits — not a general YAML parser.
    """
    if pos >= len(lines):
        return {}, pos

    is_list = lines[pos][1].startswith("- ")

    if is_list:
        result: list = []
        while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            body = lines[pos][1][2:].strip()
            if ":" in body and not body.endswith(":"):
                # Inline dict item: first key on the dash line, continuations
                # are indented deeper as plain `key: val` lines.
                k, _, v = body.partition(":")
                item: dict = {k.strip(): _yaml_unscalar(v)}
                pos += 1
                cont_indent = indent + 2
                while pos < len(lines) and lines[pos][0] >= cont_indent and not lines[pos][1].startswith("- "):
                    ck, _, cv = lines[pos][1].partition(":")
                    if cv.strip() == "":
                        sub, pos = _parse_block(lines, pos + 1, lines[pos][0] + 2)
                        item[ck.strip()] = sub
                    else:
                        item[ck.strip()] = _yaml_unscalar(cv)
                        pos += 1
                result.append(item)
            else:
                result.append(_yaml_unscalar(body))
                pos += 1
        return result, pos

    result_map: dict = {}
    while pos < len(lines) and lines[pos][0] == indent:
        key, _, val = lines[pos][1].partition(":")
        key = key.strip()
        val = val.strip()
        if val == "[]":
            result_map[key] = []
            pos += 1
        elif val == "":
            # Nested block — peek next line to know if it exists and at what indent.
            if pos + 1 < len(lines) and lines[pos + 1][0] > indent:
                sub, pos = _parse_block(lines, pos + 1, lines[pos + 1][0])
                result_map[key] = sub
            else:
                # Empty value with no children → empty list (matches our schema's
                # collection keys: recipients, captures, resulted_in).
                result_map[key] = []
                pos += 1
        else:
            result_map[key] = _yaml_unscalar(val)
            pos += 1
    return result_map, pos


def parse_yaml(text: str) -> dict:
    """Parse the limited YAML subset emitted by dump_yaml."""
    lines = _split_lines(text)
    if not lines:
        return {}
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value if isinstance(value, dict) else {"_": value}


def read_meta(note_dir: Path) -> dict:
    meta_path = note_dir / "meta.yml"
    if not meta_path.exists():
        raise FileNotFoundError(f"No meta.yml in {note_dir}")
    return parse_yaml(meta_path.read_text())


def write_meta(note_dir: Path, meta: dict) -> None:
    (note_dir / "meta.yml").write_text(dump_yaml(meta))


# === Message header parsing ===

def parse_message_header(text: str) -> tuple[dict, str]:
    """Split a message file into its small YAML front-matter header and body.

    Header is delimited by leading/trailing '---' lines (front-matter style):

        ---
        id: 002
        author: hamilton
        timestamp: 2026-06-15T16:40:00-04:00
        reply_to: {type: note_message, id: "001"}
        ---
        <markdown body>
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            header = parse_yaml(parts[1])
            body = parts[2].lstrip("\n")
            return header, body
    return {}, text


def _validate_target(target: dict) -> None:
    """Validate a target-reference dict's shape per its type (write-time guard).

    Most types are addressed by a single id: {type, id}. A `turn`, however, is
    NOT identifiable by a bare number — a turn only makes sense WITH its session
    + transcript context. So a turn target carries the richer shape
    {type: turn, session, transcript, turn}.
    """
    ttype = target.get("type")
    if ttype not in VALID_TARGET_TYPES:
        raise ValueError(
            f"Invalid target type '{ttype}'. Valid: {', '.join(VALID_TARGET_TYPES)}"
        )
    if ttype == "turn":
        missing = [k for k in ("session", "transcript", "turn") if not target.get(k)]
        if missing:
            raise ValueError(
                "turn target missing required field(s): "
                f"{', '.join(missing)}. A turn needs session (tracking id) + "
                "transcript (jsonl id) + turn (number) — a bare turn number is "
                "ambiguous."
            )
        if not re.fullmatch(r"\d+", str(target["turn"])):
            raise ValueError(f"turn must be a number, got '{target['turn']}'")
    else:
        if not target.get("id"):
            raise ValueError(f"{ttype} target requires an 'id'")


def _parse_target(spec: str | None) -> dict | None:
    """Parse a reply-to/target spec string into a validated reference dict.

    Shapes (validated at write time via _validate_target):
      - note_message | todo | artifact:  'type:id'  -> {type, id}
      - turn:  'turn:<session>:<transcript>:<turn>'  -> {type: turn, session,
            transcript, turn}.  (A turn is only addressable WITH its session +
            transcript context; a bare turn number is ambiguous.)
    """
    if not spec:
        return None
    if ":" not in spec:
        raise ValueError(
            f"Invalid target '{spec}'. Expected 'type:id' (or "
            f"'turn:<session>:<transcript>:<turn>'); type in {VALID_TARGET_TYPES}"
        )
    ttype, _, rest = spec.partition(":")
    ttype = ttype.strip()
    if ttype not in VALID_TARGET_TYPES:
        raise ValueError(
            f"Invalid target type '{ttype}'. Valid: {', '.join(VALID_TARGET_TYPES)}"
        )

    if ttype == "turn":
        parts = [p.strip() for p in rest.split(":")]
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                "Invalid turn target. Expected "
                "'turn:<session>:<transcript>:<turn>' "
                "(session=tracking-id, transcript=jsonl-id, turn=number)."
            )
        session, transcript, turn = parts
        target = {
            "type": "turn",
            "session": session,
            "transcript": transcript,
            "turn": int(turn) if re.fullmatch(r"\d+", turn) else turn,
        }
    else:
        target = {"type": ttype, "id": rest.strip()}

    _validate_target(target)
    return target


# === Note resolution ===

def resolve_note_dir(identifier: str) -> Path:
    """Resolve a note identifier to its directory.

    Accepts: full dir name (note_0001_foo), number (1 / 0001),
    or 'note_0001'. Searches active + archived.
    """
    ident = identifier.strip()
    candidates: list[Path] = []
    scan_dirs = [CURRENT_ROOT, CURRENT_ROOT / "archived"]

    # Numeric → zero-pad
    num: int | None = None
    if re.fullmatch(r"\d{1,4}", ident):
        num = int(ident)
    m = re.match(r"note_(\d{1,4})", ident)
    if m:
        num = int(m.group(1))

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for item in scan_dir.iterdir():
            if not item.is_dir() or not item.name.startswith("note_"):
                continue
            if item.name == ident:
                return item
            if num is not None and re.match(rf"note_{num:04d}_", item.name):
                candidates.append(item)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous note '{identifier}': {[c.name for c in candidates]}"
        )
    raise ValueError(f"Note not found: {identifier}")


def next_message_number(note_dir: Path) -> int:
    msgs_dir = note_dir / "messages"
    if not msgs_dir.exists():
        return 1
    max_n = 0
    for f in msgs_dir.glob("*.md"):
        m = re.match(r"(\d{3})_", f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def next_capture_number(note_dir: Path) -> int:
    cap_dir = note_dir / "captures"
    if not cap_dir.exists():
        return 1
    max_n = 0
    for f in cap_dir.glob("capture_*.yml"):
        m = re.match(r"capture_(\d{3})\.yml", f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


# === Operations (return result dicts; CLI/JSON layers format them) ===

def op_create(
    text: str,
    recipients: list[str] | None = None,
    source_tab: str | None = None,
    created_by: str | None = None,
    name: str | None = None,
    captures: list[dict] | None = None,
    title: str | None = None,
    status: str = "open",
) -> dict:
    """Create a new note. Allocates note_NNNN_slug atomically.

    status defaults to 'open'; pass 'draft' to save an unfinished note (it shows
    in the list marked 'draft' and reopens in the Add Note dialog). A draft may
    have an empty body as long as it has a title.
    """
    text = text or ""
    title = (title or "").strip()
    status = (status or "open").strip().lower()
    if status not in VALID_STATUSES:
        status = "open"
    # A finalized note needs a body; a draft may lean on just a title.
    if not text.strip() and not (status == "draft" and title):
        return {"success": False, "error": "Note text required"}

    recipients = recipients or []
    created_by = created_by or os.environ.get("AI_TRACKING_ID") or "unknown"
    # Derive slug from the title (best), else an explicit name, else the first
    # line of the text — capped to a few words so dir names stay short.
    if title:
        slug_source = "_".join(slugify(title).split("_")[:8])
    elif name:
        slug_source = name
    else:
        first_line = text.strip().splitlines()[0]
        slug_source = "_".join(slugify(first_line).split("_")[:8])

    try:
        note_dir = allocate_note_dir(slug_source)
    except (ValueError, OSError) as e:
        return {"success": False, "error": str(e)}

    note_id = note_dir.name
    created_at = now_local_iso()

    # content.md — note body + captured-content references.
    (note_dir / "content.md").write_text(text.rstrip("\n") + "\n")

    # messages/ — thread starts empty; the note body lives in content.md.
    (note_dir / "messages").mkdir()
    (note_dir / "captures").mkdir()

    capture_refs: list[dict] = []
    for cap in (captures or []):
        cap_ref = _write_capture(note_dir, cap)
        capture_refs.append(cap_ref)

    meta = {
        "id": note_id,
        "title": title,
        "created_by": created_by,
        "created_at": created_at,
        "recipients": recipients,
        "source_tab": source_tab,
        "captures": capture_refs,
        "status": status,
        "resulted_in": [],
    }
    write_meta(note_dir, meta)

    return {
        "success": True,
        "id": note_id,
        "path": str(note_dir),
        "meta": meta,
        "message": f"Created note {note_id}",
    }


def _write_capture(note_dir: Path, cap: dict) -> dict:
    """Write a capture_NNN.yml and return its captures[] reference entry."""
    cap_dir = note_dir / "captures"
    cap_dir.mkdir(exist_ok=True)
    n = next_capture_number(note_dir)
    fname = f"capture_{n:03d}.yml"
    body = {
        "captured_at": cap.get("captured_at") or now_local_iso(),
        "source_tab": cap.get("source_tab"),
        "component_path": cap.get("component_path"),
        "data": cap.get("data") or {},
    }
    (cap_dir / fname).write_text(dump_yaml(body))
    return {"file": f"captures/{fname}", "component_path": body["component_path"]}


def op_add_capture(identifier: str, component_path: str, source_tab: str | None,
                   data: dict | None) -> dict:
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    ref = _write_capture(note_dir, {
        "component_path": component_path,
        "source_tab": source_tab,
        "data": data or {},
    })
    meta = read_meta(note_dir)
    meta.setdefault("captures", [])
    meta["captures"].append(ref)
    write_meta(note_dir, meta)
    return {"success": True, "id": note_dir.name, "capture": ref}


def op_delete_capture(identifier: str, capture_file: str) -> dict:
    """Detach a capture from a note: delete its capture_NNN.yml + drop it from
    the meta ``captures[]`` list. ``capture_file`` may be the full ref
    (``captures/capture_001.yml``) or just the basename."""
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    base = os.path.basename(capture_file)
    if not base or not base.startswith("capture_") or "/" in capture_file.replace(
            "captures/", "", 1):
        return {"success": False, "error": f"invalid capture file: {capture_file}"}
    cap_path = note_dir / "captures" / base
    if not cap_path.exists():
        return {"success": False, "error": f"capture not found: {base}"}
    cap_path.unlink()
    meta = read_meta(note_dir)
    before = meta.get("captures") or []
    meta["captures"] = [c for c in before
                        if os.path.basename((c or {}).get("file", "")) != base]
    write_meta(note_dir, meta)
    return {"success": True, "id": note_dir.name, "removed": base,
            "remaining": len(meta["captures"])}


def op_add_message(
    identifier: str,
    author: str,
    body: str,
    reply_to: str | None = None,
) -> dict:
    """Append a message to a note's thread (append-only numbering)."""
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    if not author or not author.strip():
        return {"success": False, "error": "author required"}
    if not body or not body.strip():
        return {"success": False, "error": "message body required"}

    try:
        target = _parse_target(reply_to)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    msgs_dir = note_dir / "messages"
    msgs_dir.mkdir(exist_ok=True)
    n = next_message_number(note_dir)
    author_slug = slugify(author) or "anon"
    fname = f"{n:03d}_{author_slug}.md"

    header = {
        "id": f"{n:03d}",
        "author": author,
        "timestamp": now_local_iso(),
    }
    if target:
        header["reply_to"] = target

    front = dump_yaml(header).rstrip("\n")
    content = f"---\n{front}\n---\n\n{body.rstrip(chr(10))}\n"
    (msgs_dir / fname).write_text(content)

    return {
        "success": True,
        "id": note_dir.name,
        "message_id": f"{n:03d}",
        "file": f"messages/{fname}",
        "reply_to": target,
    }


def op_edit(identifier: str, text: str) -> dict:
    """Rewrite a note's body (content.md).

    The note body is authored once at create time; this lets it be corrected or
    expanded afterward without touching the thread. The thread (messages/) is the
    append-only conversation and is NOT edited here — only the top-of-note body.
    """
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if text is None or not str(text).strip():
        return {"success": False, "error": "Note text required"}
    (note_dir / "content.md").write_text(str(text).rstrip("\n") + "\n")
    return {"success": True, "id": note_dir.name, "message": f"Edited note {note_dir.name}"}


def op_set_title(identifier: str, title: str) -> dict:
    """Set/replace a note's optional title (meta.title). Empty clears it."""
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    meta = read_meta(note_dir)
    meta["title"] = (title or "").strip()
    write_meta(note_dir, meta)
    return {"success": True, "id": note_dir.name, "title": meta["title"]}


def op_set_status(identifier: str, status: str) -> dict:
    status = status.strip().lower()
    if status not in VALID_STATUSES:
        return {
            "success": False,
            "error": f"Invalid status '{status}'. Valid: {', '.join(VALID_STATUSES)}",
        }
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    meta = read_meta(note_dir)
    old = meta.get("status")
    meta["status"] = status
    write_meta(note_dir, meta)
    return {"success": True, "id": note_dir.name, "status": status, "previous": old}


def op_link_todo(identifier: str, todo_id: str) -> dict:
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    if not todo_id or not todo_id.strip():
        return {"success": False, "error": "todo id required"}
    meta = read_meta(note_dir)
    resulted = meta.get("resulted_in") or []
    if not isinstance(resulted, list):
        resulted = [resulted]
    if todo_id not in resulted:
        resulted.append(todo_id)
    meta["resulted_in"] = resulted
    write_meta(note_dir, meta)
    return {"success": True, "id": note_dir.name, "resulted_in": resulted}


def op_list(status: str | None = None, recipient: str | None = None) -> dict:
    if not CURRENT_ROOT.exists():
        return {"success": True, "notes": []}
    out: list[dict] = []
    for item in sorted(CURRENT_ROOT.iterdir()):
        if not item.is_dir() or not item.name.startswith("note_"):
            continue
        try:
            meta = read_meta(item)
        except FileNotFoundError:
            continue
        if status and (meta.get("status") or "").lower() != status.lower():
            continue
        if recipient:
            recips = meta.get("recipients") or []
            if recipient not in recips:
                continue
        summary = ""
        content_path = item / "content.md"
        if content_path.exists():
            summary = content_path.read_text().strip().splitlines()[0] if content_path.read_text().strip() else ""
        msg_count = len(list((item / "messages").glob("*.md"))) if (item / "messages").exists() else 0
        out.append({
            "id": meta.get("id", item.name),
            "title": meta.get("title") or "",
            "status": meta.get("status"),
            "recipients": meta.get("recipients") or [],
            "created_by": meta.get("created_by"),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at") or meta.get("created_at"),
            "messages": msg_count,
            "resulted_in": meta.get("resulted_in") or [],
            "summary": summary,
        })
    out.sort(key=lambda n: n["id"])
    return {"success": True, "notes": out}


def op_read(identifier: str) -> dict:
    try:
        note_dir = resolve_note_dir(identifier)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    meta = read_meta(note_dir)
    content = ""
    if (note_dir / "content.md").exists():
        content = (note_dir / "content.md").read_text()

    messages: list[dict] = []
    msgs_dir = note_dir / "messages"
    if msgs_dir.exists():
        for f in sorted(msgs_dir.glob("*.md")):
            header, body = parse_message_header(f.read_text())
            messages.append({
                "file": f"messages/{f.name}",
                "id": header.get("id"),
                "author": header.get("author"),
                "timestamp": header.get("timestamp"),
                "reply_to": header.get("reply_to"),
                "body": body.strip(),
            })

    captures: list[dict] = []
    cap_dir = note_dir / "captures"
    if cap_dir.exists():
        for f in sorted(cap_dir.glob("capture_*.yml")):
            captures.append({"file": f"captures/{f.name}", **parse_yaml(f.read_text())})

    return {
        "success": True,
        "id": note_dir.name,
        "path": str(note_dir),
        "meta": meta,
        "content": content,
        "messages": messages,
        "captures": captures,
    }


# === CLI formatting ===

def _fmt_list(result: dict) -> str:
    notes = result.get("notes", [])
    if not notes:
        return _dim("No notes.")
    lines = [_bold(f"{'ID':<22} {'STATUS':<9} {'MSGS':<5} {'RECIPIENTS':<18} SUMMARY")]
    for n in notes:
        recips = ",".join(n.get("recipients") or []) or "-"
        lines.append(
            f"{_cyan(n['id']):<22} {(n.get('status') or '-'):<9} "
            f"{str(n.get('messages', 0)):<5} {recips:<18} {n.get('summary', '')[:50]}"
        )
    return "\n".join(lines)


def _fmt_read(result: dict) -> str:
    if not result.get("success"):
        return _red(f"Error: {result.get('error')}")
    meta = result["meta"]
    lines = [_bold(result["id"])]
    lines.append(_dim(f"  status: {meta.get('status')}  recipients: {meta.get('recipients')}"))
    lines.append(_dim(f"  created_by: {meta.get('created_by')}  created_at: {meta.get('created_at')}"))
    if meta.get("source_tab"):
        lines.append(_dim(f"  source_tab: {meta.get('source_tab')}"))
    if meta.get("resulted_in"):
        lines.append(_dim(f"  resulted_in: {meta.get('resulted_in')}"))
    if result.get("captures"):
        lines.append(_bold("\nCaptures:"))
        for cap in result["captures"]:
            lines.append(f"  {cap.get('file')}  {_dim(cap.get('component_path') or '')}")
    lines.append(_bold("\nContent:"))
    lines.append(result.get("content", "").rstrip())
    lines.append(_bold("\nMessages:"))
    if not result.get("messages"):
        lines.append(_dim("  (none)"))
    for m in result.get("messages", []):
        reply = ""
        if m.get("reply_to"):
            rt = m["reply_to"]
            if rt.get("type") == "turn" and rt.get("session"):
                reply = _dim(f"  ↳ reply_to turn {rt.get('session')}"
                             f"/{rt.get('transcript')}#{rt.get('turn')}")
            elif rt.get("type") == "turn":
                # Legacy bare-turn shape {type: turn, id: N} — read-only fallback.
                reply = _dim(f"  ↳ reply_to turn:{rt.get('id')}")
            else:
                reply = _dim(f"  ↳ reply_to {rt.get('type')}:{rt.get('id')}")
        lines.append(_cyan(f"  [{m.get('id')}] {m.get('author')} {_dim(m.get('timestamp') or '')}{reply}"))
        for bl in m.get("body", "").splitlines():
            lines.append(f"      {bl}")
    return "\n".join(lines)


# === Argument parsing & dispatch ===

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notes_mgr", description="Filesystem Notes manager")
    p.add_argument("--json", action="store_true", help="Structured JSON output for MCP/scripts")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    p.add_argument("--root", help="Alternate notes root (default ai_general/work/notes/)")
    p.add_argument("--version", action="store_true", help="Print version and exit")

    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("create", help="Create a new note")
    c.add_argument("--text", required=True, help="Note body text")
    c.add_argument("--recipients", help="Comma-separated recipients (e.g. PM,Hamilton)")
    c.add_argument("--source-tab", help="UAI tab that was active")
    c.add_argument("--created-by", help="Session tracking id (default $AI_TRACKING_ID)")
    c.add_argument("--name", help="Explicit slug source (default: first line of text)")
    c.add_argument("--title", help="Optional note title/subject")
    c.add_argument("--status", default="open", help="open (default) | draft (unfinished, reopens in the dialog)")

    st = sub.add_parser("set-title", help="Set a note's optional title/subject")
    st.add_argument("--id", required=True, help="Note identifier")
    st.add_argument("--title", required=True, help="New title (empty to clear)")

    am = sub.add_parser("add-message", help="Append a message to a note")
    am.add_argument("--id", required=True, help="Note identifier")
    am.add_argument("--author", required=True, help="Message author")
    am.add_argument("--body", required=True, help="Message markdown body")
    am.add_argument("--reply-to", help="Target reference. 'type:id' for "
                                       "note_message|todo|artifact, or "
                                       "'turn:<session>:<transcript>:<turn>' for a turn "
                                       "(a turn needs session + transcript + turn).")

    ls = sub.add_parser("list", help="List notes")
    ls.add_argument("--status", help="Filter by status (open|resolved|archived)")
    ls.add_argument("--recipient", help="Filter by recipient")

    rd = sub.add_parser("read", help="Read a note (meta + messages)")
    rd.add_argument("--id", required=True, help="Note identifier")

    ed = sub.add_parser("edit", help="Rewrite a note's body (content.md)")
    ed.add_argument("--id", required=True, help="Note identifier")
    ed.add_argument("--text", required=True, help="New note body text")

    ss = sub.add_parser("set-status", help="Set note status")
    ss.add_argument("--id", required=True, help="Note identifier")
    ss.add_argument("--status", required=True, help="open|resolved|archived")

    lt = sub.add_parser("link-todo", help="Append a todo id to resulted_in[]")
    lt.add_argument("--id", required=True, help="Note identifier")
    lt.add_argument("--todo", required=True, help="Todo id (e.g. todo_0308_fix_x)")

    ac = sub.add_parser("add-capture", help="Attach a structured component-tree capture")
    ac.add_argument("--id", required=True, help="Note identifier")
    ac.add_argument("--component-path", required=True, help="Hierarchical component path")
    ac.add_argument("--source-tab", help="UAI tab that was active")
    ac.add_argument("--data", help="JSON string of structured component state")

    dc = sub.add_parser("delete-capture", help="Detach a capture from a note")
    dc.add_argument("--id", required=True, help="Note identifier")
    dc.add_argument("--file", required=True, help="Capture file (captures/capture_NNN.yml or basename)")

    return p


def main(argv: list[str] | None = None) -> int:
    global CURRENT_ROOT, _COLOR_ENABLED
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"notes_mgr v{VERSION}")
        return 0

    if args.no_color or args.json:
        _COLOR_ENABLED = False
    if args.root:
        CURRENT_ROOT = Path(args.root).expanduser().resolve()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "create":
        recipients = [r.strip() for r in (args.recipients or "").split(",") if r.strip()]
        result = op_create(
            status=args.status,
            text=args.text,
            recipients=recipients,
            source_tab=args.source_tab,
            created_by=args.created_by,
            name=args.name,
            title=args.title,
        )
    elif args.command == "set-title":
        result = op_set_title(args.id, args.title)
    elif args.command == "add-message":
        result = op_add_message(args.id, args.author, args.body, args.reply_to)
    elif args.command == "list":
        result = op_list(status=args.status, recipient=args.recipient)
    elif args.command == "read":
        result = op_read(args.id)
    elif args.command == "edit":
        result = op_edit(args.id, args.text)
    elif args.command == "set-status":
        result = op_set_status(args.id, args.status)
    elif args.command == "link-todo":
        result = op_link_todo(args.id, args.todo)
    elif args.command == "add-capture":
        data = None
        if args.data:
            try:
                data = json.loads(args.data)
            except json.JSONDecodeError as e:
                result = {"success": False, "error": f"Invalid --data JSON: {e}"}
                _emit(result, args)
                return 0 if result.get("success") else 1
        result = op_add_capture(args.id, args.component_path, args.source_tab, data)
    elif args.command == "delete-capture":
        result = op_delete_capture(args.id, args.file)
    else:
        parser.print_help()
        return 1

    return _emit(result, args)


def _emit(result: dict, args) -> int:
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success", True) else 1

    # Human-readable formatting per command.
    if args.command == "list":
        print(_fmt_list(result))
    elif args.command == "read":
        print(_fmt_read(result))
    elif not result.get("success", True):
        print(_red(f"Error: {result.get('error')}"))
        return 1
    else:
        print(_green(result.get("message") or f"OK: {json.dumps(result, default=str)}"))
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())
