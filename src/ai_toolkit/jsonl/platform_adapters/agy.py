from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_toolkit.jsonl.standardized_session import (
    StandardizedMessageRecord,
    StandardizedSession,
    StandardizedSessionHeader,
    StandardizedSourceRecord,
)
from ai_toolkit.jsonl.platform_adapters.common import compact_json, normalize_timestamp

PLATFORM = "agy"

# AGY step types that represent tool results (model-side tool execution)
_TOOL_RESULT_TYPES = {
    "GREP_SEARCH", "LIST_DIRECTORY", "VIEW_FILE",
    "RUN_COMMAND", "SEARCH_WEB", "GENERIC",
}

# Known source values for sniffing
_KNOWN_SOURCES = {"USER_EXPLICIT", "SYSTEM", "MODEL"}


def _classify_user_input(content: str, source: str) -> str:
    """Classify a USER_INPUT step into a specific message type.

    AGY doesn't have structural metadata like Claude's isMeta/sourceToolUseID/origin,
    so we use content-based heuristics to distinguish real human input from injected
    content, skill expansions, and agent/subagent messages.

    Returns one of: user, injected, skill, agent_result
    """
    # Non-explicit sources are always injected (e.g., system-generated user messages)
    if source != "USER_EXPLICIT":
        return "injected"

    # Skill loading / expansion markers
    if "<command-name>" in content or "<skill-" in content or "Launching skill:" in content:
        return "skill"

    # Subagent / task notification results
    if "<task-notification>" in content or "<agent-result>" in content:
        return "agent_result"

    # System-reminder / hook injections that arrive as user-role messages
    if content.lstrip().startswith("<system-reminder>"):
        return "injected"

    # Messages from other AIs via send_prompt / comms
    if "[Message]" in content and "sender=" in content and "priority=" in content:
        return "injected"

    # Hook-injected additionalContext (no USER_REQUEST wrapper but has metadata tags)
    if "<ADDITIONAL_METADATA>" in content and "<USER_REQUEST>" not in content:
        return "injected"

    # USER_SETTINGS_CHANGE without any actual user text
    if "<USER_SETTINGS_CHANGE>" in content and "<USER_REQUEST>" not in content:
        return "injected"

    return "user"


def sniff(path: Path, first_obj: Any | None = None) -> bool:
    """Detect Anti-Gravity JSONL format.

    Signature: top-level dict with 'step_index' (int) and
    'source' in {USER_EXPLICIT, SYSTEM, MODEL}.
    """
    if isinstance(first_obj, dict):
        if (
            isinstance(first_obj.get("step_index"), int)
            and first_obj.get("source") in _KNOWN_SOURCES
        ):
            return True
    return False


def _extract_tool_name_from_type(step_type: str) -> str:
    """Map AGY step type to a readable tool name."""
    mapping = {
        "GREP_SEARCH": "grep_search",
        "LIST_DIRECTORY": "list_dir",
        "VIEW_FILE": "view_file",
        "RUN_COMMAND": "run_command",
        "SEARCH_WEB": "search_web",
        "GENERIC": "generic",
    }
    return mapping.get(step_type, step_type.lower())


