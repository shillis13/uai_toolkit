#!$HOME/myenv/bin/python3
"""
scrub_files — Interactive REPL + CLI for managing file attachments in Claude Code JSONL transcripts.

Replaces scrub_large_images.py with a richer interface: list, inspect, remove,
and bulk-scrub images, PDFs, and large text attachments.

Usage:
    scrub_files.py                               # REPL mode (use 'open' to load session)
    scrub_files.py <session>                     # REPL with session pre-loaded
    scrub_files.py <session> list [--type TYPE]   # one-shot CLI
    scrub_files.py <session> rm 1 3 5            # remove by # ref
    scrub_files.py <session> scrub --all         # bulk scrub
    scrub_files.py <session> info 2              # detailed info

Exit codes:
    0  Success
    1  File not found or unreadable
    2  Write error
"""

from __future__ import annotations

import atexit
import base64
import io
import json
import os
import re
import readline
import shlex
import shutil
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VERSION = "1.0.0"
HISTORY_FILE = Path.home() / ".scrub_files_history"
MAX_DIMENSION = 2000

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
sys.path.insert(0, '$AI_ROOT/ai_general/scripts/utils')
from uai_toolkit.common_utils.standard_colors import c, format_help, bold, dim, heading  # noqa: E402


# ---------------------------------------------------------------------------
# JSONL resolution (preserved from scrub_large_images.py)
# ---------------------------------------------------------------------------

def find_jsonl(identifier: str) -> Optional[Path]:
    """Find JSONL file by any session identifier, URI, display name, or direct path.

    Resolution goes through session_store.resolve() which handles URIs
    (uai://session/<id>, prompt://target/<id>), tracking IDs, display names,
    CLI UUIDs, UUID prefixes, and terminal session names.
    """
    # Direct file path
    p = Path(identifier).expanduser()
    if p.exists() and p.is_file():
        return p

    # Resolve through session_store → get CLI UUID → find JSONL
    try:
        sm_path = str(Path.home() / "AI/ai_root/ai_general/scripts/session_mgmt")
        if sm_path not in sys.path:
            sys.path.insert(0, sm_path)
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
        row = store.resolve(identifier)
        if row:
            # Try transcript_path first
            tp = row.get("transcript_path")
            if tp:
                paths = [tp] if isinstance(tp, str) else tp
                for t in paths:
                    candidate = Path(t).expanduser()
                    if candidate.exists():
                        return candidate
            # Fall back to CLI UUID filesystem search
            cli_uuid = row.get("cli_session_id")
            if cli_uuid:
                claude_dir = Path.home() / ".claude" / "projects"
                if claude_dir.exists():
                    for proj_dir in claude_dir.iterdir():
                        if not proj_dir.is_dir():
                            continue
                        candidate = proj_dir / f"{cli_uuid}.jsonl"
                        if candidate.exists():
                            return candidate
    except Exception:
        pass

    # Last resort: substring search in Claude project dirs
    identifier_lower = identifier.lower()
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        for proj_dir in claude_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                stem = f.stem.lower()
                if stem == identifier_lower or stem.startswith(identifier_lower) or identifier_lower in stem:
                    return f

    return None


# ---------------------------------------------------------------------------
# Image dimension detection (preserved from scrub_large_images.py)
# ---------------------------------------------------------------------------

def get_image_dimensions_from_base64(b64_data: str) -> Optional[Tuple[int, int]]:
    """Get (width, height) from base64-encoded image data. Returns None on failure."""
    try:
        raw = base64.b64decode(b64_data[:1024])  # Only need the header
    except Exception:
        return None

    # PNG
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        width = struct.unpack(">I", raw[16:20])[0]
        height = struct.unpack(">I", raw[20:24])[0]
        return (width, height)

    # JPEG
    if raw[:2] == b"\xff\xd8":
        try:
            f = io.BytesIO(raw)
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)
                    height = struct.unpack(">H", f.read(2))[0]
                    width = struct.unpack(">H", f.read(2))[0]
                    return (width, height)
                else:
                    length = struct.unpack(">H", f.read(2))[0]
                    f.seek(length - 2, 1)
        except Exception:
            pass

    # GIF
    if raw[:6] in (b"GIF87a", b"GIF89a") and len(raw) >= 10:
        width = struct.unpack("<H", raw[6:8])[0]
        height = struct.unpack("<H", raw[8:10])[0]
        return (width, height)

    # WebP
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP" and len(raw) >= 30:
        if raw[12:16] == b"VP8 " and len(raw) >= 30:
            width = struct.unpack("<H", raw[26:28])[0] & 0x3FFF
            height = struct.unpack("<H", raw[28:30])[0] & 0x3FFF
            return (width, height)

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


def _format_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes}B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.0f}K"
    elif nbytes < 1024 * 1024 * 1024:
        return f"{nbytes / (1024 * 1024):.1f}M"
    else:
        return f"{nbytes / (1024 * 1024 * 1024):.1f}G"


def _format_ts(ts_str: str) -> str:
    """Format ISO timestamp to local time display."""
    if not ts_str:
        return ""
    try:
        ts_clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        dt_local = dt.astimezone()
        return dt_local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts_str[:16] if len(ts_str) >= 16 else ts_str


def _b64_byte_size(b64_len: int) -> int:
    """Estimate raw byte size from base64 string length."""
    return int(b64_len * 3 / 4)


# ---------------------------------------------------------------------------
# Scanning: build attachment inventory
# ---------------------------------------------------------------------------

