#!/usr/bin/env python3
"""
messaging_mgr.py -- Unified CLI + interactive REPL for file-based AI messaging.

Replaces messaging.py (business logic) and messaging_repl.py (REPL).
All business logic functions remain importable. CLI subcommands emit JSON.
Running with no args (or just --as) enters the interactive REPL.

Schemas documented in SCHEMA.md alongside this file.

Usage (CLI):
    messaging_mgr.py send --from alice --to bob --content "Hello"
    messaging_mgr.py broadcast --from alice --content "Attention all"
    messaging_mgr.py list --dir inbox --recipient bob
    messaging_mgr.py acknowledge --id msg_20260425_120000_abc12345 --by bob
    messaging_mgr.py check-responses --id msg_20260425_120000_abc12345
    messaging_mgr.py read --id msg_20260425_120000_abc12345
    messaging_mgr.py reply --id msg_20260425_120000_abc12345 --from bob --content "Got it"
    messaging_mgr.py reply-all --id msg_20260425_120000_abc12345 --from bob --content "Got it"
    messaging_mgr.py check --session SESSION_ID
    messaging_mgr.py archive --id msg_20260425_120000_abc12345
    messaging_mgr.py queue-prompt --to SESSION_ID --content "Do the thing" --urgency prompt
    messaging_mgr.py post-standing --scope global --from admin --content "System maintenance at 2am"
    messaging_mgr.py query-standing --scopes global,platform --platform claude_cli
    messaging_mgr.py cancel-standing --id standing_20260425_120000_abc12345
    messaging_mgr.py send --from alice --to bob --content "Need answer" --response-required
    messaging_mgr.py list-pending --session SESSION_ID
    messaging_mgr.py check-owed --session SESSION_ID

Usage (REPL):
    messaging_mgr.py                        # REPL with identity from $AI_TRACKING_ID
    messaging_mgr.py --as TRACKING_ID       # REPL as specific identity
"""

import argparse
import json
import logging
import os
import readline  # noqa: F401 -- enables arrow keys and history in input()
import shlex
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS  # noqa: E402

_CB = AI_SCRIPTS / "callbacks"
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

_SM = AI_SCRIPTS / "session_mgmt"
if str(_SM) not in sys.path:
    sys.path.insert(0, str(_SM))

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.session_mgmt.get_comms_id import _generate_id  # single source for ID generation

# --- v2 Conversations/Messaging send contract (siblings in this dir) ---------
# These modules live alongside messaging_mgr.py. Ensure our own directory is on
# sys.path so the imports resolve whether we are run as a script or imported.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from uai_toolkit.messages import comms_index  # noqa: E402  (module ref kept so tests can monkeypatch COMMS_ROOT)
from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402
from uai_toolkit.messages.lib_reply_rule import (  # noqa: E402
    normalize_reply_to,
    resolve_conversation,
    validate_reply_target,
    ReplyRuleError,
)
from uai_toolkit.messages.lib_identity_resolve import (  # noqa: E402
    resolve_sender,
    resolve_recipient,
    SenderUnresolved,
    RecipientNotFound,
    RecipientAmbiguous,
)
try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity  # noqa: E402  (session_mgmt on _SM path)
except Exception:  # pragma: no cover - degrade to raw identity if unavailable
    def format_identity(identity, *, unknown="unknown"):  # type: ignore
        return identity if identity else unknown

logger = logging.getLogger(__name__)

# Import standard_colors for consistent color output
_AI_BIN = AI_SCRIPTS
if str(_AI_BIN) not in sys.path:
    sys.path.insert(0, str(_AI_BIN))
from uai_toolkit.common_utils.standard_colors import (
    CODES as _SC_CODES,
    c as _sc_c,
    colors_enabled as _sc_colors_enabled,
)

# Raw code aliases — routes through standard_colors CODES dict
_R   = _SC_CODES["reset"]
_B   = _SC_CODES["bold"]
_U   = _SC_CODES["underline"]
_C   = _SC_CODES["cyan"]
_G   = _SC_CODES["green"]
_Y   = _SC_CODES["yellow"]
_M   = _SC_CODES["magenta"]
_D   = _SC_CODES["dim"]
_W   = _SC_CODES["bright_white"]
_RED = _SC_CODES["red"]
_BC  = _SC_CODES["bright_cyan"]
_BG  = _SC_CODES["bright_green"]
_BY  = _SC_CODES["bright_yellow"]


def _c(code, text):
    # type: (str, object) -> str
    """Wrap text in an ANSI color code, respecting NO_COLOR and TTY detection."""
    if not _sc_colors_enabled():
        return str(text)
    return "{}{}{}".format(code, text, _R)


def _cp(code, text):
    # type: (str, object) -> str
    """Like _c but for input() prompts -- wraps ANSI in \\001/\\002 for readline."""
    if not _sc_colors_enabled():
        return str(text)
    return "\001{}\002{}\001{}\002".format(code, text, _R)


# === Configuration ===

def _get_ai_root() -> Path:
    """Resolve AI_ROOT from env or default."""
    return AI_ROOT


AI_ROOT = _get_ai_root()
COMMS_DIR = AI_ROOT / "ai_comms"
MESSAGES_DIR = COMMS_DIR / "messages"
MESSAGES_INBOX = MESSAGES_DIR / "inbox"
MESSAGE_BODIES = MESSAGES_DIR / "bodies"   # externalized large message bodies

# Content over this is written to a body file + referenced, so the wire message
# stays small: lossless, still readable on read, and well clear of the fuzzy
# context-archiving zone that can stub large tool inputs. Conservative on purpose.
MAX_INLINE_CHARS = 800
MESSAGES_ARCHIVE = MESSAGES_DIR / "archive"
MESSAGES_SENT = MESSAGES_DIR / "sent"
BROADCASTS_DIR = MESSAGES_INBOX / "broadcasts"
PROMPTS_INBOX = COMMS_DIR / "prompts_inbox"
STANDING_DIR = AI_ROOT / "ai_general" / "data" / "standing_messages"
LOCKS_DIR = AI_ROOT / "ai_general" / "data" / "locks" / "conversations"
PENDING_REPLIES_DIR = AI_ROOT / "ai_general" / "data" / "comms" / "pending_replies"

VERSION = "3.0.0"


# === Directory Helpers (no mkdir -p) ===

def _ensure_dir(path: Path) -> None:
    """Create a directory if it doesn't exist. Does NOT use mkdir -p.
    Walks up to find the first existing ancestor, then creates downward."""
    if path.exists():
        return
    # Ensure parent exists first (one level at a time, recursive)
    if not path.parent.exists():
        _ensure_dir(path.parent)
    path.mkdir()


def _ensure_base_dirs() -> None:
    """Ensure the base message directories exist."""
    _ensure_dir(MESSAGES_INBOX)
    _ensure_dir(BROADCASTS_DIR)
    _ensure_dir(PROMPTS_INBOX)


# === ID Generation ===
# _generate_id() is imported from uai_toolkit.session_mgmt.get_comms_id.py (single source of truth)


# === YAML I/O ===

