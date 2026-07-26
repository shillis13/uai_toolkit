from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uai_toolkit.jsonl.standardized_session import (
    StandardizedMessageRecord,
    StandardizedSession,
    StandardizedSessionHeader,
    StandardizedSourceRecord,
)
from uai_toolkit.jsonl.platform_adapters.common import compact_json, join_text_parts, normalize_timestamp

PLATFORM = "grok"

# Grok top-level record types observed in ~/.grok/sessions/**/chat_history.jsonl
_GROK_TYPES = {
    "system",
    "user",
    "assistant",
    "reasoning",
    "tool_result",
    "backend_tool_call",
}

# Keys that appear on Grok chat_history lines (used for content-based sniff).
_GROK_KEYS = {
    "type",
    "content",
    "synthetic_reason",
    "prompt_index",
    "id",
    "summary",
    "encrypted_content",
    "status",
    "model_id",
    "model_fingerprint",
    "reasoning_effort",
    "tool_calls",
    "tool_call_id",
    "kind",
}


def sniff(path: Path, first_obj: Any | None = None) -> bool:
    """Detect Grok CLI chat_history.jsonl transcripts.

    Path signals (strong):
      - resolved path contains ``/.grok/sessions/``
      - filename is ``chat_history.jsonl``

    Content signals:
      - first object is a dict whose keys are a subset of known Grok keys, with
        ``type`` in the Grok type set (and typically ``content`` present).
      - exact ``{type, content}`` shape (common for the leading system line).
    """
    resolved = str(path.resolve())
    if "/.grok/sessions/" in resolved or path.name == "chat_history.jsonl":
        return True

    if not isinstance(first_obj, dict):
        return False

    # Avoid colliding with AGY (step_index/source) and Claude (uuid/parentUuid).
    if "step_index" in first_obj or "uuid" in first_obj or "parentUuid" in first_obj:
        return False
    if first_obj.get("type") in {"session_meta", "response_item", "event_msg", "turn_context"}:
        return False

    keys = set(first_obj.keys())
    record_type = first_obj.get("type")

    if keys == {"type", "content"} and record_type in _GROK_TYPES:
        return True

    if record_type in _GROK_TYPES and keys <= _GROK_KEYS and (
        "content" in first_obj or record_type in {"reasoning", "backend_tool_call"}
    ):
        return True

    return False


