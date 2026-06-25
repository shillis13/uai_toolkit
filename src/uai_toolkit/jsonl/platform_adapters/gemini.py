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

PLATFORM = "gemini"


def sniff(path: Path, first_obj: Any | None = None) -> bool:
    if "/.gemini/" in str(path.resolve()):
        return True
    if isinstance(first_obj, list):
        return True
    if isinstance(first_obj, dict):
        if {"sessionId", "projectHash"} <= set(first_obj.keys()):
            return True
        if first_obj.get("$set"):
            return True
    return False



def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        return "\n".join(texts)
    return ""



def _message_record_from_gemini_message(message: dict[str, Any], msg_seq: int, source_ids: list[str]) -> list[StandardizedMessageRecord]:
    records: list[StandardizedMessageRecord] = []
    msg_type = message.get("type")
    ts = normalize_timestamp(message.get("timestamp"))
    message_id = str(message.get("id", ""))

    if msg_type == "user":
        text = _extract_text_from_content(message.get("content", ""))
        if not text and isinstance(message.get("message"), str):
            text = str(message.get("message"))
        if text:
            records.append(
                StandardizedMessageRecord(
                    record_id=f"msg-{msg_seq:06d}",
                    sequence=msg_seq,
                    timestamp=ts,
                    role="user",
                    message_type="user",
                    content_text=text,
                    content_blocks=[{"type": "text", "text": text}],
                    source_ids=source_ids,
                    platform_extras={"message_id": message_id, "message_type": msg_type},
                )
            )
        return records

    if msg_type == "gemini":
        text = _extract_text_from_content(message.get("content", ""))
        if text:
            records.append(
                StandardizedMessageRecord(
                    record_id=f"msg-{msg_seq:06d}",
                    sequence=msg_seq,
                    timestamp=ts,
                    role="assistant",
                    message_type="response",
                    content_text=text,
                    content_blocks=[{"type": "text", "text": text}],
                    source_ids=source_ids,
                    platform_extras={"message_id": message_id, "message_type": msg_type, "model": message.get("model")},
                )
            )
            msg_seq += 1

        for thought in message.get("thoughts", []) or []:
            thought_text = ""
            if isinstance(thought, dict):
                subject = thought.get("subject", "")
                description = thought.get("description", "")
                thought_text = f"{subject}: {description}".strip(": ")
            if thought_text:
                records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=normalize_timestamp(thought.get("timestamp")) or ts,
                        role="assistant",
                        message_type="thinking",
                        content_text=thought_text,
                        content_blocks=[{"type": "thinking", "text": thought_text}],
                        source_ids=source_ids,
                        platform_extras={"message_id": message_id, "message_type": msg_type},
                    )
                )
                msg_seq += 1

        for tool_call in message.get("toolCalls", []) or []:
            tool_timestamp = normalize_timestamp(tool_call.get("timestamp")) or ts
            tool_call_id = str(tool_call.get("id", ""))
            records.append(
                StandardizedMessageRecord(
                    record_id=f"msg-{msg_seq:06d}",
                    sequence=msg_seq,
                    timestamp=tool_timestamp,
                    role="assistant",
                    message_type="tool_use",
                    tool_name=str(tool_call.get("name", "unknown")),
                    tool_input=dict(tool_call.get("args", {}) or {}),
                    tool_call_id=tool_call_id,
                    source_ids=source_ids,
                    platform_extras={"message_id": message_id, "message_type": msg_type},
                )
            )
            msg_seq += 1
            result_display = tool_call.get("resultDisplay")
            if result_display:
                if isinstance(result_display, str):
                    result_text = result_display
                else:
                    result_text = json.dumps(result_display, ensure_ascii=False)
                records.append(
                    StandardizedMessageRecord(
                        record_id=f"msg-{msg_seq:06d}",
                        sequence=msg_seq,
                        timestamp=tool_timestamp,
                        role="assistant",
                        message_type="tool_result",
                        content_text=result_text,
                        content_blocks=[{"type": "text", "text": result_text}],
                        tool_call_id=tool_call_id,
                        source_ids=source_ids,
                        platform_extras={"message_id": message_id, "message_type": msg_type},
                    )
                )
                msg_seq += 1
        return records

    if msg_type in {"info", "error", "warning", "meta"}:
        records.append(
            StandardizedMessageRecord(
                record_id=f"msg-{msg_seq:06d}",
                sequence=msg_seq,
                timestamp=ts,
                role="system",
                message_type="system" if msg_type == "error" else "meta",
                content_text=str(message.get("content", "")),
                content_blocks=[{"type": "text", "text": str(message.get('content', ''))}] if message.get("content") else [],
                source_ids=source_ids,
                platform_extras={"message_id": message_id, "message_type": msg_type},
            )
        )
    return records



