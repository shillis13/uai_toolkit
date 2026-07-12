"""
Comms tool module: messages tools.

Thin subprocess wrapper around ~/bin/ai/messages/messaging.py.
Each tool invokes messaging.py with the appropriate subcommand and arguments,
reads JSON from stdout, and returns it as TextContent.

Exports tools() and call_tool().
"""

import json
import os
import subprocess
from typing import Any

from mcp.types import Tool, TextContent


MESSAGING_SCRIPT = os.path.expanduser("~/bin/ai/messages/messaging.py")
BROADCAST_SCRIPT = os.path.expanduser("~/bin/ai/messages/broadcast.py")
SWEEP_SCRIPT = os.path.expanduser("~/bin/ai/messages/sweep_expired.py")


def _run_messaging(args: list[str]) -> dict:
    """
    Run messaging.py with the given argument list.
    Returns parsed JSON from stdout, or an error dict on failure.
    """
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    cmd = ["python3", MESSAGING_SCRIPT] + args
    try:
        result = logged_run(
            "comms", cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        stdout = result.stdout.strip()
        if stdout:
            return json.loads(stdout)
        if result.returncode != 0:
            return {
                "success": False,
                "error": f"messaging.py exited {result.returncode}",
                "stderr": result.stderr.strip(),
            }
        return {"success": True, "output": ""}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "messaging.py timed out after 30s"}
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid JSON from uai_toolkit.messages.messaging.py: {exc}",
            "raw_output": stdout,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": f"messaging.py not found at {MESSAGING_SCRIPT}",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _run_script(script_path: str, args: list[str], timeout: int = 120) -> dict:
    """Run an arbitrary script, parse JSON stdout."""
    cmd = ["python3", script_path] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        stdout = result.stdout.strip()
        if stdout:
            return json.loads(stdout)
        if result.returncode != 0:
            return {"success": False, "error": f"Script exited {result.returncode}", "stderr": result.stderr.strip()}
        return {"success": True, "output": ""}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Script timed out after {timeout}s"}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON: {exc}", "raw_output": stdout}
    except FileNotFoundError:
        return {"success": False, "error": f"Script not found at {script_path}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# === Tool Definitions ===

def tools() -> list[Tool]:
    """Return messages tool definitions with comms_ prefix."""
    return [
        Tool(
            name="comms_message_broadcast",
            description="Send a message to all agents (creates broadcast file)",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_sender": {
                        "type": "string",
                        "description": "Sender identifier (e.g., desktop_claude, cli_librarian)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message body (markdown supported)"
                    },
                    "reply_to": {
                        "type": "string",
                        "description": "Optional parent message ID for threading"
                    }
                },
                "required": ["from_sender", "content"]
            }
        ),
        Tool(
            name="comms_message",
            description=(
                "Send a durable, threaded message to an agent/session's inbox. The "
                "sender is the trusted resolved session — do NOT pass a sender. "
                "REACHABILITY: an IDLE recipient is actively nudged (a '📬 you have "
                "unread mail' prompt pushed to their terminal so they read now) ONLY "
                "when urgency is 'prompt' (default) or 'interrupt'; 'async'/'passive' "
                "land silently in the inbox and are seen on the recipient's next turn. "
                "A BUSY recipient is never interrupted — the message waits in their "
                "inbox regardless of urgency. For a direct, non-threaded terminal "
                "prompt (not inbox mail), use comms_send_prompt instead. "
                "Returns {conversationId, messageId}."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "to_recipient": {
                        "type": "string",
                        "description": "Recipient identifier (session ID or agent name)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message body (markdown supported)"
                    },
                    "reply_to": {
                        "type": ["string", "null"],
                        "description": "REQUIRED. Parent message ID to thread under, OR null to start a NEW conversation (which then REQUIRES subject). The string 'none' is also accepted as a synonym for null."
                    },
                    "subject": {
                        "type": "string",
                        "description": "Conversation subject. REQUIRED when reply_to is null/'none' (becomes the conversation topic); optional when replying."
                    },
                    "body_file": {
                        "type": "string",
                        "description": "Optional path to a file holding a large body; the message references it (read inlines it). Write big content to a file first and pass the path with a short content note — keeps the wire message and your tool args small."
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["interrupt", "prompt", "async", "passive"],
                        "description": "How hard to reach the recipient. 'prompt' (default) and 'interrupt' PUSH a nudge to an IDLE recipient's terminal so they read now; a busy recipient is never interrupted and reads it on their next turn. 'async'/'passive' are PULL-ONLY — no push; the message just waits in the inbox. Default: prompt.",
                        "default": "prompt"
                    },
                    "notify": {
                        "type": "string",
                        "enum": ["immediate", "batched", "silent"],
                        "description": "Advanced override of the nudge policy (default: derived from urgency). 'immediate' = nudge an idle recipient now; 'batched' = coalesce nudges to at most one per short window (use for BULK sends to one recipient so you don't flood them — each message still lands individually); 'silent' = never nudge (inbox-only). Leave unset to let urgency decide."
                    }
                },
                "required": ["to_recipient", "content", "reply_to"]
            }
        ),
        Tool(
            name="comms_message_list_broadcasts",
            description="List recent broadcast messages",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default 20)",
                        "default": 20
                    }
                }
            }
        ),
        Tool(
            name="comms_message_list",
            description="List direct messages (inbox) for a recipient",
            inputSchema={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Recipient to filter by (optional, lists all if omitted)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default 20)",
                        "default": 20
                    }
                }
            }
        ),
        Tool(
            name="comms_message_responses",
            description="Check for responses to a specific message",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "Message ID to check responses for"
                    }
                },
                "required": ["message_id"]
            }
        ),
        Tool(
            name="comms_message_ack",
            description="Mark a message as read/processed",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "Message ID to acknowledge"
                    },
                    "acknowledger": {
                        "type": "string",
                        "description": "Who is acknowledging (agent/session identifier)"
                    }
                },
                "required": ["message_id", "acknowledger"]
            }
        ),
        Tool(
            name="comms_list_prompt_queue",
            description="List pending prompts for a session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session to list prompts for (lists all if omitted)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of prompts to return (default 20)",
                        "default": 20
                    }
                }
            }
        ),
        Tool(
            name="comms_post_standing",
            description="Post a standing message — a persistent announcement that sessions query on demand",
            inputSchema={
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["global", "team", "platform", "project"],
                        "description": "Message scope"
                    },
                    "scope_name": {
                        "type": "string",
                        "description": "Scope name (required for team/platform/project, ignored for global)"
                    },
                    "from_sender": {
                        "type": "string",
                        "description": "Sender identifier"
                    },
                    "content": {
                        "type": "string",
                        "description": "Message text"
                    },
                    "ttl_seconds": {
                        "type": "integer",
                        "description": "Time-to-live in seconds (default: no expiry)"
                    }
                },
                "required": ["scope", "from_sender", "content"]
            }
        ),
        Tool(
            name="comms_query_standing",
            description="Query standing messages across scopes — pull persistent announcements relevant to this session",
            inputSchema={
                "type": "object",
                "properties": {
                    "scopes": {
                        "type": "string",
                        "description": "Comma-separated scopes to query (e.g. 'global,platform,team')"
                    },
                    "team": {
                        "type": "string",
                        "description": "Team name (required if querying team scope)"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform name (required if querying platform scope)"
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name (required if querying project scope)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default 50)",
                        "default": 50
                    }
                },
                "required": ["scopes"]
            }
        ),
        Tool(
            name="comms_lock_session",
            description="Lock a conversation session to prevent concurrent access",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to lock"
                    },
                    "locked_by": {
                        "type": "string",
                        "description": "Who is locking (default: user)",
                        "default": "user"
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for the lock"
                    }
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="comms_unlock_session",
            description="Unlock a conversation session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to unlock"
                    }
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name="comms_list_locks",
            description="List all conversation locks with their metadata",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # comms_broadcast_prompt / comms_broadcast_message moved to comms_broadcast.py
        # (engine-backed suite over broadcast_mgr.py, with recipient-set targeting).
        Tool(
            name="comms_sweep_expired",
            description="Remove expired messages, queue entries, and standing messages. Also cleans delivered prompt files older than 7 days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "Report only, don't delete", "default": False},
                },
            }
        ),
        Tool(
            name="comms_read_message",
            description="Read a message by its ID and mark it as read. Returns the full message content. If the message was already read by this reader, it is returned without adding a duplicate read_by entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Message ID to read (e.g. msg_20260425_120000_abc12345)"
                    },
                    "reader": {
                        "type": "string",
                        "description": "Who is reading — defaults to caller's AI_TRACKING_ID if omitted"
                    },
                },
                "required": ["id"]
            }
        ),
        Tool(
            name="comms_reply",
            description=(
                "Reply to a specific message, threading it under the same conversation "
                "to the original sender. Resolves any pending reply obligation. "
                "REACHABILITY (same rule as comms_message): an IDLE recipient is "
                "nudged when urgency is 'prompt' (default) or 'interrupt'; "
                "'async'/'passive' are inbox-only (seen on their next turn); a busy "
                "recipient is never interrupted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Message ID to reply to"
                    },
                    "from_sender": {
                        "type": "string",
                        "description": "Sender identifier (your tracking ID or name)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Reply body (markdown supported)"
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["interrupt", "prompt", "async", "passive"],
                        "description": "How hard to reach the recipient. 'prompt' (default)/'interrupt' PUSH a nudge to an idle recipient; 'async'/'passive' are PULL-ONLY (inbox, no push). Default: prompt.",
                        "default": "prompt"
                    },
                    "notify": {
                        "type": "string",
                        "enum": ["immediate", "batched", "silent"],
                        "description": "Advanced override of the nudge policy (default: derived from urgency). 'immediate' = nudge idle recipient now; 'batched' = coalesce nudges (bulk sends); 'silent' = never nudge. Leave unset to let urgency decide."
                    },
                    "response_required": {
                        "type": "boolean",
                        "description": "Whether this reply itself requires a response (default: false)",
                        "default": False
                    },
                },
                "required": ["id", "from_sender", "content"]
            }
        ),
        Tool(
            name="comms_reply_all",
            description=(
                "Reply to all participants of a message. For direct messages, sends to "
                "all parties except yourself; for broadcasts, sends a broadcast reply. "
                "Resolves any pending reply obligation. REACHABILITY (same rule as "
                "comms_message): each idle recipient is nudged when urgency is 'prompt' "
                "(default)/'interrupt'; 'async'/'passive' are inbox-only. For a reply "
                "to MANY recipients, consider notify='batched' to avoid flooding."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Message ID to reply to"
                    },
                    "from_sender": {
                        "type": "string",
                        "description": "Sender identifier (your tracking ID or name)"
                    },
                    "content": {
                        "type": "string",
                        "description": "Reply body (markdown supported)"
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["interrupt", "prompt", "async", "passive"],
                        "description": "How hard to reach recipients. 'prompt' (default)/'interrupt' PUSH a nudge to idle recipients; 'async'/'passive' are PULL-ONLY (inbox, no push). Default: prompt.",
                        "default": "prompt"
                    },
                    "notify": {
                        "type": "string",
                        "enum": ["immediate", "batched", "silent"],
                        "description": "Advanced override of the nudge policy (default: derived from urgency). 'batched' = coalesce nudges to at most one per short window (recommended for reply-all to many recipients); 'immediate' = nudge now; 'silent' = never nudge. Leave unset to let urgency decide."
                    },
                    "response_required": {
                        "type": "boolean",
                        "description": "Whether this reply itself requires a response (default: false)",
                        "default": False
                    },
                },
                "required": ["id", "from_sender", "content"]
            }
        ),
        Tool(
            name="comms_check_messages",
            description="Check unread message counts. If session is provided, returns inbox and broadcast unread counts for that session. If omitted, returns per-session unread counts across all sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session tracking ID to check (omit to check all sessions)"
                    },
                },
            }
        ),
        Tool(
            name="comms_archive_message",
            description="Archive a message by moving it from inbox to archive directory. Use this to clean up processed messages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Message ID to archive"
                    },
                },
                "required": ["id"]
            }
        ),
        Tool(
            name="comms_list_pending",
            description="List pending replies — messages that were sent with response_required=true and have not yet been answered. Optionally filter by session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Filter to pending replies where 'to' matches this session (omit for all)"
                    },
                },
            }
        ),
        Tool(
            name="comms_check_owed",
            description="Check what replies this session owes. Returns pending reply entries where 'to' matches the given session — these are messages you received with response_required that you have not yet replied to.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session tracking ID to check owed replies for"
                    },
                },
                "required": ["session"]
            }
        ),
        Tool(
            name="comms_search_messages",
            description="Search all messages (inbox, broadcasts, and archive) for text in their content. Case-insensitive substring match. Returns newest first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in message content"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 20)",
                        "default": 20
                    },
                },
                "required": ["query"]
            }
        ),
    ]


