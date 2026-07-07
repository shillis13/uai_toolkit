"""
lib_paths.py — Centralized path constants for the unified CLI infrastructure.

All scripts that need session data paths should import from here.
Platform/yyyy segmentation is added at write time by callers.
"""

import os
from pathlib import Path

# Last-resort portable fallback only (NOT the source of truth). Reached solely
# when $AI_ROOT is unusable AND this file isn't inside a tree — which shouldn't
# happen in normal operation. Path.home() keeps it OS-portable (no literal user
# path); the real location comes from the tree itself (see get_ai_root).
_FALLBACK_AI_ROOT = Path.home() / "AI" / "ai_root"

# Marker that identifies a tree root: an ancestor dir named "ai_root" that
# actually contains ai_general/. The tree carries this with it when it moves.
_TREE_MARKER = "ai_general"


def _is_tree(path) -> bool:
    try:
        return (Path(path) / _TREE_MARKER).is_dir()
    except (OSError, TypeError):
        return False


def get_ai_root() -> Path:
    """Resolve AI_ROOT robustly. Single source of truth for all consumers.

    Precedence (the order matters):
      1. $AI_ROOT — but only if it points at a REAL tree (contains ai_general/).
         A devTree launcher sets it to the worktree root, so the override must
         win; validation means a STALE value (e.g. a since-deleted
         ~/Documents/AI) is rejected rather than trusted — it falls through.
      2. Self-location: walk up from this file (resolved through any symlink,
         e.g. the ~/bin/ai -> scripts link) to the ancestor named "ai_root"
         that contains ai_general/. The tree knows its own location, so moving
         or renaming it needs no code change and embeds no user/OS path.
      3. Portable last resort: ~/AI/ai_root via Path.home().
    """
    env = os.environ.get("AI_ROOT")
    if env and _is_tree(env):
        return Path(env).resolve()

    for anc in Path(__file__).resolve().parents:
        if anc.name == "ai_root" and _is_tree(anc):
            return anc

    return _FALLBACK_AI_ROOT.resolve()


AI_ROOT = get_ai_root()

# Primary data directory (app-owned state)
UNIFIED_CLI_DIR = AI_ROOT / "ai_general/data/unified_cli"

# Session registry base — actual files at {platform}/{yyyy}/{zellij_name}.json
SESSION_REGISTRY_DIR = AI_ROOT / "ai_general/data/session_registry"

# Per-session dirs base — actual dirs at {platform}/{yyyy}/{zellij_name}/
SESSIONS_DIR = AI_ROOT / "ai_general/data/sessions"

# App state (UCI Electron app owns this)
APP_STATE_FILE = UNIFIED_CLI_DIR / "app_state.json"

# Per-session app data base — at unified_cli/sessions/{zellij_name}.json
APP_SESSIONS_DIR = UNIFIED_CLI_DIR / "sessions"
