#!/usr/bin/env python3
"""UserPromptSubmit handler — check image dimensions before submission.

Parses the prompt text for image file paths (png, jpg, jpeg, gif, webp, bmp).
If any referenced image exceeds 2000px in either dimension, blocks with a
message to resize it.

Uses PIL/Pillow if available, falls back to parsing PNG/JPEG headers directly.
"""

import os
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

MAX_DIMENSION = 2000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

# Match file paths — absolute paths or ~/paths that end with image extensions
PATH_PATTERN = re.compile(
    r'(?:^|\s|["\'])'
    r'((?:/[^\s"\']+|~[^\s"\']+)\.(?:png|jpg|jpeg|gif|webp|bmp|tiff|tif))',
    re.IGNORECASE | re.MULTILINE,
)


def get_image_dimensions(filepath):
    """Get (width, height) of an image file. Returns None on failure."""
    # Try Pillow first
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            return img.size  # (width, height)
    except ImportError:
        pass
    except Exception:
        return None

    # Fallback: parse headers manually for PNG and JPEG
    try:
        with open(filepath, "rb") as f:
            header = f.read(32)

            # PNG: width and height at bytes 16-23
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                width = struct.unpack(">I", header[16:20])[0]
                height = struct.unpack(">I", header[20:24])[0]
                return (width, height)

            # JPEG: need to find SOF marker
            if header[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2:
                        break
                    if marker[0] != 0xFF:
                        break
                    # SOF markers: C0, C1, C2
                    if marker[1] in (0xC0, 0xC1, 0xC2):
                        f.read(3)  # length + precision
                        height = struct.unpack(">H", f.read(2))[0]
                        width = struct.unpack(">H", f.read(2))[0]
                        return (width, height)
                    else:
                        length = struct.unpack(">H", f.read(2))[0]
                        f.seek(length - 2, 1)
    except (OSError, struct.error):
        pass

    return None


def handler(hook_input, context):
    prompt = hook_input.get("prompt", "")
    if not prompt:
        return HookResult.skip("no prompt")

    # Find image paths in the prompt
    matches = PATH_PATTERN.findall(prompt)
    if not matches:
        return HookResult.skip("no image paths in prompt")

    oversized = []
    for path_str in matches:
        # Expand ~ if present
        expanded = os.path.expanduser(path_str.strip())
        if not os.path.isfile(expanded):
            continue

        ext = Path(expanded).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue

        dims = get_image_dimensions(expanded)
        if dims is None:
            continue

        width, height = dims
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            oversized.append((expanded, width, height))

    if not oversized:
        return HookResult.allow()

    # Block with details
    lines = [f"[04_check_image_dimensions] {len(oversized)} image(s) exceed {MAX_DIMENSION}px limit:\n"]
    for path, w, h in oversized:
        lines.append(f"  {Path(path).name}: {w}x{h}px")
    lines.append(f"\nResize to ≤{MAX_DIMENSION}px in both dimensions before submitting.")
    lines.append(f"Example: sips --resampleWidth {MAX_DIMENSION} <file>")

    return HookResult.block("\n".join(lines), f"{len(oversized)} oversized images")


if __name__ == "__main__":
    sys.exit(run_hook("check_image_dimensions", "UserPromptSubmit", handler))