def scan_attachments(jsonl_path: Path) -> List[Dict]:
    """Scan JSONL and return a list of attachment records.

    Each record has keys:
        num, line, att_type, size, dims, dim_str, name, file_path,
        timestamp, tool_use_id, b64_len, page_count, output_dir,
        block_path, oversized, scrub_text
    """
    attachments = []  # type: List[Dict]
    lines = jsonl_path.read_text().splitlines()

    # Build a map of tool_use_id -> Read file_path from tool_use entries
    tool_use_paths = {}  # type: Dict[str, str]

    for i, line_text in enumerate(lines):
        if not line_text.strip():
            continue
        try:
            entry = json.loads(line_text)
        except json.JSONDecodeError:
            continue

        timestamp = entry.get("timestamp", "")
        msg = entry.get("message", {})
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        tur = entry.get("toolUseResult")

        # Collect tool_use Read calls for path correlation
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Read":
                inp = block.get("input", {})
                fp = inp.get("file_path", "")
                tid = block.get("id", "")
                if tid and fp:
                    tool_use_paths[tid] = fp

        # Check for PDF via toolUseResult (type: "parts" with outputDir)
        if isinstance(tur, dict) and tur.get("type") == "parts":
            file_info = tur.get("file", {})
            file_path = file_info.get("filePath", "")
            output_dir = file_info.get("outputDir", "")
            page_count = file_info.get("count", 0)
            original_size = file_info.get("originalSize", 0)
            name = Path(file_path).name if file_path else "unknown.pdf"

            if not page_count and output_dir and Path(output_dir).exists():
                page_count = len([f for f in Path(output_dir).iterdir()
                                  if f.suffix.lower() in (".jpg", ".jpeg", ".png")])

            size = original_size
            if not size and output_dir and Path(output_dir).exists():
                size = sum(f.stat().st_size for f in Path(output_dir).iterdir()
                           if f.is_file())

            attachments.append({
                "line": i + 1,
                "att_type": "pdf",
                "size": size,
                "dims": None,
                "dim_str": "{} pages".format(page_count) if page_count else "-",
                "name": name,
                "file_path": file_path,
                "timestamp": timestamp,
                "tool_use_id": "",
                "b64_len": 0,
                "page_count": page_count,
                "output_dir": output_dir,
                "block_path": "toolUseResult",
                "oversized": False,
                "scrub_text": None,
            })
            continue

        # Check for PDF-raw via toolUseResult (file ref to .pdf without rendered pages)
        if isinstance(tur, dict):
            tur_file = tur.get("file", {})
            if isinstance(tur_file, dict):
                fp = tur_file.get("filePath", "")
                if fp and fp.lower().endswith(".pdf") and tur.get("type") != "parts":
                    size = tur_file.get("originalSize", 0)
                    name = Path(fp).name
                    attachments.append({
                        "line": i + 1,
                        "att_type": "pdf-raw",
                        "size": size,
                        "dims": None,
                        "dim_str": "-",
                        "name": name,
                        "file_path": fp,
                        "timestamp": timestamp,
                        "tool_use_id": "",
                        "b64_len": 0,
                        "page_count": 0,
                        "output_dir": "",
                        "block_path": "toolUseResult",
                        "oversized": False,
                        "scrub_text": None,
                    })
                    continue

        # Walk content blocks
        for bj, block in enumerate(content):
            if not isinstance(block, dict):
                continue

            # Direct inline image (user-pasted)
            if block.get("type") == "image":
                src = block.get("source", {})
                if src.get("type") == "base64":
                    b64 = src.get("data", "")
                    dims = get_image_dimensions_from_base64(b64) if b64 else None
                    media_type = src.get("media_type", "image/unknown")
                    attachments.append({
                        "line": i + 1,
                        "att_type": "image",
                        "size": _b64_byte_size(len(b64)),
                        "dims": dims,
                        "dim_str": "{}x{}".format(dims[0], dims[1]) if dims else "-",
                        "name": "(pasted {})".format(media_type.split("/")[-1]),
                        "file_path": "(pasted image)",
                        "timestamp": timestamp,
                        "tool_use_id": "",
                        "b64_len": len(b64),
                        "page_count": 0,
                        "output_dir": "",
                        "block_path": "content[{}]".format(bj),
                        "oversized": bool(dims and max(dims) > MAX_DIMENSION),
                        "scrub_text": None,
                    })
                continue

            # tool_result blocks
            if block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                inner = block.get("content")

                # tool_result with list content
                if isinstance(inner, list):
                    for bk, ib in enumerate(inner):
                        if not isinstance(ib, dict):
                            continue

                        # Image inside tool_result
                        if ib.get("type") == "image":
                            src = ib.get("source", {})
                            b64 = src.get("data", "")
                            dims = get_image_dimensions_from_base64(b64) if b64 else None
                            media_type = src.get("media_type", "image/unknown")
                            fp = tool_use_paths.get(tool_use_id, "")
                            name = Path(fp).name if fp else "(tool_result {})".format(media_type.split("/")[-1])
                            attachments.append({
                                "line": i + 1,
                                "att_type": "image",
                                "size": _b64_byte_size(len(b64)),
                                "dims": dims,
                                "dim_str": "{}x{}".format(dims[0], dims[1]) if dims else "-",
                                "name": name,
                                "file_path": fp,
                                "timestamp": timestamp,
                                "tool_use_id": tool_use_id,
                                "b64_len": len(b64),
                                "page_count": 0,
                                "output_dir": "",
                                "block_path": "content[{}].content[{}]".format(bj, bk),
                                "oversized": bool(dims and max(dims) > MAX_DIMENSION),
                                "scrub_text": None,
                            })
                            continue

                        # Scrubbed placeholder
                        if ib.get("type") == "text":
                            text = ib.get("text", "")
                            if "[Image removed by scrub_large_images:" in text or "[Removed:" in text:
                                fp = tool_use_paths.get(tool_use_id, "")
                                name = Path(fp).name if fp else "(scrubbed)"
                                dim_str = "-"
                                dims_match = re.search(r"(\d+)x(\d+)", text)
                                if dims_match:
                                    dim_str = "{}x{}".format(dims_match.group(1), dims_match.group(2))
                                attachments.append({
                                    "line": i + 1,
                                    "att_type": "scrubbed",
                                    "size": 0,
                                    "dims": None,
                                    "dim_str": dim_str,
                                    "name": name,
                                    "file_path": fp,
                                    "timestamp": timestamp,
                                    "tool_use_id": tool_use_id,
                                    "b64_len": 0,
                                    "page_count": 0,
                                    "output_dir": "",
                                    "block_path": "content[{}].content[{}]".format(bj, bk),
                                    "oversized": False,
                                    "scrub_text": text,
                                })
                                continue

                # tool_result with string content (large text / Read output)
                elif isinstance(inner, str) and len(inner) > 10240:
                    fp = tool_use_paths.get(tool_use_id, "")
                    name = Path(fp).name if fp else "(text output)"
                    attachments.append({
                        "line": i + 1,
                        "att_type": "file",
                        "size": len(inner),
                        "dims": None,
                        "dim_str": "-",
                        "name": name,
                        "file_path": fp,
                        "timestamp": timestamp,
                        "tool_use_id": tool_use_id,
                        "b64_len": 0,
                        "page_count": 0,
                        "output_dir": "",
                        "block_path": "content[{}].content".format(bj),
                        "oversized": False,
                        "scrub_text": None,
                    })

    # Assign display numbers
    for idx, att in enumerate(attachments):
        att["num"] = idx + 1

    return attachments


