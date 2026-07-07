#!/usr/bin/env python3
"""UserPromptSubmit hook — inject unloaded global context files.

Scans ai_context_files/globals/ for .md/.yml/.txt files. Compares against
the session's loaded.manifest to find globals not yet delivered. Injects
new globals via additionalContext and tracks them as loaded.

Files in globals/ are broadcast knowledge — environment changes, new tools,
directory restructures — that every session needs without explicit action.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
GLOBALS_DIR = AI_ROOT / "ai_general" / "ai_context_files" / "globals"
SESSION_TRAITS = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_traits.py"

VALID_EXTENSIONS = {".md", ".yml", ".txt"}
MAX_FILE_SIZE = 10 * 1024      # 10KB per file
MAX_TOTAL_SIZE = 50 * 1024     # 50KB total injection


def _list_globals() -> list[Path]:
    """List global context files."""
    if not GLOBALS_DIR.exists():
        return []
    return sorted(
        f for f in GLOBALS_DIR.iterdir()
        if f.is_file() and f.suffix in VALID_EXTENSIONS and not f.name.startswith(".")
    )


def _get_loaded_globals(tracking_id: str) -> set[str]:
    """Get set of global names already loaded in this session."""
    try:
        cmd = [sys.executable, str(SESSION_TRAITS), "--session", tracking_id, "--json", "list", "--loaded", "globals"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            items = data if isinstance(data, list) else data.get("items", [])
            return {item.get("name", "") if isinstance(item, dict) else str(item) for item in items}
    except Exception:
        pass
    return set()


def _track_loaded(tracking_id: str, name: str):
    """Record a global as loaded in session state."""
    try:
        subprocess.run(
            [sys.executable, str(SESSION_TRAITS), "--session", tracking_id, "--json", "load", "globals", name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def handler(hook_input, context):
    tracking_id = context.tracking_id
    if not tracking_id:
        return HookResult.skip("no tracking ID")

    all_globals = _list_globals()
    if not all_globals:
        return HookResult.skip("no globals files")

    loaded = _get_loaded_globals(tracking_id)
    unloaded = [f for f in all_globals if f.stem not in loaded]

    if not unloaded:
        return HookResult.skip("all globals already loaded")

    # Read and assemble content
    parts = []
    total_size = 0
    delivered = []

    for f in unloaded:
        try:
            size = f.stat().st_size
            if size > MAX_FILE_SIZE:
                continue
            if total_size + size > MAX_TOTAL_SIZE:
                break
            content = f.read_text()
            parts.append(f"# === globals/{f.stem} ===\n\n{content}")
            total_size += size
            delivered.append(f.stem)
        except Exception:
            continue

    if not delivered:
        return HookResult.skip("no deliverable globals (size limits)")

    # Track each delivered global
    for name in delivered:
        _track_loaded(tracking_id, name)

    # Build additionalContext
    header = "The following global context files have been loaded. These contain environment knowledge that applies to all sessions.\n\n"
    injection = header + "\n\n".join(parts)

    output = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": injection,
        }
    })
    return HookResult.output(output, f"injected {len(delivered)} globals: {', '.join(delivered)}")


if __name__ == "__main__":
    sys.exit(run_hook("inject_globals", "UserPromptSubmit", handler))
