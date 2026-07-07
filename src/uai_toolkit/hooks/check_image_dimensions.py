#!/usr/bin/env python3
"""Block prompt submit when recent conversation images exceed API-safe dimensions.

Usage:
  check_image_dimensions.py /absolute/path/to/session.jsonl

This script is intended for a UserPromptSubmit-style hook. It scans only the
tail of the JSONL transcript, looking at the most recent user messages for
image attachments represented like:

  [Image: source: /path/to/file.png]

If any referenced image exceeds 2000px in width or height, the script prints a
warning to stderr and exits 1 to block the submit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


MAX_DIMENSION = 2000
MAX_MESSAGE_RECORDS = 12
TAIL_BYTES = 1_000_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_MARKER_RE = re.compile(
    r"\[Image:\s*source:\s*(.+?\.(?:png|jpg|jpeg|gif|webp))\]",
    re.IGNORECASE,
)


def read_tail_lines(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    """Read only the tail of a JSONL file for speed."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_size = handle.tell()
        start = max(0, file_size - max_bytes)
        handle.seek(start)
        payload = handle.read()

    if start > 0:
        newline_index = payload.find(b"\n")
        if newline_index != -1:
            payload = payload[newline_index + 1 :]

    return payload.decode("utf-8", errors="ignore").splitlines()


def recent_user_records(jsonl_path: Path, max_messages: int = MAX_MESSAGE_RECORDS) -> list[dict]:
    """Return the most recent user records from the JSONL tail."""
    records: list[dict] = []
    for line in reversed(read_tail_lines(jsonl_path)):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if parsed.get("type") != "user":
            continue
        records.append(parsed)
        if len(records) >= max_messages:
            break
    records.reverse()
    return records


def iter_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)


def extract_recent_image_paths(jsonl_path: Path) -> list[Path]:
    """Extract unique recent image file paths from recent user records."""
    seen: set[str] = set()
    results: list[Path] = []

    for record in recent_user_records(jsonl_path):
        for text in iter_strings(record):
            for match in IMAGE_MARKER_RE.finditer(text):
                raw_path = match.group(1).strip().strip("\"'")
                expanded = os.path.expanduser(raw_path)
                suffix = Path(expanded).suffix.lower()
                if suffix not in IMAGE_EXTENSIONS:
                    continue
                if expanded in seen:
                    continue
                seen.add(expanded)
                results.append(Path(expanded))

    return results


def dimensions_with_pillow(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            width, height = image.size
        return int(width), int(height)
    except ImportError:
        return None
    except Exception:
        return None


def dimensions_with_sips(path: Path) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                "sips",
                "--getProperty",
                "pixelWidth",
                "--getProperty",
                "pixelHeight",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    width: int | None = None
    height: int | None = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("pixelWidth:"):
            try:
                width = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                return None
        elif stripped.startswith("pixelHeight:"):
            try:
                height = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                return None

    if width is None or height is None:
        return None
    return width, height


def get_dimensions(path: Path) -> tuple[int, int] | None:
    dims = dimensions_with_pillow(path)
    if dims is not None:
        return dims
    return dimensions_with_sips(path)


def oversized_images(paths: Iterable[Path]) -> list[tuple[Path, int, int]]:
    oversized: list[tuple[Path, int, int]] = []

    for path in paths:
        if not path.exists() or not path.is_file():
            continue

        dims = get_dimensions(path)
        if dims is None:
            continue

        width, height = dims
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            oversized.append((path, width, height))

    return oversized


def build_block_message(images: list[tuple[Path, int, int]]) -> str:
    lines = [
        "[check_image_dimensions] Blocked: recent conversation context still references oversized images:",
    ]
    for path, width, height in images:
        lines.append(f"  - {path} ({width}x{height}px)")
    lines.append(
        f"Longest edge must be <= {MAX_DIMENSION}px. Resize/remove the image(s), or run /compact to remove old images from context."
    )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: check_image_dimensions.py /absolute/path/to/session.jsonl", file=sys.stderr)
        return 1

    jsonl_path = Path(os.path.expanduser(argv[1]))
    if not jsonl_path.exists() or not jsonl_path.is_file():
        return 0

    try:
        recent_paths = extract_recent_image_paths(jsonl_path)
    except OSError:
        return 0

    if not recent_paths:
        return 0

    blocked = oversized_images(recent_paths)
    if not blocked:
        return 0

    print(build_block_message(blocked), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