# ---------------------------------------------------------------------------
# Display: list attachments
# ---------------------------------------------------------------------------

def _type_label(att_type: str) -> str:
    """Return colored type label."""
    colors = {
        "image": "cyan",
        "pdf": "magenta",
        "pdf-raw": "magenta",
        "file": "yellow",
        "scrubbed": "dim",
    }
    color = colors.get(att_type, "white")
    return c(att_type.ljust(8), color)


def _normalize_type_filter(type_filter: str) -> set:
    """Convert a comma-separated type filter string to a set of att_type values."""
    types = set(t.strip() for t in type_filter.split(","))
    type_map = {
        "images": {"image"},
        "image": {"image"},
        "pdf": {"pdf", "pdf-raw"},
        "pdfs": {"pdf", "pdf-raw"},
        "files": {"file"},
        "file": {"file"},
        "scrubbed": {"scrubbed"},
        "text": {"file"},
    }
    allowed = set()  # type: set
    for t in types:
        mapped = type_map.get(t.lower())
        if mapped:
            allowed.update(mapped)
        else:
            allowed.add(t.lower())
    return allowed


def format_list(attachments, type_filter=None, sort_by="line", as_json=False):
    # type: (List[Dict], Optional[str], str, bool) -> str
    """Format attachment list as a table string."""
    filtered = attachments
    if type_filter:
        allowed = _normalize_type_filter(type_filter)
        filtered = [a for a in attachments if a["att_type"] in allowed]

    sort_keys = {
        "line": lambda a: a["line"],
        "name": lambda a: a["name"].lower(),
        "size": lambda a: a["size"],
        "type": lambda a: a["att_type"],
        "date": lambda a: a["timestamp"],
    }
    key_fn = sort_keys.get(sort_by)
    if key_fn:
        reverse = sort_by == "size"
        filtered = sorted(filtered, key=key_fn, reverse=reverse)

    if as_json:
        return json.dumps(
            [{k: v for k, v in a.items() if k not in ("b64_data",)} for a in filtered],
            indent=2,
        )

    if not filtered:
        return c("  No attachments found.", "dim")

    # Build table
    out = []  # type: List[str]
    header = " {:>3}  {:>5}  {:<8}  {:>6}  {:<11}  {:<17}  {}".format(
        "#", "Line", "Type", "Size", "Dims", "Timestamp", "Name")
    out.append(c(header, "dim"))
    sep = " {:>3}  {:>5}  {:<8}  {:>6}  {:<11}  {:<17}  {}".format(
        "---", "-----", "--------", "------", "-----------", "-----------------", "----")
    out.append(c(sep, "dim"))

    total_size = 0
    for a in filtered:
        num = a["num"]
        line_no = a["line"]
        att_type = _type_label(a["att_type"])
        size = _format_size(a["size"])
        dim_str = a["dim_str"]
        ts = _format_ts(a["timestamp"])
        name = a["name"]
        total_size += a["size"]
        out.append(
            " {:3d}  {:5d}  {}  {:>6}  {:<11}  {:<17}  {}".format(
                num, line_no, att_type, size, dim_str, ts, name)
        )

    out.append("")
    out.append(dim("  {} attachment(s), {} total".format(len(filtered), _format_size(total_size))))

    return "\n".join(out)