# === Tool Dispatch ===

async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle messages tool calls via subprocess to messaging.py."""

    if name == "comms_message_broadcast":
        args = [
            "broadcast",
            "--from", arguments["from_sender"],
            "--content", arguments["content"],
        ]
        if arguments.get("reply_to"):
            args += ["--reply-to", arguments["reply_to"]]
        result = _run_messaging(args)

    elif name == "comms_message":
        # v2 send contract: sender is the trusted resolved session (no --from),
        # reply_to is required + nullable (JSON null OR "none"/"null" => new
        # conversation), subject is required when starting a new conversation.
        deprecations = []
        args = [
            "send",
            "--to", arguments["to_recipient"],
            "--content", arguments["content"],
        ]
        # reply_to: required + nullable. Normalize JSON null / "none"/"null"/""
        # to the CLI sentinel 'none' (new conversation). A missing key is
        # tolerated during the deprecation window (defaults to a new conversation).
        if "reply_to" not in arguments:
            deprecations.append(
                "reply_to is now REQUIRED (nullable). Defaulting to a new "
                "conversation; pass reply_to=null (new) or a parent message id."
            )
            reply_to_val = None
        else:
            reply_to_val = arguments["reply_to"]
        if reply_to_val is None or (
            isinstance(reply_to_val, str)
            and reply_to_val.strip().lower() in ("", "none", "null")
        ):
            args += ["--reply-to", "none"]
        else:
            args += ["--reply-to", str(reply_to_val)]
        if arguments.get("subject"):
            args += ["--subject", arguments["subject"]]
        if arguments.get("body_file"):
            args += ["--body-file", arguments["body_file"]]
        if arguments.get("urgency"):
            args += ["--urgency", arguments["urgency"]]
        if arguments.get("notify"):
            args += ["--notify", arguments["notify"]]
        # 'from'/'from_sender' is no longer authoritative — ignore it (the CLI
        # resolves the trusted sender) but note the deprecation in the result.
        if arguments.get("from") or arguments.get("from_sender"):
            deprecations.append(
                "'from'/'from_sender' is ignored — the sender is the trusted "
                "resolved session. Stop passing it."
            )
        result = _run_messaging(args)
        if deprecations and isinstance(result, dict):
            result.setdefault("deprecations", []).extend(deprecations)

    elif name == "comms_message_list_broadcasts":
        args = [
            "list",
            "--folder", "broadcasts",
            "--limit", str(arguments.get("limit", 20)),
        ]
        result = _run_messaging(args)

    elif name == "comms_message_list":
        args = [
            "list",
            "--folder", "inbox",
            "--limit", str(arguments.get("limit", 20)),
        ]
        if arguments.get("recipient"):
            args += ["--session", arguments["recipient"]]
        result = _run_messaging(args)

    elif name == "comms_message_responses":
        args = [
            "check-responses",
            "--id", arguments["message_id"],
        ]
        result = _run_messaging(args)

    elif name == "comms_message_ack":
        args = [
            "acknowledge",
            "--id", arguments["message_id"],
            "--by", arguments["acknowledger"],
        ]
        result = _run_messaging(args)

    elif name == "comms_list_prompt_queue":
        args = [
            "list",
            "--folder", "prompts",
            "--limit", str(arguments.get("limit", 20)),
        ]
        if arguments.get("session"):
            args += ["--session", arguments["session"]]
        result = _run_messaging(args)

    elif name == "comms_post_standing":
        args = [
            "post-standing",
            "--scope", arguments["scope"],
            "--from", arguments["from_sender"],
            "--content", arguments["content"],
        ]
        if arguments.get("scope_name"):
            args += ["--scope-name", arguments["scope_name"]]
        if arguments.get("ttl_seconds") is not None:
            args += ["--ttl", str(arguments["ttl_seconds"])]
        result = _run_messaging(args)

    elif name == "comms_query_standing":
        args = [
            "query-standing",
            "--scopes", arguments["scopes"],
            "--limit", str(arguments.get("limit", 50)),
        ]
        if arguments.get("team"):
            args += ["--team", arguments["team"]]
        if arguments.get("platform"):
            args += ["--platform", arguments["platform"]]
        if arguments.get("project"):
            args += ["--project", arguments["project"]]
        result = _run_messaging(args)

    elif name == "comms_lock_session":
        args = [
            "lock",
            "--session", arguments["session_id"],
            "--by", arguments.get("locked_by", "user"),
        ]
        if arguments.get("reason"):
            args += ["--reason", arguments["reason"]]
        result = _run_messaging(args)

    elif name == "comms_unlock_session":
        args = [
            "unlock",
            "--session", arguments["session_id"],
        ]
        result = _run_messaging(args)

    elif name == "comms_list_locks":
        args = ["list-locks"]
        result = _run_messaging(args)

    elif name == "comms_sweep_expired":
        args = []
        if arguments.get("dry_run"):
            args.append("--dry-run")
        result = _run_script(SWEEP_SCRIPT, args)

    elif name == "comms_read_message":
        args = ["read", "--id", arguments["id"]]
        if arguments.get("reader"):
            args += ["--reader", arguments["reader"]]
        result = _run_messaging(args)

    elif name == "comms_reply":
        args = [
            "reply",
            "--id", arguments["id"],
            "--from", arguments["from_sender"],
            "--content", arguments["content"],
        ]
        if arguments.get("urgency"):
            args += ["--urgency", arguments["urgency"]]
        if arguments.get("notify"):
            args += ["--notify", arguments["notify"]]
        if arguments.get("response_required"):
            args.append("--response-required")
        result = _run_messaging(args)

    elif name == "comms_reply_all":
        args = [
            "reply-all",
            "--id", arguments["id"],
            "--from", arguments["from_sender"],
            "--content", arguments["content"],
        ]
        if arguments.get("urgency"):
            args += ["--urgency", arguments["urgency"]]
        if arguments.get("notify"):
            args += ["--notify", arguments["notify"]]
        if arguments.get("response_required"):
            args.append("--response-required")
        result = _run_messaging(args)

    elif name == "comms_check_messages":
        args = ["check"]
        if arguments.get("session"):
            args += ["--session", arguments["session"]]
        result = _run_messaging(args)

    elif name == "comms_archive_message":
        args = ["archive", "--id", arguments["id"]]
        result = _run_messaging(args)

    elif name == "comms_list_pending":
        args = ["list-pending"]
        if arguments.get("session"):
            args += ["--session", arguments["session"]]
        result = _run_messaging(args)

    elif name == "comms_check_owed":
        args = ["check-owed", "--session", arguments["session"]]
        result = _run_messaging(args)

    elif name == "comms_search_messages":
        args = [
            "search",
            "--query", arguments["query"],
            "--limit", str(arguments.get("limit", 20)),
        ]
        result = _run_messaging(args)

    else:
        return None  # Not handled by this module

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