def _write_yaml(data: dict, filepath: Path) -> Path:
    """Write a dict to a YAML file atomically. Returns the filepath."""
    tmp = filepath.with_suffix(".tmp")
    with open(tmp, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    os.replace(str(tmp), str(filepath))
    return filepath


def _read_yaml(filepath: Path) -> Optional[dict]:
    """Read a YAML file, returning None on failure."""
    try:
        with open(filepath, "r") as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        return None


def _sync_sent_copy(message: dict) -> None:
    """Mirror a message's read_by onto the sender's Sent copy.

    The Sent copy is hardlinked at send time, but _write_yaml's atomic replace
    (os.replace) breaks the hardlink on the recipient's first read — so the Sent
    box would otherwise show the SENDER's (always-unread) state rather than the
    recipient's. Mirror read_by explicitly so Sent reflects the receiver's read
    state. Best-effort; never raises into the caller.
    """
    try:
        mid = message.get("id")
        if not mid or not MESSAGES_SENT.exists():
            return
        for sender_dir in MESSAGES_SENT.iterdir():
            if not sender_dir.is_dir():
                continue
            for p in sender_dir.glob("*.yml"):
                d = _read_yaml(p) if (mid not in p.name) else None
                if mid in p.name or (d and d.get("id") == mid):
                    doc = d if d is not None else _read_yaml(p)
                    if doc is not None:
                        doc["read_by"] = message.get("read_by", [])
                        _write_yaml(doc, p)
                    return
    except Exception:
        pass


# === Core Business Logic ===

def send_to_multiple(
    from_sender: str,
    to_recipients_csv: str,
    content: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Send to multiple recipients (comma-separated string).

    Generates a shared conversation_id so all recipients are in the same thread.
    Filters out empty/whitespace-only entries from the CSV split.
    """
    recipients = [r.strip() for r in to_recipients_csv.split(",") if r.strip()]
    if not recipients:
        return {"success": False, "error": "No valid recipients after filtering"}

    # Generate a shared conversation_id for the thread (unless caller provided one)
    shared_convo_id = kwargs.get("conversation_id") or _generate_id("convo")
    kwargs["conversation_id"] = shared_convo_id

    results = []  # type: List[Dict[str, Any]]
    for recipient in recipients:
        result = send_direct(from_sender, recipient, content, **kwargs)
        results.append(result)
    all_success = all(r.get("success") for r in results)
    return {
        "success": all_success,
        "recipients": len(recipients),
        "conversation_id": shared_convo_id,
        "results": results,
    }


# ── Active delivery (B): don't wait for the recipient to poll ──────────────
_PLATFORM_TARGET = {"claude_cli": "claude-cli", "codex_cli": "codex-cli", "gemini_cli": "gemini-cli"}
_PROMPTING_DIR = AI_SCRIPTS / "prompting"

# Urgencies that actively POKE a verifiably-idle recipient with a "you've got
# mail" nudge. interrupt/prompt mean "reach me now"; async/passive stay pull-only
# (the recipient discovers them on its next prompt / via the unread hook).
# NB: 'background' is NOT a valid send urgency — the choices are
# interrupt/prompt/async/passive — so gating on `!= "background"` (the old code)
# excluded nothing and nudged on every urgency, including passive. Don't do that.
_ACTIVE_NUDGE_URGENCIES = ("interrupt", "prompt")


def _recipient_is_busy(target: str, terminal: str) -> bool:
    """True if the recipient is NOT verifiably idle. Uses the canonical
    double-checked terminal status (reads twice ~2s apart; BOTH must be idle),
    so a session mid-response with an empty input box is correctly seen as busy.
    Any error / missing session => busy (safe: we never nudge on uncertainty)."""
    if not target or not terminal:
        return True
    try:
        if str(_PROMPTING_DIR) not in sys.path:
            sys.path.insert(0, str(_PROMPTING_DIR))
        from uai_toolkit.prompting.lib_send_prompt import is_busy_cli
        return bool(is_busy_cli(target, terminal, double_check=True))
    except Exception:
        return True


def _send_nudge(platform: str, terminal: str, from_label: str, preview: str) -> bool:
    """Push a 'you've got mail' nudge to a CONFIRMED-IDLE recipient. Points at the
    whole inbox, not one message, so the recipient reads ALL unread."""
    target = _PLATFORM_TARGET.get(platform)
    if not target or not terminal:
        return False
    endpoint = "prompt://{}/{}?submit=true".format(target, terminal)
    text = ("\U0001F4EC You have unread mail (latest from {}: \"{}\"). "
            "Check your inbox with comms_check_messages; read with comms_read_message.").format(
                format_identity(from_label), preview)
    script = _PROMPTING_DIR / "send_prompt.py"
    if not script.exists():
        return False
    try:
        # --fb_queue: if the session became busy in the race window since the
        # idle check, send_prompt queues instead of submitting mid-response.
        r = subprocess.run(
            [str(script), "--endpoint", endpoint, "--message", text, "--fb_queue"],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def _stage_inbox_ref(session_dir: str, recipient_tid: str) -> bool:
    """Stage ONE idempotent INBOX reference into the recipient's context_to_load/.
    A busy recipient is told to check its WHOLE inbox on its next turn — not a
    per-message ref (which would make it read only that one message and miss the
    rest). Fixed filename: repeated arrivals collapse to a single notice."""
    if not session_dir:
        return False
    inbox = Path(session_dir) / "context_to_load"
    try:
        inbox.mkdir(exist_ok=True)
        ref = {"type": "inbox", "uri": "uai://session/{}/inbox".format(recipient_tid)}
        (inbox / "00_unread_inbox.ref").write_text(json.dumps(ref, indent=2))
        return True
    except OSError:
        return False


def deliver_to_recipient(recipient_tid: str, from_label: str, preview: str,
                         policy: str = "immediate", urgency: Optional[str] = None,
                         sender: Optional[str] = None) -> Dict[str, Any]:
    """Deliver notification of already-durable mail to one recipient.

    Delegates to the shared notify_lib.notify_recipient(): ALWAYS stages the
    idempotent inbox-ref (even when idle), is prompt-block-safe, and applies the
    notify policy (immediate | batched | silent). `policy='immediate'` reproduces
    the legacy nudge-if-idle behavior. Kept as a thin wrapper so existing callers
    are unchanged; `_send_nudge`/`_stage_inbox_ref`/`_recipient_is_busy` remain the
    primitives notify_lib composes."""
    try:
        from uai_toolkit.messages import notify_lib
        return notify_lib.notify_recipient(
            recipient_tid, from_label, preview,
            policy=policy, urgency=urgency, sender=sender or from_label)
    except Exception as e:  # noqa: BLE001 — delivery must never fail the send
        return {"delivered": False, "mode": "error", "error": str(e)}


def _prompt_block_check(tid: str, sender: Optional[str], urgency: Optional[str] = None) -> Dict[str, Any]:
    """Fail-open prompt-block decision (see prompt_blocks.is_blocked). Returns
    {'blocked': False} on any import/error so a block-check never breaks a send."""
    try:
        from uai_toolkit.messages import prompt_blocks as pb  # same dir; on sys.path when run as a script
    except Exception:
        try:
            md = str(Path(__file__).resolve().parent)
            if md not in sys.path:
                sys.path.insert(0, md)
            from uai_toolkit.messages import prompt_blocks as pb  # type: ignore
        except Exception:
            return {"blocked": False}
    try:
        return pb.is_blocked(tid, sender=sender, urgency=urgency)
    except Exception:
        return {"blocked": False}


def _notify_user_blocked_interrupt(tid: str, sender: str, preview: str, blk: Dict[str, Any]) -> None:
    """Pop a user notification that an interrupt-urgency message was held by a
    prompt block, so PianoMan knows an urgent one is waiting. Best-effort."""
    try:
        notify = AI_SCRIPTS / "notifications" / "send_user_notification.py"
        if not notify.exists():
            return
        msg = "Interrupt message held — {} is prompt-blocked. From {}: \"{}\"".format(
            format_identity(tid), format_identity(sender), preview)
        subprocess.run([sys.executable, str(notify), "info", msg],
                       timeout=15, capture_output=True)
    except Exception:
        pass


# How many leading characters of an offloaded body to keep inline as a preview
# hint. The full body still lives in body_file and is inlined on read.
BODY_PREVIEW_CHARS = 100


def _body_preview(text):
    """First ~BODY_PREVIEW_CHARS of an offloaded body, as an inline hint."""
    text = text or ""
    preview = text[:BODY_PREVIEW_CHARS]
    if len(text) > BODY_PREVIEW_CHARS:
        preview += "…"
    return preview


def _externalize_body(msg_id, content, body_file=None):
    """Keep the wire message small for large bodies, losslessly.

    Returns (wire_content, body_path_or_None):
      - body_file given: the caller already wrote the body to a file — reference it
        (lets a caller keep its OWN tool args tiny, dodging context-archiving).
      - else content > MAX_INLINE_CHARS: write content to messages/bodies/<id>.md
        and reference that.
      - else: inline unchanged.
    The recipient gets the full body transparently — read_message inlines
    body_file (keyed off the body_file field, not this text). The wire 'content'
    keeps the first ~BODY_PREVIEW_CHARS of the body as a hint of what's inside.
    """
    if body_file:
        p = Path(body_file)
        try:
            body_text = p.read_text() if p.exists() else ""
        except OSError:
            body_text = ""
        return _body_preview(body_text), str(p.resolve())

    if content is not None and len(content) > MAX_INLINE_CHARS:
        try:
            _ensure_dir(MESSAGE_BODIES)
            p = MESSAGE_BODIES / "{}.md".format(msg_id)
            p.write_text(content)
            return _body_preview(content), str(p)
        except OSError:
            return content, None  # can't externalize -> fall back to inline

    return content, None


def send_direct(
    from_sender: str,
    to_recipient: str,
    content: str,
    urgency: str = "prompt",
    response_type: str = "reply",
    ttl_seconds: Optional[int] = None,
    callback_endpoint: Optional[str] = None,
    replying_to: Optional[str] = None,
    conversation_id: Optional[str] = None,
    response_required: bool = False,
    body_file: Optional[str] = None,
    notify: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a direct message. Writes YAML to ai_comms/messages/inbox/{recipient}/.

    `notify` selects the notification policy ('immediate'|'batched'|'silent');
    default derives from urgency. See send_message / notify_lib for semantics.

    to_recipient and from_sender accept tracking IDs, display names, or
    prompt:// URIs. URIs are resolved to session IDs for addressing; the
    URI itself is preserved as callback_endpoint if none was explicitly set.

    If to_recipient contains commas, delegates to send_to_multiple().
    If response_required is True, creates a pending reply entry.
    Returns a result dict with success status and metadata.
    """
    # Resolve from_sender best-effort (it is only a label on the message).
    if "://" in from_sender:
        from_sender = _resolve_session(from_sender)

    # Multiple recipients: delegate (each is resolved + validated individually).
    if "," in to_recipient:
        return send_to_multiple(
            from_sender=from_sender,
            to_recipients_csv=to_recipient,
            content=content,
            urgency=urgency,
            response_type=response_type,
            ttl_seconds=ttl_seconds,
            callback_endpoint=callback_endpoint,
            replying_to=replying_to,
            conversation_id=conversation_id,
            response_required=response_required,
        )

    # Single recipient: resolve STRICTLY to a canonical tracking_id. A miss is a
    # hard reject back to the sender — never a silent fall back to a raw key
    # (which would drop the message in a phantom dir the recipient never scans).
    if "://" in to_recipient and callback_endpoint is None:
        callback_endpoint = to_recipient
    to_recipient, _resolve_err = _resolve_recipient_strict(to_recipient)
    if _resolve_err:
        return {"success": False, "error": _resolve_err, "rejected": True}

    _ensure_base_dirs()

    msg_id = _generate_id("msg")
    now = datetime.now()

    # Large bodies go to a file + a short note (lossless); read_message inlines.
    wire_content, body_path = _externalize_body(msg_id, content, body_file)

    message = {
        "id": msg_id,
        "type": "direct",
        "urgency": urgency,
        "response_type": response_type,
        "from": from_sender,
        "to": to_recipient,
        "created_at": now.isoformat(),
        "ttl_seconds": ttl_seconds,
        "expires_at": None,
        "replying_to": replying_to,
        "conversation_id": conversation_id,
        "callback_endpoint": callback_endpoint,
        "response_required": response_required,
        "content": wire_content,
        "body_file": body_path,
        "acknowledgments": [],
        "read_by": [],
    }

    if ttl_seconds is not None:
        from datetime import timedelta
        message["expires_at"] = (now + timedelta(seconds=ttl_seconds)).isoformat()

    recipient_dir = MESSAGES_INBOX / to_recipient
    _ensure_dir(recipient_dir)

    filepath = _write_yaml(message, recipient_dir / "{}.yml".format(msg_id))

    # Sender-side retention: hardlink the message into sent/<from_sender>/.
    # Hardlink keeps storage near-zero and reflects edits; if the recipient
    # later deletes their copy, the inode survives via the sender's link.
    try:
        sender_dir = MESSAGES_SENT / from_sender
        _ensure_dir(sender_dir)
        sent_path = sender_dir / "{}.yml".format(msg_id)
        if not sent_path.exists():
            os.link(filepath, sent_path)
    except OSError:
        pass  # never fail the send because retention failed

    # Create a pending reply entry if response is required
    if response_required:
        create_pending_reply(
            conversation_id=conversation_id or msg_id,
            message_id=msg_id,
            to_recipient=to_recipient,
            from_sender=from_sender,
            callback_endpoint=callback_endpoint,
            ttl_seconds=ttl_seconds or 259200,
        )

    # Active delivery (B): notify the recipient now instead of waiting for it to
    # poll; policy = explicit `notify` else derived from urgency (async stays
    # pull-only). deliver_to_recipient -> notify_recipient (block-safe, always-ref).
    delivery = None
    _pol = notify or ("immediate" if urgency in _ACTIVE_NUDGE_URGENCIES else None)
    if _pol in ("immediate", "batched"):
        preview = " ".join((content or "").split())[:80]
        try:
            delivery = deliver_to_recipient(to_recipient, from_sender, preview,
                                            policy=_pol, urgency=urgency, sender=from_sender)
        except Exception as e:
            delivery = {"delivered": False, "error": str(e)}

    return {
        "success": True,
        "message_id": msg_id,
        "to": to_recipient,
        "file": str(filepath),
        "response_required": response_required,
        "delivery": delivery,
    }


def _record_body_ref(index: "CommsIndex", body_path: str) -> str:
    """Register an externalized body file in the index's body_refs table and
    return the new body_ref id.

    `body_path` is the absolute path written by `_externalize_body`. The stored
    `path` is made relative to `comms_index.COMMS_ROOT` so the read side
    (`CommsIndex._resolve_body`) can resolve it back. There is no public
    insert_body_ref API on the index, so we write the row through the index's
    own connection — keeping WAL/PRAGMA settings consistent.
    """
    p = Path(body_path)
    try:
        nbytes = p.stat().st_size
    except OSError:
        nbytes = None
    try:
        rel = os.path.relpath(str(p.resolve()), str(Path(comms_index.COMMS_ROOT).resolve()))
    except ValueError:
        # Different drive / unrelated root: store the absolute path verbatim.
        rel = str(p.resolve())
    ref_id = _generate_id("bodyref")
    con = index._connect()
    try:
        con.execute(
            "INSERT INTO body_refs (id, path, bytes, external) VALUES (?, ?, ?, ?)",
            (ref_id, rel, nbytes, 1),
        )
        con.commit()
    finally:
        con.close()
    return ref_id


def send_message(
    *,
    to: str,
    content: str,
    reply_to: Optional[str],
    subject: Optional[str] = None,
    sender_ctx: Optional[str] = None,
    urgency: str = "prompt",
    response_type: str = "reply",
    ttl_seconds: Optional[int] = None,
    body_file: Optional[str] = None,
    response_required: bool = False,
    delivery: str = "message",
    notify: Optional[str] = None,
    index: Optional["CommsIndex"] = None,
) -> Dict[str, Any]:
    """Send a message under the v2 Conversations/Messaging contract.

    `notify` selects the notification policy: 'immediate' | 'batched' | 'silent'.
    Default None derives from urgency (async -> silent, prompt/interrupt ->
    immediate) — backward compatible. 'batched' coalesces nudges to <=1 per
    recipient per window (see notify_lib), for bulk senders like Git-Guardian.

    The sender is TRUSTED — derived from `sender_ctx` (or $AI_TRACKING_ID), never
    a self-asserted wire field. `reply_to` is enforced: it must be a null
    sentinel (new thread, requires `subject`) or a valid message id (reply,
    inherits the parent's conversation). Writes the canonical Message + Delivery
    (+ obligations) rows to the comms index and a back-compat YAML artifact.

    Returns ``{"conversationId": <id>, "messageId": <id>}``.

    Crash-safe order (§12.G): every validation that can reject the send runs
    BEFORE any index write, so a rejected send leaves no partial index rows.
    """
    if index is None:
        index = CommsIndex()

    # 1. Fold sentinels / validate reply_to shape (ambiguous -> raise).
    reply_to = normalize_reply_to(reply_to)

    # 2. Trusted sender (rejects an unresolvable identity; no 'unknown' fallback).
    sender = resolve_sender(explicit=sender_ctx)

    # 3. Recipient classification (0 -> RecipientNotFound, >1 -> RecipientAmbiguous).
    recipient = resolve_recipient(to)
    kind = recipient["kind"]
    if kind == "session":
        delivery_recipients = [recipient["tracking_id"]]
        to_entity = "uai://session/{}/message".format(recipient["tracking_id"])
    elif kind == "user":
        delivery_recipients = [recipient["entity_id"]]
        to_entity = "uai://user/{}".format(recipient["entity_id"])
    else:  # entity + deferred_fanout: recorded, but NO deliveries in this slice.
        delivery_recipients = []
        to_entity = recipient["to_entity"]

    # 4. Mint the message id.
    msg_id = _generate_id("msg")

    # 5. Validate the reply target (no-op for a new thread).
    if reply_to is not None:
        validate_reply_target(index, reply_to, sender, new_message_id=msg_id)

    # 6. Derive the conversation (mints when reply_to is None; SubjectRequired
    #    otherwise). All rejecting validation is now behind us.
    conversation_id, _eff_subject = resolve_conversation(index, reply_to, subject)

    # 7. Externalize a large body to a file + body_refs row; else store inline.
    wire_content, body_path = _externalize_body(msg_id, content, body_file)
    body_val: Optional[str] = None
    body_ref: Optional[str] = None
    if body_path is not None:
        body_ref = _record_body_ref(index, body_path)
    else:
        body_val = content

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # 8. Canonical message row.
    index.insert_message({
        "id": msg_id,
        "conversation_id": conversation_id,
        "reply_to": reply_to,
        "subject": subject,
        "from_id": sender,
        "to_entity": to_entity,
        "delivery": delivery,
        "type": "direct",
        "urgency": urgency,
        "response_type": response_type,
        "ttl_seconds": ttl_seconds,
        "response_required": 1 if response_required else 0,
        "created_at": now,
        "body": body_val,
        "body_ref": body_ref,
    })

    # 9. Delivery rows (session -> 1; user -> the user id; deferred entity -> 0).
    for rcpt in delivery_recipients:
        index.insert_delivery(msg_id, rcpt)

    # 10. Obligations (§12.H): a response_required send (or a prompt delivery)
    #     opens one obligation per recipient; then this send discharges the
    #     sender's own pending obligation in the conversation.
    if response_required or delivery == "prompt":
        for rcpt in delivery_recipients:
            index.open_obligation(conversation_id, msg_id, rcpt)
    index.clear_obligations(conversation_id, sender, by=sender)

    # 11. Back-compat YAML artifact (one per concrete recipient), written AFTER
    #     the index so the index is never behind the artifact. Carries the v2
    #     fields plus a `replying_to` mirror for old readers.
    expires_at = None
    if ttl_seconds is not None:
        from datetime import timedelta
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()

    for rcpt in delivery_recipients:
        artifact = {
            "id": msg_id,
            "type": "direct",
            "urgency": urgency,
            "response_type": response_type,
            "from": sender,
            "to": rcpt,
            "to_entity": to_entity,
            "created_at": now,
            "ttl_seconds": ttl_seconds,
            "expires_at": expires_at,
            "conversation_id": conversation_id,
            "reply_to": reply_to,
            "replying_to": reply_to,  # mirror for pre-v2 readers
            "subject": subject,
            "response_required": response_required,
            "content": wire_content,
            "body_file": body_path,
            "acknowledgments": [],
            "read_by": [],
        }
        recipient_dir = MESSAGES_INBOX / rcpt
        _ensure_dir(recipient_dir)
        filepath = _write_yaml(artifact, recipient_dir / "{}.yml".format(msg_id))
        # Sender-side retention via hardlink (best-effort; never fails the send).
        try:
            sender_dir = MESSAGES_SENT / sender
            _ensure_dir(sender_dir)
            sent_path = sender_dir / "{}.yml".format(msg_id)
            if not sent_path.exists():
                os.link(filepath, sent_path)
        except OSError:
            pass

    # 12. Active delivery (B): nudge a verifiably-IDLE session recipient NOW
    #     instead of waiting for it to discover the message on its next prompt.
    #     The v2 path historically dropped this (send_direct had it), so messages
    #     sent via the MCP/CLI `send` left idle sessions un-poked until they
    #     happened to submit a prompt. Restore parity. Gates:
    #       - delivery == "message" only — a 'prompt' delivery self-delivers, so
    #         nudging there would double-send.
    #       - urgency in interrupt/prompt — the "reach me now" urgencies; async
    #         and passive stay pull-only (discovered on the next prompt).
    #       - session recipients only — users/deferred entities aren't terminals.
    #     deliver_to_recipient is idle-double-checked + fb_queue-on-race, so it
    #     never interrupts a busy session. Best-effort; never fails the send.
    nudges = []
    # Notification policy: explicit `notify`, else derived from urgency (async ->
    # no active notification, prompt/interrupt -> immediate). notify_recipient owns
    # the prompt-block gate + blocked-interrupt user-notify + always-stage-ref.
    _pol = notify or ("immediate" if urgency in _ACTIVE_NUDGE_URGENCIES else None)
    if delivery == "message" and kind == "session" and _pol in ("immediate", "batched"):
        preview = " ".join((content or "").split())[:80]
        for rcpt in delivery_recipients:
            try:
                nudges.append({"to": rcpt, **deliver_to_recipient(
                    rcpt, sender, preview, policy=_pol, urgency=urgency, sender=sender)})
            except Exception as e:  # noqa: BLE001 — delivery must never fail the send
                nudges.append({"to": rcpt, "delivered": False, "error": str(e)})

    result = {"conversationId": conversation_id, "messageId": msg_id}
    if nudges:
        result["delivery"] = nudges
    return result


def broadcast(
    from_sender: str,
    content: str,
    urgency: str = "prompt",
    scope: str = "active",
    group: Optional[str] = None,
    replying_to: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a broadcast message. Writes YAML to ai_comms/messages/inbox/broadcasts/.

    Returns a result dict with success status and metadata.
    """
    _ensure_base_dirs()

    msg_id = _generate_id("msg")
    now = datetime.now()

    message = {
        "id": msg_id,
        "type": "broadcast",
        "urgency": urgency,
        "response_type": "acknowledge",
        "from": from_sender,
        "to": "all",
        "created_at": now.isoformat(),
        "ttl_seconds": None,
        "replying_to": replying_to,
        "conversation_id": conversation_id,
        "callback_endpoint": None,
        "scope": scope,
        "content": content,
        "acknowledgments": [],
        "read_by": [],
    }

    if group is not None:
        message["group"] = group

    filepath = _write_yaml(message, BROADCASTS_DIR / "{}.yml".format(msg_id))

    return {
        "success": True,
        "message_id": msg_id,
        "file": str(filepath),
    }


def list_messages(
    dir_name: str = "inbox",
    recipient: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    List messages from directories, newest first.

    dir_name: "inbox" for direct messages, "broadcasts" for broadcasts.
    recipient: If provided with dir_name="inbox", filters to that recipient's folder.
    limit: Maximum number of results.
    """
    if dir_name == "broadcasts":
        target = BROADCASTS_DIR
        messages = _list_from_dir(target, limit)
    elif dir_name == "inbox":
        if recipient:
            target = MESSAGES_INBOX / recipient
            messages = _list_from_dir(target, limit)
        else:
            # Aggregate across all recipient subdirs (skip broadcasts)
            messages = []  # type: List[Dict[str, Any]]
            if MESSAGES_INBOX.exists():
                for entry in MESSAGES_INBOX.iterdir():
                    if entry.is_dir() and entry.name != "broadcasts":
                        messages.extend(_list_from_dir(entry, limit))
            messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
            messages = messages[:limit]
    elif dir_name == "prompts":
        # Queued prompts live under prompts_inbox/<session>/ (.yml entries).
        target = PROMPTS_INBOX / recipient if recipient else PROMPTS_INBOX
        messages = _list_from_dir(target, limit)
    else:
        return {"success": False, "error": "dir must be 'inbox', 'broadcasts', or 'prompts'"}

    return {
        "success": True,
        "count": len(messages),
        "messages": messages,
    }


def _list_from_dir(directory: Path, limit: int) -> List[Dict[str, Any]]:
    """Read all .yml files in a directory, return summaries sorted newest first."""
    results = []  # type: List[Dict[str, Any]]
    if not directory.exists():
        return results

    yml_files = sorted(
        directory.glob("*.yml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for filepath in yml_files[:limit]:
        msg = _read_yaml(filepath)
        if msg and "id" in msg:
            preview = ""
            content = msg.get("content", "")
            if isinstance(content, str):
                preview = content[:100] + ("..." if len(content) > 100 else "")

            results.append({
                "id": msg["id"],
                "type": msg.get("type", "unknown"),
                "from": msg.get("from", "unknown"),
                "to": msg.get("to", "unknown"),
                "created_at": msg.get("created_at", ""),
                "urgency": msg.get("urgency", ""),
                "read_by": msg.get("read_by", []),
                "preview": preview,
                "file": str(filepath),
            })

    return results


def list_sent(sender: str, limit: int = 50) -> Dict[str, Any]:
    """List messages sent by a session (scans all inboxes + broadcasts)."""
    messages = []
    # Scan all recipient subdirs
    if MESSAGES_INBOX.exists():
        for entry in MESSAGES_INBOX.iterdir():
            if entry.is_dir():
                for msg in _list_from_dir(entry, limit * 2):
                    if msg.get("from") == sender:
                        messages.append(msg)
    # Also check broadcasts
    for msg in _list_from_dir(BROADCASTS_DIR, limit):
        if msg.get("from") == sender:
            messages.append(msg)
    messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return {"success": True, "count": len(messages[:limit]), "messages": messages[:limit]}


def list_archived(recipient: str, limit: int = 50) -> Dict[str, Any]:
    """List archived messages for a recipient."""
    target = MESSAGES_ARCHIVE / recipient
    messages = _list_from_dir(target, limit)
    return {"success": True, "count": len(messages), "messages": messages}


def acknowledge(msg_id: str, acknowledger: str) -> Dict[str, Any]:
    """
    Add an acknowledgment entry to an existing message.

    Searches inbox and broadcasts directories for the message.
    """
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}

    filepath, message = found

    if "acknowledgments" not in message:
        message["acknowledgments"] = []

    ack_entry = {
        "by": acknowledger,
        "at": datetime.now().isoformat(),
    }
    message["acknowledgments"].append(ack_entry)

    _write_yaml(message, filepath)

    return {
        "success": True,
        "message_id": msg_id,
        "acknowledged_by": acknowledger,
        "file": str(filepath),
    }


def check_responses(msg_id: str) -> Dict[str, Any]:
    """
    Find messages that have replying_to pointing to the given msg_id.

    Searches all inbox and broadcast directories.
    Handles both old 'reply_to' and new 'replying_to' field names for compatibility.
    """
    responses = []  # type: List[Dict[str, Any]]
    search_dirs = [BROADCASTS_DIR]

    # Also search all recipient subdirs under inbox
    if MESSAGES_INBOX.exists():
        for entry in MESSAGES_INBOX.iterdir():
            if entry.is_dir():
                search_dirs.append(entry)

    for directory in search_dirs:
        if not directory.exists():
            continue
        for filepath in directory.glob("*.yml"):
            msg = _read_yaml(filepath)
            if not msg:
                continue
            # Check both old and new field names for compatibility
            replying = msg.get("replying_to") or msg.get("reply_to")
            if replying == msg_id:
                content = msg.get("content", "")
                preview = ""
                if isinstance(content, str):
                    preview = content[:100]
                responses.append({
                    "id": msg.get("id"),
                    "from": msg.get("from"),
                    "created_at": msg.get("created_at", ""),
                    "preview": preview,
                    "file": str(filepath),
                })

    responses.sort(key=lambda r: r.get("created_at", ""))

    return {
        "success": True,
        "parent_message_id": msg_id,
        "response_count": len(responses),
        "responses": responses,
    }


def read_message(msg_id: str, reader: str) -> Dict[str, Any]:
    """
    Read a message by ID and mark it as read.

    Searches inbox dirs and broadcasts for the message.
    Adds a read_by entry with timestamp and reader ID.
    If already read by this reader, displays but does not add duplicate.
    """
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}

    filepath, message = found

    # Ensure read_by list exists (backward compat with old messages)
    if "read_by" not in message:
        message["read_by"] = []

    # Check if already read by this reader
    already_read = any(
        entry.get("by") == reader for entry in message["read_by"]
    )

    if not already_read:
        read_entry = {
            "by": reader,
            "at": datetime.now().isoformat(),
        }
        message["read_by"].append(read_entry)
        _write_yaml(message, filepath)
        _sync_sent_copy(message)

    # Inline an externalized large body so the reader gets the full message
    # transparently. Done AFTER the read-receipt write, so the stored YAML keeps
    # the small wire note + body_file reference. A missing body is surfaced
    # loudly (never silently pass off the note as the message).
    bf = message.get("body_file")
    if bf:
        try:
            bp = Path(bf)
            if bp.exists():
                message["content"] = bp.read_text()
                message["body_externalized"] = True
            else:
                message["content"] = (message.get("content", "")
                    + "\n\n[!] body file missing ({}): full content unavailable.".format(bf))
                message["body_externalized"] = False
        except OSError as e:
            message["body_externalized"] = False
            message["body_error"] = str(e)

    return {
        "success": True,
        "message_id": msg_id,
        "already_read": already_read,
        "message": message,
    }


def reply_to_message(
    msg_id: str,
    from_sender: str,
    content: str,
    urgency: str = "prompt",
    response_required: bool = False,
    notify: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reply to a message.

    Finds the original message, sends a new message to the original sender,
    sets replying_to to the original msg_id, and sets conversation_id to
    the original message's conversation_id (or the original msg_id if none).
    After sending, resolves any pending reply that this reply satisfies.
    """
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}

    _, original = found
    original_sender = original.get("from", "")
    if not original_sender:
        return {"success": False, "error": "Original message has no 'from' field"}

    # Determine conversation_id: use original's, or fall back to original msg_id
    convo_id = original.get("conversation_id") or msg_id

    result = send_direct(
        from_sender=from_sender,
        to_recipient=original_sender,
        content=content,
        urgency=urgency,
        replying_to=msg_id,
        conversation_id=convo_id,
        response_required=response_required,
        notify=notify,
    )

    # Resolve any pending reply this message satisfies
    if result.get("success"):
        resolved = resolve_pending_reply(
            conversation_id=convo_id,
            message_id=msg_id,
            from_sender=from_sender,
        )
        # Invoke callback_endpoint if the resolved pending entry had one
        if resolved and resolved.get("callback_endpoint"):
            try:
                from uai_toolkit.callbacks.callback_lib import execute_uri
                cb_result = execute_uri(resolved["callback_endpoint"], content)
                result["callback_result"] = {
                    "success": cb_result.success,
                    "message": cb_result.message,
                }
            except Exception as e:
                result["callback_result"] = {
                    "success": False,
                    "message": "callback error: {}".format(e),
                }

    return result


def reply_to_all(
    msg_id: str,
    from_sender: str,
    content: str,
    urgency: str = "prompt",
    response_required: bool = False,
    notify: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reply to all recipients of a message.

    Finds all participants (original sender + all 'to' recipients),
    sends to each except the current sender.
    For broadcasts, sends a broadcast reply.
    After sending, resolves any pending reply that this reply satisfies.
    """
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}

    _, original = found
    original_sender = original.get("from", "")
    original_to = original.get("to", "")

    # Determine conversation_id
    convo_id = original.get("conversation_id") or msg_id

    # If it was a broadcast, reply with a broadcast
    if original.get("type") == "broadcast" or original_to == "all":
        result = broadcast(
            from_sender=from_sender,
            content=content,
            urgency=urgency,
            replying_to=msg_id,
            conversation_id=convo_id,
        )
        # Resolve pending reply even for broadcast replies
        if result.get("success"):
            resolved = resolve_pending_reply(
                conversation_id=convo_id,
                message_id=msg_id,
                from_sender=from_sender,
            )
            if resolved and resolved.get("callback_endpoint"):
                try:
                    from uai_toolkit.callbacks.callback_lib import execute_uri
                    cb_result = execute_uri(resolved["callback_endpoint"], content)
                    result["callback_result"] = {
                        "success": cb_result.success,
                        "message": cb_result.message,
                    }
                except Exception as e:
                    result["callback_result"] = {
                        "success": False,
                        "message": "callback error: {}".format(e),
                    }
        return result

    # For direct messages, collect all participants
    participants = set()  # type: set
    if original_sender:
        participants.add(original_sender)
    if original_to:
        participants.add(original_to)

    # Remove the current sender from recipients
    participants.discard(from_sender)

    if not participants:
        return {"success": False, "error": "No recipients to reply to (sender is the only participant)"}

    results = []  # type: List[Dict[str, Any]]
    for recipient in sorted(participants):
        result = send_direct(
            from_sender=from_sender,
            to_recipient=recipient,
            content=content,
            urgency=urgency,
            replying_to=msg_id,
            conversation_id=convo_id,
            response_required=response_required,
            notify=notify,
        )
        results.append(result)

    all_success = all(r.get("success") for r in results)

    # Resolve pending reply
    final_result = {
        "success": all_success,
        "replies_sent": len(results),
        "results": results,
    }
    if all_success:
        resolved = resolve_pending_reply(
            conversation_id=convo_id,
            message_id=msg_id,
            from_sender=from_sender,
        )
        if resolved and resolved.get("callback_endpoint"):
            try:
                from uai_toolkit.callbacks.callback_lib import execute_uri
                cb_result = execute_uri(resolved["callback_endpoint"], content)
                final_result["callback_result"] = {
                    "success": cb_result.success,
                    "message": cb_result.message,
                }
            except Exception as e:
                final_result["callback_result"] = {
                    "success": False,
                    "message": "callback error: {}".format(e),
                }

    return final_result


def check_unread(session: Optional[str] = None) -> Dict[str, Any]:
    """
    Check unread message counts.

    If session is provided, check that session's inbox for messages without
    a read_by entry from that session.
    If no session, check all inbox dirs and report per-session unread counts.
    Also checks broadcasts dir for unread broadcasts.
    """
    counts = {}  # type: Dict[str, int]
    broadcast_unread = 0

    def _count_unread_in_dir(directory: Path, reader_id: str) -> int:
        """Count messages in directory not read by reader_id."""
        unread = 0
        if not directory.exists():
            return 0
        for filepath in directory.glob("*.yml"):
            msg = _read_yaml(filepath)
            if not msg:
                continue
            read_by = msg.get("read_by", [])
            if not any(entry.get("by") == reader_id for entry in read_by):
                unread += 1
        return unread

    if session:
        # Normalize to the canonical tracking_id — the same key send_direct now
        # writes under — so a display-name / URI caller still scans the right
        # inbox and matches read_by entries (which are keyed by tracking_id).
        session = _resolve_session(session) or session
        session_dir = MESSAGES_INBOX / session
        inbox_count = _count_unread_in_dir(session_dir, session)

        # Check broadcasts unread by this session
        broadcast_count = _count_unread_in_dir(BROADCASTS_DIR, session)

        return {
            "success": True,
            "session": session,
            "inbox_unread": inbox_count,
            "broadcast_unread": broadcast_count,
            "total_unread": inbox_count + broadcast_count,
        }
    else:
        # Check all sessions
        total = 0
        if MESSAGES_INBOX.exists():
            for entry in MESSAGES_INBOX.iterdir():
                if entry.is_dir() and entry.name != "broadcasts":
                    session_name = entry.name
                    unread = _count_unread_in_dir(entry, session_name)
                    if unread > 0:
                        counts[session_name] = unread
                        total += unread

        # Broadcasts: count messages with empty read_by
        if BROADCASTS_DIR.exists():
            for filepath in BROADCASTS_DIR.glob("*.yml"):
                msg = _read_yaml(filepath)
                if msg and not msg.get("read_by", []):
                    broadcast_unread += 1

        return {
            "success": True,
            "scope": "all_inboxes",
            "note": (
                "Fleet-wide unread across EVERY session's inbox, keyed by "
                "recipient (these are each session's own unread mail, NOT "
                "senders to you). Pass session=<tracking_id> for a single "
                "session's own inbox."
            ),
            "sessions": counts,
            "broadcast_unread": broadcast_unread,
            "total_unread": total + broadcast_unread,
        }


def mark_as(msg_id: str, reader: str, state: str = "read") -> Dict[str, Any]:
    """Mark a message as read or unread for a reader."""
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}
    filepath, message = found
    if "read_by" not in message:
        message["read_by"] = []

    already_read = any(entry.get("by") == reader for entry in message["read_by"])

    if state == "read" and not already_read:
        message["read_by"].append({"by": reader, "at": datetime.now().isoformat()})
        _write_yaml(message, filepath)
        _sync_sent_copy(message)
        return {"success": True, "message_id": msg_id, "marked": "read"}
    elif state == "unread" and already_read:
        message["read_by"] = [e for e in message["read_by"] if e.get("by") != reader]
        _write_yaml(message, filepath)
        _sync_sent_copy(message)
        return {"success": True, "message_id": msg_id, "marked": "unread"}
    return {"success": True, "message_id": msg_id, "marked": state, "no_change": True}


def move_message(msg_id: str, to_folder: str, recipient: str, from_folder: str = "inbox") -> Dict[str, Any]:
    """Move a message between folders (inbox, archive)."""
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}
    filepath, message = found

    if to_folder == "archive":
        dest_dir = MESSAGES_ARCHIVE / recipient
    elif to_folder == "inbox":
        dest_dir = MESSAGES_INBOX / recipient
    else:
        return {"success": False, "error": "Invalid destination folder: {}".format(to_folder)}

    _ensure_dir(dest_dir)
    new_path = dest_dir / filepath.name
    filepath.rename(new_path)
    return {"success": True, "message_id": msg_id, "moved_to": to_folder}


def archive_message(msg_id: str) -> Dict[str, Any]:
    """
    Archive a message by moving it from inbox to archive directory.

    Moves to ai_comms/messages/archive/{recipient}/.
    """
    found = _find_message(msg_id)
    if found is None:
        return {"success": False, "error": "Message not found: {}".format(msg_id)}

    filepath, message = found

    # Determine the recipient subdirectory name
    # Use the parent directory name (e.g., "bob" from inbox/bob/, or "broadcasts")
    recipient_dir_name = filepath.parent.name

    archive_dir = MESSAGES_ARCHIVE / recipient_dir_name
    _ensure_dir(archive_dir)

    new_path = archive_dir / filepath.name
    filepath.rename(new_path)

    return {
        "success": True,
        "message_id": msg_id,
        "archived_from": str(filepath),
        "archived_to": str(new_path),
    }


def queue_prompt(
    to_session: str,
    content: str,
    urgency: str = "prompt",
    delivery: str = "pre-prompt",
    source: Optional[str] = None,
    callback_endpoint: Optional[str] = None,
    ttl_seconds: int = 259200,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write a prompt queue entry to ai_comms/prompts_inbox/{session}/.

    Returns a result dict with success status and metadata.
    Default TTL is 259200 seconds (3 days).

    `message_id`: when the caller already minted a canonical message id (e.g.
    `send_prompt` recording the prompt durably in the index), pass it so the
    queue entry and the index row share one id. Defaults to a freshly-minted id
    for legacy callers.
    """
    from datetime import timedelta

    _ensure_base_dirs()

    queue_id = _generate_id("queue")
    msg_id = message_id or _generate_id("msg")
    now = datetime.now()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

    entry = {
        "id": queue_id,
        "message_id": msg_id,
        "to": to_session,
        "content": content,
        "urgency": urgency,
        "delivery": delivery,
        "ready_for_delivery": True,
        "queued_at": now.isoformat(),
        "ttl_seconds": ttl_seconds,
        "expires_at": expires_at,
        "source": source,
        "callback_endpoint": callback_endpoint,
    }

    session_dir = PROMPTS_INBOX / to_session
    _ensure_dir(session_dir)

    filepath = _write_yaml(entry, session_dir / "{}.yml".format(queue_id))

    return {
        "success": True,
        "queue_id": queue_id,
        "message_id": msg_id,
        "to": to_session,
        "file": str(filepath),
    }


def send_prompt(
    *,
    to: str,
    content: str,
    reply_to: Optional[str] = None,
    subject: Optional[str] = None,
    sender_ctx: Optional[str] = None,
    urgency: str = "prompt",
    ttl_seconds: int = 259200,
    timing: str = "pre-prompt",
    source: Optional[str] = None,
    callback_endpoint: Optional[str] = None,
    body_file: Optional[str] = None,
    index: Optional["CommsIndex"] = None,
    queue: bool = True,
) -> Dict[str, Any]:
    """Send a prompt under the v2 Conversations/Messaging contract (§6).

    A prompt is persisted exactly like a message — a canonical Message row with
    ``delivery='prompt'``, a queued Delivery row, and an obligation for each
    recipient (a prompt implies a response) — so a sent prompt is WRITTEN, never
    evaporates. Routes through :func:`send_message` with ``delivery='prompt'`` to
    reuse the same trusted-sender / enforced-``reply_to`` / conversation logic;
    ``reply_to``/``subject`` semantics are identical to messages (a prompt with
    ``reply_to=None`` requires a ``subject``).

    ADDITIVELY, the legacy ``prompts_inbox/`` queue-file is still written (the
    UserPromptSubmit hook and other systems consume it). The queue entry shares
    the canonical message id minted by the index write. Set ``queue=False`` to
    skip the legacy file when only the durable record is wanted.

    Returns ``{"conversationId": <id>, "messageId": <id>, "queue_id": <id|None>,
    "file": <path|None>}``.
    """
    sent = send_message(
        to=to,
        content=content,
        reply_to=reply_to,
        subject=subject,
        sender_ctx=sender_ctx,
        urgency=urgency,
        response_type="reply",
        ttl_seconds=ttl_seconds,
        body_file=body_file,
        response_required=True,
        delivery="prompt",
        index=index,
    )

    result: Dict[str, Any] = dict(sent)
    result.setdefault("queue_id", None)
    result.setdefault("file", None)

    if queue:
        q = queue_prompt(
            to_session=to,
            content=content,
            urgency=urgency,
            delivery=timing,
            source=source,
            callback_endpoint=callback_endpoint,
            ttl_seconds=ttl_seconds,
            message_id=sent["messageId"],
        )
        result["queue_id"] = q.get("queue_id")
        result["file"] = q.get("file")

    return result


# === Standing Messages ===

STANDING_SCOPES = ("global", "team", "platform", "project")


def post_standing(
    scope: str,
    from_sender: str,
    content: str,
    scope_name: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    approved_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Post a standing message to the appropriate scope directory.

    scope: one of global, team, platform, project
    scope_name: required for team/platform/project; ignored for global
    approved_by: audit trail -- who approved this standing message (defaults to from_sender)
    """
    if scope not in STANDING_SCOPES:
        return {"success": False, "error": "Invalid scope: {}. Must be one of: {}".format(scope, ", ".join(STANDING_SCOPES))}

    if scope != "global" and not scope_name:
        return {"success": False, "error": "scope_name is required for scope '{}'".format(scope)}

    msg_id = _generate_id("standing")
    now = datetime.now()

    expires_at = None
    if ttl_seconds is not None:
        from datetime import timedelta
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()

    message = {
        "id": msg_id,
        "scope": scope,
        "scope_name": scope_name if scope != "global" else None,
        "from": from_sender,
        "approved_by": approved_by or from_sender,
        "content": content,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }

    # Determine target directory
    target_dir = STANDING_DIR / scope
    if scope != "global":
        target_dir = target_dir / scope_name
    _ensure_dir(target_dir)

    filepath = _write_yaml(message, target_dir / "{}.yml".format(msg_id))

    return {
        "success": True,
        "id": msg_id,
        "file": str(filepath),
    }


def query_standing(
    scopes: List[str],
    team: Optional[str] = None,
    platform: Optional[str] = None,
    project: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Query standing messages across requested scopes.

    Filters out expired messages but does not delete them.
    Returns newest first.
    """
    now = datetime.now()
    messages = []  # type: List[Dict[str, Any]]

    for scope in scopes:
        if scope not in STANDING_SCOPES:
            continue

        if scope == "global":
            target_dir = STANDING_DIR / "global"
            messages.extend(_collect_standing(target_dir, now))
        elif scope == "team" and team:
            target_dir = STANDING_DIR / "team" / team
            messages.extend(_collect_standing(target_dir, now))
        elif scope == "platform" and platform:
            target_dir = STANDING_DIR / "platform" / platform
            messages.extend(_collect_standing(target_dir, now))
        elif scope == "project" and project:
            target_dir = STANDING_DIR / "project" / project
            messages.extend(_collect_standing(target_dir, now))

    # Sort newest first
    messages.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    messages = messages[:limit]

    return {
        "success": True,
        "count": len(messages),
        "messages": messages,
    }


def _collect_standing(directory: Path, now: datetime) -> List[Dict[str, Any]]:
    """Read standing messages from a directory, filtering expired ones."""
    results = []  # type: List[Dict[str, Any]]
    if not directory.exists():
        return results

    for filepath in directory.glob("*.yml"):
        msg = _read_yaml(filepath)
        if not msg or "id" not in msg:
            continue

        # Filter expired
        expires_at = msg.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt <= now:
                    continue
            except (ValueError, TypeError):
                pass

        results.append(msg)

    return results


def cancel_standing(msg_id: str) -> Dict[str, Any]:
    """
    Remove a standing message by ID. Searches all scope directories.
    """
    for scope in STANDING_SCOPES:
        scope_dir = STANDING_DIR / scope
        if not scope_dir.exists():
            continue

        # Check directly in scope dir (global)
        candidate = scope_dir / "{}.yml".format(msg_id)
        if candidate.exists():
            candidate.unlink()
            return {"success": True, "id": msg_id, "removed_from": str(candidate)}

        # Check subdirectories (team/platform/project)
        for sub in scope_dir.iterdir():
            if sub.is_dir():
                candidate = sub / "{}.yml".format(msg_id)
                if candidate.exists():
                    candidate.unlink()
                    return {"success": True, "id": msg_id, "removed_from": str(candidate)}

    return {"success": False, "error": "Standing message not found: {}".format(msg_id)}


# === Conversation Locks ===

def lock_session(
    session_id: str,
    locked_by: str = "user",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a conversation lock for a session."""
    _ensure_dir(LOCKS_DIR)

    lock_file = LOCKS_DIR / "{}.lock".format(session_id)
    if lock_file.exists():
        return {"success": False, "error": "Session already locked: {}".format(session_id)}

    now = datetime.now()
    lock_data = {
        "locked_at": now.isoformat(),
        "locked_by": locked_by,
        "reason": reason,
    }

    _write_yaml(lock_data, lock_file)

    return {
        "success": True,
        "session_id": session_id,
        "file": str(lock_file),
    }


def unlock_session(session_id: str) -> Dict[str, Any]:
    """Remove a conversation lock for a session."""
    lock_file = LOCKS_DIR / "{}.lock".format(session_id)
    if not lock_file.exists():
        return {"success": False, "error": "No lock found for session: {}".format(session_id)}

    lock_file.unlink()
    return {"success": True, "session_id": session_id}


def lock_global(
    locked_by: str = "user",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a global conversation lock."""
    _ensure_dir(LOCKS_DIR)

    lock_file = LOCKS_DIR / "global.lock"
    if lock_file.exists():
        return {"success": False, "error": "Global lock already exists"}

    now = datetime.now()
    lock_data = {
        "locked_at": now.isoformat(),
        "locked_by": locked_by,
        "reason": reason,
    }

    _write_yaml(lock_data, lock_file)

    return {
        "success": True,
        "file": str(lock_file),
    }


def unlock_global() -> Dict[str, Any]:
    """Remove the global conversation lock."""
    lock_file = LOCKS_DIR / "global.lock"
    if not lock_file.exists():
        return {"success": False, "error": "No global lock found"}

    lock_file.unlink()
    return {"success": True}


def list_locks() -> Dict[str, Any]:
    """List all conversation lock files with their metadata."""
    locks = []  # type: List[Dict[str, Any]]
    if not LOCKS_DIR.exists():
        return {"success": True, "count": 0, "locks": locks}

    for filepath in sorted(LOCKS_DIR.glob("*.lock")):
        data = _read_yaml(filepath)
        entry = {
            "session_id": filepath.stem,
            "file": str(filepath),
        }
        if data:
            entry["locked_at"] = data.get("locked_at")
            entry["locked_by"] = data.get("locked_by")
            entry["reason"] = data.get("reason")
        locks.append(entry)

    return {"success": True, "count": len(locks), "locks": locks}


# === Pending Reply Management ===

def create_pending_reply(
    conversation_id: str,
    message_id: str,
    to_recipient: str,
    from_sender: str,
    callback_endpoint: Optional[str] = None,
    ttl_seconds: int = 259200,
) -> Dict[str, Any]:
    """Create a pending reply entry. Called when sending with response_required=True."""
    from datetime import timedelta

    _ensure_dir(PENDING_REPLIES_DIR)

    now = datetime.now()
    expires_at = now + timedelta(seconds=ttl_seconds)

    entry = {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "responding_to_msg_id": message_id,
        "to": to_recipient,
        "from": from_sender,
        "callback_endpoint": callback_endpoint,
        "response_required": True,
        "created_at": now.isoformat(),
        "ttl_seconds": ttl_seconds,
        "expires_at": expires_at.isoformat(),
    }

    filename = "pending_{}.yml".format(message_id)
    filepath = _write_yaml(entry, PENDING_REPLIES_DIR / filename)

    return {
        "success": True,
        "pending_file": str(filepath),
    }


def resolve_pending_reply(
    conversation_id: str,
    message_id: str,
    from_sender: str,
) -> Optional[Dict[str, Any]]:
    """Check if an incoming message resolves a pending reply.

    Match requires ALL of:
      1. Entry's responding_to_msg_id matches the provided message_id (exact match)
      2. Entry's conversation_id matches
      3. Entry's 'to' field matches from_sender

    If the exact message_id match fails but conversation_id + from_sender match
    exists, logs a warning (reply is to a different message in the same conversation)
    but does NOT resolve.

    Returns the resolved entry dict, or None if no match.
    """
    if not PENDING_REPLIES_DIR.exists():
        return None

    soft_match_found = False

    for filepath in PENDING_REPLIES_DIR.glob("pending_*.yml"):
        entry = _read_yaml(filepath)
        if not entry:
            continue

        entry_convo = entry.get("conversation_id", "")
        entry_to = entry.get("to", "")
        entry_msg_id = entry.get("responding_to_msg_id", "")

        # Exact match: responding_to_msg_id + conversation_id + from_sender
        if entry_msg_id == message_id and entry_convo == conversation_id and entry_to == from_sender:
            filepath.unlink()
            return entry

        # Track soft matches for warning
        if entry_convo == conversation_id and entry_to == from_sender:
            soft_match_found = True

    if soft_match_found:
        logger.warning(
            "resolve_pending_reply: conversation_id=%s from_sender=%s matched "
            "but responding_to_msg_id did not match message_id=%s -- not resolving",
            conversation_id, from_sender, message_id,
        )

    return None


def list_pending_replies(session: Optional[str] = None) -> Dict[str, Any]:
    """List pending replies. If session specified, only those where 'to' matches session."""
    now = datetime.now()
    entries = []  # type: List[Dict[str, Any]]

    if not PENDING_REPLIES_DIR.exists():
        return {"success": True, "count": 0, "pending": entries}

    for filepath in sorted(PENDING_REPLIES_DIR.glob("pending_*.yml")):
        entry = _read_yaml(filepath)
        if not entry:
            continue

        # Filter expired
        expires_at = entry.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt <= now:
                    continue
            except (ValueError, TypeError):
                pass

        # Filter by session if specified
        if session and entry.get("to") != session:
            continue

        entry["file"] = str(filepath)
        entries.append(entry)

    return {
        "success": True,
        "count": len(entries),
        "pending": entries,
    }


def check_owed_replies(session: Optional[str] = None) -> Dict[str, Any]:
    """Check owed replies. If session given, filter to that session. If None, return all.

    Returns list of pending entries (non-expired only).
    """
    now = datetime.now()
    owed = []  # type: List[Dict[str, Any]]

    if not PENDING_REPLIES_DIR.exists():
        return {"success": True, "count": 0, "owed": owed}

    for filepath in sorted(PENDING_REPLIES_DIR.glob("pending_*.yml")):
        entry = _read_yaml(filepath)
        if not entry:
            continue

        if session and entry.get("to") != session:
            continue

        # Filter expired
        expires_at = entry.get("expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if exp_dt <= now:
                    continue
            except (ValueError, TypeError):
                pass

        entry["file"] = str(filepath)
        owed.append(entry)

    return {
        "success": True,
        "count": len(owed),
        "owed": owed,
    }


# === Search ===

def search_messages(
    query: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Search all messages (inbox + broadcasts + archive) for text in content.

    Case-insensitive substring match against the content field.
    Returns newest first, up to limit results.
    """
    query_lower = query.lower()
    matches = []  # type: List[Dict[str, Any]]

    search_dirs = []  # type: List[Path]

    # Inbox: all recipient subdirs
    if MESSAGES_INBOX.exists():
        for entry in MESSAGES_INBOX.iterdir():
            if entry.is_dir():
                search_dirs.append(entry)

    # Archive: all recipient subdirs
    if MESSAGES_ARCHIVE.exists():
        for entry in MESSAGES_ARCHIVE.iterdir():
            if entry.is_dir():
                search_dirs.append(entry)

    for directory in search_dirs:
        if not directory.exists():
            continue
        for filepath in directory.glob("*.yml"):
            msg = _read_yaml(filepath)
            if not msg or "id" not in msg:
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if query_lower in content.lower():
                preview = content[:150] + ("..." if len(content) > 150 else "")
                matches.append({
                    "id": msg["id"],
                    "type": msg.get("type", "unknown"),
                    "from": msg.get("from", "unknown"),
                    "to": msg.get("to", "unknown"),
                    "created_at": msg.get("created_at", ""),
                    "urgency": msg.get("urgency", ""),
                    "preview": preview,
                    "file": str(filepath),
                })

    # Sort newest first
    matches.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    matches = matches[:limit]

    return {
        "success": True,
        "query": query,
        "count": len(matches),
        "messages": matches,
    }


# === Internal Helpers ===

def _find_message(msg_id: str) -> Optional[Tuple[Path, dict]]:
    """
    Find a message by ID across inbox, broadcasts, and archive.

    Checks exact filename match in broadcasts dir, all recipient subdirs
    under inbox, and all subdirs under archive.
    """
    fname = "{}.yml".format(msg_id)

    # Check broadcasts
    candidate = BROADCASTS_DIR / fname
    if candidate.exists():
        msg = _read_yaml(candidate)
        if msg:
            return (candidate, msg)

    # Check all recipient subdirs under inbox
    for search_dir in (MESSAGES_INBOX, MESSAGES_ARCHIVE):
        if search_dir.exists():
            for entry in search_dir.iterdir():
                if entry.is_dir():
                    candidate = entry / fname
                    if candidate.exists():
                        msg = _read_yaml(candidate)
                        if msg:
                            return (candidate, msg)

    return None


# =========================================================================
# Display / Formatting Helpers (shared by REPL and potential CLI callers)
# =========================================================================

def format_relative_time(iso_str: str) -> str:
    """Return a human-friendly relative time string for an ISO datetime."""
    try:
        dt = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return iso_str
    now = datetime.now()
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "in the future"
    if seconds < 60:
        return "{}s ago".format(seconds)
    minutes = seconds // 60
    if minutes < 60:
        return "{}m ago".format(minutes)
    hours = minutes // 60
    if hours < 24:
        return "{}h ago".format(hours)
    days = hours // 24
    if days < 30:
        return "{}d ago".format(days)
    return dt.strftime("%Y-%m-%d %H:%M")


def format_timestamp(iso_str: str) -> str:
    """Format an ISO timestamp for display: YYYY-MM-DD HH:MM:SS (relative)."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return "{} ({})".format(dt.strftime("%Y-%m-%d %H:%M:%S"), format_relative_time(iso_str))
    except (ValueError, TypeError):
        return str(iso_str)


# === Session name resolution (lazy-loaded) ===

_store = None  # type: Any
_store_loaded = False


def _load_store() -> Any:
    """Lazy-load SessionStore. Returns the store or None."""
    global _store, _store_loaded
    if _store_loaded:
        return _store
    _store_loaded = True
    try:
        _sm_path = str(AI_SCRIPTS / "session_mgmt")
        if _sm_path not in sys.path:
            sys.path.insert(0, _sm_path)
        from uai_toolkit.session_mgmt.session_store import SessionStore  # type: ignore
        _store = SessionStore()
    except ImportError:
        pass
    except Exception:
        pass
    return _store


def _get_display_name(tracking_id: str) -> Optional[str]:
    """Look up the display name for a tracking_id via SessionStore."""
    store = _load_store()
    if store is None:
        return None
    try:
        session = store.get(tracking_id)
        if session:
            return session.get("display_name")
    except Exception:
        pass
    return None


def _resolve_session(ref: str) -> Optional[str]:
    """Resolve a session reference to a tracking_id.

    Accepts:
    - tracking ID, display name, CLI UUID, UUID prefix (via SessionStore)
    - prompt://target/session URI (extracts session component)
    - Raw string (returned as-is if unresolvable)
    """
    # Handle prompt:// URIs — extract session ID from path
    if "://" in ref:
        try:
            from uai_toolkit.callbacks.callback_lib import parse_endpoint
            ep = parse_endpoint(ref)
            if ep.scheme == "prompt" and ep.session:
                ref = ep.session
            elif ep.scheme == "prompt" and ep.path:
                ref = ep.path
        except Exception:
            pass

    store = _load_store()
    if store is None:
        return ref
    try:
        session = store.resolve(ref)
        if session:
            return session.get("tracking_id", ref)
    except Exception:
        pass
    return ref


def _resolve_recipient_strict(ref: str) -> tuple:
    """Resolve a single recipient to a canonical tracking_id, strictly.

    Returns (tracking_id, None) on success, or (None, error_message) on a miss
    or when the session store is unavailable. Unlike _resolve_session it NEVER
    falls back to the raw key — a delivery to an unverified key is a silent loss,
    so the send is rejected back to the sender instead.
    """
    orig = ref
    if "://" in ref:
        try:
            from uai_toolkit.callbacks.callback_lib import parse_endpoint
            ep = parse_endpoint(ref)
            if ep.scheme == "prompt" and (ep.session or ep.path):
                ref = ep.session or ep.path
        except Exception:
            pass

    store = _load_store()
    if store is None:
        return None, (
            "session store unavailable — cannot resolve recipient {!r} "
            "(refusing to deliver to an unverified key)".format(orig)
        )
    try:
        session = store.resolve(ref)
    except Exception as e:
        return None, "recipient resolution failed for {!r}: {}".format(orig, e)
    if session and session.get("tracking_id"):
        return session["tracking_id"], None
    # The session store missed. Fall back to the canonical resolver, which also
    # honors the user registry — so a bare registered-user handle (e.g.
    # "piano_man") delivers to the user's inbox. Without this, reply / reply-all
    # to the user fail here (the session store has no user record), which is why
    # answering the user threaded as a new conversation via the send path instead
    # (todo_0502 fixed the send path; this brings reply to parity).
    try:
        from uai_toolkit.messages.lib_identity_resolve import resolve_recipient as _rr
        target = _rr(orig)
        if target.get("kind") == "user" and target.get("entity_id"):
            return target["entity_id"], None
        if target.get("kind") == "session" and target.get("tracking_id"):
            return target["tracking_id"], None
    except Exception:
        pass  # fall through to the strict rejection below
    return None, (
        "unresolvable recipient: {!r} — provide a known tracking_id, display "
        "name, CLI UUID, or prompt:// URI".format(orig)
    )


def _to_endpoint_uri(ref: str) -> Optional[str]:
    """If ref is already a URI, return it. Otherwise return None."""
    if "://" in ref:
        return ref
    return None


def _session_label(tracking_id: str) -> str:
    """Return 'DisplayName (tracking_id)' or just tracking_id."""
    name = _get_display_name(tracking_id)
    if name:
        return "{} ({})".format(name, tracking_id)
    return tracking_id


# === Read status helpers ===

def _is_read_by(msg: dict, session: str) -> bool:
    """Check if a message has been read by the given session."""
    read_by = msg.get("read_by", [])
    return any(entry.get("by") == session for entry in read_by)


# === Index map -- temp indices for REPL inbox results ===

VALID_FOLDERS = ("inbox", "sent", "archive", "broadcasts")


def parse_index_range(spec: str, max_idx: int) -> list[int]:
    """Parse index range specs like 1-5, 1,3,5, 1-3,7, 5- into 0-based indices.

    Input uses 1-based indices. Returns sorted unique 0-based indices.
    """
    indices = set()
    for part in spec.split(","):
        part = part.strip().lstrip("#")
        if not part:
            continue
        if "-" in part:
            pieces = part.split("-", 1)
            start_str, end_str = pieces[0].strip(), pieces[1].strip()
            start = int(start_str) - 1 if start_str else 0
            end = int(end_str) - 1 if end_str else max_idx - 1
            for i in range(max(start, 0), min(end + 1, max_idx)):
                indices.add(i)
        else:
            idx = int(part) - 1
            if 0 <= idx < max_idx:
                indices.add(idx)
    return sorted(indices)


class IndexMap:
    """Manages temporary index-to-message-ID mapping from the last listing."""

    def __init__(self):
        self._ids = []  # type: List[str]
        self._messages = []  # type: List[dict]

    def assign(self, messages: List[dict]) -> None:
        """Assign indices to a list of messages."""
        self._ids = [m.get("id", "") for m in messages]
        self._messages = list(messages)

    def count(self) -> int:
        return len(self._ids)

    def resolve_range(self, spec: str) -> list[str]:
        """Resolve an index range spec to message IDs."""
        indices = parse_index_range(spec, len(self._ids))
        return [self._ids[i] for i in indices if i < len(self._ids)]

    def resolve(self, ref: str) -> Optional[str]:
        """Resolve a ref to a message ID. Accepts #N, N, or raw msg_id."""
        ref = ref.strip().lstrip("#")
        # Try as index
        try:
            idx = int(ref) - 1  # 1-based
            if 0 <= idx < len(self._ids):
                return self._ids[idx]
        except ValueError:
            pass
        # Try as raw message ID
        if ref.startswith("msg_") or ref.startswith("conv_"):
            return ref
        # Check if it matches any stored id
        for mid in self._ids:
            if mid == ref:
                return mid
        return ref  # return as-is, let business logic handle it

    def get_message(self, ref: str) -> Optional[dict]:
        """Get the cached message dict for a ref."""
        ref = ref.strip().lstrip("#")
        try:
            idx = int(ref) - 1
            if 0 <= idx < len(self._messages):
                return self._messages[idx]
        except ValueError:
            pass
        for m in self._messages:
            if m.get("id") == ref:
                return m
        return None

    def get_conversation_id(self, ref: str) -> Optional[str]:
        """Get the conversation_id for a ref (from cached message)."""
        msg = self.get_message(ref)
        if msg:
            return msg.get("conversation_id")
        return None


# =========================================================================
# REPL Display Helpers
# =========================================================================

def format_message_list(messages: List[dict], session: str, imap: IndexMap,
                        empty_label: str = "no messages") -> str:
    """Format a list of messages for human display. Returns the formatted string."""
    imap.assign(messages)
    if not messages:
        return "  ({})".format(empty_label)
    lines = []
    for i, msg in enumerate(messages, 1):
        is_read = _is_read_by(msg, session)
        if is_read:
            status_str = _c(_D, "[read]")
        else:
            status_str = _c(_Y + _B, "[unread]")
        msg_id = msg.get("id", "???")
        sender = msg.get("from", "???")
        sender_name = _get_display_name(sender) or sender
        created = msg.get("created_at", "")
        rel = format_relative_time(created) if created else ""
        preview = msg.get("preview", msg.get("content", ""))
        if isinstance(preview, str) and len(preview) > 50:
            preview = preview[:50] + "..."
        preview_str = '"{}"'.format(preview) if preview else ""
        lines.append("  {} {} {} {}{} {} {}".format(
            _c(_BY, "#{}".format(i)),
            status_str,
            _c(_D, msg_id),
            _c(_D, "from:"),
            _c(_C, sender_name),
            _c(_D, rel),
            _c(_W, preview_str),
        ))
    return "\n".join(lines)


def format_message_detail(msg: dict) -> str:
    """Format a single message for detailed human display. Returns the formatted string."""
    msg_id = msg.get("id", "???")
    sender = msg.get("from", "???")
    recipient = msg.get("to", "???")
    created = msg.get("created_at", "")
    urgency = msg.get("urgency", "")
    convo_id = msg.get("conversation_id", "")
    replying_to = msg.get("replying_to", "")
    content = msg.get("content", "")
    msg_type = msg.get("type", "direct")

    # Format urgency with color
    if urgency == "interrupt":
        urgency_str = _c(_RED + _B, urgency)
    elif urgency == "prompt":
        urgency_str = _c(_Y, urgency)
    elif urgency == "async":
        urgency_str = _c(_D, urgency)
    else:
        urgency_str = str(urgency)

    lines = []
    lines.append("")
    lines.append(_c(_D, "=" * 50))
    lines.append("  Message {}".format(_c(_D, msg_id)))
    lines.append(_c(_D, "=" * 50))
    lines.append("  {}      {}".format(_c(_G, "From:"), _c(_W, _session_label(sender))))
    lines.append("  {}        {}".format(_c(_G, "To:"), _c(_W, _session_label(recipient) if recipient != "all" else "all (broadcast)")))
    lines.append("  {}      {}".format(_c(_G, "Type:"), _c(_W, msg_type)))
    lines.append("  {}      {}".format(_c(_G, "Sent:"), _c(_W, format_timestamp(created) if created else "(unknown)")))
    lines.append("  {}   {}".format(_c(_G, "Urgency:"), urgency_str))
    if convo_id:
        lines.append("  {}    {}".format(_c(_G, "Thread:"), _c(_W, convo_id)))
    lines.append("  {}  {}".format(_c(_G, "Reply to:"), _c(_W, replying_to if replying_to else "(none)")))

    read_by = msg.get("read_by", [])
    if read_by:
        readers = ", ".join(entry.get("by", "?") for entry in read_by)
        lines.append("  {}   {}".format(_c(_G, "Read by:"), _c(_W, readers)))

    acks = msg.get("acknowledgments", [])
    if acks:
        ackers = ", ".join(entry.get("by", "?") for entry in acks)
        lines.append("  {}  {}".format(_c(_G, "Acked by:"), _c(_W, ackers)))

    resp_req = msg.get("response_required", False)
    if resp_req:
        lines.append("  {}  {}".format(_c(_G, "Response:"), _c(_RED + _B, "REQUIRED")))

    lines.append("  " + _c(_D, "-" * 48))
    if isinstance(content, str):
        for line in content.splitlines():
            lines.append("  {}".format(line))
    else:
        lines.append("  {}".format(content))
    lines.append("  " + _c(_D, "-" * 48))
    lines.append("")
    return "\n".join(lines)


# =========================================================================
# REPL Search (searches more fields than the CLI search_messages)
# =========================================================================

def _repl_search_messages(text: str) -> List[dict]:
    """Search all inbox and broadcast messages for text in content/from/to/id."""
    results = []  # type: List[dict]
    text_lower = text.lower()

    # Search broadcasts
    if BROADCASTS_DIR.exists():
        for filepath in BROADCASTS_DIR.glob("*.yml"):
            msg = _read_yaml(filepath)
            if msg and _msg_matches(msg, text_lower):
                results.append(msg)

    # Search all inbox subdirs
    if MESSAGES_INBOX.exists():
        for entry in MESSAGES_INBOX.iterdir():
            if entry.is_dir() and entry.name != "broadcasts":
                for filepath in entry.glob("*.yml"):
                    msg = _read_yaml(filepath)
                    if msg and _msg_matches(msg, text_lower):
                        results.append(msg)

    # Sort newest first
    results.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return results


def _msg_matches(msg: dict, text_lower: str) -> bool:
    """Check if any searchable field in a message matches the text."""
    for field in ("id", "from", "to", "content", "conversation_id"):
        val = msg.get(field, "")
        if isinstance(val, str) and text_lower in val.lower():
            return True
    return False


# =========================================================================
# REPL Thread Display
# =========================================================================

def _show_thread(conversation_id: str, session: str) -> None:
    """Show all messages in a conversation thread."""
    thread_msgs = []  # type: List[dict]

    # Search all inbox subdirs
    if MESSAGES_INBOX.exists():
        for entry in MESSAGES_INBOX.iterdir():
            if entry.is_dir():
                for filepath in entry.glob("*.yml"):
                    msg = _read_yaml(filepath)
                    if msg and msg.get("conversation_id") == conversation_id:
                        thread_msgs.append(msg)

    # Also check archive
    if MESSAGES_ARCHIVE.exists():
        for entry in MESSAGES_ARCHIVE.iterdir():
            if entry.is_dir():
                for filepath in entry.glob("*.yml"):
                    msg = _read_yaml(filepath)
                    if msg and msg.get("conversation_id") == conversation_id:
                        thread_msgs.append(msg)

    # Deduplicate by id
    seen = set()  # type: set
    unique = []  # type: List[dict]
    for m in thread_msgs:
        mid = m.get("id", "")
        if mid not in seen:
            seen.add(mid)
            unique.append(m)

    unique.sort(key=lambda m: m.get("created_at", ""))

    if not unique:
        print("  {}".format(_c(_D, "No messages found for conversation {}".format(conversation_id))))
        return

    print()
    print("  {} {}  ({} messages)".format(_c(_B, "Thread:"), _c(_D, conversation_id), len(unique)))
    print("  " + _c(_D, "=" * 48))
    for msg in unique:
        sender = msg.get("from", "???")
        sender_name = _get_display_name(sender) or sender
        created = msg.get("created_at", "")
        content = msg.get("content", "")
        is_read = _is_read_by(msg, session)
        if is_read:
            status_str = _c(_D, "[read]")
        else:
            status_str = _c(_Y + _B, "[unread]")
        print()
        print("  {} {} | {} | {}".format(
            status_str,
            _c(_D, msg.get("id", "???")),
            _c(_C, sender_name),
            _c(_D, format_timestamp(created)) if created else "",
        ))
        print("  " + _c(_D, "-" * 48))
        if isinstance(content, str):
            for line in content.splitlines():
                print("    {}".format(line))
        else:
            print("    {}".format(content))
    print()


# =========================================================================
# REPL Help Text
# =========================================================================

def _brief_help(has_session: bool = True):
    # type: (bool) -> str
    """Generate brief help with color support, context-aware."""
    def _cmd(name, desc):
        # type: (str, str) -> str
        return "  {:<30} {}".format(_c(_C, name), _c(_D, desc))
    lines = [_c(_B, "Messaging REPL Commands:")]

    lines.append("")
    lines.append(_c(_B, "Identity:"))
    lines.append(_cmd("whoami", "Show full session identity"))
    lines.append(_cmd("as <id_or_name>", "Switch session scope"))
    lines.append(_cmd("as none | as all", "Clear session scope"))

    if has_session:
        lines.append("")
        lines.append(_c(_B, "Folders:"))
        lines.append(_cmd("cd [folder]", "Switch folder (inbox, sent, archive, broadcasts)"))
        lines.append("")
        lines.append(_c(_B, "Messages:"))
        lines.append(_cmd("ls [unread|read|all]", "List messages in current folder"))
        lines.append(_cmd("read [#|all] [--incl-read]", "Read message(s); no args = first unread"))
        lines.append(_cmd("mark-as <read|unread> <range>", "Mark messages (e.g. 1-3, 2,5, 4-)"))
        lines.append(_cmd("archive <range>", "Move to archive (alias: mv --to archive)"))
        lines.append(_cmd("mv --to <folder> <range>", "Move messages between folders"))
        lines.append("")
        lines.append(_c(_B, "Sending:"))
        lines.append(_cmd("send <recipient> <msg>", "Send direct message"))
        lines.append(_cmd("reply <#> <msg>", "Reply to a message"))
        lines.append(_cmd("reply-all <#> <msg>", "Reply to all participants"))
        lines.append(_cmd("broadcast <msg>", "Broadcast to all sessions"))
        lines.append(_cmd("thread <#>", "Show all messages in a thread"))
        lines.append("")
        lines.append(_c(_B, "Status:"))
        lines.append(_cmd("check [-a]", "Unread counts (-a: all sessions)"))
        lines.append(_cmd("owed", "Replies this session owes"))
        lines.append(_cmd("pending", "Replies this session awaits"))
        lines.append(_cmd("list-sessions [opts] [pat]", "List sessions (--with-msgs, --with-unread)"))
        lines.append("")
        lines.append(_c(_B, "Other:"))
        lines.append(_cmd("standing", "Show standing messages"))
        lines.append(_cmd("post-standing <scope> <msg>", "Post standing message"))
        lines.append(_cmd("lock [session_id]", "Lock session"))
        lines.append(_cmd("unlock [session_id]", "Unlock session"))
        lines.append(_cmd("locks", "List all active locks"))
    else:
        lines.append("")
        lines.append(_c(_B, "Available without session scope:"))
        lines.append(_cmd("check --all", "Unread counts across all sessions"))
        lines.append(_cmd("list-sessions [pat]", "List sessions (--with-msgs, --with-unread)"))
        lines.append(_cmd("owed", "All owed replies (global)"))
        lines.append(_cmd("pending", "All pending replies (global)"))
        lines.append(_cmd("search <text>", "Search messages for text"))
        lines.append(_cmd("locks", "List all active locks"))
        lines.append("")
        lines.append(_c(_D, "  Set a session with 'as <name>' to unlock all commands."))

    lines.append("")
    lines.append(_cmd("search [scope] [filter] <text>", "Search (all_sessions, all_folders, read, unread)"))
    lines.append(_cmd("help [--verbose]", "This help (--verbose for details)"))
    lines.append(_cmd("quit / q / Ctrl-D", "Exit"))
    return "\n".join(lines)


BRIEF_HELP = None  # generated lazily to respect _sc_colors_enabled() at call time

def _verbose_help():
    # type: () -> str
    """Generate verbose help with color support."""
    def _hdr(text):
        # type: (str,) -> str
        return _c(_B, text)
    def _cmd(name):
        # type: (str,) -> str
        return "  {}".format(_c(_C, name))
    def _desc(text):
        # type: (str,) -> str
        return "      {}".format(_c(_D, text))
    lines = [
        _hdr("Messaging REPL -- Full Command Reference"),
        _c(_D, "=" * 41),
        "",
        _hdr("IDENTITY"),
        _cmd("whoami"),
        _desc("Show current session identity (tracking_id, display_name)."),
        "",
        _cmd("as <tracking_id_or_name>"),
        _desc("Switch identity to act as a different session. Resolves display"),
        _desc("names and partial tracking IDs via SessionStore if available."),
        "",
        _hdr("INBOX"),
        _cmd("check"),
        _desc("Show unread counts (inbox + broadcasts). Also fires on empty Enter."),
        "",
        _cmd("inbox [--all]"),
        _desc("List messages. Default: unread only. --all: include read messages."),
        _desc("Assigns temporary indices (#1, #2, ...) for use with read/reply/archive."),
        "",
        _cmd("read <id_or_#index>"),
        _desc("Read full message and mark as read. Accepts temp index (#N or N)"),
        _desc("or raw message ID."),
        "",
        _cmd("archive <id_or_#index>"),
        _desc("Move a message to archive."),
        "",
        _hdr("SENDING"),
        _cmd("send <recipient> <message...>"),
        _desc("Send a direct message. Recipient can be a tracking_id or display name."),
        _desc("Multi-word message does not need quotes."),
        "",
        _cmd("reply <id_or_#index> <message...>"),
        _desc("Reply to a message. Sets replying_to and conversation_id automatically."),
        "",
        _cmd("reply-all <id_or_#index> <message...>"),
        _desc("Reply to all participants of a message."),
        "",
        _cmd("broadcast <message...>"),
        _desc("Send a broadcast message to all active sessions."),
        "",
        _hdr("THREADS"),
        _cmd("thread <conversation_id_or_#index>"),
        _desc("Show all messages in a conversation thread. Accepts a conversation_id"),
        _desc("or a temp index (uses the conversation_id from that indexed message)."),
        "",
        _hdr("PENDING REPLIES"),
        _cmd("owed"),
        _desc("Show replies this session owes (messages requiring response)."),
        "",
        _cmd("pending"),
        _desc("Show replies this session is waiting for."),
        "",
        _hdr("STANDING MESSAGES"),
        _cmd("standing"),
        _desc("Show standing messages for current session (global + platform scopes)."),
        "",
        _cmd("post-standing <scope> <message...>"),
        _desc("Post a standing message. Scope: global, team/NAME, platform/NAME,"),
        _desc("project/NAME. Example: post-standing platform/claude_cli Reboot tonight"),
        "",
        _hdr("LOCKS"),
        _cmd("lock [session_id]"),
        _desc("Lock current or specified session."),
        "",
        _cmd("unlock [session_id]"),
        _desc("Unlock current or specified session."),
        "",
        _cmd("locks"),
        _desc("List all active locks."),
        "",
        _hdr("CROSS-SESSION VIEWS"),
        _cmd("sessions"),
        _desc("List sessions with unread message counts."),
        "",
        _cmd("all-unread"),
        _desc("Show unread counts across ALL sessions."),
        "",
        _cmd("search <text>"),
        _desc("Search all messages (inbox + broadcasts) for text in content,"),
        _desc("sender, recipient, or message ID."),
        "",
        _hdr("UTILITY"),
        "  {}               {}".format(_c(_C, "help"), _c(_D, "Show brief command list")),
        "  {}     {}".format(_c(_C, "help --verbose"), _c(_D, "Show this full reference")),
        "  {}    {}".format(_c(_C, "quit / exit / q"), _c(_D, "Exit (also Ctrl-D)")),
    ]
    return "\n".join(lines)


VERBOSE_HELP = None  # generated lazily to respect _sc_colors_enabled() at call time


# =========================================================================
# REPL Core
# =========================================================================

def _cmd_check(session: str) -> None:
    """Run the 'check' command for REPL."""
    result = check_unread(session=session)
    inbox = result.get("inbox_unread", 0)
    bcast = result.get("broadcast_unread", 0)
    total = result.get("total_unread", 0)
    if total == 0:
        print("  {}".format(_c(_G, "No unread messages.")))
    else:
        print("  {}: {} {}, {} {} ({} {})".format(
            _c(_D, "Unread"),
            _c(_Y + _B, inbox), _c(_D, "inbox"),
            _c(_Y + _B, bcast), _c(_D, "broadcast"),
            _c(_Y + _B, total), _c(_D, "total"),
        ))


_session_completer = None  # lazy-init in repl()


def repl(identity: Optional[str] = None) -> int:
    """Run the interactive messaging REPL."""
    imap = IndexMap()
    current_session = identity or ""  # type: str
    current_folder = "inbox"  # type: str

    from uai_toolkit.common_utils.lib_readline import setup_readline, make_session_completer
    setup_readline(completer=make_session_completer())

    def prompt_str() -> str:
        if not _sc_colors_enabled():
            if not current_session:
                return "msg:*> "
            name = _get_display_name(current_session)
            label = name if name else current_session
            if len(label) > 30:
                label = label[:27] + "..."
            return "msg:{}/{}> ".format(label, current_folder)

        # Use raw ANSI for color, \001/\002 wrappers for readline width calc.
        # Some terminals strip content inside \001..\002 entirely, so we
        # build both: a raw-ANSI version for display, wrapped version for
        # readline. If the wrapped version doesn't render, fall back to raw.
        if not current_session:
            raw = "{D}msg{BY}:*{R}> ".format(D=_D, BY=_BY, R=_R)
        else:
            name = _get_display_name(current_session)
            label = name if name else current_session
            if len(label) > 30:
                label = label[:27] + "..."
            raw = "{D}msg:{R}{B}{BY}{label}{R}{D}/{R}{M}{folder}{R}{D}>{R} ".format(
                D=_D, R=_R, B=_B, BY=_BY, M=_M,
                label=label, folder=current_folder,
            )
        return raw

    # Welcome
    print("{} -- type 'help' for commands, 'q' to quit".format(_c(_B, "Messaging REPL")))
    if current_session:
        print("{} {}".format(_c(_D, "Identity:"), _c(_BG, _session_label(current_session))))
    else:
        print("{} {}".format(_c(_D, "Identity:"), _c(_Y, "(none) — use 'as <name>' to set")))

    # Initial check
    if current_session:
        result = check_unread(session=current_session)
        inbox_unread = result.get("inbox_unread", 0)
        broadcast_unread = result.get("broadcast_unread", 0)
        total = result.get("total_unread", 0)
        if total > 0:
            print("{}: {} {}, {} {}".format(
                _c(_D, "Unread"),
                _c(_Y + _B, inbox_unread), _c(_D, "inbox"),
                _c(_Y + _B, broadcast_unread), _c(_D, "broadcast"),
            ))
        else:
            print(_c(_G, "No unread messages."))
    print()

    while True:
        try:
            line = input(prompt_str()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            if current_session:
                _cmd_check(current_session)
            else:
                print("  {}".format(_c(_Y, "No identity set. Use 'as <name>' to set one.")))
            continue

        # Parse command
        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print("  {}".format(_c(_RED, "Parse error: {}".format(e))))
            continue

        if not tokens:
            continue

        cmd = tokens[0].lower()
        rest_tokens = tokens[1:]
        rest_str = line[len(tokens[0]):].strip()

        # Commands that work without identity
        _NO_IDENTITY_CMDS = {"quit", "exit", "q", "help", "as", "whoami",
                             "broadcasts", "search", "find", "sessions", "list-sessions",
                             "locks", "owed", "pending"}
        # check --all works without identity too
        if cmd == "check" and ("--all" in rest_tokens or "-a" in rest_tokens):
            pass  # allow through
        elif not current_session and cmd not in _NO_IDENTITY_CMDS:
            print("  {}".format(_c(_Y, "No session scope. Use 'as <name>' first.")))
            continue

        # ----- Exit -----
        if cmd in ("quit", "exit", "q"):
            break

        # ----- Help -----
        elif cmd == "help":
            if "--verbose" in rest_tokens:
                print(_verbose_help())
            else:
                print(_brief_help(has_session=bool(current_session)))

        # ----- Identity -----
        elif cmd == "whoami":
            if not current_session:
                print("  {}".format(_c(_D, "(no session scope set)")))
            else:
                # Resolve full identity from session store
                _session_info = None
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "session_mgmt"))
                    from uai_toolkit.session_mgmt.session_store import SessionStore as _SS
                    _session_info = _SS().resolve(current_session)
                except Exception:
                    pass
                if _session_info:
                    print("  {} {}".format(_c(_D, "Tracking ID:  "), _c(_BC, _session_info.get("tracking_id", ""))))
                    print("  {} {}".format(_c(_D, "CLI UUID:     "), _c(_C, _session_info.get("cli_session_id", "") or "(none)")))
                    print("  {} {}".format(_c(_D, "Terminal:     "), _c(_C, _session_info.get("terminal_session", "") or "(none)")))
                    print("  {} {}".format(_c(_D, "Display Name: "), _c(_BG, _session_info.get("display_name", "") or "(none)")))
                    print("  {} {}".format(_c(_D, "Platform:     "), _c(_C, _session_info.get("platform", "") or "(none)")))
                else:
                    print("  {} {}".format(_c(_D, "session:"), _c(_BC, current_session)))
                    print("  {}".format(_c(_D, "(not found in session store)")))

        elif cmd == "as":
            if not rest_str:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "as <tracking_id_or_name>")))
                continue
            if rest_str.lower() in ("none", "all", "*"):
                current_session = ""
                current_folder = "inbox"
                print("  {}".format(_c(_Y, "Session scope cleared.")))
            else:
                resolved = _resolve_session(rest_str)
                if resolved:
                    current_session = resolved
                    current_folder = "inbox"
                    print("  {} {}".format(_c(_D, "Now acting as:"), _c(_BG, _session_label(current_session))))
                else:
                    print("  {}".format(_c(_RED, "Could not resolve: {}".format(rest_str))))

        # ----- Check -----
        elif cmd == "check":
            show_all = "--all" in rest_tokens or "-a" in rest_tokens
            if show_all:
                # Cross-session unread counts
                result = check_unread()
                sessions_data = result.get("sessions", {})
                bcast = result.get("broadcast_unread", 0)
                total = result.get("total_unread", 0)
                print("  {} {}".format(_c(_D, "Total unread:"), _c(_Y + _B, total) if total > 0 else _c(_G, total)))
                if sessions_data:
                    for sid, count in sorted(sessions_data.items()):
                        label = _session_label(sid)
                        print("    {}: {}".format(_c(_C, label), _c(_Y + _B, count)))
                if bcast > 0:
                    print("    {}: {}".format(_c(_D, "broadcasts"), _c(_Y + _B, bcast)))
            else:
                _cmd_check(current_session)

        # ----- cd (change folder) -----
        elif cmd == "cd":
            target = rest_tokens[0].lower() if rest_tokens else "inbox"
            if target not in VALID_FOLDERS:
                print("  {} Folders: {}".format(_c(_RED, "Unknown folder."), ", ".join(VALID_FOLDERS)))
            else:
                current_folder = target
                print("  {} {}".format(_c(_D, "Folder:"), _c(_BC, current_folder)))

        # ----- List / ls -----
        elif cmd in ("list", "ls", "inbox"):
            # Parse options: read, unread, all, -a, --all
            filter_mode = "unread"
            for t in rest_tokens:
                tl = t.lower()
                if tl in ("--all", "-a", "all"):
                    filter_mode = "all"
                elif tl == "read":
                    filter_mode = "read"
                elif tl == "unread":
                    filter_mode = "unread"

            if current_folder == "inbox":
                inbox_result = list_messages(dir_name="inbox", recipient=current_session, limit=50)
                bcast_result = list_messages(dir_name="broadcasts", limit=50)
                all_msgs = inbox_result.get("messages", []) + bcast_result.get("messages", [])
            elif current_folder == "broadcasts":
                bcast_result = list_messages(dir_name="broadcasts", limit=50)
                all_msgs = bcast_result.get("messages", [])
            elif current_folder == "sent":
                sent_result = list_sent(sender=current_session, limit=50)
                all_msgs = sent_result.get("messages", [])
            elif current_folder == "archive":
                arch_result = list_archived(recipient=current_session, limit=50)
                all_msgs = arch_result.get("messages", [])
            else:
                all_msgs = []

            all_msgs.sort(key=lambda m: m.get("created_at", ""), reverse=True)

            if filter_mode == "unread":
                all_msgs = [m for m in all_msgs if not _is_read_by(m, current_session)]
            elif filter_mode == "read":
                all_msgs = [m for m in all_msgs if _is_read_by(m, current_session)]

            empty_label = {"unread": "no unread messages in {}".format(current_folder),
                           "read": "no read messages in {}".format(current_folder),
                           "all": "no messages in {}".format(current_folder)}.get(filter_mode, "no messages")
            print(format_message_list(all_msgs, current_session, imap, empty_label=empty_label))

        # ----- mark-as -----
        elif cmd == "mark-as":
            if len(rest_tokens) < 2:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "mark-as <read|unread> <index_range>")))
                continue
            state = rest_tokens[0].lower()
            if state not in ("read", "unread"):
                print("  {}".format(_c(_RED, "State must be 'read' or 'unread'")))
                continue
            msg_ids = imap.resolve_range(rest_tokens[1])
            if not msg_ids:
                print("  {}".format(_c(_RED, "No messages matched that range.")))
                continue
            for mid in msg_ids:
                result = mark_as(msg_id=mid, reader=current_session, state=state)
                if result.get("success"):
                    if result.get("no_change"):
                        print("  {} {} {}".format(_c(_D, mid), _c(_D, "already"), _c(_D, state)))
                    else:
                        color = _G if state == "read" else _Y
                        print("  {} {}".format(_c(color, "marked " + state + ":"), _c(_D, mid)))
                else:
                    print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "?")))))

        # ----- mv / move -----
        elif cmd in ("mv", "move"):
            # Parse: mv [--from SRC] --to DST <index_range>
            # Or: mv <index_range> [--from SRC] --to DST
            from_folder = current_folder
            to_folder = None
            range_spec = None
            i_t = 0
            while i_t < len(rest_tokens):
                tok = rest_tokens[i_t]
                if tok == "--from" and i_t + 1 < len(rest_tokens):
                    from_folder = rest_tokens[i_t + 1].lower()
                    i_t += 2
                elif tok == "--to" and i_t + 1 < len(rest_tokens):
                    to_folder = rest_tokens[i_t + 1].lower()
                    i_t += 2
                else:
                    range_spec = tok
                    i_t += 1
            if not to_folder or not range_spec:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "mv --to <folder> <index_range>")))
                continue
            msg_ids = imap.resolve_range(range_spec)
            if not msg_ids:
                print("  {}".format(_c(_RED, "No messages matched that range.")))
                continue
            for mid in msg_ids:
                result = move_message(msg_id=mid, to_folder=to_folder, recipient=current_session, from_folder=from_folder)
                if result.get("success"):
                    print("  {} {} {}".format(_c(_G, "moved:"), _c(_D, mid), _c(_D, "-> " + to_folder)))
                else:
                    print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "?")))))

        # ----- archive (alias for move --to archive) -----
        elif cmd == "archive":
            if not rest_tokens:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "archive <index_range>")))
                continue
            msg_ids = imap.resolve_range(rest_tokens[0])
            if not msg_ids:
                # Fall back to single resolve for backwards compat
                mid = imap.resolve(rest_tokens[0])
                if mid:
                    msg_ids = [mid]
            for mid in msg_ids:
                result = move_message(msg_id=mid, to_folder="archive", recipient=current_session)
                if result.get("success"):
                    print("  {} {}".format(_c(_G, "archived:"), _c(_D, mid)))
                else:
                    print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "?")))))

        # ----- Read -----
        elif cmd == "read":
            if not rest_tokens:
                # No params: read first unread message in current folder listing
                # Re-fetch current folder's unread messages
                if current_folder == "inbox":
                    _ir = list_messages(dir_name="inbox", recipient=current_session, limit=50)
                    _br = list_messages(dir_name="broadcasts", limit=50)
                    _msgs = _ir.get("messages", []) + _br.get("messages", [])
                elif current_folder == "broadcasts":
                    _msgs = list_messages(dir_name="broadcasts", limit=50).get("messages", [])
                elif current_folder == "archive":
                    _msgs = list_archived(recipient=current_session, limit=50).get("messages", [])
                else:
                    _msgs = []
                _msgs.sort(key=lambda m: m.get("created_at", ""))
                _unread = [m for m in _msgs if not _is_read_by(m, current_session)]
                if not _unread:
                    print("  {}".format(_c(_D, "No unread messages in {}.".format(current_folder))))
                else:
                    mid = _unread[0].get("id", "")
                    result = read_message(msg_id=mid, reader=current_session)
                    if result.get("success"):
                        print(format_message_detail(result.get("message", {})))
                    else:
                        print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "?")))))
                continue

            first_tok = rest_tokens[0].lower()
            incl_read = "--incl-read" in rest_tokens or "-a" in rest_tokens

            if first_tok == "all":
                # read all: show all unread (or all with --incl-read)
                if current_folder == "inbox":
                    _ir = list_messages(dir_name="inbox", recipient=current_session, limit=200)
                    _br = list_messages(dir_name="broadcasts", limit=200)
                    _msgs = _ir.get("messages", []) + _br.get("messages", [])
                elif current_folder == "broadcasts":
                    _msgs = list_messages(dir_name="broadcasts", limit=200).get("messages", [])
                elif current_folder == "archive":
                    _msgs = list_archived(recipient=current_session, limit=200).get("messages", [])
                else:
                    _msgs = []
                _msgs.sort(key=lambda m: m.get("created_at", ""))
                if not incl_read:
                    _msgs = [m for m in _msgs if not _is_read_by(m, current_session)]
                if not _msgs:
                    label = "no messages" if incl_read else "no unread messages"
                    print("  {}".format(_c(_D, "{} in {}.".format(label, current_folder))))
                else:
                    for m in _msgs:
                        mid = m.get("id", "")
                        result = read_message(msg_id=mid, reader=current_session)
                        if result.get("success"):
                            print(format_message_detail(result.get("message", {})))
                            print()
                        else:
                            print("  {}".format(_c(_RED, "Error reading {}: {}".format(mid, result.get("error", "?")))))
            else:
                # read <index_or_id>
                msg_id = imap.resolve(rest_tokens[0])
                result = read_message(msg_id=msg_id, reader=current_session)
                if result.get("success"):
                    print(format_message_detail(result.get("message", {})))
                else:
                    print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Archive -----
        elif cmd == "archive":
            if not rest_tokens:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "archive <id_or_#index>")))
                continue
            msg_id = imap.resolve(rest_tokens[0])
            result = archive_message(msg_id=msg_id)
            if result.get("success"):
                print("  {} {}".format(_c(_G, "Archived:"), _c(_D, msg_id)))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Send -----
        elif cmd == "send":
            if len(rest_tokens) < 2:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "send <recipient> <message...>")))
                continue
            recipient_ref = rest_tokens[0]
            recipient = _resolve_session(recipient_ref)
            message_text = " ".join(rest_tokens[1:])
            result = send_direct(
                from_sender=current_session,
                to_recipient=recipient,
                content=message_text,
            )
            if result.get("success"):
                print("  {} {} to {}".format(
                    _c(_G, "Message sent"),
                    _c(_D, result.get("message_id", "???")),
                    _c(_C, _session_label(recipient)),
                ))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Reply -----
        elif cmd == "reply":
            if len(rest_tokens) < 2:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "reply <id_or_#index> <message...>")))
                continue
            msg_id = imap.resolve(rest_tokens[0])
            message_text = " ".join(rest_tokens[1:])
            result = reply_to_message(
                msg_id=msg_id,
                from_sender=current_session,
                content=message_text,
            )
            if result.get("success"):
                print("  {} {}".format(_c(_G, "Reply sent:"), _c(_D, result.get("message_id", "???"))))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Reply-all -----
        elif cmd == "reply-all":
            if len(rest_tokens) < 2:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "reply-all <id_or_#index> <message...>")))
                continue
            msg_id = imap.resolve(rest_tokens[0])
            message_text = " ".join(rest_tokens[1:])
            result = reply_to_all(
                msg_id=msg_id,
                from_sender=current_session,
                content=message_text,
            )
            if result.get("success"):
                sent = result.get("replies_sent", result.get("message_id", "???"))
                print("  {} ({})".format(_c(_G, "Reply-all sent"), sent))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Broadcast -----
        elif cmd == "broadcast":
            if not rest_str:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "broadcast <message...>")))
                continue
            result = broadcast(
                from_sender=current_session,
                content=rest_str,
            )
            if result.get("success"):
                print("  {} {}".format(_c(_G, "Broadcast sent:"), _c(_D, result.get("message_id", "???"))))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Thread -----
        elif cmd == "thread":
            if not rest_tokens:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "thread <conversation_id_or_#index>")))
                continue
            ref = rest_tokens[0]
            # Try to get conversation_id from index map first
            convo_id = imap.get_conversation_id(ref)
            if not convo_id:
                # Treat ref itself as a conversation_id
                convo_id = ref
            if not convo_id:
                print("  {}".format(_c(_RED, "Could not resolve thread reference: {}".format(ref))))
                continue
            _show_thread(convo_id, current_session)

        # ----- Owed -----
        elif cmd == "owed":
            scope = current_session or None
            scope_label = "({})".format(_session_label(current_session)) if current_session else "(all sessions)"
            result = check_owed_replies(session=scope)
            owed = result.get("owed", [])
            if not owed:
                print("  {}".format(_c(_G, "No replies owed {}.".format(scope_label))))
            else:
                print("  Replies owed {} ({}):\n".format(scope_label, len(owed)))
                for entry in owed:
                    from_sender = entry.get("from", "???")
                    sender_name = _get_display_name(from_sender) or from_sender
                    to_session = entry.get("to", "???")
                    to_name = _get_display_name(to_session) or to_session
                    msg_id = entry.get("message_id", "???")
                    created = entry.get("created_at", "")
                    parts = "    {} {}{}".format(
                        _c(_D, msg_id),
                        _c(_D, "from:"),
                        _c(_C, sender_name),
                    )
                    if not current_session:
                        parts += " {}{} ".format(_c(_D, "to:"), _c(_C, to_name))
                    parts += " {}".format(_c(_Y, format_relative_time(created)) if created else "")
                    print(parts)

        # ----- Pending -----
        elif cmd == "pending":
            scope = current_session or None
            scope_label = "({})".format(_session_label(current_session)) if current_session else "(all sessions)"
            result = list_pending_replies(session=scope)
            pending = result.get("pending", [])
            if not pending:
                print("  {}".format(_c(_G, "No pending replies {}.".format(scope_label))))
            else:
                print("  Pending replies {} ({}):\n".format(scope_label, len(pending)))
                for entry in pending:
                    to_session = entry.get("to", "???")
                    to_name = _get_display_name(to_session) or to_session
                    from_sender = entry.get("from", "???")
                    sender_name = _get_display_name(from_sender) or from_sender
                    msg_id = entry.get("message_id", "???")
                    created = entry.get("created_at", "")
                    parts = "    {} {}{}".format(
                        _c(_D, msg_id),
                        _c(_D, "to:"),
                        _c(_C, to_name),
                    )
                    if not current_session:
                        parts += " {}{}".format(_c(_D, "from:"), _c(_C, sender_name))
                    parts += " {}".format(_c(_Y, format_relative_time(created)) if created else "")
                    print(parts)

        # ----- Standing -----
        elif cmd == "standing":
            # Query global + platform scopes
            platform = os.environ.get("AI_SESSION_PLATFORM", "")
            scopes = ["global"]
            kwargs = {}  # type: Dict[str, Any]
            if platform:
                scopes.append("platform")
                kwargs["platform"] = platform
            result = query_standing(scopes=scopes, **kwargs)
            messages = result.get("messages", [])
            if not messages:
                print("  {}".format(_c(_G, "No standing messages.")))
            else:
                print("  Standing messages ({}):\n".format(len(messages)))
                for msg in messages:
                    scope = msg.get("scope", "?")
                    scope_name = msg.get("scope_name", "")
                    scope_str = "{}/{}".format(scope, scope_name) if scope_name else scope
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 60:
                        content = content[:60] + "..."
                    created = msg.get("created_at", "")
                    print("    [{}] {} {}".format(
                        _c(_M, scope_str), content,
                        _c(_D, format_relative_time(created)) if created else "",
                    ))
                    print("      {} {}  {} {}".format(
                        _c(_D, "id:"), _c(_D, msg.get("id", "?")),
                        _c(_D, "from:"), _c(_C, msg.get("from", "?")),
                    ))

        # ----- Post-standing -----
        elif cmd == "post-standing":
            if len(rest_tokens) < 2:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "post-standing <scope> <message...>")))
                print("  {} {}".format(_c(_D, "Scope:"), _c(_D, "global, team/NAME, platform/NAME, project/NAME")))
                continue
            scope_raw = rest_tokens[0]
            message_text = " ".join(rest_tokens[1:])

            # Parse scope: "global" or "team/engineering"
            if "/" in scope_raw:
                scope_parts = scope_raw.split("/", 1)
                scope = scope_parts[0]
                scope_name = scope_parts[1]
            else:
                scope = scope_raw
                scope_name = None

            result = post_standing(
                scope=scope,
                from_sender=current_session,
                content=message_text,
                scope_name=scope_name,
            )
            if result.get("success"):
                print("  {} {}".format(_c(_G, "Posted standing message:"), _c(_D, result.get("id", "???"))))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Lock -----
        elif cmd == "lock":
            session_to_lock = rest_tokens[0] if rest_tokens else current_session
            result = lock_session(
                session_id=session_to_lock,
                locked_by=current_session,
            )
            if result.get("success"):
                print("  {} {}".format(_c(_RED + _B, "LOCKED:"), _c(_C, session_to_lock)))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Unlock -----
        elif cmd == "unlock":
            session_to_unlock = rest_tokens[0] if rest_tokens else current_session
            result = unlock_session(session_id=session_to_unlock)
            if result.get("success"):
                print("  {} {}".format(_c(_G, "Unlocked:"), _c(_C, session_to_unlock)))
            else:
                print("  {}".format(_c(_RED, "Error: {}".format(result.get("error", "unknown")))))

        # ----- Locks -----
        elif cmd == "locks":
            result = list_locks()
            lock_list = result.get("locks", [])
            if not lock_list:
                print("  {}".format(_c(_G, "No active locks.")))
            else:
                print("  Active locks ({}):\n".format(len(lock_list)))
                for lock in lock_list:
                    sid = lock.get("session_id", "?")
                    locked_by = lock.get("locked_by", "?")
                    locked_at = lock.get("locked_at", "")
                    reason = lock.get("reason", "")
                    reason_str = " ({})".format(reason) if reason else ""
                    print("    {} {} {}{} {}{}".format(
                        _c(_RED + _B, "LOCKED"),
                        _c(_C, sid),
                        _c(_D, "by:"),
                        _c(_C, locked_by),
                        _c(_D, format_relative_time(locked_at)) if locked_at else "",
                        _c(_D, reason_str),
                    ))

        # ----- Sessions -----
        elif cmd in ("sessions", "list-sessions"):
            show_msgs = "--with-msgs" in rest_tokens or "--with-unread" in rest_tokens
            show_unread_only = "--with-unread" in rest_tokens
            pattern = None
            for t in rest_tokens:
                if not t.startswith("-"):
                    pattern = t.lower()
                    break

            store = _load_store()
            if store is None:
                print("  {}".format(_c(_RED, "Session store unavailable.")))
                continue

            try:
                with store._connect() as conn:
                    rows = conn.execute(
                        "SELECT tracking_id, cli_session_id, terminal_session, display_name, platform "
                        "FROM sessions ORDER BY created_at DESC LIMIT 100"
                    ).fetchall()
            except Exception as e:
                print("  {}".format(_c(_RED, "Error: {}".format(e))))
                continue

            # Filter by pattern
            filtered = []
            for row in rows:
                tid, cli_uuid, terminal, dname, platform = row
                if pattern:
                    searchable = " ".join(str(v or "") for v in row).lower()
                    if pattern not in searchable:
                        continue
                filtered.append(row)

            if not filtered:
                print("  {}".format(_c(_D, "No sessions found." + (" matching '{}'".format(pattern) if pattern else ""))))
                continue

            # Get unread counts if requested
            unread_map = {}
            if show_msgs:
                result = check_unread()
                unread_map = result.get("sessions", {})

            for tid, cli_uuid, terminal, dname, platform in filtered:
                label = _c(_BG, dname) if dname else _c(_C, tid)
                parts = ["  {} {}".format(label, _c(_D, "({})".format(platform or "?")))]
                if dname and dname != tid:
                    parts[0] += " " + _c(_D, tid[:30])
                count = unread_map.get(tid, 0)
                if show_msgs:
                    if show_unread_only and count == 0:
                        continue
                    parts[0] += "  {} {}".format(_c(_BY, count), _c(_D, "unread"))
                print(parts[0])

        # ----- All-unread (legacy alias for check --all) -----
        elif cmd == "all-unread":
            result = check_unread()
            sessions_data = result.get("sessions", {})
            bcast = result.get("broadcast_unread", 0)
            total = result.get("total_unread", 0)
            print("  {} {}".format(_c(_D, "Total unread:"), _c(_Y + _B, total) if total > 0 else _c(_G, total)))
            if sessions_data:
                for sid, count in sorted(sessions_data.items()):
                    label = _session_label(sid)
                    print("    {}: {}".format(_c(_C, label), _c(_Y + _B, count)))
            if bcast > 0:
                print("    {}: {}".format(_c(_D, "broadcasts"), _c(_Y + _B, bcast)))

        # ----- Search -----
        elif cmd in ("search", "find"):
            if not rest_str:
                print("  {} {}".format(_c(_D, "Usage:"), _c(_C, "search [session|all_sessions] [folder|all_folders] [read|unread|all_msgs] <text>")))
                continue

            # Smart parameter parsing: extract reserved words first
            _RESERVED = {"all_sessions", "all_folders", "all_msgs", "read", "unread",
                         "inbox", "sent", "archive", "broadcasts"}
            search_session = current_session  # default to current
            search_folders = [current_folder]  # default to current folder
            read_filter = "all_msgs"           # default show all
            search_text_parts = []

            for tok in rest_tokens:
                tl = tok.lower()
                if tl == "all_sessions":
                    search_session = ""  # empty = all
                elif tl == "all_folders":
                    search_folders = list(VALID_FOLDERS)
                elif tl in ("read", "unread", "all_msgs"):
                    read_filter = tl
                elif tl in VALID_FOLDERS:
                    search_folders = [tl]
                elif tl not in _RESERVED:
                    # Could be a session name or search text
                    resolved = _resolve_session(tl) if _load_store() else None
                    if resolved and resolved != tl:
                        search_session = resolved
                    else:
                        search_text_parts.append(tok)

            search_text = " ".join(search_text_parts)
            if not search_text:
                print("  {}".format(_c(_RED, "No search text provided.")))
                continue

            # Collect messages from targeted scope
            all_results = []
            text_lower = search_text.lower()

            for folder in search_folders:
                if folder == "inbox":
                    if search_session:
                        msgs = list_messages(dir_name="inbox", recipient=search_session, limit=200).get("messages", [])
                    else:
                        msgs = list_messages(dir_name="inbox", limit=200).get("messages", [])
                    msgs += list_messages(dir_name="broadcasts", limit=200).get("messages", [])
                elif folder == "broadcasts":
                    msgs = list_messages(dir_name="broadcasts", limit=200).get("messages", [])
                elif folder == "sent":
                    if search_session:
                        msgs = list_sent(sender=search_session, limit=200).get("messages", [])
                    else:
                        msgs = []  # can't list all sent without a session
                elif folder == "archive":
                    if search_session:
                        msgs = list_archived(recipient=search_session, limit=200).get("messages", [])
                    else:
                        msgs = []
                else:
                    msgs = []

                for m in msgs:
                    # Text match
                    searchable = " ".join(str(m.get(f, "")) for f in ("id", "from", "to", "content", "preview"))
                    if text_lower not in searchable.lower():
                        continue
                    # Read filter
                    if read_filter == "read" and not _is_read_by(m, current_session or ""):
                        continue
                    if read_filter == "unread" and _is_read_by(m, current_session or ""):
                        continue
                    all_results.append(m)

            # Dedup by message ID
            seen_ids = set()
            deduped = []
            for m in all_results:
                mid = m.get("id", "")
                if mid not in seen_ids:
                    seen_ids.add(mid)
                    deduped.append(m)
            deduped.sort(key=lambda m: m.get("created_at", ""), reverse=True)

            if not deduped:
                print("  {}".format(_c(_D, "No messages matching '{}'.".format(search_text))))
            else:
                print("  {} message(s) matching '{}':\n".format(len(deduped), search_text))
                print(format_message_list(deduped, current_session or "", imap))

        # ----- Unknown -----
        else:
            print("  {}".format(_c(_RED, "Unknown command: {}".format(cmd))))
            print("  {} {}".format(_c(_D, "Type"), _c(_C, "'help'") + " " + _c(_D, "for available commands.")))

    return 0


