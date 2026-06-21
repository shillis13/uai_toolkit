"""Locate the AI_ROOT instance and read user config.

One env var locates the writable instance: AI_ROOT. If unset, a discovery
cascade is used. Everything else the user customizes lives in
$AI_ROOT/config.toml — NOT in scattered env vars, and NOT in the package
(which is read-only and replaced on upgrade).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # 3.11+ stdlib; tomli backport on 3.10
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    import tomli as _toml  # type: ignore


CONFIG_NAME = "config.toml"


@lru_cache(maxsize=1)
def ai_root() -> Path:
    """Resolve the writable instance root.

    Order: $AI_ROOT → ./ai_root (cwd) → ~/.ai_root → platform default.
    """
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env).expanduser()
    for cand in (Path.cwd() / "ai_root", Path.home() / ".ai_root"):
        if cand.is_dir():
            return cand
    # Sensible per-OS default (kept dependency-free; platformdirs optional later).
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "ai_root"


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    """Load $AI_ROOT/config.toml, or {} if absent (all settings have defaults)."""
    path = ai_root() / CONFIG_NAME
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return _toml.load(fh)


def get(dotted: str, default: Any = None) -> Any:
    """Read a nested config value, e.g. get('jsonl.pager', 'auto')."""
    node: Any = config()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
