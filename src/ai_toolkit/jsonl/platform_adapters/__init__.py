from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_toolkit.jsonl.standardized_session import is_standardized_session_file
from ai_toolkit.jsonl.platform_adapters import claude, codex, gemini, agy

ADAPTERS = {
    "claude": claude,
    "codex": codex,
    "gemini": gemini,
    "agy": agy,
}


def _first_json_object(path: Path) -> Any | None:
    try:
        if path.suffix == ".json":
            return json.loads(path.read_text())
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                return json.loads(line)
    except (OSError, json.JSONDecodeError):
        return None
    return None



def detect_platform(path: str | Path) -> str:
    path = Path(path)
    if is_standardized_session_file(path):
        return "standardized"
    first_obj = _first_json_object(path)
    for name, adapter in (("agy", agy), ("codex", codex), ("gemini", gemini), ("claude", claude)):
        if adapter.sniff(path, first_obj):
            return name
    return "claude"



def adapter_for_platform(platform: str):
    try:
        return ADAPTERS[platform]
    except KeyError as exc:
        raise ValueError(f"Unsupported platform adapter: {platform}") from exc