def _content_to_text(content: Any) -> str:
    """Normalize Grok content (str | list of text blocks | None) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Prefer join_text_parts for dict blocks with "text"; also accept plain strings.
        parts: list[str] = []
        joined = join_text_parts(content)
        if joined:
            return joined
        for part in content:
            if isinstance(part, str) and part:
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        return compact_json(content)
    return str(content)


def _summary_to_text(summary: Any) -> str:
    """Extract readable text from a reasoning summary field."""
    if summary is None:
        return ""
    if isinstance(summary, str):
        return summary
    if isinstance(summary, list):
        texts: list[str] = []
        for item in summary:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
            elif isinstance(item, str) and item:
                texts.append(item)
        return "\n".join(texts)
    return str(summary)


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": arguments}
        except (TypeError, json.JSONDecodeError):
            return {"raw": arguments}
    if arguments is None:
        return {}
    return {"raw": arguments}


def _classify_user(obj: dict[str, Any], text: str) -> tuple[str, str]:
    """Return (role, message_type) for a Grok user-type record.

    Real human prompts often carry ``prompt_index`` and/or a ``<user_query>``
    wrapper. Synthetic injections carry ``synthetic_reason`` (project_instructions,
    system_reminder) or are bootstrap wrappers (``<user_info>``, etc.).
    """
    if obj.get("synthetic_reason"):
        return "user", "injected"
    if "prompt_index" in obj or "<user_query>" in text:
        return "user", "user"
    stripped = text.lstrip()
    if stripped.startswith(("<system-reminder>", "<user_info>", "<environment_")):
        return "user", "injected"
    # Default remaining untagged user-role lines to human input.
    return "user", "user"


def from_file(path: str | Path) -> StandardizedSession:
    """Parse a Grok CLI chat_history.jsonl into StandardizedSession."""
    path = Path(path)
    source_records: list[StandardizedSourceRecord] = []
    message_records: list[StandardizedMessageRecord] = []
    start_time = ""
    last_updated = ""
    msg_seq = 0
    model_id = ""

    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            raw_text = line.rstrip("\n")
            if not raw_text.strip():
                continue
            try:
                entry = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue

            entry_type = str(entry.get("type", ""))
            source_id = f"src-{line_number:06d}"
            # Grok transcripts generally omit per-line timestamps.
            ts = normalize_timestamp(entry.get("timestamp") or entry.get("created_at"))
            if ts:
                if not start_time:
                    start_time = ts
                last_updated = ts

            subtype = ""
            if entry_type == "user" and entry.get("synthetic_reason"):
                subtype = str(entry.get("synthetic_reason"))
            elif entry_type == "backend_tool_call":
                kind = entry.get("kind") or {}
                if isinstance(kind, dict):
                    subtype = str(kind.get("tool_type", ""))
            elif entry_type == "assistant" and entry.get("model_id"):
                subtype = str(entry.get("model_id"))
                model_id = model_id or subtype

            source_records.append(
                StandardizedSourceRecord(
                    source_id=source_id,
                    sequence=line_number,
                    raw_text=raw_text,
                    raw_obj=entry,
                    timestamp=ts,
                    platform_type=entry_type,
                    platform_subtype=subtype,
                )
            )

            if entry_type == "system":
                text = _content_to_text(entry.get("content"))
                if not text:
                    continue
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="system",
                        message_type="system",
                        content_text=text,
                        content_blocks=[{"type": "text", "text": text}],
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type},
                    )
                )
                continue

            if entry_type == "user":
                text = _content_to_text(entry.get("content"))
                if not text:
                    continue
                role, message_type = _classify_user(entry, text)
                msg_seq += 1
                extras: dict[str, Any] = {"source_entry_type": entry_type}
                if entry.get("synthetic_reason"):
                    extras["synthetic_reason"] = entry.get("synthetic_reason")
                if "prompt_index" in entry:
                    extras["prompt_index"] = entry.get("prompt_index")
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role=role,
                        message_type=message_type,
                        content_text=text,
                        content_blocks=[{"type": "text", "text": text}],
                        source_ids=[source_id],
                        platform_extras=extras,
                    )
                )
                continue

            if entry_type == "reasoning":
                text = _summary_to_text(entry.get("summary"))
                # Encrypted reasoning has no readable body; still emit a thinking
                # record so the turn structure is visible (content may be empty).
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="assistant",
                        message_type="thinking",
                        content_text=text,
                        content_blocks=[{"type": "thinking", "text": text}] if text else [],
                        source_ids=[source_id],
                        platform_extras={
                            "source_entry_type": entry_type,
                            "reasoning_id": entry.get("id", ""),
                            "status": entry.get("status", ""),
                            "has_encrypted_content": bool(entry.get("encrypted_content")),
                        },
                    )
                )
                continue

            if entry_type == "assistant":
                if entry.get("model_id"):
                    model_id = model_id or str(entry.get("model_id"))
                text = _content_to_text(entry.get("content"))
                if text:
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role="assistant",
                            message_type="response",
                            content_text=text,
                            content_blocks=[{"type": "text", "text": text}],
                            source_ids=[source_id],
                            platform_extras={
                                "source_entry_type": entry_type,
                                "model_id": entry.get("model_id", ""),
                                "reasoning_effort": entry.get("reasoning_effort", ""),
                            },
                        )
                    )

                tool_calls = entry.get("tool_calls") or []
                if isinstance(tool_calls, list):
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        tool_name = str(tc.get("name", "unknown"))
                        tool_input = _parse_tool_arguments(tc.get("arguments"))
                        call_id = str(tc.get("id", ""))
                        msg_seq += 1
                        message_records.append(
                            StandardizedMessageRecord(
                                record_id=f"msg-{msg_seq:06d}",
                                sequence=msg_seq,
                                timestamp=ts,
                                role="assistant",
                                message_type="tool_use",
                                tool_name=tool_name,
                                tool_input=tool_input,
                                tool_call_id=call_id,
                                source_ids=[source_id],
                                platform_extras={
                                    "source_entry_type": entry_type,
                                    "payload_type": "tool_call",
                                },
                            )
                        )
                continue

            if entry_type == "tool_result":
                text = _content_to_text(entry.get("content"))
                call_id = str(entry.get("tool_call_id", ""))
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="tool",
                        message_type="tool_result",
                        content_text=text,
                        content_blocks=[{"type": "text", "text": text}] if text else [],
                        tool_call_id=call_id,
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type},
                    )
                )
                continue

            if entry_type == "backend_tool_call":
                kind = entry.get("kind") or {}
                if not isinstance(kind, dict):
                    kind = {}
                tool_name = str(kind.get("tool_type") or "backend_tool")
                action = kind.get("action")
                if isinstance(action, dict):
                    tool_input = dict(action)
                elif action is None:
                    tool_input = {}
                else:
                    tool_input = {"raw": action}
                call_id = str(kind.get("id", ""))
                # Surface a short readable line (query when present).
                query = ""
                if isinstance(action, dict):
                    query = str(action.get("query") or "")
                content_text = query or compact_json(kind) if kind else tool_name
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="assistant",
                        message_type="tool_use",
                        content_text=content_text,
                        content_blocks=[{"type": "text", "text": content_text}] if content_text else [],
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_call_id=call_id,
                        source_ids=[source_id],
                        platform_extras={
                            "source_entry_type": entry_type,
                            "status": kind.get("status", ""),
                        },
                    )
                )
                continue

            # Unknown type: keep source_record only (already appended).

    # Session id is the parent directory UUID for the standard layout
    # ~/.grok/sessions/<urlencoded-cwd>/<session_uuid>/chat_history.jsonl
    session_id = path.parent.name if path.name == "chat_history.jsonl" else path.stem

    header = StandardizedSessionHeader(
        session_id=session_id,
        platform=PLATFORM,
        source_format="jsonl",
        platform_variant="grok_chat_history_jsonl",
        source_path=str(path),
        start_time=start_time,
        last_updated=last_updated,
        kind="main",
        metadata={"source_line_count": len(source_records)},
        platform_metadata={"model_id": model_id} if model_id else {},
        roundtrip={"strategy": "emit_source_records"},
    )
    return StandardizedSession(
        header=header,
        source_records=source_records,
        message_records=message_records,
    )


def to_platform_text(session: StandardizedSession) -> str:
    """Best-effort re-emit from source records (lossless when present)."""
    if session.source_records:
        ordered = [
            record.raw_text
            for record in sorted(session.source_records, key=lambda item: item.sequence)
        ]
        return "\n".join(ordered) + ("\n" if ordered else "")

    lines: list[str] = []
    for record in sorted(session.message_records, key=lambda item: item.sequence):
        if record.message_type == "system":
            lines.append(compact_json({"type": "system", "content": record.content_text}))
        elif record.message_type in {"user", "injected"}:
            obj: dict[str, Any] = {
                "type": "user",
                "content": [{"type": "text", "text": record.content_text}],
            }
            if record.message_type == "injected":
                obj["synthetic_reason"] = record.platform_extras.get(
                    "synthetic_reason", "injected"
                )
            lines.append(compact_json(obj))
        elif record.message_type == "thinking":
            summary = (
                [{"type": "summary_text", "text": record.content_text}]
                if record.content_text
                else []
            )
            lines.append(
                compact_json(
                    {
                        "type": "reasoning",
                        "id": record.platform_extras.get("reasoning_id", ""),
                        "summary": summary,
                        "status": record.platform_extras.get("status", "completed"),
                    }
                )
            )
        elif record.message_type == "response":
            lines.append(
                compact_json(
                    {
                        "type": "assistant",
                        "content": record.content_text,
                        "model_id": record.platform_extras.get("model_id", ""),
                    }
                )
            )
        elif record.message_type == "tool_use":
            if record.platform_extras.get("source_entry_type") == "backend_tool_call":
                lines.append(
                    compact_json(
                        {
                            "type": "backend_tool_call",
                            "kind": {
                                "tool_type": record.tool_name,
                                "action": record.tool_input,
                                "id": record.tool_call_id,
                                "status": record.platform_extras.get("status", "completed"),
                            },
                        }
                    )
                )
            else:
                lines.append(
                    compact_json(
                        {
                            "type": "assistant",
                            "content": record.content_text or "",
                            "tool_calls": [
                                {
                                    "id": record.tool_call_id,
                                    "name": record.tool_name,
                                    "arguments": record.tool_input,
                                }
                            ],
                        }
                    )
                )
        elif record.message_type == "tool_result":
            lines.append(
                compact_json(
                    {
                        "type": "tool_result",
                        "tool_call_id": record.tool_call_id,
                        "content": record.content_text,
                    }
                )
            )
    return "\n".join(lines) + ("\n" if lines else "")
