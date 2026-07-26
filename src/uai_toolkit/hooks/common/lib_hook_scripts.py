"""
Shared library for hook scripts.

Provides queue loading, filtering, delivery tracking, and composition
utilities used by prompt queue hooks (UserPromptSubmit, Stop, etc.).
"""

import os
import shutil
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
PROMPTS_INBOX = AI_ROOT / "ai_comms" / "prompts_inbox"
DELIVERED_DIR = AI_ROOT / "ai_general" / "data" / "hooks" / "data" / "prompt_queue" / "delivered"
# send_prompt was ported .sh → .py; the old .sh no longer exists. Pointing at the
# deleted .sh silently disabled post-response queued-prompt delivery (todo_0602).
SEND_PROMPT = AI_ROOT / "ai_general" / "scripts" / "prompting" / "send_prompt.py"


def is_locked(session_id: str) -> bool:
    """Check if a session is conversation-locked (global or per-session).

    Returns True if either lock file exists:
      - ai_general/data/locks/conversations/global.lock
      - ai_general/data/locks/conversations/{session_id}.lock
    """
    locks_dir = AI_ROOT / "ai_general" / "data" / "locks" / "conversations"
    if (locks_dir / "global.lock").exists():
        return True
    if (locks_dir / "{}.lock".format(session_id)).exists():
        return True
    return False


def drop_blocked_sources(tracking_id: str, entries: List[Dict]) -> List[Dict]:
    """Remove queued entries this session is prompt-blocked from receiving (their
    `source` is not exempt), so they stay queued until the block lifts. Exempt
    sources (user/self/allow_from) and the unblocked case pass through. This is
    the single drain-side gate that holds queued prompts regardless of which path
    enqueued them. Fail-open: any error returns the entries unfiltered."""
    try:
        import sys
        msgs = str(AI_ROOT / "ai_general" / "scripts" / "messages")
        if msgs not in sys.path:
            sys.path.insert(0, msgs)
        from uai_toolkit.messages import prompt_blocks as pb
    except Exception:
        return entries
    kept = []
    for e in entries:
        src = e.get("source") or "user"
        if src != tracking_id:        # self-queued entries are always exempt
            try:
                if pb.is_blocked(tracking_id, sender=src).get("blocked"):
                    continue  # held while blocked
            except Exception:
                pass
        kept.append(e)
    return kept


def get_tracking_id() -> Optional[str]:
    """Get the current session's tracking ID from environment."""
    return os.environ.get("AI_TRACKING_ID")


def get_queue_dir(tracking_id: str) -> Path:
    """Get the prompt queue directory for a session."""
    return PROMPTS_INBOX / tracking_id


def load_queue_entries(queue_dir: Path) -> List[Dict]:
    """Load all YAML queue entries from a directory, sorted by filename."""
    entries = []
    if not queue_dir.exists():
        return entries

    for f in sorted(queue_dir.glob("queue_*.yml")):
        try:
            with open(f) as fh:
                entry = yaml.safe_load(fh)
            if entry:
                entry["_file"] = str(f)
                entries.append(entry)
        except (yaml.YAMLError, OSError):
            continue

    return entries


def filter_ready(entries: List[Dict], delivery_types: Optional[List[str]] = None) -> List[Dict]:
    """Filter entries that are ready for delivery and optionally match delivery types.

    Args:
        entries: List of queue entry dicts
        delivery_types: If set, only include entries with matching delivery field.
                       If None, include all ready entries regardless of delivery type.
    """
    now = datetime.now()
    ready = []

    for entry in entries:
        if not entry.get("ready_for_delivery", False):
            continue

        if delivery_types and entry.get("delivery", "") not in delivery_types:
            continue

        # Check expiration
        expires_at = entry.get("expires_at")
        if expires_at:
            try:
                exp = datetime.fromisoformat(str(expires_at))
                if now > exp:
                    continue
            except (ValueError, TypeError):
                pass

        ready.append(entry)

    return ready


# Consolidation defaults — configurable via environment
DEFAULT_MAX_ENTRIES = int(os.environ.get("HOOK_MAX_ENTRIES", "10"))
DEFAULT_MAX_CHARS = int(os.environ.get("HOOK_MAX_CHARS", "8000"))


def compose_context(
    entries: List[Dict],
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple:
    """Compose queued entries into a formatted string with sender identification.

    Entries are sorted by urgency (interrupt first) then by queued_at timestamp.
    Returns (composed_text, included_entries, overflow_entries).
    Overflow entries stay in queue for next delivery opportunity.
    """
    def sort_key(e: Dict):
        urgency_order = 0 if e.get("urgency") == "interrupt" else 1
        return (urgency_order, e.get("queued_at", ""))

    entries.sort(key=sort_key)

    parts = []
    included = []
    overflow = []
    total_chars = 0

    for entry in entries:
        source = entry.get("source", "unknown")
        urgency = entry.get("urgency", "prompt")
        content = entry.get("content", "")
        urgency_tag = f" [{urgency}]" if urgency == "interrupt" else ""

        block = (
            f"--- Queued Message from {source}{urgency_tag} ---\n"
            f"{content}\n"
            f"--- End Message ---"
        )

        if len(included) >= max_entries or (total_chars + len(block)) > max_chars:
            overflow.append(entry)
            continue

        parts.append(block)
        included.append(entry)
        total_chars += len(block)

    return "\n\n".join(parts), included, overflow


def mark_delivered(entry: Dict) -> None:
    """Move a delivered entry to the delivered directory."""
    src = Path(entry["_file"])
    if not src.exists():
        return

    # Ensure delivered directory exists (parents=True acceptable for hook infra)
    if not DELIVERED_DIR.exists():
        DELIVERED_DIR.mkdir(parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = DELIVERED_DIR / f"{src.stem}_delivered_{timestamp}.yml"

    try:
        shutil.move(str(src), str(dest))
    except OSError as e:
        # On move failure, do NOT delete the source — leave it in queue
        import logging
        logging.getLogger(__name__).warning(
            "Failed to move %s to delivered: %s", src, e
        )


def mark_all_delivered(entries: List[Dict]) -> None:
    """Move all entries to delivered directory."""
    for entry in entries:
        mark_delivered(entry)
