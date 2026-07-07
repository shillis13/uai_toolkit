#!/usr/bin/env python3
"""lib_reply_rule.py — the conversation-linker for the comms model.

Pure logic that turns the enforced `reply_to` parameter into a conversation
assignment, with strict validation. There is no guessing here: an ambiguous
`reply_to` is an error, a missing subject on a new thread is an error, and a
reply that can't be tied to a live, authorized conversation is an error.

Three entry points:

  * `normalize_reply_to(raw)`        — sentinel folding + id-shape validation.
  * `resolve_conversation(index, reply_to, subject)`
                                     — mint-or-inherit the conversation id.
  * `validate_reply_target(index, reply_to, sender, ...)`
                                     — reject missing/cyclic/orphaned targets
                                       and unauthorized senders.

The functions that need lookups take a `CommsIndex` (see comms_index.py); the
module itself stores nothing.

Terms:
  * reply_to          — the message id this message answers, or a sentinel
                        meaning "this starts a new thread".
  * effective_subject — the subject that actually applies to a message; for a
                        reply it is inherited from the parent at insert time
                        (insert_message), NOT decided here.
  * participant       — a tracking id that is either the sender (from_id) of
                        some message in the conversation or a delivery
                        recipient of one.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Message ids look like: msg_20260622_085514_j1d1gusq
MESSAGE_ID_RE = re.compile(r"^msg_\d{8}_\d{6}_[0-9a-z]{8}$")

# Strings that mean "no parent / start a new thread".
_SENTINEL_WORDS = frozenset({"none", "null"})

# Guard against runaway / cyclic reply chains.
_MAX_CHAIN_DEPTH = 1000


# =============================================================================
# Typed errors
# =============================================================================

class ReplyRuleError(Exception):
    """Base class for all reply-rule failures."""


class ReplyToAmbiguous(ReplyRuleError):
    """`reply_to` was neither a sentinel nor a well-formed message id."""


class SubjectRequired(ReplyRuleError):
    """A new thread (no reply_to) was requested without a subject."""


class ReplyTargetNotFound(ReplyRuleError):
    """The parent message is missing, or its conversation is gone/archived."""


class ReplyCycle(ReplyRuleError):
    """The reply would create a self-reference or close a reply loop."""


class ReplyNotAuthorized(ReplyRuleError):
    """The sender is not a participant of the parent's conversation."""


# =============================================================================
# 1. normalize_reply_to
# =============================================================================

def normalize_reply_to(raw) -> Optional[str]:
    """Fold sentinels to None and validate id shape. Pure; no index access.

    * None / "" / whitespace-only / "none"/"null" (case-insensitive) -> None.
    * A value matching the message-id regex -> returned (stripped of any
      surrounding whitespace, otherwise unchanged).
    * Anything else (wrong shape, wrong type) -> ReplyToAmbiguous. We never
      guess what an unrecognized value was meant to be.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ReplyToAmbiguous(
            f"reply_to must be a message id string or a null sentinel, "
            f"got {type(raw).__name__}: {raw!r}"
        )
    stripped = raw.strip()
    if stripped == "":
        return None
    if stripped.lower() in _SENTINEL_WORDS:
        return None
    if MESSAGE_ID_RE.match(stripped):
        return stripped
    raise ReplyToAmbiguous(
        f"reply_to {raw!r} is neither a null sentinel nor a valid message id "
        f"(expected msg_YYYYMMDD_HHMMSS_xxxxxxxx)"
    )


# =============================================================================
# 2. resolve_conversation
# =============================================================================

def resolve_conversation(
    index, reply_to: Optional[str], subject: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Return (conversation_id, effective_subject_for_new_message).

    * reply_to is None and subject truthy -> mint a new conversation.
    * reply_to is None and no subject     -> SubjectRequired.
    * reply_to set -> inherit the parent's conversation_id. Subject is passed
      through untouched (None is fine; effective_subject inheritance happens in
      insert_message, not here).

    Pass `reply_to` through `normalize_reply_to` before calling this.
    """
    if reply_to is None:
        if subject and subject.strip():
            new_id = index.create_conversation(topic=subject)
            return new_id, subject
        raise SubjectRequired(
            "a new conversation requires a subject when reply_to is null"
        )

    parent = index.get_message(reply_to)
    if parent is None:
        raise ReplyTargetNotFound(
            f"reply_to {reply_to!r} does not exist"
        )
    cid = parent.get("conversation_id")
    # Schema guarantees a single, non-null conversation_id column (PK on id),
    # so we assert the invariant rather than re-deriving it.
    assert cid, f"message {reply_to!r} has no conversation_id (schema invariant violated)"
    return cid, subject


# =============================================================================
# 3. validate_reply_target
# =============================================================================

def validate_reply_target(
    index,
    reply_to: Optional[str],
    sender: str,
    *,
    new_message_id: Optional[str] = None,
    allow_archived: bool = False,
) -> None:
    """Raise if the reply target is invalid; return None when OK.

    No-op when reply_to is None (a new thread has no target to validate).

    Checks, in order:
      1. self-reply (reply_to == new_message_id)                  -> ReplyCycle
      2. parent missing                                  -> ReplyTargetNotFound
      3. orphaned parent / missing or archived conversation
                                                         -> ReplyTargetNotFound
         (archived is allowed only when allow_archived=True)
      4. reply chain loops, or reaches new_message_id            -> ReplyCycle
      5. sender not a participant of the conversation     -> ReplyNotAuthorized
    """
    if reply_to is None:
        return None

    # 1. Self-reply — checked before any lookup; a message can't answer itself.
    if new_message_id is not None and reply_to == new_message_id:
        raise ReplyCycle(
            f"message {new_message_id!r} cannot reply to itself"
        )

    # 2. Parent must exist.
    parent = index.get_message(reply_to)
    if parent is None:
        raise ReplyTargetNotFound(
            f"reply_to {reply_to!r} does not exist"
        )

    # 3. Parent must belong to a live conversation.
    cid = parent.get("conversation_id")
    convo = index.get_conversation(cid) if cid else {}
    convo_row = convo.get("conversation") if convo else None
    if not cid or convo_row is None:
        raise ReplyTargetNotFound(
            f"parent {reply_to!r} is orphaned (its conversation is gone)"
        )
    if convo_row.get("status") == "archived" and not allow_archived:
        raise ReplyTargetNotFound(
            f"parent {reply_to!r} is in an archived conversation"
        )

    # 4. Walk the parent chain; detect loops or a path back to new_message_id.
    seen = {parent["id"]}
    rt = parent.get("reply_to")
    depth = 0
    while rt is not None:
        depth += 1
        if depth > _MAX_CHAIN_DEPTH:
            raise ReplyCycle(
                f"reply chain from {reply_to!r} exceeds max depth "
                f"{_MAX_CHAIN_DEPTH}"
            )
        if new_message_id is not None and rt == new_message_id:
            raise ReplyCycle(
                f"reply chain from {reply_to!r} loops back to "
                f"{new_message_id!r}"
            )
        if rt in seen:
            raise ReplyCycle(
                f"reply chain from {reply_to!r} contains a loop at {rt!r}"
            )
        seen.add(rt)
        nxt = index.get_message(rt)
        if nxt is None:
            break
        rt = nxt.get("reply_to")

    # 5. Sender authorization.
    participants = index.conversation_participants(cid)
    if sender not in participants:
        raise ReplyNotAuthorized(
            f"{sender!r} is not a participant of conversation {cid!r}"
        )

    return None
