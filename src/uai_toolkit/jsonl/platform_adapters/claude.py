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

PLATFORM = "claude"


def sniff(path: Path, first_obj: Any | None = None) -> bool:
    if "/.claude/" in str(path.resolve()):
        return True
    if isinstance(first_obj, dict):
        if first_obj.get("type") in {"user", "assistant", "system", "custom-title", "queue-operation", "file-history-snapshot", "last-prompt", "agent-name", "agent-color"}:
            return True
        if isinstance(first_obj.get("message"), dict):
            role = first_obj["message"].get("role")
            if role in {"user", "assistant"}:
                return True
    return False



def from_file(path: str | Path) -> StandardizedSession:
    path = Path(path)
    source_records: list[StandardizedSourceRecord] = []
    message_records: list[StandardizedMessageRecord] = []
    session_id = ""
    start_time = ""
    last_updated = ""
    kind = "main"
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

            source_id = f"src-{line_number:06d}"
            source_records.append(
                StandardizedSourceRecord(
                    source_id=source_id,
                    sequence=line_number,
                    raw_text=raw_text,
                    raw_obj=entry,
                    timestamp=normalize_timestamp(entry.get("timestamp")),
                    platform_type=str(entry.get("type", "")),
                )
            )

            session_id = session_id or str(entry.get("sessionId") or entry.get("promptId") or "")
            ts = normalize_timestamp(entry.get("timestamp"))
            if ts:
                if not start_time:
                    start_time = ts
                last_updated = ts
            if entry.get("isSidechain"):
                kind = "subagent"

            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue

            raw_content = message.get("content", "")

            def classify_user_type(raw_entry: dict[str, Any]) -> str:
                origin = raw_entry.get("origin")
                if isinstance(origin, dict) and origin.get("kind") == "task-notification":
                    return "agent_result"
                if raw_entry.get("isMeta", False):
                    if raw_entry.get("sourceToolUseID"):
                        return "skill"
                    return "injected"
                return "user"

            if isinstance(raw_content, str):
                if raw_content:
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role=role,
                            message_type=classify_user_type(entry) if role == "user" else "response",
                            content_text=raw_content,
                            content_blocks=[{"type": "text", "text": raw_content}],
                            source_ids=[source_id],
                            platform_extras={
                                "entry_type": entry.get("type"),
                                "entry_uuid": entry.get("uuid"),
                                "is_sidechain": entry.get("isSidechain"),
                            },
                        )
                    )
                continue

            if not isinstance(raw_content, list):
                continue

            text_parts: list[str] = []
            for block_index, block in enumerate(raw_content):
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
                elif block_type == "thinking":
                    thinking_text = block.get("thinking", "")
                    if thinking_text:
                        msg_seq += 1
                        message_records.append(
                            StandardizedMessageRecord(
                                record_id=f"msg-{msg_seq:06d}",
                                sequence=msg_seq,
                                timestamp=ts,
                                role="assistant",
                                message_type="thinking",
                                content_text=thinking_text,
                                content_blocks=[{"type": "thinking", "text": thinking_text}],
                                source_ids=[source_id],
                                platform_extras={"block_index": block_index, "entry_uuid": entry.get("uuid")},
                            )
                        )
                elif block_type == "tool_use":
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role=role,
                            message_type="tool_use",
                            source_ids=[source_id],
                            tool_name=str(block.get("name", "unknown")),
                            tool_input=dict(block.get("input", {}) or {}),
                            tool_call_id=str(block.get("id", "")),
                            platform_extras={"block_index": block_index, "entry_uuid": entry.get("uuid")},
                        )
                    )
                elif block_type == "tool_result":
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        text = "\n".join(
                            sub_block.get("text", "")
                            for sub_block in result_content
                            if isinstance(sub_block, dict) and sub_block.get("type") == "text"
                        )
                    elif isinstance(result_content, str):
                        text = result_content
                    else:
                        text = json.dumps(result_content, ensure_ascii=False) if result_content else ""
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role="user",
                            message_type="tool_result",
                            content_text=text,
                            content_blocks=[{"type": "text", "text": text}] if text else [],
                            source_ids=[source_id],
                            tool_call_id=str(block.get("tool_use_id", "")),
                            platform_extras={"block_index": block_index, "entry_uuid": entry.get("uuid")},
                        )
                    )

            if text_parts:
                text = "\n".join(text_parts)
                msg_seq += 1
                message_records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=ts,
                        role=role,
                        message_type=classify_user_type(entry) if role == "user" else "response",
                        content_text=text,
                        content_blocks=[{"type": "text", "text": text}],
                        source_ids=[source_id],
                        platform_extras={
                            "entry_type": entry.get("type"),
                            "entry_uuid": entry.get("uuid"),
                            "is_sidechain": entry.get("isSidechain"),
                        },
                    )
                )

    header = StandardizedSessionHeader(
        session_id=session_id or path.stem,
        platform=PLATFORM,
        source_format="jsonl",
        platform_variant="claude_cli_jsonl",
        source_path=str(path),
        start_time=start_time,
        last_updated=last_updated,
        kind=kind,
        metadata={"source_line_count": len(source_records)},
        roundtrip={"strategy": "emit_source_records"},
    )
    return StandardizedSession(header=header, source_records=source_records, message_records=message_records)



def to_platform_text(session: StandardizedSession) -> str:
    if session.source_records:
        ordered = [record.raw_text for record in sorted(session.source_records, key=lambda item: item.sequence)]
        return "\n".join(ordered) + ("\n" if ordered else "")

    lines: list[str] = []
    previous_uuid = None
    for record in sorted(session.message_records, key=lambda item: item.sequence):
        entry: dict[str, Any] = {
            "parentUuid": previous_uuid,
            "isSidechain": session.header.kind == "subagent",
            "type": "assistant" if record.role == "assistant" else "user",
            "message": {
                "role": record.role if record.role in {"user", "assistant"} else "assistant",
                "content": [],
            },
            "timestamp": record.timestamp,
            "sessionId": session.header.session_id,
        }
        if record.message_type in {"user", "response", "skill", "agent_result", "injected"}:
            entry["message"]["content"] = record.content_text
        elif record.message_type == "thinking":
            entry["message"]["content"] = [{"type": "thinking", "thinking": record.content_text}]
            entry["type"] = "assistant"
        elif record.message_type == "tool_use":
            entry["message"]["content"] = [{
                "type": "tool_use",
                "name": record.tool_name,
                "id": record.tool_call_id,
                "input": record.tool_input,
            }]
        elif record.message_type == "tool_result":
            entry["message"]["role"] = "user"
            entry["type"] = "user"
            entry["message"]["content"] = [{
                "type": "tool_result",
                "tool_use_id": record.tool_call_id,
                "content": record.content_text,
            }]
        else:
            entry["message"]["content"] = record.content_text
        previous_uuid = record.platform_extras.get("entry_uuid") or previous_uuid
        lines.append(compact_json(entry))
    return "\n".join(lines) + ("\n" if lines else "")