# =========================================================================
# CLI Parser (subcommand mode)
# =========================================================================

def _help_examples():
    """Generate --help-examples output with example use cases, commands, and output."""
    H = lambda t: _c(_B, t)
    C = lambda t: _c(_C, t)
    D = lambda t: _c(_D, t)
    G = lambda t: _c(_G, t)
    Y = lambda t: _c(_Y, t)
    lines = [
        H("Messaging Manager — Example Use Cases"),
        _c(_D, "=" * 42),
        "",
        H("1. Send a message to another session"),
        "  " + C("messaging_mgr.py send --from $AI_TRACKING_ID --to Kael --content \"Ready for review\""),
        "  " + D("→ Resolves 'Kael' to its tracking ID via SessionStore"),
        "  " + D("→ Output:"),
        "    " + G('{"success": true, "id": "msg_20260602_143000_a1b2c3d4", "to": "20260601_..."}'),
        "",
        H("2. Send to a session using a prompt:// URI"),
        "  " + C("messaging_mgr.py send --from $AI_TRACKING_ID --to prompt://Kael/session --content \"ping\""),
        "  " + D("→ URI is resolved; session component extracted for addressing"),
        "",
        H("3. Broadcast to all active sessions"),
        "  " + C("messaging_mgr.py broadcast --from $AI_TRACKING_ID --content \"Deploy in 5 min\""),
        "  " + D("→ Output:"),
        "    " + G('{"success": true, "id": "bcast_20260602_...", "scope": "active"}'),
        "",
        H("4. Check unread messages for a session"),
        "  " + C("messaging_mgr.py check --session $AI_TRACKING_ID"),
        "  " + D("→ Output:"),
        "    " + G('{"unread": 3, "inbox": 2, "broadcasts": 1}'),
        "",
        H("5. List inbox messages"),
        "  " + C("messaging_mgr.py list --folder inbox --filter unread --session $AI_TRACKING_ID"),
        "  " + D("→ Returns JSON array of unread messages with IDs, senders, timestamps"),
        "",
        H("6. Read and mark a message"),
        "  " + C("messaging_mgr.py read --id msg_20260602_143000_a1b2c3d4"),
        "  " + D("→ Returns full message content and marks it as read"),
        "",
        H("7. Reply to a message"),
        "  " + C("messaging_mgr.py reply --id msg_20260602_143000_a1b2c3d4 --from $AI_TRACKING_ID --content \"On it\""),
        "  " + D("→ Threads the reply under the original conversation"),
        "",
        H("8. Queue a prompt for delivery to a session"),
        "  " + C("messaging_mgr.py queue-prompt --to $AI_TRACKING_ID --content \"Run tests\" --urgency prompt"),
        "  " + D("→ Queued for delivery on next UserPromptSubmit hook fire"),
        "",
        H("9. Post a standing message"),
        "  " + C("messaging_mgr.py post-standing --scope global --from admin --content \"Freeze merges until Friday\""),
        "  " + D("→ Visible to all sessions that query standing messages"),
        "",
        H("10. Search across all messages"),
        "  " + C("messaging_mgr.py search --query \"deploy\" --limit 10"),
        "  " + D("→ Searches content, sender, recipient, and message ID"),
        "",
        H("11. Lock a session (prevent message delivery)"),
        "  " + C("messaging_mgr.py lock --session $AI_TRACKING_ID --by user --reason \"deep work\""),
        "",
        H("12. Check what replies you owe"),
        "  " + C("messaging_mgr.py check-owed --session $AI_TRACKING_ID"),
        "  " + D("→ Shows messages marked response-required that you haven't replied to"),
        "",
        H("13. Interactive REPL mode"),
        "  " + C("messaging_mgr.py"),
        "  " + C("messaging_mgr.py --as Kael"),
        "  " + D("→ Enters interactive REPL with readline, tab completion, and color"),
        "  " + D("→ Type 'help' for REPL commands, 'help --verbose' for full reference"),
        "",
        H("Identifiers"),
        "  " + D("All --from, --to, --session args accept:"),
        "  " + Y("tracking ID") + D("  — 20260602_143000_a1b2c3d4_cla"),
        "  " + Y("display name") + D(" — Kael, Hamilton, Relay"),
        "  " + Y("prompt:// URI") + D(" — prompt://Kael/session"),
        "  " + Y("CLI UUID") + D("     — c0403980-61e7-402a-8deb-2ecb20e3381c"),
    ]
    return "\n".join(lines)