def format_info(att):
    # type: (Dict) -> str
    """Format detailed info about a single attachment."""
    out = []  # type: List[str]
    out.append(heading("Attachment #{}".format(att["num"])))
    out.append("  {}       {}".format(bold("Type:"), att["att_type"]))
    out.append("  {}       {}".format(bold("Name:"), att["name"]))
    out.append("  {}  {}".format(bold("File path:"), att["file_path"] or "-"))
    out.append("  {}       {}".format(bold("Line:"), att["line"]))
    out.append("  {}       {} ({:,} bytes)".format(bold("Size:"), _format_size(att["size"]), att["size"]))
    out.append("  {}       {}".format(bold("Dims:"), att["dim_str"]))
    out.append("  {}  {}".format(bold("Timestamp:"), _format_ts(att["timestamp"])))
    out.append("  {}   {}".format(bold("Tool use:"), att["tool_use_id"] or "-"))
    out.append("  {} {}".format(bold("Block path:"), att["block_path"]))
    out.append("  {}  {}".format(bold("Oversized:"), "Yes" if att["oversized"] else "No"))
    if att["att_type"] == "pdf":
        out.append("  {}      {}".format(bold("Pages:"), att["page_count"]))
        out.append("  {} {}".format(bold("Output dir:"), att["output_dir"]))
        if att["output_dir"] and Path(att["output_dir"]).exists():
            out.append("  {} Yes".format(bold("Dir exists:")))
        elif att["output_dir"]:
            out.append("  {} {}".format(bold("Dir exists:"), c("No", "yellow")))
    if att["scrub_text"]:
        out.append("  {} {}".format(bold("Scrub text:"), att["scrub_text"]))
    if att["b64_len"]:
        out.append("  {} {:,} chars".format(bold("Base64 len:"), att["b64_len"]))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Modification: remove / scrub
# ---------------------------------------------------------------------------

def _parse_refs(ref_args):
    # type: (List[str]) -> List[int]
    """Parse reference arguments like '1 3 5' or '1-5' into a list of ints."""
    refs = []  # type: List[int]
    for arg in ref_args:
        if "-" in arg and not arg.startswith("-"):
            parts = arg.split("-", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
                refs.extend(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                refs.append(int(arg))
            except ValueError:
                pass
    return sorted(set(refs))


def _ensure_backup(jsonl_path):
    # type: (Path) -> bool
    """Create .bak copy if one doesn't exist. Returns True if backup exists or was created."""
    backup = jsonl_path.with_suffix(".jsonl.bak")
    if backup.exists():
        return True
    try:
        shutil.copy2(jsonl_path, backup)
        print(c("  Backup created: {}".format(backup), "green"))
        return True
    except OSError as e:
        print(c("  Failed to create backup: {}".format(e), "red"), file=sys.stderr)
        return False


def _atomic_write(jsonl_path, content):
    # type: (Path, str) -> bool
    """Write content to file atomically via temp file + rename."""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(jsonl_path.parent),
            prefix=".scrub_tmp_",
            suffix=".jsonl",
        )
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp_path, str(jsonl_path))
        return True
    except OSError as e:
        print(c("  Write error: {}".format(e), "red"), file=sys.stderr)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return False


def remove_attachments(jsonl_path, attachments, ref_nums):
    # type: (Path, List[Dict], List[int]) -> Tuple[int, int]
    """Remove specific attachments by reference number.

    Returns (removed_count, bytes_saved).
    """
    to_remove = []  # type: List[Dict]
    for num in ref_nums:
        found = False
        for att in attachments:
            if att["num"] == num:
                found = True
                if att["att_type"] == "scrubbed":
                    print(c("  #{} already scrubbed, skipping".format(num), "yellow"))
                else:
                    to_remove.append(att)
                break
        if not found:
            print(c("  #{} not found".format(num), "yellow"))

    if not to_remove:
        return 0, 0

    if not _ensure_backup(jsonl_path):
        return 0, 0

    lines = jsonl_path.read_text().splitlines()
    removed = 0
    bytes_saved = 0

    # Group by line number
    by_line = {}  # type: Dict[int, List[Dict]]
    for att in to_remove:
        by_line.setdefault(att["line"], []).append(att)

    new_lines = []  # type: List[str]
    for i, line_text in enumerate(lines):
        line_no = i + 1
        if line_no not in by_line:
            new_lines.append(line_text)
            continue

        try:
            entry = json.loads(line_text)
        except json.JSONDecodeError:
            new_lines.append(line_text)
            continue

        original_len = len(line_text)

        for att in by_line[line_no]:
            entry = _remove_one_attachment(entry, att)
            removed += 1

        new_line = json.dumps(entry, ensure_ascii=False)
        bytes_saved += original_len - len(new_line)
        new_lines.append(new_line)

    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"

    if _atomic_write(jsonl_path, content):
        return removed, bytes_saved
    return 0, 0


def _remove_one_attachment(entry, att):
    # type: (Dict, Dict) -> Dict
    """Remove a single attachment from a JSONL entry, returning modified entry."""
    att_type = att["att_type"]
    block_path = att["block_path"]

    # Build replacement text
    if att_type == "image":
        dims = att["dims"]
        dim_str = "{}x{}".format(dims[0], dims[1]) if dims else "unknown"
        replacement_text = "[Removed: image, {}]".format(dim_str)
    elif att_type in ("pdf", "pdf-raw"):
        pages = att["page_count"]
        replacement_text = "[Removed: PDF, {} pages]".format(pages) if pages else "[Removed: PDF]"
    elif att_type == "file":
        size_str = _format_size(att["size"])
        replacement_text = "[Removed: file, {}]".format(size_str)
    else:
        replacement_text = "[Removed]"

    replacement_block = {"type": "text", "text": replacement_text}

    msg = entry.get("message", {})
    if isinstance(msg, dict):
        content = msg.get("content", [])
        if isinstance(content, list):
            _apply_block_replacement(content, block_path, replacement_block, replacement_text)
            entry["message"]["content"] = content

    # Also handle toolUseResult
    tur = entry.get("toolUseResult")
    if isinstance(tur, dict):
        if att_type in ("pdf", "pdf-raw") and block_path == "toolUseResult":
            entry["toolUseResult"] = {"type": "text", "text": replacement_text}
            if att["output_dir"] and Path(att["output_dir"]).exists():
                try:
                    shutil.rmtree(att["output_dir"])
                except OSError:
                    pass
        elif att_type == "image":
            # Scrub parallel toolUseResult image data
            if tur.get("type") == "image":
                entry["toolUseResult"] = {"type": "text", "text": replacement_text}
            elif isinstance(tur.get("file"), dict):
                tur_file = tur["file"]
                if tur_file.get("type", "").startswith("image/") or tur_file.get("base64"):
                    entry["toolUseResult"] = {"type": "text", "text": replacement_text}

    return entry