def from_file(path: str | Path) -> StandardizedSession:
    """Parse an Anti-Gravity JSONL transcript into StandardizedSession."""
    path = Path(path)
    source_records: list[StandardizedSourceRecord] = []
    message_records: list[StandardizedMessageRecord] = []
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

            source_id = f"src-{line_number:06d}"
            step_type = str(entry.get("type", ""))
            source = str(entry.get("source", ""))
            ts = normalize_timestamp(entry.get("created_at"))

            source_records.append(
                StandardizedSourceRecord(
                    source_id=source_id,
                    sequence=line_number,
                    raw_text=raw_text,
                    raw_obj=entry,
                    timestamp=ts,
                    platform_type=step_type,
                    platform_subtype=source,
                )
            )

            if ts:
                if not start_time:
                    start_time = ts
                last_updated = ts

            content = entry.get("content", "") or ""
            status = entry.get("status", "")
            step_index = entry.get("step_index", 0)
            tool_calls = entry.get("tool_calls")

            # --- User input ---
            if step_type == "USER_INPUT":
                if content:
                    classified = _classify_user_input(content, source)
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role="user",
                            message_type=classified,
                            content_text=content,
                            content_blocks=[{"type": "text", "text": content}],
                            source_ids=[source_id],
                            platform_extras={
                                "step_index": step_index,
                                "agy_source": source,
                                "agy_type": step_type,
                                "classified_as": classified,
                            },
                        )
                    )

            # --- System messages ---
            elif source == "SYSTEM":
                if step_type == "SYSTEM_MESSAGE" and content:
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role="system",
                            message_type="system",
                            content_text=content,
                            content_blocks=[{"type": "text", "text": content}],
                            source_ids=[source_id],
                            platform_extras={
                                "step_index": step_index,
                                "agy_type": step_type,
                            },
                        )
                    )
                # CONVERSATION_HISTORY and other system steps are metadata-only

            # --- Model responses ---
            elif source == "MODEL":
                if step_type == "PLANNER_RESPONSE":
                    # Assistant thinking/response text
                    if content:
                        msg_seq += 1
                        message_records.append(
                            StandardizedMessageRecord(
                                record_id=f"msg-{msg_seq:06d}",
                                sequence=msg_seq,
                                timestamp=ts,
                                role="assistant",
                                message_type="response",
                                content_text=content,
                                content_blocks=[{"type": "text", "text": content}],
                                source_ids=[source_id],
                                platform_extras={
                                    "step_index": step_index,
                                    "agy_type": step_type,
                                },
                            )
                        )
                    # Emit tool_use records for each tool_call
                    if tool_calls and isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            tool_name = str(tc.get("name", "unknown"))
                            tool_args = tc.get("args", {}) or {}
                            call_id = f"agy-step-{step_index}-{tool_name}"
                            msg_seq += 1
                            message_records.append(
                                StandardizedMessageRecord(
                                    record_id=f"msg-{msg_seq:06d}",
                                    sequence=msg_seq,
                                    timestamp=ts,
                                    role="assistant",
                                    message_type="tool_use",
                                    tool_name=tool_name,
                                    tool_input=dict(tool_args) if isinstance(tool_args, dict) else {},
                                    tool_call_id=call_id,
                                    source_ids=[source_id],
                                    platform_extras={
                                        "step_index": step_index,
                                        "agy_type": step_type,
                                    },
                                )
                            )

                elif step_type in _TOOL_RESULT_TYPES:
                    # Tool result
                    tool_name = _extract_tool_name_from_type(step_type)
                    call_id = f"agy-step-{step_index}-{tool_name}"
                    msg_seq += 1
                    message_records.append(
                        StandardizedMessageRecord(
                            record_id=f"msg-{msg_seq:06d}",
                            sequence=msg_seq,
                            timestamp=ts,
                            role="tool",
                            message_type="tool_result",
                            content_text=content,
                            content_blocks=[{"type": "text", "text": content}] if content else [],
                            tool_name=tool_name,
                            tool_call_id=call_id,
                            source_ids=[source_id],
                            platform_extras={
                                "step_index": step_index,
                                "agy_type": step_type,
                                "agy_status": status,
                            },
                        )
                    )

    header = StandardizedSessionHeader(
        session_id=path.stem,
        platform=PLATFORM,
        source_format="jsonl",
        platform_variant="anti_gravity_jsonl",
        source_path=str(path),
        start_time=start_time,
        last_updated=last_updated,
        kind="main",
        metadata={"source_line_count": len(source_records)},
        roundtrip={"strategy": "emit_source_records"},
    )
    return StandardizedSession(
        header=header,
        source_records=source_records,
        message_records=message_records,
    )
