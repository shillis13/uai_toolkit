from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))



def normalize_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if value > 1_000_000_000_000:
            value = value / 1000
        return datetime.fromtimestamp(value).isoformat()
    if isinstance(value, str):
        return value
    return ""



def join_text_parts(parts: Iterable[Any]) -> str:
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts)



def path_contains(path: Path, needle: str) -> bool:
    return needle in str(path.resolve())