def _grouped_help():
    """Generate scope-grouped help text for --help output."""
    H = lambda t: _c(_B, t)
    C = lambda t: "  {:30s}".format(_c(_C, t))
    D = lambda t: _c(_D, t)
    lines = [
        H("Global (no session required)"),
        C("broadcast") + D("Send a broadcast to all active sessions"),
        C("post-standing") + D("Post a standing message (global/team/platform/project)"),
        C("query-standing") + D("Query standing messages by scope"),
        C("cancel-standing") + D("Cancel a standing message by ID"),
        C("lock-global") + D("Create a global conversation lock"),
        C("unlock-global") + D("Remove the global conversation lock"),
        C("list-locks") + D("List all active locks"),
        C("list-sessions") + D("List sessions with optional message counts"),
        C("search") + D("Search messages by text content"),
        "",
        H("Session (operates on a specific session)"),
        C("check") + D("Check unread message counts"),
        C("list") + D("List messages in a folder (inbox/sent/archive/broadcasts)"),
        C("check-owed") + D("Check replies this session owes"),
        C("list-pending") + D("List replies this session is waiting for"),
        C("lock") + D("Lock a session"),
        C("unlock") + D("Unlock a session"),
        C("whoami") + D("Show session identity details"),
        "",
        H("Message (operates on a specific message)"),
        C("send") + D("Send a direct message"),
        C("read") + D("Read a message by ID and mark as read"),
        C("reply") + D("Reply to a message"),
        C("reply-all") + D("Reply to all recipients"),
        C("acknowledge") + D("Acknowledge a message"),
        C("check-responses") + D("Find replies to a message"),
        C("archive") + D("Archive a message"),
        C("mark-as") + D("Mark messages as read or unread"),
        C("move") + D("Move messages between folders"),
        "",
        H("Delivery"),
        C("queue-prompt") + D("Queue a prompt for delivery to a session"),
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="messaging_mgr",
        description="Unified AI messaging CLI + REPL. Run with no args to enter interactive mode.",
        epilog=_grouped_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="messaging_mgr {}".format(VERSION))
    parser.add_argument("--as", dest="as_session", default=None,
                        help="Set session identity (tracking_id or name) for REPL mode")
    parser.add_argument("--help-verbose", action="store_true", default=False,
                        help="Print full REPL command reference and exit")
    parser.add_argument("--help-examples", action="store_true", default=False,
                        help="Show example use cases with commands and output")
    parser.add_argument("--format", dest="output_format", default="json",
                        choices=["json", "jsonl", "markdown", "md", "text"],
                        help="Output format (default: json; jsonl = one JSON object per line)")

    # Shared args added to every subparser
    def _add_common(sub_parser):
        sub_parser.add_argument("--format", dest="output_format", default=None,
                                choices=["json", "jsonl", "markdown", "md", "text"],
                                help="Output format (overrides top-level --format)")

    subs = parser.add_subparsers(dest="command")

    # --- send ---
    p_send = subs.add_parser("send", help="Send a direct message")
    p_send.add_argument("--from", dest="from_sender", default=None,
                        help="(DEPRECATED, IGNORED) Sender is the trusted resolved "
                             "session; --from is ignored with a warning during the "
                             "deprecation window and will be removed at cutover.")
    p_send.add_argument("--subject", default=None,
                        help="Subject for a NEW conversation (required when "
                             "--reply-to is none/absent)")
    p_send.add_argument("--to", dest="to_recipient", required=True,
                        help="Recipient (tracking ID, display name, prompt:// URI, or comma-separated)")
    p_send.add_argument("--content", required=True, help="Message body")
    p_send.add_argument("--body-file", dest="body_file", default=None,
                        help="Path to a file holding a large body; the message "
                             "references it (read inlines it). Keeps the wire "
                             "message — and the caller's tool args — small.")
    p_send.add_argument("--urgency", default="prompt",
                        choices=["interrupt", "prompt", "async", "passive"],
                        help="Message urgency (default: prompt)")
    p_send.add_argument("--notify", default=None,
                        choices=["immediate", "batched", "silent"],
                        help="Notification policy (default: derived from urgency). "
                             "'batched' coalesces nudges to <=1 per recipient per window.")
    p_send.add_argument("--response-type", default="reply",
                        choices=["reply", "acknowledge", "none"],
                        help="Expected response type (default: reply)")
    p_send.add_argument("--ttl", type=int, default=None, help="TTL in seconds")
    p_send.add_argument("--callback-endpoint", default=None,
                        help="Callback URI (prompt://, file://, fifo://, none://)")
    p_send.add_argument("--reply-to", dest="replying_to", default=None,
                        help="Parent message ID for threading, or 'none' to start "
                             "a new thread (requires --subject)")
    p_send.add_argument("--conversation-id", default=None,
                        help="(DEPRECATED, IGNORED) v2 derives the conversation from "
                             "--reply-to; accepted-but-ignored with a warning during "
                             "the deprecation window, removed at cutover.")
    p_send.add_argument("--response-required", action="store_true", default=False,
                         help="Mark message as requiring a response (creates pending reply)")

    # --- broadcast ---
    p_bcast = subs.add_parser("broadcast", help="Send a broadcast message")
    p_bcast.add_argument("--from", dest="from_sender", required=True,
                         help="Sender (tracking ID, display name, or prompt:// URI)")
    p_bcast.add_argument("--content", required=True, help="Message body")
    p_bcast.add_argument("--urgency", default="prompt",
                         choices=["interrupt", "prompt", "async", "passive"],
                         help="Message urgency (default: prompt)")
    p_bcast.add_argument("--scope", default="active",
                         choices=["active", "targeted"],
                         help="Broadcast scope (default: active)")
    p_bcast.add_argument("--group", default=None, help="Target group name")
    p_bcast.add_argument("--reply-to", dest="replying_to", default=None, help="Parent message ID for threading")
    p_bcast.add_argument("--conversation-id", default=None, help="Conversation ID for threading")

    # --- list ---
    p_list = subs.add_parser("list", help="List messages")
    p_list.add_argument("--folder", default="inbox",
                        choices=["inbox", "sent", "archive", "broadcasts", "prompts"],
                        help="Folder to list (default: inbox)")
    p_list.add_argument("--filter", dest="read_filter", default="all",
                        choices=["read", "unread", "all"],
                        help="Filter by read state (default: all)")
    p_list.add_argument("--session", default=None, help="Session to list messages for")
    p_list.add_argument("--limit", type=int, default=50, help="Max results (default: 50)")

    # --- acknowledge ---
    p_ack = subs.add_parser("acknowledge", help="Acknowledge a message")
    p_ack.add_argument("--id", dest="msg_id", required=True, help="Message ID to acknowledge")
    p_ack.add_argument("--by", dest="acknowledger", required=True, help="Who is acknowledging")

    # --- check-responses ---
    p_resp = subs.add_parser("check-responses", help="Find replies to a message")
    p_resp.add_argument("--id", dest="msg_id", required=True, help="Parent message ID")

    # --- queue-prompt ---
    p_queue = subs.add_parser("queue-prompt", help="Queue a prompt for a session")
    p_queue.add_argument("--to", dest="to_session", required=True, help="Target session tracking ID")
    p_queue.add_argument("--content", required=True, help="Prompt text")
    p_queue.add_argument("--urgency", default="prompt",
                         choices=["interrupt", "prompt"],
                         help="Prompt urgency (default: prompt)")
    p_queue.add_argument("--delivery", default="pre-prompt",
                         choices=["pre-prompt", "post-prompt", "postResponse"],
                         help="Delivery timing (default: pre-prompt)")
    p_queue.add_argument("--source", default=None, help="Source tracking ID or script name")
    p_queue.add_argument("--callback-endpoint", default=None, help="Callback URI")
    p_queue.add_argument("--ttl", type=int, default=259200, help="TTL in seconds (default: 259200 = 3 days)")

    # --- send-prompt (v2: durable prompt, persisted like a message) ---
    p_sp = subs.add_parser(
        "send-prompt",
        help="Send a prompt persisted like a message (delivery=prompt) + queue it",
    )
    p_sp.add_argument("--to", required=True,
                      help="Recipient (tracking ID, display name, or prompt:// URI)")
    p_sp.add_argument("--content", required=True, help="Prompt text")
    p_sp.add_argument("--reply-to", dest="reply_to", default=None,
                      help="Parent message id (omit/none to start a new thread)")
    p_sp.add_argument("--subject", default=None,
                      help="Subject (required when not a reply)")
    p_sp.add_argument("--from", dest="sender_ctx", default=None,
                      help="(DEPRECATED, IGNORED) Sender is the trusted resolved "
                           "session ($AI_TRACKING_ID); --from is ignored with a "
                           "warning during the deprecation window, removed at cutover.")
    p_sp.add_argument("--urgency", default="prompt",
                      choices=["interrupt", "prompt", "async", "passive"],
                      help="Prompt urgency (default: prompt)")
    p_sp.add_argument("--timing", default="pre-prompt",
                      choices=["pre-prompt", "post-prompt", "postResponse"],
                      help="Queue delivery timing (default: pre-prompt)")
    p_sp.add_argument("--source", default=None, help="Source tracking ID or script name")
    p_sp.add_argument("--callback-endpoint", default=None, help="Callback URI")
    p_sp.add_argument("--ttl", type=int, default=259200,
                      help="TTL in seconds (default: 259200 = 3 days)")
    p_sp.add_argument("--no-queue", dest="queue", action="store_false", default=True,
                      help="Skip the legacy queue-file write (durable record only)")

    # --- post-standing ---
    p_post_standing = subs.add_parser("post-standing", help="Post a standing message")
    p_post_standing.add_argument("--scope", required=True,
                                 choices=["global", "team", "platform", "project"],
                                 help="Message scope")
    p_post_standing.add_argument("--scope-name", default=None,
                                 help="Scope name (required for team/platform/project)")
    p_post_standing.add_argument("--from", dest="from_sender", required=True,
                                 help="Sender identifier")
    p_post_standing.add_argument("--content", required=True, help="Message text")
    p_post_standing.add_argument("--ttl", type=int, default=None,
                                 help="TTL in seconds (default: no expiry)")
    p_post_standing.add_argument("--approved-by", default=None,
                                 help="Who approved this standing message (default: --from value)")

    # --- query-standing ---
    p_query_standing = subs.add_parser("query-standing", help="Query standing messages")
    p_query_standing.add_argument("--scopes", required=True,
                                  help="Comma-separated list of scopes to query")
    p_query_standing.add_argument("--team", default=None, help="Team name filter")
    p_query_standing.add_argument("--platform", default=None, help="Platform name filter")
    p_query_standing.add_argument("--project", default=None, help="Project name filter")
    p_query_standing.add_argument("--limit", type=int, default=50,
                                  help="Max results (default: 50)")

    # --- cancel-standing ---
    p_cancel_standing = subs.add_parser("cancel-standing", help="Cancel a standing message by ID")
    p_cancel_standing.add_argument("--id", dest="msg_id", required=True,
                                   help="Standing message ID to cancel")

    # --- read ---
    p_read = subs.add_parser("read", help="Read a message by ID and mark as read")
    p_read.add_argument("--id", dest="msg_id", required=True, help="Message ID to read")
    p_read.add_argument("--reader", default=None,
                        help="Reader identifier (default: $AI_TRACKING_ID or 'unknown')")

    # --- reply ---
    p_reply = subs.add_parser("reply", help="Reply to a message")
    p_reply.add_argument("--id", dest="msg_id", required=True, help="Message ID to reply to")
    p_reply.add_argument("--from", dest="from_sender", required=True, help="Sender identifier")
    p_reply.add_argument("--content", required=True, help="Reply body")
    p_reply.add_argument("--urgency", default="prompt",
                         choices=["interrupt", "prompt", "async", "passive"],
                         help="Message urgency (default: prompt)")
    p_reply.add_argument("--notify", default=None,
                         choices=["immediate", "batched", "silent"],
                         help="Notification policy (default: derived from urgency)")
    p_reply.add_argument("--response-required", action="store_true", default=False,
                         help="Mark reply as requiring a response")

    # --- reply-all ---
    p_reply_all = subs.add_parser("reply-all", help="Reply to all recipients of a message")
    p_reply_all.add_argument("--id", dest="msg_id", required=True, help="Message ID to reply to")
    p_reply_all.add_argument("--from", dest="from_sender", required=True, help="Sender identifier")
    p_reply_all.add_argument("--content", required=True, help="Reply body")
    p_reply_all.add_argument("--urgency", default="prompt",
                             choices=["interrupt", "prompt", "async", "passive"],
                             help="Message urgency (default: prompt)")
    p_reply_all.add_argument("--notify", default=None,
                             choices=["immediate", "batched", "silent"],
                             help="Notification policy (default: derived from urgency)")
    p_reply_all.add_argument("--response-required", action="store_true", default=False,
                             help="Mark reply as requiring a response")

    # --- list-pending ---
    p_list_pending = subs.add_parser("list-pending", help="List pending replies")
    p_list_pending.add_argument("--session", default=None, help="Filter by session tracking ID")

    # --- check-owed ---
    p_check_owed = subs.add_parser("check-owed", help="Check owed replies")
    p_check_owed.add_argument("--session", default=None, help="Session tracking ID (default: all)")

    # --- check ---
    p_check = subs.add_parser("check", help="Check unread message counts")
    p_check.add_argument("--session", default=None, help="Session tracking ID to check (default: all)")

    # --- archive ---
    p_archive = subs.add_parser("archive", help="Archive a message")
    p_archive.add_argument("--id", dest="msg_id", required=True, help="Message ID to archive")

    # --- search ---
    p_search = subs.add_parser("search", help="Search messages by text content")
    p_search.add_argument("--query", required=True, help="Text to search for (case-insensitive)")
    p_search.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    # --- lock ---
    p_lock = subs.add_parser("lock", help="Lock a conversation session")
    p_lock.add_argument("--session", required=True, help="Session ID to lock")
    p_lock.add_argument("--by", dest="locked_by", default="user", help="Who is locking (default: user)")
    p_lock.add_argument("--reason", default=None, help="Reason for the lock")

    # --- unlock ---
    p_unlock = subs.add_parser("unlock", help="Unlock a conversation session")
    p_unlock.add_argument("--session", required=True, help="Session ID to unlock")

    # --- lock-global ---
    p_lock_global = subs.add_parser("lock-global", help="Create a global conversation lock")
    p_lock_global.add_argument("--by", dest="locked_by", default="user", help="Who is locking (default: user)")
    p_lock_global.add_argument("--reason", default=None, help="Reason for the global lock")

    # --- unlock-global ---
    subs.add_parser("unlock-global", help="Remove the global conversation lock")

    # --- list-locks ---
    subs.add_parser("list-locks", help="List all conversation locks")

    # --- list-sessions ---
    p_ls_sessions = subs.add_parser("list-sessions", help="List sessions")
    p_ls_sessions.add_argument("--with-msgs", action="store_true", help="Show message counts")
    p_ls_sessions.add_argument("--with-unread", action="store_true", help="Only sessions with unread")
    p_ls_sessions.add_argument("--pattern", default=None, help="Substring filter on name/ID")

    # --- mark-as ---
    p_mark = subs.add_parser("mark-as", help="Mark messages as read or unread")
    p_mark.add_argument("state", choices=["read", "unread"], help="Target state")
    p_mark.add_argument("--id", dest="msg_ids", required=True, help="Comma-separated message IDs")
    p_mark.add_argument("--reader", default=None, help="Reader ID (default: $AI_TRACKING_ID)")

    # --- move ---
    p_move = subs.add_parser("move", help="Move messages between folders")
    p_move.add_argument("--id", dest="msg_ids", required=True, help="Comma-separated message IDs")
    p_move.add_argument("--to", dest="to_folder", required=True,
                        choices=["inbox", "archive"], help="Destination folder")
    p_move.add_argument("--session", default=None, help="Session/recipient for folder paths")

    # --- whoami ---
    p_whoami = subs.add_parser("whoami", help="Show session identity details")
    p_whoami.add_argument("--session", default=None, help="Session to query (default: $AI_TRACKING_ID)")

    # Add --format to every subparser so it works after the subcommand
    for choice in subs.choices.values():
        _add_common(choice)

    return parser


