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
from uai_toolkit.jsonl.platform_adapters.common import compact_json, normalize_timestamp

PLATFORM = "codex"


def sniff(path: Path, first_obj: Any | None = None) -> bool:
    if "/.codex/" in str(path.resolve()) or path.name.startswith("rollout-"):
        return True
    if isinstance(first_obj, dict):
        record_type = first_obj.get("type")
        if record_type in {"session_meta", "response_item", "event_msg", "turn_context"}:
            return True
    return False



def from_file(path: str | Path) -> StandardizedSession:
    path = Path(path)
    source_records: list[StandardizedSourceRecord] = []
    message_records: list[StandardizedMessageRecord] = []
    session_payload: dict[str, Any] = {}
    start_time = ""
    last_updated = ""
    msg_seq = 0

    with path.open() as handle:
        for line_number, line in enumerate(handle, 1):
            raw_text = line.rstrip("\n")
            if not raw_text.strip():
                continue
            try:
                entry = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            payload = entry.get("payload", {}) or {}
            source_id = f"src-{line_number:06d}"
            source_records.append(
                StandardizedSourceRecord(
                    source_id=source_id,
                    sequence=line_number,
                    raw_text=raw_text,
                    raw_obj=entry,
                    timestamp=normalize_timestamp(entry.get("timestamp")),
                    platform_type=str(entry_type),
                    platform_subtype=str(payload.get("type", "")),
                )
            )

            ts = normalize_timestamp(entry.get("timestamp"))
            if ts:
                if not start_time:
                    start_time = ts
                last_updated = ts

            if entry_type == "session_meta":
                session_payload = dict(payload)
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="system",
                        message_type="meta",
                        content_text=f"Session {payload.get('id', '')} ({payload.get('originator', 'codex')})",
                        content_blocks=[{"type": "text", "text": f"Session {payload.get('id', '')} ({payload.get('originator', 'codex')})"}],
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type},
                    )
                )
                continue

            if entry_type != "response_item":
                continue

            payload_type = payload.get("type")
            if payload_type == "message":
                role = payload.get("role", "")
                normalized_role = "system" if role == "developer" else role
                if normalized_role not in {"user", "assistant", "system"}:
                    continue
                raw_content = payload.get("content", [])
                if isinstance(raw_content, str):
                    text = raw_content
                elif isinstance(raw_content, list):
                    text = "\n".join(
                        block.get("text", "")
                        for block in raw_content
                        if isinstance(block, dict) and block.get("type") in {"input_text", "output_text", "text"}
                    )
                else:
                    text = ""
                if not text:
                    continue
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role=normalized_role,
                        message_type="system" if normalized_role == "system" else ("user" if normalized_role == "user" else "response"),
                        content_text=text,
                        content_blocks=[{"type": "text", "text": text}],
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type, "payload_role": role},
                    )
                )
            elif payload_type == "function_call":
                arguments = payload.get("arguments", "{}")
                try:
                    tool_input = json.loads(arguments)
                except (TypeError, json.JSONDecodeError):
                    tool_input = {"raw": arguments}
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="assistant",
                        message_type="tool_use",
                        tool_name=str(payload.get("name", "unknown")),
                        tool_input=tool_input,
                        tool_call_id=str(payload.get("call_id", "")),
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type, "payload_type": payload_type},
                    )
                )
            elif payload_type == "function_call_output":
                msg_seq += 1
                output_text = payload.get("output", "")
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role="assistant",
                        message_type="tool_result",
                        content_text=output_text,
                        content_blocks=[{"type": "text", "text": output_text}] if output_text else [],
                        tool_call_id=str(payload.get("call_id", "")),
                        source_ids=[source_id],
                        platform_extras={"source_entry_type": entry_type, "payload_type": payload_type},
                    )
                )

    header = StandardizedSessionHeader(
        session_id=str(session_payload.get("id") or path.stem[-36:]),
        platform=PLATFORM,
        source_format="jsonl",
        platform_variant="codex_rollout_jsonl",
        source_path=str(path),
        start_time=start_time,
        last_updated=last_updated,
        kind="main",
        metadata={"source_line_count": len(source_records)},
        platform_metadata=session_payload,
        roundtrip={"strategy": "emit_source_records"},
    )
    return StandardizedSession(header=header, source_records=source_records, message_records=message_records)



def to_platform_text(session: StandardizedSession) -> str:
    if session.source_records:
        ordered = [record.raw_text for record in sorted(session.source_records, key=lambda item: item.sequence)]
        return "\n".join(ordered) + ("\n" if ordered else "")

    lines: list[str] = []
    session_meta = dict(session.header.platform_metadata)
    session_meta.setdefault("id", session.header.session_id)
    lines.append(
        compact_json({
            "timestamp": session.header.start_time,
            "type": "session_meta",
            "payload": session_meta,
        })
    )

    for record in sorted(session.message_records, key=lambda item: item.sequence):
        if record.message_type == "meta":
            continue
        if record.message_type in {"user", "response", "system"}:
            role = record.role
            if role == "system":
                role = "developer"
            payload = {
                "type": "message",
                "role": role,
                "content": [{
                    "type": "input_text" if role in {"user", "developer"} else "output_text",
                    "text": record.content_text,
                }],
            }
        elif record.message_type == "tool_use":
            payload = {
                "type": "function_call",
                "name": record.tool_name,
                "arguments": compact_json(record.tool_input),
                "call_id": record.tool_call_id,
            }
        elif record.message_type == "tool_result":
            payload = {
                "type": "function_call_output",
                "call_id": record.tool_call_id,
                "output": record.content_text,
            }
        else:
            continue
        lines.append(compact_json({
            "timestamp": record.timestamp,
            "type": "response_item",
            "payload": payload,
        }))
    return "\n".join(lines) + ("\n" if lines else "")