def _apply_block_replacement(content, block_path, replacement, replacement_text):
    # type: (list, str, Dict, str) -> None
    """Navigate block_path and replace the target with the replacement block."""
    # Parse paths like "content[2].content[0]" or "content[2].content"
    parts = re.findall(r'content\[(\d+)\]|content$', block_path)

    if not parts:
        return

    if len(parts) == 1:
        idx = parts[0]
        if idx == '':
            # "content[N].content" - replace the string content of a tool_result block
            match = re.match(r'content\[(\d+)\]\.content', block_path)
            if match:
                bi = int(match.group(1))
                if bi < len(content) and isinstance(content[bi], dict):
                    content[bi] = dict(content[bi], content=replacement_text)
        else:
            bi = int(idx)
            if bi < len(content):
                content[bi] = replacement
    elif len(parts) >= 2:
        outer_idx = int(parts[0])
        inner_idx = parts[1]
        if outer_idx < len(content) and isinstance(content[outer_idx], dict):
            inner = content[outer_idx].get("content", [])
            if isinstance(inner, list):
                if inner_idx != '':
                    ii = int(inner_idx)
                    if ii < len(inner):
                        inner[ii] = replacement
                        content[outer_idx] = dict(content[outer_idx], content=inner)


def scrub_bulk(jsonl_path, attachments, type_filter=None, max_px=MAX_DIMENSION, scrub_all=False):
    # type: (Path, List[Dict], Optional[str], int, bool) -> Tuple[int, int]
    """Bulk scrub attachments matching criteria.

    Returns (removed_count, bytes_saved).
    """
    refs_to_remove = []  # type: List[int]
    for att in attachments:
        if att["att_type"] == "scrubbed":
            continue

        # Type filter
        if type_filter:
            allowed = _normalize_type_filter(type_filter)
            if att["att_type"] not in allowed:
                continue

        if scrub_all:
            refs_to_remove.append(att["num"])
        else:
            # Default: only oversized images
            if att["att_type"] == "image" and att["oversized"]:
                refs_to_remove.append(att["num"])

    if not refs_to_remove:
        print(c("  No attachments match scrub criteria.", "dim"))
        return 0, 0

    return remove_attachments(jsonl_path, attachments, refs_to_remove)


# ---------------------------------------------------------------------------
# Backup / Restore
# ---------------------------------------------------------------------------

def do_backup(jsonl_path):
    # type: (Path) -> str
    """Create a .bak copy."""
    backup = jsonl_path.with_suffix(".jsonl.bak")
    if backup.exists():
        return c("  Backup already exists: {}".format(backup), "yellow")
    try:
        shutil.copy2(jsonl_path, backup)
        return c("  Backup created: {}".format(backup), "green")
    except OSError as e:
        return c("  Backup failed: {}".format(e), "red")