def _deprecation_warn(msg: str) -> None:
    """Emit a v2 transition-shim deprecation warning to stderr (never stdout).

    stdout is reserved for the JSON result; warnings go to stderr so machine
    callers that parse stdout are unaffected while humans/log scrapers still see
    the notice during the deprecation window (§12.L).
    """
    sys.stderr.write("[messaging_mgr][DEPRECATED] {}\n".format(msg))
    sys.stderr.flush()


def _run_subcommand(args: argparse.Namespace) -> int:
    """Execute a CLI subcommand and print JSON result. Returns exit code."""
    result = {}  # type: Dict[str, Any]

    # Resolve URIs in common fields
    if hasattr(args, "from_sender") and args.from_sender and "://" in args.from_sender:
        args.from_sender = _resolve_session(args.from_sender)
    if hasattr(args, "session") and args.session and "://" in args.session:
        args.session = _resolve_session(args.session)
    if hasattr(args, "to_session") and args.to_session and "://" in args.to_session:
        args.to_session = _resolve_session(args.to_session)
    if hasattr(args, "to_recipient") and args.to_recipient and "://" in args.to_recipient:
        args.to_recipient = _resolve_session(args.to_recipient)

    if args.command == "send":
        # --- v2 transition shim (deprecation window; §12.L) -----------------
        # Legacy callers may still pass --from / --conversation-id and may omit
        # --reply-to. Accept them so live sessions don't break, but steer to the
        # v2 contract: --from is IGNORED (trusted resolved sender wins),
        # --conversation-id is IGNORED (v2 derives it from --reply-to), and a
        # missing --reply-to defaults to 'none' (new conversation). Each emits a
        # stderr deprecation warning. Remove this block at the hard cutover.
        if args.from_sender:
            _deprecation_warn(
                "--from is IGNORED: the sender is the trusted resolved session "
                "($AI_TRACKING_ID / authenticated context). Stop passing --from."
            )
        if getattr(args, "conversation_id", None):
            _deprecation_warn(
                "--conversation-id is IGNORED: v2 derives the conversation from "
                "--reply-to. Stop passing --conversation-id."
            )
        if args.replying_to is None:
            _deprecation_warn(
                "--reply-to is now REQUIRED (nullable). Defaulting to 'none' (a "
                "new conversation) for this deprecation window; this becomes a "
                "hard error after the cutover. Pass --reply-to <msg_id> or "
                "--reply-to none explicitly."
            )
            args.replying_to = "none"
        # v2 send contract: trusted sender (resolved), enforced reply_to/subject,
        # conversation derived, Message+Delivery(+obligations) written to the index.
        try:
            result = send_message(
                to=args.to_recipient,
                content=args.content,
                reply_to=args.replying_to,
                subject=getattr(args, "subject", None),
                sender_ctx=None,  # --from ignored (shim): trusted sender resolved
                urgency=args.urgency,
                response_type=args.response_type,
                ttl_seconds=args.ttl,
                body_file=getattr(args, "body_file", None),
                response_required=args.response_required,
                notify=getattr(args, "notify", None),
            )
        except (
            ReplyRuleError, SenderUnresolved, RecipientNotFound, RecipientAmbiguous,
        ) as e:
            result = {"success": False, "error": str(e),
                      "error_type": type(e).__name__}
    elif args.command == "broadcast":
        result = broadcast(
            from_sender=args.from_sender,
            content=args.content,
            urgency=args.urgency,
            scope=args.scope,
            group=args.group,
            replying_to=args.replying_to,
            conversation_id=args.conversation_id,
        )
    elif args.command == "list":
        session = args.session or os.environ.get("AI_TRACKING_ID", "")
        folder = args.folder
        if folder == "sent":
            result = list_sent(sender=session, limit=args.limit)
        elif folder == "archive":
            result = list_archived(recipient=session, limit=args.limit)
        elif folder == "broadcasts":
            result = list_messages(dir_name="broadcasts", limit=args.limit)
        else:
            result = list_messages(dir_name="inbox", recipient=session or None, limit=args.limit)
        # Apply read filter
        if args.read_filter != "all" and session:
            msgs = result.get("messages", [])
            if args.read_filter == "unread":
                msgs = [m for m in msgs if not _is_read_by(m, session)]
            elif args.read_filter == "read":
                msgs = [m for m in msgs if _is_read_by(m, session)]
            result["messages"] = msgs
            result["count"] = len(msgs)
    elif args.command == "acknowledge":
        result = acknowledge(
            msg_id=args.msg_id,
            acknowledger=args.acknowledger,
        )
    elif args.command == "check-responses":
        result = check_responses(msg_id=args.msg_id)
    elif args.command == "queue-prompt":
        result = queue_prompt(
            to_session=args.to_session,
            content=args.content,
            urgency=args.urgency,
            delivery=args.delivery,
            source=args.source,
            callback_endpoint=args.callback_endpoint,
            ttl_seconds=args.ttl,
        )
    elif args.command == "send-prompt":
        # --- v2 transition shim (deprecation window; §12.L) -----------------
        # Mirror the `send` shim: --from is IGNORED (trusted resolved sender),
        # a missing --reply-to defaults to 'none' (new conversation). Each warns.
        if args.sender_ctx:
            _deprecation_warn(
                "--from is IGNORED: the sender is the trusted resolved session "
                "($AI_TRACKING_ID / authenticated context). Stop passing --from."
            )
        if args.reply_to is None:
            _deprecation_warn(
                "--reply-to is now REQUIRED (nullable). Defaulting to 'none' (a "
                "new conversation) for this deprecation window; this becomes a "
                "hard error after the cutover. Pass --reply-to <msg_id> or "
                "--reply-to none explicitly."
            )
            args.reply_to = "none"
        try:
            result = send_prompt(
                to=args.to,
                content=args.content,
                reply_to=args.reply_to,
                subject=args.subject,
                sender_ctx=None,  # --from ignored (shim): trusted sender resolved
                urgency=args.urgency,
                ttl_seconds=args.ttl,
                timing=args.timing,
                source=args.source,
                callback_endpoint=args.callback_endpoint,
                queue=args.queue,
            )
        except (
            ReplyRuleError, SenderUnresolved, RecipientNotFound, RecipientAmbiguous,
        ) as e:
            result = {"success": False, "error": str(e),
                      "error_type": type(e).__name__}
    elif args.command == "post-standing":
        result = post_standing(
            scope=args.scope,
            from_sender=args.from_sender,
            content=args.content,
            scope_name=args.scope_name,
            ttl_seconds=args.ttl,
            approved_by=args.approved_by,
        )
    elif args.command == "query-standing":
        scope_list = [s.strip() for s in args.scopes.split(",")]
        result = query_standing(
            scopes=scope_list,
            team=args.team,
            platform=args.platform,
            project=args.project,
            limit=args.limit,
        )
    elif args.command == "cancel-standing":
        result = cancel_standing(msg_id=args.msg_id)
    elif args.command == "read":
        reader = args.reader or os.environ.get("AI_TRACKING_ID", "unknown")
        result = read_message(msg_id=args.msg_id, reader=reader)
    elif args.command == "reply":
        result = reply_to_message(
            msg_id=args.msg_id,
            from_sender=args.from_sender,
            content=args.content,
            urgency=args.urgency,
            response_required=args.response_required,
            notify=getattr(args, "notify", None),
        )
    elif args.command == "reply-all":
        result = reply_to_all(
            msg_id=args.msg_id,
            from_sender=args.from_sender,
            content=args.content,
            urgency=args.urgency,
            response_required=args.response_required,
            notify=getattr(args, "notify", None),
        )
    elif args.command == "check":
        result = check_unread(session=args.session)
    elif args.command == "archive":
        result = archive_message(msg_id=args.msg_id)
    elif args.command == "list-pending":
        result = list_pending_replies(session=args.session)
    elif args.command == "check-owed":
        result = check_owed_replies(session=args.session)
    elif args.command == "search":
        result = search_messages(
            query=args.query,
            limit=args.limit,
        )
    elif args.command == "lock":
        result = lock_session(
            session_id=args.session,
            locked_by=args.locked_by,
            reason=args.reason,
        )
    elif args.command == "unlock":
        result = unlock_session(session_id=args.session)
    elif args.command == "lock-global":
        result = lock_global(
            locked_by=args.locked_by,
            reason=args.reason,
        )
    elif args.command == "unlock-global":
        result = unlock_global()
    elif args.command == "list-locks":
        result = list_locks()
    elif args.command == "list-sessions":
        store = _load_store()
        if store is None:
            result = {"error": "Session store unavailable"}
        else:
            try:
                with store._connect() as conn:
                    rows = conn.execute(
                        "SELECT tracking_id, cli_session_id, terminal_session, display_name, platform "
                        "FROM sessions ORDER BY created_at DESC LIMIT 100"
                    ).fetchall()
                sessions_list = []
                unread_map = {}
                if args.with_msgs or args.with_unread:
                    unread_map = check_unread().get("sessions", {})
                for tid, cli_uuid, terminal, dname, platform in rows:
                    if args.pattern:
                        searchable = " ".join(str(v or "") for v in (tid, cli_uuid, terminal, dname, platform)).lower()
                        if args.pattern.lower() not in searchable:
                            continue
                    entry = {"tracking_id": tid, "display_name": dname, "platform": platform,
                             "cli_uuid": cli_uuid, "terminal": terminal}
                    if args.with_msgs or args.with_unread:
                        entry["unread"] = unread_map.get(tid, 0)
                        if args.with_unread and entry["unread"] == 0:
                            continue
                    sessions_list.append(entry)
                result = {"sessions": sessions_list, "count": len(sessions_list)}
            except Exception as e:
                result = {"error": str(e)}
    elif args.command == "mark-as":
        reader = args.reader or os.environ.get("AI_TRACKING_ID", "unknown")
        ids = [mid.strip() for mid in args.msg_ids.split(",") if mid.strip()]
        results_list = []
        for mid in ids:
            r = mark_as(msg_id=mid, reader=reader, state=args.state)
            results_list.append(r)
        result = {"success": all(r.get("success") for r in results_list), "results": results_list}
    elif args.command == "move":
        session = args.session or os.environ.get("AI_TRACKING_ID", "")
        ids = [mid.strip() for mid in args.msg_ids.split(",") if mid.strip()]
        results_list = []
        for mid in ids:
            r = move_message(msg_id=mid, to_folder=args.to_folder, recipient=session)
            results_list.append(r)
        result = {"success": all(r.get("success") for r in results_list), "results": results_list}
    elif args.command == "whoami":
        session = args.session or os.environ.get("AI_TRACKING_ID", "")
        if not session:
            result = {"error": "No session. Set AI_TRACKING_ID or use --session."}
        else:
            resolved = _resolve_session(session)
            store = _load_store()
            if store:
                info = store.resolve(resolved)
                if info:
                    result = {"tracking_id": info.get("tracking_id"),
                              "cli_uuid": info.get("cli_session_id"),
                              "terminal": info.get("terminal_session"),
                              "display_name": info.get("display_name"),
                              "platform": info.get("platform")}
                else:
                    result = {"tracking_id": resolved, "error": "not found in session store"}
            else:
                result = {"tracking_id": resolved, "error": "session store unavailable"}

    # Subparser --format overrides top-level --format
    fmt = getattr(args, "output_format", None) or "json"
    if fmt in ("markdown", "md"):
        sys.stdout.write(_format_result_markdown(args.command, result))
        sys.stdout.write("\n")
    elif fmt == "text":
        sys.stdout.write(_format_result_text(args.command, result))
        sys.stdout.write("\n")
    elif fmt == "jsonl":
        _write_jsonl(result)
    else:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")

    if result.get("success") is False:
        return 1
    return 0