def _from_snapshot_json(path: Path, data: Any) -> StandardizedSession:
    source_text = path.read_text()
    session_id = path.stem
    project_hash = ""
    start_time = ""
    last_updated = ""
    kind = "main"
    messages: list[dict[str, Any]] = []
    platform_variant = "gemini_json_snapshot"

    if isinstance(data, dict):
        session_id = str(data.get("sessionId") or session_id)
        project_hash = str(data.get("projectHash") or "")
        start_time = normalize_timestamp(data.get("startTime"))
        last_updated = normalize_timestamp(data.get("lastUpdated"))
        kind = str(data.get("kind") or kind)
        messages = list(data.get("messages", []) or [])
    elif isinstance(data, list):
        platform_variant = "gemini_json_legacy_list"
        messages = [message for message in data if isinstance(message, dict)]
        if messages:
            session_id = str(messages[0].get("sessionId") or session_id)
            start_time = normalize_timestamp(messages[0].get("timestamp"))
            last_updated = normalize_timestamp(messages[-1].get("timestamp"))

    source_record = StandardizedSourceRecord(
        source_id="src-000001",
        sequence=1,
        raw_text=source_text,
        raw_obj=data,
        timestamp=start_time,
        platform_type="conversation_record",
    )

    message_records: list[StandardizedMessageRecord] = []
    next_sequence = 1
    for message in messages:
        created = _message_record_from_gemini_message(message, next_sequence, [source_record.source_id])
        message_records.extend(created)
        next_sequence += len(created)

    header = StandardizedSessionHeader(
        session_id=session_id,
        platform=PLATFORM,
        source_format="json",
        platform_variant=platform_variant,
        source_path=str(path),
        start_time=start_time,
        last_updated=last_updated,
        kind=kind,
        metadata={"source_record_count": 1},
        platform_metadata={"projectHash": project_hash},
        roundtrip={"strategy": "emit_source_text", "json_style": "pretty-2"},
    )
    return StandardizedSession(header=header, source_records=[source_record], message_records=message_records)



def _load_jsonl_conversation(lines: list[dict[str, Any]]) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any], list[str]]]]:
    metadata: dict[str, Any] = {}
    message_order: list[str] = []
    message_map: dict[str, dict[str, Any]] = {}
    message_sources: dict[str, list[str]] = {}

    for index, record in enumerate(lines, 1):
        source_id = f"src-{index:06d}"
        if not isinstance(record, dict):
            continue
        if "$rewindTo" in record:
            rewind_id = record.get("$rewindTo")
            if rewind_id in message_order:
                rewind_index = message_order.index(rewind_id)
                removed = message_order[rewind_index:]
                message_order = message_order[:rewind_index]
                for message_id in removed:
                    message_map.pop(message_id, None)
                    message_sources.pop(message_id, None)
            else:
                message_order = []
                message_map.clear()
                message_sources.clear()
            continue
        if "$set" in record and isinstance(record.get("$set"), dict):
            metadata.update(record["$set"])
            continue
        if "sessionId" in record and "projectHash" in record and "id" not in record:
            metadata.update(record)
            continue
        record_id = record.get("id")
        if isinstance(record_id, str):
            if record_id not in message_map:
                message_order.append(record_id)
                message_sources[record_id] = [source_id]
            else:
                message_sources[record_id].append(source_id)
            message_map[record_id] = record

    ordered_messages = [(message_id, message_map[message_id], message_sources.get(message_id, [])) for message_id in message_order if message_id in message_map]
    return metadata, ordered_messages



