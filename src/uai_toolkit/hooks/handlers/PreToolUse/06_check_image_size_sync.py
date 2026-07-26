#!/usr/bin/env python3
"""PreToolUse hook — block Read of oversized images before they enter context.

Claude's API rejects images >2000px on any edge when there are many images
in the conversation. Once an image is in context, the only fix is /compact
or a new session. This handler prevents the problem at the source.

Checks dimensions using sips (macOS, no deps) and blocks with a suggestion
to resize using resize-for-claude.sh.
"""

import os
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

MAX_DIMENSION = 2000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
RESIZE_SCRIPT = "ai_general/scripts/utils/resize-for-claude.sh"


def _get_dimensions_sips(file_path):
    """Get image dimensions using macOS sips (no dependencies)."""
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(file_path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None, None
        w = h = None
        for line in result.stdout.splitlines():
            if "pixelWidth" in line:
                w = int(line.split(":")[-1].strip())
            elif "pixelHeight" in line:
                h = int(line.split(":")[-1].strip())
        return w, h
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None, None


def _get_dimensions_header(file_path):
    """Get image dimensions by reading file headers (fallback, no deps)."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(32)

        # PNG
        if header[:8] == b'\x89PNG\r\n\x1a\n':
            w, h = struct.unpack(">II", header[16:24])
            return w, h

        # JPEG
        if header[:2] == b'\xff\xd8':
            f = open(file_path, "rb")
            f.read(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xFF:
                    break
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)  # length + precision
                    h, w = struct.unpack(">HH", f.read(4))
                    f.close()
                    return w, h
                else:
                    length = struct.unpack(">H", f.read(2))[0]
                    f.read(length - 2)
            f.close()

        # GIF
        if header[:6] in (b'GIF87a', b'GIF89a'):
            w, h = struct.unpack("<HH", header[6:10])
            return w, h

        # BMP
        if header[:2] == b'BM':
            w, h = struct.unpack("<II", header[18:26])
            return w, abs(h)

    except (OSError, struct.error):
        pass

    return None, None


def _read_state(context):
    """Read session state (union: canonical accessor over legacy) for bypass checks.
    The bypass flags may be set via the MCP into the canonical file, and post-flip
    all writes land there, so a legacy-only read would miss them (todo_0495)."""
    if not context.tracking_id or not context.session_dir:
        return {}
    try:
        from uai_toolkit.hooks.common.lib_session_state_union import read_union
        return read_union(context.session_dir, context.tracking_id)
    except Exception:
        return {}


def _is_allowed(file_path, state):
    """Check session state for image bypass flags.

    hooks.allow_oversized_images — truthy = skip all image checks this session
    hooks.image_allow — comma-separated paths that bypass the check
    """
    if state.get("hooks.allow_oversized_images"):
        return True
    allow_list = state.get("hooks.image_allow", "")
    if allow_list:
        resolved = str(Path(file_path).resolve())
        for entry in allow_list.split(","):
            entry = entry.strip()
            if entry and (entry == file_path or entry == resolved or resolved.endswith(entry)):
                return True
    return False


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Read":
        return HookResult.skip("not Read")

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return HookResult.skip("no file_path")

    # Check if it's an image file
    ext = Path(file_path).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        return HookResult.skip("not an image file")

    # Check if file exists
    if not Path(file_path).exists():
        return HookResult.skip("file does not exist")

    # Get dimensions — sips first, header fallback
    w, h = _get_dimensions_sips(file_path)
    if w is None or h is None:
        w, h = _get_dimensions_header(file_path)

    if w is None or h is None:
        return HookResult.allow("could not determine dimensions")

    max_edge = max(w, h)
    if max_edge <= MAX_DIMENSION:
        return HookResult.allow(f"{w}x{h} within limit")

    # Check session state for bypass
    state = _read_state(context)
    if _is_allowed(file_path, state):
        return HookResult.allow(f"bypassed: {w}x{h} image allowed by session state")

    # Block — image is too large
    reason = (
        f"Image {Path(file_path).name} is {w}x{h}px (max edge: {max_edge}px). "
        f"Claude's API rejects images >2000px when many images are in context, "
        f"and once loaded there is no way to remove it without /compact.\n\n"
        f"Resize first: {RESIZE_SCRIPT} \"{file_path}\"\n"
        f"Or use: sips --resampleHeightWidthMax {MAX_DIMENSION} \"{file_path}\"\n\n"
        f"To bypass for this session: set hooks.allow_oversized_images=true in session state.\n"
        f"To bypass for this file: add the path to hooks.image_allow in session state."
    )

    return HookResult.block(reason, f"blocked {w}x{h} image: {Path(file_path).name}")


if __name__ == "__main__":
    sys.exit(run_hook("check_image_size", "PreToolUse", handler))