def do_restore(jsonl_path):
    # type: (Path) -> str
    """Restore from .bak file."""
    backup = jsonl_path.with_suffix(".jsonl.bak")
    if not backup.exists():
        return c("  No backup file found.", "red")
    try:
        shutil.copy2(backup, jsonl_path)
        return c("  Restored from: {}".format(backup), "green")
    except OSError as e:
        return c("  Restore failed: {}".format(e), "red")


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP_TEXT = rf"""
scrub_files v{VERSION} -- attachment scrubber for CLI session transcripts

Description:
    scrub_files finds and REMOVES heavy file attachments (inline/base64 images,
    PDFs, and other embedded files) from a Claude Code / Codex / Gemini session
    .jsonl transcript, replacing each removed block with a small "[Removed]" text
    placeholder and rewriting the file in place. Use it to reclaim disk + on-resume
    context that is dominated by bulky, disposable attachments -- oversized
    screenshots, multi-megabyte PDFs, pasted images you no longer need.

    It is a LOSSY, disk-level scrubber, NOT part of the reversible context-reclaim
    ladder: Offload (chain_skip.py) relocates blocks LOSSLESSLY and is byte-exact
    reversible, so prefer Offload when you might want the content back. Reach for
    scrub_files only for attachments you are willing to lose (recoverable afterward
    only via the .bak backup, or by re-fetching). 'list' and 'info' are read-only
    previews; 'rm' and 'scrub' are the destructive, file-rewriting operations.

Usage:
    scrub_files                                    Enter REPL (use 'open' to load a session)
    scrub_files <session>                          REPL with session pre-loaded
    scrub_files <session> [command] [args...]      One-shot CLI

Commands:
    open <session>                                 Load a session to inspect/scrub. <session> = a session
                                                   UUID (partial OK), an AI tracking-id
                                                   (YYYYMMDD_HHMMSS_uuid8_plat3), or an explicit path to a .jsonl
    list [--type TYPE] [--sort FIELD] [--json]     List all file attachments with #ref, type, size, line, oversized
                                                   flag. READ-ONLY -- run this to preview before rm/scrub
    ls                                             Alias for list
    rm <ref...>                                    Remove specific attachments by # from 'list' (e.g. rm 1 3 5 or
                                                   a range rm 1-5). Replaces each with "[Removed]", rewrites the
                                                   file. DESTRUCTIVE (auto-creates .bak on first write)
    remove                                         Alias for rm
    scrub [--type TYPE] [--max-px N] [--all]       Bulk scrub matching attachments. Default (no --all): only
                                                   OVERSIZED images (largest dimension > --max-px). --all: every
                                                   attachment matching --type. DESTRUCTIVE (auto-backup on first write)
    info <ref>                                     Detailed metadata for one attachment # (type, size, dimensions,
                                                   line, oversized). READ-ONLY
    backup                                         Manually create <transcript>.jsonl.bak (skips if one exists)
    restore                                        Copy <transcript>.jsonl.bak back over the transcript -- the undo
                                                   for rm/scrub
    help                                           Show this help
    quit                                           Exit REPL

Filters:
    --type images,pdf,files,scrubbed,all           Comma-separated type filter. images = inline/base64 images;
                                                   pdf = PDF attachments; files = other embedded files;
                                                   scrubbed = already-removed placeholders; all = every type
                                                   (default: all)
    --sort line,name,size,type,date                Sort field for 'list' (default: line = file/source order)
    --max-px N                                     Pixel threshold: an image is OVERSIZED when its largest
                                                   dimension exceeds N px. Governs the default 'scrub'
                                                   (units: pixels; default: 2000)
    --all                                          Scrub ALL matching attachments, not just oversized images
                                                   (default: off)
    --json                                         Emit machine-readable JSON ('list' only; default: colored text)

Examples:
    scrub_files 7edf list                          # preview every attachment (non-destructive)
    scrub_files 7edf list --type images --sort size --json
    scrub_files 7edf info 2                         # inspect attachment #2
    scrub_files 7edf backup                         # take an explicit .bak first (optional; scrub auto-backs up)
    scrub_files 7edf scrub                          # scrub only oversized images (> 2000 px)
    scrub_files 7edf scrub --all --type pdf         # scrub every PDF attachment
    scrub_files 7edf scrub --max-px 1200            # treat images > 1200 px as oversized
    scrub_files 7edf rm 1 3 5                        # remove specific attachments by #
    scrub_files 7edf restore                        # undo: restore the transcript from its .jsonl.bak

Caveats:
    * MODIFIES THE TRANSCRIPT IN PLACE. rm and scrub rewrite the .jsonl (atomic temp-file + rename).
      list, info, and backup are safe/read-only; only rm and scrub mutate the file.
    * Auto-backup is ONE-SHOT: the first rm/scrub of a session creates <transcript>.jsonl.bak, and later
      ops do NOT re-back-up. So the .bak always holds the PRE-FIRST-EDIT state -- 'restore' rewinds to
      before your first mutation this session, not to the previous step. 'backup' also won't overwrite an
      existing .bak.
    * LOSSY: removed content is replaced by a "[Removed]" placeholder; the original bytes are gone from the
      transcript. Recover only via the .bak (or re-fetch the source). Scrubbing a PDF also deletes its
      extracted output_dir on disk.
    * Prefer LOSSLESS Offload (chain_skip.py offload) when you might want the content back -- that path is
      byte-exact reversible. Use scrub_files for genuinely disposable heavy attachments.
    * Operates on the WHOLE file (every attachment line), not just the active --resume chain.
"""


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