def _format_result_markdown(command: str, result: dict) -> str:
    """Format a CLI result as markdown."""
    if "error" in result:
        return "**Error:** {}\n".format(result["error"])

    lines = []

    if command == "list":
        msgs = result.get("messages", [])
        lines.append("## Messages ({})".format(len(msgs)))
        lines.append("")
        if not msgs:
            lines.append("_(no messages)_")
        for m in msgs:
            read_by = m.get("read_by", [])
            status = "read" if read_by else "unread"
            lines.append("- **[{}]** `{}` from **{}** _{}_".format(
                status, m.get("id", "?"), m.get("from", "?"),
                _md_time(m.get("created_at", ""))))
            preview = m.get("preview", "")
            if preview:
                lines.append("  > {}".format(preview[:100]))

    elif command == "whoami":
        lines.append("## Session Identity")
        lines.append("")
        for key in ("tracking_id", "cli_uuid", "terminal", "display_name", "platform"):
            val = result.get(key, "")
            lines.append("- **{}:** {}".format(key, val or "_(none)_"))

    elif command in ("check", "check-owed", "list-pending"):
        lines.append("## {}".format(command.replace("-", " ").title()))
        lines.append("")
        # Generic key-value dump
        for key, val in result.items():
            if key == "success":
                continue
            if isinstance(val, list):
                lines.append("### {} ({})".format(key, len(val)))
                for item in val:
                    if isinstance(item, dict):
                        parts = ["{}: {}".format(k, v) for k, v in item.items() if k != "file"]
                        lines.append("- {}".format(", ".join(parts)))
                    else:
                        lines.append("- {}".format(item))
            elif isinstance(val, dict):
                lines.append("### {}".format(key))
                for k, v in val.items():
                    lines.append("- **{}:** {}".format(k, v))
            else:
                lines.append("- **{}:** {}".format(key, val))

    elif command == "list-sessions":
        sessions = result.get("sessions", [])
        lines.append("## Sessions ({})".format(len(sessions)))
        lines.append("")
        if not sessions:
            lines.append("_(no sessions)_")
        else:
            lines.append("| Display Name | Platform | Tracking ID |")
            lines.append("|---|---|---|")
            for s in sessions:
                dname = s.get("display_name") or "_(none)_"
                lines.append("| {} | {} | `{}` |".format(
                    dname, s.get("platform", "?"), s.get("tracking_id", "?")))

    elif command == "read":
        msg = result.get("message", {})
        lines.append("## Message `{}`".format(msg.get("id", "?")))
        lines.append("")
        lines.append("- **From:** {}".format(msg.get("from", "?")))
        lines.append("- **To:** {}".format(msg.get("to", "?")))
        lines.append("- **Sent:** {}".format(_md_time(msg.get("created_at", ""))))
        lines.append("- **Urgency:** {}".format(msg.get("urgency", "")))
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(msg.get("content", ""))

    elif command in ("send", "broadcast", "reply", "reply-all"):
        lines.append("**{}:** `{}`".format(
            "Sent" if result.get("success") else "Failed",
            result.get("message_id", result.get("error", "?"))))

    elif command in ("mark-as", "move"):
        results_list = result.get("results", [])
        lines.append("## {} ({} items)".format(command, len(results_list)))
        for r in results_list:
            status = "ok" if r.get("success") else "error"
            lines.append("- `{}`: {}".format(r.get("message_id", "?"), status))

    else:
        # Generic fallback
        for key, val in result.items():
            if key == "success":
                continue
            lines.append("- **{}:** {}".format(key, val))

    return "\n".join(lines)


