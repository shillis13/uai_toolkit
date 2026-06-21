from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

STANDARDIZED_SCHEMA_NAME = "ai_root.standardized_cli_session_jsonl"
STANDARDIZED_SCHEMA_VERSION = "1.0"

RecordKind = Literal["session", "source_record", "message", "event"]


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class StandardizedSessionHeader:
    session_id: str
    platform: str
    source_format: str
    platform_variant: str = ""
    source_path: str = ""
    start_time: str = ""
    last_updated: str = ""
    kind: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    platform_metadata: dict[str, Any] = field(default_factory=dict)
    roundtrip: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": STANDARDIZED_SCHEMA_NAME,
            "version": STANDARDIZED_SCHEMA_VERSION,
            "record_kind": "session",
            "payload": {
                "session_id": self.session_id,
                "platform": self.platform,
                "source_format": self.source_format,
                "platform_variant": self.platform_variant,
                "source_path": self.source_path,
                "start_time": self.start_time,
                "last_updated": self.last_updated,
                "kind": self.kind,
                "metadata": self.metadata,
                "platform_metadata": self.platform_metadata,
                "roundtrip": self.roundtrip,
                "extensions": self.extensions,
            },
        }

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> "StandardizedSessionHeader":
        payload = envelope.get("payload", {})
        return cls(
            session_id=payload.get("session_id", ""),
            platform=payload.get("platform", ""),
            source_format=payload.get("source_format", "jsonl"),
            platform_variant=payload.get("platform_variant", ""),
            source_path=payload.get("source_path", ""),
            start_time=payload.get("start_time", ""),
            last_updated=payload.get("last_updated", ""),
            kind=payload.get("kind", ""),
            metadata=dict(payload.get("metadata", {}) or {}),
            platform_metadata=dict(payload.get("platform_metadata", {}) or {}),
            roundtrip=dict(payload.get("roundtrip", {}) or {}),
            extensions=dict(payload.get("extensions", {}) or {}),
        )


@dataclass
class StandardizedSourceRecord:
    source_id: str
    sequence: int
    raw_text: str
    raw_obj: Any
    timestamp: str = ""
    platform_type: str = ""
    platform_subtype: str = ""
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": STANDARDIZED_SCHEMA_NAME,
            "version": STANDARDIZED_SCHEMA_VERSION,
            "record_kind": "source_record",
            "payload": {
                "source_id": self.source_id,
                "sequence": self.sequence,
                "raw_text": self.raw_text,
                "raw_obj": self.raw_obj,
                "timestamp": self.timestamp,
                "platform_type": self.platform_type,
                "platform_subtype": self.platform_subtype,
                "extensions": self.extensions,
            },
        }

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> "StandardizedSourceRecord":
        payload = envelope.get("payload", {})
        return cls(
            source_id=payload.get("source_id", ""),
            sequence=payload.get("sequence", 0),
            raw_text=payload.get("raw_text", ""),
            raw_obj=payload.get("raw_obj"),
            timestamp=payload.get("timestamp", ""),
            platform_type=payload.get("platform_type", ""),
            platform_subtype=payload.get("platform_subtype", ""),
            extensions=dict(payload.get("extensions", {}) or {}),
        )


@dataclass
class StandardizedMessageRecord:
    record_id: str
    sequence: int
    timestamp: str
    role: str
    message_type: str
    content_text: str = ""
    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
    visible: bool = True
    source_ids: list[str] = field(default_factory=list)
    platform_extras: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": STANDARDIZED_SCHEMA_NAME,
            "version": STANDARDIZED_SCHEMA_VERSION,
            "record_kind": "message",
            "payload": {
                "record_id": self.record_id,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
                "role": self.role,
                "message_type": self.message_type,
                "content_text": self.content_text,
                "content_blocks": self.content_blocks,
                "tool": {
                    "name": self.tool_name,
                    "input": self.tool_input,
                    "call_id": self.tool_call_id,
                },
                "visible": self.visible,
                "source_ids": self.source_ids,
                "platform_extras": self.platform_extras,
                "extensions": self.extensions,
            },
        }

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> "StandardizedMessageRecord":
        payload = envelope.get("payload", {})
        tool = payload.get("tool", {}) or {}
        return cls(
            record_id=payload.get("record_id", ""),
            sequence=payload.get("sequence", 0),
            timestamp=payload.get("timestamp", ""),
            role=payload.get("role", ""),
            message_type=payload.get("message_type", ""),
            content_text=payload.get("content_text", ""),
            content_blocks=list(payload.get("content_blocks", []) or []),
            tool_name=tool.get("name", ""),
            tool_input=dict(tool.get("input", {}) or {}),
            tool_call_id=tool.get("call_id", ""),
            visible=payload.get("visible", True),
            source_ids=list(payload.get("source_ids", []) or []),
            platform_extras=dict(payload.get("platform_extras", {}) or {}),
            extensions=dict(payload.get("extensions", {}) or {}),
        )