def _from_jsonl(path: Path) -> StandardizedSession:
    raw_lines = [line.rstrip("\n") for line in path.read_text().splitlines() if line.strip()]
    parsed_lines: list[dict[str, Any]] = []
    source_records: list[StandardizedSourceRecord] = []
    for index, raw_text in enumerate(raw_lines, 1):
        try:
            record = json.loads(raw_text)
        except json.JSONDecodeError:
            continue
        parsed_lines.append(record)
        source_records.append(
            StandardizedSourceRecord(
                source_id=f"src-{index:06d}",
                sequence=index,
                raw_text=raw_text,
                raw_obj=record,
                timestamp=normalize_timestamp(record.get("timestamp")) if isinstance(record, dict) else "",
                platform_type=str(record.get("type", "")) if isinstance(record, dict) else "",
                platform_subtype="$set" if isinstance(record, dict) and "$set" in record else ("$rewindTo" if isinstance(record, dict) and "$rewindTo" in record else ""),
            )
        )

    metadata, ordered_messages = _load_jsonl_conversation(parsed_lines)
    header = StandardizedSessionHeader(
        session_id=str(metadata.get("sessionId") or path.stem[-8:]),
        platform=PLATFORM,
        source_format="jsonl",
        platform_variant="gemini_jsonl_event_log",
        source_path=str(path),
        start_time=normalize_timestamp(metadata.get("startTime")),
        last_updated=normalize_timestamp(metadata.get("lastUpdated")),
        kind=str(metadata.get("kind") or "main"),
        metadata={"source_record_count": len(source_records)},
        platform_metadata={key: value for key, value in metadata.items() if key not in {"sessionId", "startTime", "lastUpdated", "kind"}},
        roundtrip={"strategy": "emit_source_records"},
    )

    message_records: list[StandardizedMessageRecord] = []
    next_sequence = 1
    for _message_id, message, source_ids in ordered_messages:
        created = _message_record_from_gemini_message(message, next_sequence, source_ids)
        message_records.extend(created)
        next_sequence += len(created)

    return StandardizedSession(header=header, source_records=source_records, message_records=message_records)



def from_file(path: str | Path) -> StandardizedSession:
    path = Path(path)
    if path.suffix == ".jsonl":
        return _from_jsonl(path)

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _from_snapshot_json(path, [])
    return _from_snapshot_json(path, data)



def to_platform_text(session: StandardizedSession) -> str:
    if session.header.source_format == "json":
        if session.source_records and session.source_records[0].raw_text:
            return session.source_records[0].raw_text

        payload: dict[str, Any] = {
            "sessionId": session.header.session_id,
            "projectHash": session.header.platform_metadata.get("projectHash", ""),
            "startTime": session.header.start_time,
            "lastUpdated": session.header.last_updated,
            "messages": [],
            "kind": session.header.kind or "main",
        }
        for record in sorted(session.message_records, key=lambda item: item.sequence):
            if record.message_type == "user":
                payload["messages"].append({
                    "id": record.platform_extras.get("message_id") or record.record_id,
                    "timestamp": record.timestamp,
                    "type": "user",
                    "content": [{"text": record.content_text}],
                })
            elif record.message_type == "response":
                payload["messages"].append({
                    "id": record.platform_extras.get("message_id") or record.record_id,
                    "timestamp": record.timestamp,
                    "type": "gemini",
                    "content": record.content_text,
                    "thoughts": [],
                    "tokens": None,
                    "model": record.platform_extras.get("model"),
                })
            elif record.message_type in {"system", "meta"}:
                payload["messages"].append({
                    "id": record.platform_extras.get("message_id") or record.record_id,
                    "timestamp": record.timestamp,
                    "type": "info" if record.message_type == "meta" else "error",
                    "content": record.content_text,
                })
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if session.source_records:
        ordered = [record.raw_text for record in sorted(session.source_records, key=lambda item: item.sequence)]
        return "\n".join(ordered) + ("\n" if ordered else "")

    lines: list[str] = []
    header = {
        "sessionId": session.header.session_id,
        "projectHash": session.header.platform_metadata.get("projectHash", ""),
        "startTime": session.header.start_time,
        "lastUpdated": session.header.last_updated,
        "kind": session.header.kind or "main",
    }
    lines.append(compact_json(header))
    for record in sorted(session.message_records, key=lambda item: item.sequence):
        if record.message_type == "user":
            lines.append(compact_json({
                "id": record.platform_extras.get("message_id") or record.record_id,
                "timestamp": record.timestamp,
                "type": "user",
                "content": [{"text": record.content_text}],
            }))
            lines.append(compact_json({"$set": {"lastUpdated": record.timestamp}}))
        elif record.message_type == "response":
            lines.append(compact_json({
                "id": record.platform_extras.get("message_id") or record.record_id,
                "timestamp": record.timestamp,
                "type": "gemini",
                "content": record.content_text,
                "thoughts": [],
                "tokens": None,
                "model": record.platform_extras.get("model"),
            }))
            lines.append(compact_json({"$set": {"lastUpdated": record.timestamp}}))
        elif record.message_type in {"system", "meta"}:
            lines.append(compact_json({
                "id": record.platform_extras.get("message_id") or record.record_id,
                "timestamp": record.timestamp,
                "type": "info" if record.message_type == "meta" else "error",
                "content": record.content_text,
            }))
            lines.append(compact_json({"$set": {"lastUpdated": record.timestamp}}))
    return "\n".join(lines) + ("\n" if lines else "")