def _format_result_text(command: str, result: dict) -> str:
    """Format a CLI result as plain text."""
    if "error" in result:
        return "Error: {}\n".format(result["error"])

    lines = []

    if command == "list":
        msgs = result.get("messages", [])
        for m in msgs:
            read_by = m.get("read_by", [])
            status = "read" if read_by else "unread"
            lines.append("[{}] {} from:{} {} {}".format(
                status, m.get("id", "?"), m.get("from", "?"),
                m.get("created_at", "")[:16],
                (m.get("preview", "") or "")[:60]))

    elif command == "whoami":
        for key in ("tracking_id", "cli_uuid", "terminal", "display_name", "platform"):
            lines.append("{}: {}".format(key, result.get(key, "")))

    elif command == "list-sessions":
        for s in result.get("sessions", []):
            dname = s.get("display_name") or s.get("tracking_id", "?")
            parts = [dname, s.get("platform", "")]
            if "unread" in s:
                parts.append("{} unread".format(s["unread"]))
            lines.append("  ".join(p for p in parts if p))

    else:
        # Generic: dump as key=value
        for key, val in result.items():
            if key == "success":
                continue
            lines.append("{}: {}".format(key, val))

    return "\n".join(lines) if lines else str(result)


def _write_jsonl(result: dict) -> None:
    """Write each top-level value as one compact JSON line.

    For lists, each element gets its own line.
    For dicts, each key-value pair gets its own line.
    Scalars get a single line.
    """
    if isinstance(result, dict):
        for key, val in result.items():
            if isinstance(val, list):
                for item in val:
                    sys.stdout.write(json.dumps(item, default=str))
                    sys.stdout.write("\n")
            else:
                sys.stdout.write(json.dumps({key: val}, default=str))
                sys.stdout.write("\n")
    elif isinstance(result, list):
        for item in result:
            sys.stdout.write(json.dumps(item, default=str))
            sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(result, default=str))
        sys.stdout.write("\n")


