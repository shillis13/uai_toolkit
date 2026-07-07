"""
Stop hook helpers — common patterns for Stop event handlers.

Stop hooks receive these fields in stdin JSON (beyond common fields):
  - stop_hook_active: bool — true if this is a retry from a previous Stop block
  - last_assistant_message: string — the AI's response text

See: https://code.claude.com/docs/en/hooks#stop-input
"""

import glob
import json
from pathlib import Path


def is_retry(hook_input):
    """Check if this is a retry turn (stop_hook_active=true). Handlers should skip."""
    return hook_input.get("stop_hook_active", False)


def get_response_text(hook_input):
    """Get the last assistant response text from Stop hook input.

    Uses last_assistant_message field provided by Claude Code.
    Falls back to JSONL transcript if not present (older versions).
    """
    # Primary: Stop hook provides this field
    text = hook_input.get("last_assistant_message", "")
    if text:
        return text

    # Fallback: read from JSONL transcript
    # Use transcript_path from stdin if available (works across Claude + Codex)
    transcript_path = hook_input.get("transcript_path", "")
    if transcript_path:
        from pathlib import Path as _P
        tp = _P(transcript_path)
        if tp.exists():
            return _extract_last_assistant_text(tp)

    # Last resort: search by session_id (Claude-specific path)
    session_id = hook_input.get("session_id", "")
    if not session_id:
        return ""

    jsonl_path = _find_jsonl(session_id)
    if not jsonl_path:
        return ""

    return _extract_last_assistant_text(jsonl_path)


def get_last_user_message(hook_input, max_chars=2000):
    """Get the last user message from the JSONL transcript.

    Stop hooks don't receive the user message in stdin — must read from JSONL.
    """
    transcript_path = hook_input.get("transcript_path", "")
    if transcript_path:
        from pathlib import Path as _P
        tp = _P(transcript_path)
        if tp.exists():
            return _extract_last_message_by_role(tp, "user", max_chars)

    session_id = hook_input.get("session_id", "")
    if not session_id:
        return ""
    jsonl_path = _find_jsonl(session_id)
    if not jsonl_path:
        return ""
    return _extract_last_message_by_role(jsonl_path, "user", max_chars)


def get_response_tail(hook_input, chars=400):
    """Get the last N characters of the response text."""
    text = get_response_text(hook_input)
    if not text:
        return ""
    return text[-chars:]


def should_evaluate(hook_input, min_length=200):
    """Pre-filter: skip retries and short responses.

    Returns (should_proceed: bool, skip_reason: str).
    """
    if is_retry(hook_input):
        return False, "stop_hook_active (retry turn)"

    text = get_response_text(hook_input)
    if not text:
        return False, "no response text"

    if len(text) < min_length:
        return False, f"response too short ({len(text)} chars)"

    return True, ""


# ─── JSONL fallback (for older Claude Code versions) ─────────────────────

def _find_jsonl(session_id):
    """Find the JSONL transcript for a Claude Code session by CLI UUID."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None
    pattern = str(claude_dir / "*" / f"{session_id}.jsonl")
    matches = glob.glob(pattern)
    if matches:
        return Path(matches[0])
    pattern = str(claude_dir / "*" / f"{session_id[:8]}*.jsonl")
    matches = glob.glob(pattern)
    if matches:
        return Path(sorted(matches, key=lambda p: Path(p).stat().st_mtime, reverse=True)[0])
    return None


def _extract_last_assistant_text(jsonl_path, max_bytes=200_000):
    """Extract the last assistant text message from the JSONL."""
    try:
        with open(jsonl_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            content = f.read().decode('utf-8', errors='replace')
    except (OSError, IOError):
        return ""

    lines = content.strip().split('\n')
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue

        blocks = msg.get("content", [])
        if isinstance(blocks, str):
            return blocks
        if isinstance(blocks, list):
            texts = [b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"]
            combined = "\n".join(texts).strip()
            if combined:
                return combined

    return ""


def _extract_last_message_by_role(jsonl_path, role, max_chars=2000, max_bytes=200_000):
    """Extract the last message text by role (user or assistant) from JSONL."""
    try:
        with open(jsonl_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            content = f.read().decode('utf-8', errors='replace')
    except (OSError, IOError):
        return ""

    lines = content.strip().split('\n')
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != role:
            continue
        msg = entry.get("message", {})
        if msg.get("role") != role:
            continue

        blocks = msg.get("content", [])
        if isinstance(blocks, str):
            return blocks[:max_chars]
        if isinstance(blocks, list):
            texts = [b.get("text", "") for b in blocks
                     if isinstance(b, dict) and b.get("type") == "text"]
            combined = "\n".join(texts).strip()
            if combined:
                return combined[:max_chars]

    return ""