@dataclass
class StandardizedEventRecord:
    record_id: str
    sequence: int
    timestamp: str = ""
    event_type: str = ""
    content_text: str = ""
    source_ids: list[str] = field(default_factory=list)
    platform_extras: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema": STANDARDIZED_SCHEMA_NAME,
            "version": STANDARDIZED_SCHEMA_VERSION,
            "record_kind": "event",
            "payload": {
                "record_id": self.record_id,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
                "event_type": self.event_type,
                "content_text": self.content_text,
                "source_ids": self.source_ids,
                "platform_extras": self.platform_extras,
                "extensions": self.extensions,
            },
        }

    @classmethod
    def from_envelope(cls, envelope: dict[str, Any]) -> "StandardizedEventRecord":
        payload = envelope.get("payload", {})
        return cls(
            record_id=payload.get("record_id", ""),
            sequence=payload.get("sequence", 0),
            timestamp=payload.get("timestamp", ""),
            event_type=payload.get("event_type", ""),
            content_text=payload.get("content_text", ""),
            source_ids=list(payload.get("source_ids", []) or []),
            platform_extras=dict(payload.get("platform_extras", {}) or {}),
            extensions=dict(payload.get("extensions", {}) or {}),
        )


@dataclass
class StandardizedSession:
    header: StandardizedSessionHeader
    source_records: list[StandardizedSourceRecord] = field(default_factory=list)
    message_records: list[StandardizedMessageRecord] = field(default_factory=list)
    event_records: list[StandardizedEventRecord] = field(default_factory=list)

    def all_envelopes(self) -> list[dict[str, Any]]:
        envelopes: list[dict[str, Any]] = [self.header.to_envelope()]
        envelopes.extend(record.to_envelope() for record in self.source_records)
        envelopes.extend(record.to_envelope() for record in self.event_records)
        envelopes.extend(record.to_envelope() for record in self.message_records)
        return envelopes

    def to_jsonl_text(self) -> str:
        lines = [_compact_json(envelope) for envelope in self.all_envelopes()]
        return "\n".join(lines) + ("\n" if lines else "")

    def source_record_map(self) -> dict[str, StandardizedSourceRecord]:
        return {record.source_id: record for record in self.source_records}



def write_standardized_session(session: StandardizedSession, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(session.to_jsonl_text())
    return path



def load_standardized_session(path: str | Path) -> StandardizedSession:
    path = Path(path)
    header: StandardizedSessionHeader | None = None
    source_records: list[StandardizedSourceRecord] = []
    message_records: list[StandardizedMessageRecord] = []
    event_records: list[StandardizedEventRecord] = []

    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        envelope = json.loads(line)
        if envelope.get("schema") != STANDARDIZED_SCHEMA_NAME:
            raise ValueError(f"Unsupported standardized schema in {path}: {envelope.get('schema')!r}")
        record_kind = envelope.get("record_kind")
        if record_kind == "session":
            header = StandardizedSessionHeader.from_envelope(envelope)
        elif record_kind == "source_record":
            source_records.append(StandardizedSourceRecord.from_envelope(envelope))
        elif record_kind == "message":
            message_records.append(StandardizedMessageRecord.from_envelope(envelope))
        elif record_kind == "event":
            event_records.append(StandardizedEventRecord.from_envelope(envelope))
        else:
            raise ValueError(f"Unsupported standardized record kind in {path}: {record_kind!r}")

    if header is None:
        raise ValueError(f"No session header found in standardized file: {path}")

    return StandardizedSession(
        header=header,
        source_records=sorted(source_records, key=lambda record: record.sequence),
        message_records=sorted(message_records, key=lambda record: record.sequence),
        event_records=sorted(event_records, key=lambda record: record.sequence),
    )



def is_standardized_session_file(path: str | Path) -> bool:
    path = Path(path)
    try:
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    return False
                return (
                    envelope.get("schema") == STANDARDIZED_SCHEMA_NAME
                    and envelope.get("record_kind") == "session"
                )
    except (OSError, json.JSONDecodeError):
        return False
    return False
