#!/usr/bin/env python3
"""
Messages Library — Business logic for file-based message drops.

Extracted from apps/mcps/messages/server.py to follow the
"thin wrapper around scripts" pattern.

IMPORTANT: This library writes messages to files in ai_comms/. It does NOT
deliver messages to running sessions. No session is notified when a message
arrives. Messages sit on disk until someone explicitly checks.
"""

import os
import random
import string
import sys
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402


# === Configuration ===
COMMS_DIR = AI_ROOT / "ai_comms"
BROADCASTS_DIR = COMMS_DIR / "claude_cli/broadcasts"
DIRECT_DIR = COMMS_DIR / "claude_cli/instant_messaging/active"
RESPONSES_DIR = COMMS_DIR / "claude_cli/tasks/responses"

SERVER_VERSION = "1.2.0"


def ensure_directories():
    """Ensure required directories exist."""
    BROADCASTS_DIR.mkdir(parents=True, exist_ok=True)
    DIRECT_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)


# === Helper Functions ===

def generate_message_id() -> str:
    """Generate unique message ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"msg_{timestamp}_{suffix}"


def create_message(
    from_sender: str,
    to_recipient: str,
    content: str,
    msg_type: str = "direct",
    reply_to: Optional[str] = None
) -> dict:
    """
    Create a message structure.

    Args:
        from_sender: Sender identifier (e.g., desktop_claude, cli_librarian)
        to_recipient: Recipient identifier (all for broadcast, or specific session)
        content: Message body (markdown supported)
        msg_type: Message type (broadcast, direct, response)
        reply_to: Optional parent message ID for threading

    Returns:
        Message dictionary with metadata and content
    """
    msg_id = generate_message_id()
    timestamp = datetime.now().isoformat()

    message = {
        "metadata": {
            "id": msg_id,
            "from": from_sender,
            "to": to_recipient,
            "timestamp": timestamp,
            "type": msg_type,
        },
        "content": content,
    }

    if reply_to:
        message["metadata"]["reply_to"] = reply_to

    return message


def write_message_file(message: dict, directory: Path, filename: Optional[str] = None) -> Path:
    """
    Write message to YAML file.

    Args:
        message: Message dictionary
        directory: Target directory
        filename: Optional custom filename (default: {msg_id}.yml)

    Returns:
        Path to created file
    """
    if filename is None:
        filename = f"{message['metadata']['id']}.yml"

    filepath = directory / filename

    with open(filepath, 'w') as f:
        yaml.dump(message, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return filepath


def read_message_file(filepath: Path) -> Optional[dict]:
    """
    Read message from YAML file.

    Args:
        filepath: Path to message file

    Returns:
        Message dictionary or None if read fails
    """
    result = None
    try:
        with open(filepath, 'r') as f:
            result = yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        pass

    return result


def list_messages_in_dir(directory: Path, limit: int = 20) -> list[dict]:
    """
    List messages in directory, sorted by timestamp (newest first).

    Args:
        directory: Directory to scan
        limit: Maximum number of messages to return

    Returns:
        List of message summaries
    """
    messages = []

    if not directory.exists():
        return messages

    # Collect all .yml files
    yml_files = sorted(directory.glob("*.yml"), key=lambda p: p.stat().st_mtime, reverse=True)

    for filepath in yml_files[:limit]:
        msg = read_message_file(filepath)
        if msg and "metadata" in msg:
            summary = {
                "id": msg["metadata"].get("id", filepath.stem),
                "from": msg["metadata"].get("from", "unknown"),
                "to": msg["metadata"].get("to", "unknown"),
                "timestamp": msg["metadata"].get("timestamp", ""),
                "type": msg["metadata"].get("type", "unknown"),
                "acknowledged": msg.get("acknowledged", False),
                "file": str(filepath),
            }
            # Add content preview (first 100 chars)
            content = msg.get("content", "")
            if isinstance(content, str):
                summary["preview"] = content[:100] + ("..." if len(content) > 100 else "")
            messages.append(summary)

    return messages


def find_message_by_id(msg_id: str, search_dirs: list[Path]) -> Optional[tuple[Path, dict]]:
    """
    Find a message by ID across multiple directories.

    Args:
        msg_id: Message ID to find
        search_dirs: Directories to search

    Returns:
        Tuple of (filepath, message) or None if not found
    """
    for directory in search_dirs:
        if not directory.exists():
            continue

        # Check for exact match
        filepath = directory / f"{msg_id}.yml"
        if filepath.exists():
            msg = read_message_file(filepath)
            if msg:
                return (filepath, msg)

        # Check subdirectories (for threaded messages)
        for subdir in directory.iterdir():
            if subdir.is_dir():
                filepath = subdir / f"{msg_id}.yml"
                if filepath.exists():
                    msg = read_message_file(filepath)
                    if msg:
                        return (filepath, msg)

    return None


# === Core Operations ===

def op_test() -> dict:
    """Test server connectivity and configuration."""
    broadcast_count = sum(1 for _ in BROADCASTS_DIR.glob("*.yml")) if BROADCASTS_DIR.exists() else 0
    direct_count = sum(1 for _ in DIRECT_DIR.glob("*.yml")) if DIRECT_DIR.exists() else 0
    response_count = sum(1 for _ in RESPONSES_DIR.glob("*.yml")) if RESPONSES_DIR.exists() else 0

    return {
        "server": "messages",
        "version": SERVER_VERSION,
        "status": "ok",
        "config": {
            "ai_root": str(AI_ROOT),
            "ai_root_exists": AI_ROOT.exists(),
            "comms_dir": str(COMMS_DIR),
            "comms_dir_exists": COMMS_DIR.exists(),
            "broadcasts_dir": str(BROADCASTS_DIR),
            "broadcasts_dir_exists": BROADCASTS_DIR.exists(),
            "direct_dir": str(DIRECT_DIR),
            "direct_dir_exists": DIRECT_DIR.exists()
        },
        "message_counts": {
            "broadcasts": broadcast_count,
            "direct": direct_count,
            "responses": response_count
        }
    }


def op_broadcast(from_sender: str, content: str, reply_to: str = None) -> dict:
    """Send a broadcast message."""
    message = create_message(
        from_sender=from_sender,
        to_recipient="all",
        content=content,
        msg_type="broadcast",
        reply_to=reply_to
    )

    filepath = write_message_file(message, BROADCASTS_DIR)

    return {
        "success": True,
        "message_id": message["metadata"]["id"],
        "file": str(filepath),
        "message": f"Broadcast sent: {message['metadata']['id']}"
    }


def op_send_direct(from_sender: str, to_recipient: str, content: str, reply_to: str = None) -> dict:
    """Send a direct message to a specific recipient."""
    message = create_message(
        from_sender=from_sender,
        to_recipient=to_recipient,
        content=content,
        msg_type="direct",
        reply_to=reply_to
    )

    target_dir = DIRECT_DIR / to_recipient
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = write_message_file(message, target_dir)

    return {
        "success": True,
        "message_id": message["metadata"]["id"],
        "to": to_recipient,
        "file": str(filepath),
        "message": f"Direct message sent to {to_recipient}: {message['metadata']['id']}"
    }


def op_list_broadcasts(limit: int = 20) -> dict:
    """List recent broadcast messages."""
    messages = list_messages_in_dir(BROADCASTS_DIR, limit)

    return {
        "success": True,
        "count": len(messages),
        "broadcasts": messages
    }


def op_list_direct(recipient: str = None, limit: int = 20) -> dict:
    """List direct messages, optionally filtered by recipient."""
    base_dir = DIRECT_DIR

    if recipient:
        recipient_dir = base_dir / recipient
        messages = list_messages_in_dir(recipient_dir, limit)
    else:
        # List all direct messages across all recipients
        messages = []
        if base_dir.exists():
            # Check if this is a leaf directory (has .yml files) or has subdirs
            yml_files = list(base_dir.glob("*.yml"))
            if yml_files:
                messages = list_messages_in_dir(base_dir, limit)
            else:
                for subdir in base_dir.iterdir():
                    if subdir.is_dir():
                        messages.extend(list_messages_in_dir(subdir, limit))
        # Sort by timestamp and limit
        messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        messages = messages[:limit]

    return {
        "success": True,
        "count": len(messages),
        "recipient_filter": recipient,
        "messages": messages
    }


def op_check_responses(message_id: str) -> dict:
    """Check for responses to a specific message."""
    responses = []
    search_dirs = [BROADCASTS_DIR, DIRECT_DIR, RESPONSES_DIR]

    for directory in search_dirs:
        if not directory.exists():
            continue

        for filepath in directory.rglob("*.yml"):
            msg = read_message_file(filepath)
            if msg and msg.get("metadata", {}).get("reply_to") == message_id:
                responses.append({
                    "id": msg["metadata"].get("id"),
                    "from": msg["metadata"].get("from"),
                    "timestamp": msg["metadata"].get("timestamp"),
                    "preview": str(msg.get("content", ""))[:100],
                    "file": str(filepath)
                })

    # Sort by timestamp
    responses.sort(key=lambda r: r.get("timestamp", ""))

    return {
        "success": True,
        "parent_message_id": message_id,
        "response_count": len(responses),
        "responses": responses
    }


def op_acknowledge(message_id: str, acknowledger: str) -> dict:
    """Mark a message as read/processed."""
    search_dirs = [BROADCASTS_DIR, DIRECT_DIR, RESPONSES_DIR]

    found = find_message_by_id(message_id, search_dirs)

    if not found:
        return {
            "success": False,
            "error": f"Message not found: {message_id}"
        }

    filepath, message = found

    # Add acknowledgment
    if "acknowledgments" not in message:
        message["acknowledgments"] = []

    ack_entry = {
        "by": acknowledger,
        "at": datetime.now().isoformat()
    }
    message["acknowledgments"].append(ack_entry)
    message["acknowledged"] = True

    # Write back
    with open(filepath, 'w') as f:
        yaml.dump(message, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return {
        "success": True,
        "message_id": message_id,
        "acknowledged_by": acknowledger,
        "file": str(filepath),
        "message": f"Message {message_id} acknowledged by {acknowledger}"
    }