class ScrubSession:
    """Holds state for a scrub_files session (REPL or one-shot)."""

    def __init__(self, jsonl_path=None):
        # type: (Optional[Path]) -> None
        self.jsonl_path = jsonl_path
        self._attachments = None  # type: Optional[List[Dict]]

    @property
    def is_loaded(self):
        # type: () -> bool
        return self.jsonl_path is not None

    def _require_session(self):
        # type: () -> Optional[str]
        """Return error message if no session is loaded, else None."""
        if not self.is_loaded:
            return c("No session loaded. Use 'open <session>' first.", "yellow")
        return None

    def cmd_open(self, args):
        # type: (List[str]) -> str
        """Load a session by UUID, tracking ID, or path."""
        if not args:
            return c("Usage: open <session_id_or_path>", "yellow")
        identifier = args[0]
        jsonl_path = find_jsonl(identifier)
        if not jsonl_path:
            return c("JSONL file not found for: {}".format(identifier), "red")
        self.jsonl_path = jsonl_path
        self._attachments = None
        return c("Loaded: ", "green") + dim(str(jsonl_path))

    @property
    def attachments(self):
        # type: () -> List[Dict]
        """Lazy-load and cache attachment list."""
        if self._attachments is None:
            self._attachments = scan_attachments(self.jsonl_path)
        return self._attachments

    def invalidate_cache(self):
        # type: () -> None
        """Force re-scan on next access."""
        self._attachments = None

    def run_command(self, line):
        # type: (str) -> Optional[str]
        """Parse and execute a command. Returns output string or None."""
        try:
            parts = shlex.split(line)
        except ValueError as e:
            return c("Parse error: {}".format(e), "red")

        if not parts:
            return None

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "open":
            return self.cmd_open(args)
        elif cmd in ("help", "?"):
            return format_help(HELP_TEXT)
        elif cmd in ("quit", "exit", "q"):
            return None

        # All remaining commands require a loaded session
        err = self._require_session()
        if err:
            return err

        if cmd in ("list", "ls"):
            return self.cmd_list(args)
        elif cmd in ("rm", "remove"):
            return self.cmd_rm(args)
        elif cmd == "scrub":
            return self.cmd_scrub(args)
        elif cmd == "info":
            return self.cmd_info(args)
        elif cmd == "backup":
            return do_backup(self.jsonl_path)
        elif cmd == "restore":
            result = do_restore(self.jsonl_path)
            self.invalidate_cache()
            return result
        else:
            return c("  Unknown command: {}".format(cmd), "yellow")

    def cmd_list(self, args):
        # type: (List[str]) -> str
        """List attachments."""
        type_filter = None  # type: Optional[str]
        sort_by = "line"
        as_json = False

        i = 0
        while i < len(args):
            if args[i] == "--type" and i + 1 < len(args):
                type_filter = args[i + 1]
                if type_filter == "all":
                    type_filter = None
                i += 2
            elif args[i] == "--sort" and i + 1 < len(args):
                sort_by = args[i + 1]
                i += 2
            elif args[i] == "--json":
                as_json = True
                i += 1
            else:
                i += 1

        return format_list(self.attachments, type_filter=type_filter,
                           sort_by=sort_by, as_json=as_json)

    def cmd_rm(self, args):
        # type: (List[str]) -> str
        """Remove attachments by reference number."""
        if not args:
            return c("  Usage: rm <ref...>  (e.g., rm 1 3 5 or rm 1-5)", "yellow")

        refs = _parse_refs(args)
        if not refs:
            return c("  No valid references provided.", "yellow")

        removed, saved = remove_attachments(self.jsonl_path, self.attachments, refs)
        self.invalidate_cache()

        if removed > 0:
            return c("  Removed {} attachment(s), saved {}".format(removed, _format_size(saved)), "green")
        return c("  No attachments removed.", "dim")

    def cmd_scrub(self, args):
        # type: (List[str]) -> str
        """Bulk scrub attachments."""
        type_filter = None  # type: Optional[str]
        max_px = MAX_DIMENSION
        scrub_all = False

        i = 0
        while i < len(args):
            if args[i] == "--type" and i + 1 < len(args):
                type_filter = args[i + 1]
                i += 2
            elif args[i] == "--max-px" and i + 1 < len(args):
                try:
                    max_px = int(args[i + 1])
                except ValueError:
                    return c("  Invalid --max-px value: {}".format(args[i + 1]), "red")
                i += 2
            elif args[i] == "--all":
                scrub_all = True
                i += 1
            else:
                i += 1

        removed, saved = scrub_bulk(self.jsonl_path, self.attachments,
                                    type_filter=type_filter, max_px=max_px,
                                    scrub_all=scrub_all)
        self.invalidate_cache()

        if removed > 0:
            return c("  Scrubbed {} attachment(s), saved {}".format(removed, _format_size(saved)), "green")
        return ""

    def cmd_info(self, args):
        # type: (List[str]) -> str
        """Show detailed info about an attachment."""
        if not args:
            return c("  Usage: info <ref>", "yellow")
        try:
            num = int(args[0])
        except ValueError:
            return c("  Invalid reference: {}".format(args[0]), "red")

        for att in self.attachments:
            if att["num"] == num:
                return format_info(att)
        return c("  Attachment #{} not found.".format(num), "yellow")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def setup_readline():
    # type: () -> None
    """Set up readline with history."""
    try:
        readline.read_history_file(str(HISTORY_FILE))
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(500)
    atexit.register(_save_history)


def _save_history():
    # type: () -> None
    """Save readline history."""
    try:
        readline.write_history_file(str(HISTORY_FILE))
    except OSError:
        pass