def _md_time(iso_str: str) -> str:
    """Format ISO timestamp for markdown display."""
    if not iso_str:
        return ""
    return iso_str[:16].replace("T", " ")


# =========================================================================
# Main Entry Point
# =========================================================================

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns exit code.

    - No args (or just --as): enter interactive REPL.
    - With subcommand: execute and emit JSON.
    """
    # Detect REPL mode: no args, or only --as SESSION
    raw_args = argv if argv is not None else sys.argv[1:]

    # Check for --help-verbose / --help-examples before anything else
    if "--help-verbose" in raw_args:
        print(_verbose_help())
        return 0
    if "--help-examples" in raw_args:
        print(_help_examples())
        return 0

    # Determine if we should enter REPL mode
    # REPL if: no args, or only --as <value>
    enter_repl = False
    if len(raw_args) == 0:
        enter_repl = True
    elif len(raw_args) == 2 and raw_args[0] == "--as":
        enter_repl = True

    if enter_repl:
        # Determine identity — optional; REPL works without one
        identity = None  # type: Optional[str]
        if len(raw_args) == 2 and raw_args[0] == "--as":
            identity = _resolve_session(raw_args[1])
        else:
            identity = os.environ.get("AI_TRACKING_ID", "") or None

        return repl(identity)

    # Subcommand mode
    parser = _build_parser()
    args = parser.parse_args(raw_args)

    if not args.command:
        parser.print_help()
        return 1

    return _run_subcommand(args)


if __name__ == "__main__":
    sys.exit(main())