def repl(session):
    # type: (ScrubSession) -> None
    """Interactive REPL mode."""
    setup_readline()

    print(bold("scrub_files v{}".format(VERSION)))
    if session.is_loaded:
        print(dim("  {}".format(session.jsonl_path)))
        print()
        print(session.cmd_list([]))
    else:
        print(dim("  No session loaded. Use 'open <session>' to begin."))
    print()
    print(dim("Type 'help' for commands, 'quit' to exit."))

    while True:
        try:
            from uai_toolkit.common_utils.standard_colors import colors_enabled
            if colors_enabled():
                prompt = "\001\033[36m\002scrub> \001\033[0m\002"
            else:
                prompt = "scrub> "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not line:
            continue

        if line.lower() in ("quit", "exit", "q"):
            break

        result = session.run_command(line)
        if result:
            print(result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def offload_embeds(jsonl_path, keep_last_turns=5, min_bytes=512, mode="archive",
                   dry_run=False, archive_dir=None):
    """Resume-safe archive-and-stub of embedded images (engine-backed).

    The reversible successor to strip-scrubbing: instead of replacing an image
    with a bare placeholder, archive the original block to the portable per-
    session archive and leave a pointer stub (rehydratable via read_jsonl
    --resolve). Protects the last N human turns (no stripping a current-turn
    screenshot), CAS-guarded, byte-identical untouched lines. Same archive +
    manifest as offload_tool_results.py (manifest kind="embed").
    """
    import json as _json
    from uai_toolkit.jsonl import lib_jsonl_archive as A

    sig0 = A._stat_sig(jsonl_path)
    raw_text = jsonl_path.read_text(encoding="utf-8")
    sig1 = A._stat_sig(jsonl_path)
    raw_lines = raw_text.splitlines()
    records = []
    for line in raw_lines:
        try:
            records.append(_json.loads(line))
        except _json.JSONDecodeError:
            records.append(line)

    protect_from = A.protect_from_index(jsonl_path, records, keep_last_turns)
    # Embeds share the OFFLOAD namespace dir/manifest with offload_tool_results
    # (offload_session combines them); kept separate from engram (todo_0366).
    archive = A.Archive(jsonl_path, dry_run, archive_dir, namespace="offload")
    archive.ensure()

    stats = {"embeds": 0, "bytes_before": 0, "bytes_after": 0, "skipped_small": 0,
             "skipped_protected": 0, "protect_from_line": protect_from,
             "total_lines": len(records), "status": "nochange"}
    manifest = []
    dirty = set()

    def _is_image(b):
        return isinstance(b, dict) and b.get("type") == "image" and isinstance(b.get("source"), dict)

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        rec_uuid = rec.get("uuid") or f"line{i}"
        # collect (block, path, slugbase) for top-level and nested image blocks
        targets = []
        for j, block in enumerate(content):
            if _is_image(block):
                targets.append((block, ["message", "content", j], f"{rec_uuid}.{j}"))
            elif isinstance(block, dict) and isinstance(block.get("content"), list):
                for k, sub in enumerate(block["content"]):
                    if _is_image(sub):
                        targets.append((sub, ["message", "content", j, "content", k], f"{rec_uuid}.{j}_{k}"))

        for val, path, slugbase in targets:
            sz = A.wire_size(val)
            if i >= protect_from:
                stats["skipped_protected"] += 1
                continue
            if sz < min_bytes:
                stats["skipped_small"] += 1
                continue
            src = val.get("source", {})
            b64 = src.get("data", "") if isinstance(src, dict) else ""
            dims = get_image_dimensions_from_base64(b64) if b64 else None
            dimstr = "{}x{}".format(dims[0], dims[1]) if dims else "?"
            mt = src.get("media_type", "image") if isinstance(src, dict) else "image"
            stats["bytes_before"] += sz
            ref = None
            sh = A.sha8(A.render_readable(val))
            if mode == "archive":
                ref, mrec = archive.write_body(
                    f"{slugbase}.embed", val,
                    {"kind": "embed", "line": i, "path": path, "embed_type": "image",
                     "media_type": mt, "dims": dimstr})
                manifest.append(mrec)
                sh = mrec["sha8"]
            if ref:
                stub = (f"[embed archived: image {dimstr} {mt} · {sz:,} chars · {sh} "
                        f"→ ref {ref} (resolve via read_jsonl) if needed; do NOT reconstruct from memory]")
            else:
                stub = f"[embed stripped: image {dimstr} {mt} · {sz:,} chars · {sh}]"
            A._nav_set(rec, path, {"type": "text", "text": stub})
            stats["bytes_after"] += len(stub)
            stats["embeds"] += 1
            dirty.add(i)

    stats["bytes_reclaimed"] = stats["bytes_before"] - stats["bytes_after"]
    stats["tokens_reclaimed"] = A.tokens(stats["bytes_reclaimed"]) if stats["bytes_reclaimed"] > 0 else 0
    if dirty and not dry_run:
        stats["status"] = A.commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=True)
        if stats["status"] == "ok":
            archive.append_manifest(manifest)
    return stats


def main():
    # type: () -> None
    """Main entry point."""
    args = sys.argv[1:]

    if args and args[0] in ("--help", "-h"):
        print(format_help(HELP_TEXT))
        sys.exit(0)

    if args and args[0] == "--version":
        print("scrub_files v{}".format(VERSION))
        sys.exit(0)

    # No args at all → REPL with no session loaded
    if not args:
        session = ScrubSession()
        repl(session)
        return

    # First arg might be a session identifier or a command
    # If it looks like a known command, enter REPL without session
    known_commands = {"help", "?", "quit", "exit", "q", "--help", "-h", "--version"}
    if args[0] in known_commands:
        session = ScrubSession()
        repl(session)
        return

    # First arg is the session identifier
    session_id = args[0]
    cmd_args = args[1:]

    # Resolve JSONL path
    jsonl_path = find_jsonl(session_id)
    if not jsonl_path:
        print(c("JSONL file not found for: {}".format(session_id), "red"), file=sys.stderr)
        sys.exit(1)

    # Engine-backed embed offload / rehydrate (archive-and-stub, resume-safe)
    if cmd_args and cmd_args[0] in ("offload", "rehydrate"):
        from uai_toolkit.jsonl import lib_jsonl_archive as A
        sub, rest = cmd_args[0], cmd_args[1:]

        def _flag(name, default, cast=str):
            if name in rest:
                ix = rest.index(name)
                if ix + 1 < len(rest):
                    try:
                        return cast(rest[ix + 1])
                    except ValueError:
                        return default
            return default

        dry = "--dry-run" in rest
        if sub == "rehydrate":
            res = A.rehydrate(jsonl_path, dry, namespace="offload")
            print("Rehydrated {} embed/block(s){}{}".format(
                res.get("restored", 0), " (dry-run)" if dry else "",
                " — " + res["note"] if res.get("note") else ""))
            return
        st = offload_embeds(jsonl_path,
                            keep_last_turns=_flag("--keep-last-turns", 5, int),
                            min_bytes=_flag("--min-bytes", 2048, int),
                            mode="strip" if "--strip" in rest else "archive",
                            dry_run=dry)
        tag = " (dry-run)" if dry else ""
        print("Transcript: {}".format(jsonl_path))
        print("  Embeds archived{}: {}  | skipped {} small, {} protected".format(
            tag, st["embeds"], st["skipped_small"], st["skipped_protected"]))
        if st["bytes_reclaimed"] > 0:
            print("  Reclaimed: {:,} chars (~{:,} tokens)".format(
                st["bytes_reclaimed"], st["tokens_reclaimed"]))
        if not dry and st["embeds"]:
            print("  Reverse with: scrub_files.py {} rehydrate".format(session_id))
        return

    session = ScrubSession(jsonl_path)

    # If no command args, run REPL with session pre-loaded
    if not cmd_args:
        repl(session)
        return

    # One-shot CLI mode
    command_line = " ".join(shlex.quote(a) for a in cmd_args)
    result = session.run_command(command_line)
    if result:
        print(result)


if __name__ == "__main__":
    main()
