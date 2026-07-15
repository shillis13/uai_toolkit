"""
Comms tool module: prompting tools.

Extracted from mcps/prompting/server.py.
Exports tools() and call_tool().
"""

import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Any, Optional

from mcp.types import Tool, TextContent

# === Configuration ===
PROMPTING_DIR = Path(os.path.expanduser("~/bin/ai/prompting"))
AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[5]))
READ_JSONL_SCRIPT = AI_ROOT / "ai_general/scripts/jsonl/read_jsonl.py"
LOG_DIR = AI_ROOT / "ai_general/logs"
SCHEDULE_SCRIPT = PROMPTING_DIR / "schedule_prompt.py"
SERVER_VERSION = "1.2.0"
_MESSAGES_DIR = AI_ROOT / "ai_general/scripts/messages"


def _resolve_target_tid(endpoint: Optional[str], target: Optional[str],
                        session: Optional[str]) -> Optional[str]:
    """Best-effort target tracking-id for a prompt-block check. For CLI targets
    `session` is the terminal name (== tracking id); otherwise parse it out of a
    prompt://<target>/<session>[?...] endpoint."""
    if session:
        return session
    if endpoint:
        tail = endpoint.split("://", 1)[-1]
        parts = tail.split("/", 1)
        if len(parts) == 2:
            return parts[1].split("?", 1)[0]
    return None


def _check_prompt_block(endpoint, target, session, message):
    """If the target session is prompt-blocked and the sender isn't exempt, HOLD
    the prompt (queued, delivered on unblock) and return a result dict; else None.
    Fail-OPEN: any error in the check must never break normal sends."""
    ttid = _resolve_target_tid(endpoint, target, session)
    if not ttid:
        return None
    sender = os.environ.get("AI_TRACKING_ID") or "user"
    if sender == ttid:            # self-sends are always allowed
        return None
    try:
        if str(_MESSAGES_DIR) not in sys.path:
            sys.path.insert(0, str(_MESSAGES_DIR))
        from uai_toolkit.messages import prompt_blocks as pb
        decision = pb.is_blocked(ttid, sender=sender)
        if not decision.get("blocked"):
            return None
        held = pb.hold_prompt(ttid, message, source=sender)
    except Exception:
        return None
    return {
        "success": True, "blocked": True, "held": True, "target": ttid,
        "queue_id": held.get("queue_id"),
        "mode": decision.get("mode"), "reason": decision.get("reason"),
        "remaining": decision.get("remaining"), "until": decision.get("until"),
        "note": ("Target session is prompt-blocked (prompts from others are held). "
                 "Queued; it delivers when the block lifts."),
    }


# === Session locks (module-level state) ===
_session_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def get_session_lock(session: str) -> threading.Lock:
    """Get or create a lock for a session."""
    with _locks_lock:
        if session not in _session_locks:
            _session_locks[session] = threading.Lock()
        return _session_locks[session]


# === Helper Functions ===

def _audit_prompt_dispatch(target, session, message, submit, label):
    """Emit high-level audit event for prompt dispatch. Never raises."""
    try:
        from uai_toolkit.audit import lib_audit
        target_type = "cli_session" if target in ("claude-cli", "codex-cli", "gemini-cli", "cli-direct") else (
            "desktop" if target == "claude-desktop" else "webui")
        lib_audit.emit(
            category="comms",
            action="prompt_dispatch",
            target={"type": target_type, "session": session, "platform": target},
            details={
                "text_length": len(message) if message else 0,
                "text_preview": (message or "")[:512],
                "submit": submit,
            },
            label=label,
        )
    except Exception:
        pass


MESSAGING_SCRIPT = os.path.expanduser("~/bin/ai/messages/messaging.py")


def _durable_send_prompt(session: str, message: str, reply_to, subject) -> dict:
    """Persist a prompt durably via the v2 send-prompt path (§6).

    Additive to the live terminal delivery — writes the canonical message row +
    delivery (the prompt does not evaporate) WITHOUT re-queuing the legacy
    prompt file (the live path already delivered). Returns the parsed
    {conversationId, messageId} result, or an error dict. Never raises.
    """
    args = [
        "python3", MESSAGING_SCRIPT, "send-prompt",
        "--to", session, "--content", message, "--no-queue",
    ]
    # reply_to: None/"none"/"null"/"" => new conversation; else a parent id.
    if reply_to is None or (
        isinstance(reply_to, str) and reply_to.strip().lower() in ("", "none", "null")
    ):
        args += ["--reply-to", "none"]
    elif reply_to != "__absent__":
        args += ["--reply-to", str(reply_to)]
    else:
        # No reply_to passed but a subject was — start a new conversation.
        args += ["--reply-to", "none"]
    if subject:
        args += ["--subject", subject]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        if out:
            return json.loads(out)
        return {"success": False, "error": result.stderr.strip() or
                f"send-prompt exited {result.returncode}"}
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON from send-prompt: {exc}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def run_script(script_name: str, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run a shell script and return (returncode, stdout, stderr)."""
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    script_path = PROMPTING_DIR / script_name
    if not script_path.exists():
        return (1, "", f"Script not found: {script_path}")

    try:
        result = logged_run(
            "comms", [str(script_path)] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(AI_ROOT)
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (1, "", f"Script timed out after {timeout}s")
    except Exception as e:
        return (1, "", str(e))


def _ensure_session_paths():
    """Add session_mgmt and prompting libraries to sys.path."""
    session_mgmt_dir = os.path.join(os.path.expanduser("~"), "bin", "ai", "session_mgmt")
    prompting_dir = os.path.join(os.path.expanduser("~"), "bin", "ai", "prompting")
    for d in [session_mgmt_dir, prompting_dir]:
        if d not in sys.path:
            sys.path.insert(0, d)


def _capture_terminal(session: str, lines: int = 50) -> Optional[str]:
    """Capture terminal content via session_ops (substrate-agnostic)."""
    try:
        _ensure_session_paths()
        from uai_toolkit.session_mgmt.session_ops import read_terminal
        output = read_terminal(session)
        if not output:
            return None
        all_lines = output.split("\n")
        if lines and len(all_lines) > lines:
            all_lines = all_lines[-lines:]
        return "\n".join(all_lines)
    except Exception:
        return None


def _has_session(session: str) -> bool:
    """Check if terminal session exists via session_ops (substrate-agnostic)."""
    try:
        _ensure_session_paths()
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        sessions = list_sessions()
        return any(s.get("name") == session for s in sessions)
    except Exception:
        return False


def _is_session_ready(session: str) -> bool:
    """Check if session is ready for input via session_ops."""
    try:
        _ensure_session_paths()
        from uai_toolkit.session_mgmt.session_ops import get_ai_status
        status = get_ai_status(session)
        return status.get("state") == "idle" if status.get("ok") else False
    except Exception:
        output = _capture_terminal(session, 20)
        if not output:
            return False
        if "Type your message" in output or "@path/to/file" in output:
            return True
        lines = output.strip().split("\n")
        for line in reversed(lines):
            if line.strip() in [">", "❯"]:
                return True
        return False


def list_terminal_sessions(pattern: Optional[str] = None) -> list[dict]:
    """List terminal sessions via session_ops (substrate-agnostic)."""
    try:
        _ensure_session_paths()
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        all_sessions = list_sessions()
        sessions = []
        for s in all_sessions:
            name = s.get("name", "")
            if pattern and pattern not in name:
                continue
            sessions.append({
                "name": name,
                "attached": s.get("attached", False)
            })
        return sessions
    except Exception:
        return []


def _run_schedule_script(sub_args: list[str], timeout: int = 15) -> dict:
    """Run schedule_prompt.py with --json and return parsed result."""
    if not SCHEDULE_SCRIPT.exists():
        return {"error": f"schedule_prompt.py not found at {SCHEDULE_SCRIPT}"}
    try:
        result = subprocess.run(
            [sys.executable, str(SCHEDULE_SCRIPT), "--json"] + sub_args,
            capture_output=True, text=True, timeout=timeout,
            cwd=str(AI_ROOT)
        )
        output = result.stdout.strip()
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"raw_output": output, "returncode": result.returncode}
        return {"error": result.stderr.strip() or "No output", "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"schedule_prompt.py timed out after {timeout}s"}
    except Exception as e:
        return {"error": str(e)}


def test_server() -> dict:
    """Test server connectivity and configuration."""
    scripts = ["send_prompt.py", "lib_send_prompt.py", "lib_send_prompt_desktop.py", "lib_send_prompt_webui.py"]
    script_status = {}
    for script in scripts:
        script_status[script] = (PROMPTING_DIR / script).exists()

    sessions = list_terminal_sessions()
    cli_sessions = [s for s in sessions if any(p in s["name"] for p in ["claude", "codex", "gemini", "shard"])]

    return {
        "server": "comms (prompting)",
        "version": SERVER_VERSION,
        "status": "ok",
        "prompting_dir": str(PROMPTING_DIR),
        "prompting_dir_exists": PROMPTING_DIR.exists(),
        "scripts": script_status,
        "terminal_sessions": len(sessions),
        "cli_sessions": len(cli_sessions),
        "active_cli_sessions": [s["name"] for s in cli_sessions[:10]]
    }


# === Tool Definitions ===

def tools() -> list[Tool]:
    """Return prompting tool definitions with comms_ prefix."""
    return [
        Tool(
            name="comms_test",
            description="Test comms server connectivity and configuration (prompting + messages)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="comms_send_prompt",
            description="""Send a prompt to an AI target. THIS IS THE CORRECT WAY TO SEND PROMPTS.

DO NOT write your own terminal write scripts. They will fail due to timing issues.
This tool handles:
- Proper timing between text and Enter
- Verification that input was received
- Busy state detection
- Fallback options

Targets: claude-desktop, claude-web, claude-cli, codex-cli, gemini-cli, chatgpt-web, chatgpt-app
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "DEPRECATED (use `endpoint`). Target AI platform: claude-desktop, claude-web, claude-cli, codex-cli, gemini-cli, chatgpt-web. Prefer endpoint=uai://session/<id> (a session already implies its platform).",
                        "enum": ["claude-desktop", "claude-web", "claude-cli", "codex-cli", "gemini-cli", "chatgpt-web", "chatgpt-app"]
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send"
                    },
                    "submit": {
                        "type": "boolean",
                        "description": "Submit the message (press Enter). Default: true",
                        "default": True
                    },
                    "session": {
                        "type": "string",
                        "description": "DEPRECATED (encode in `endpoint`). Explicit terminal/session for CLI targets. Prefer endpoint=uai://session/<id> — the action-aware resolver maps it to the right terminal."
                    },
                    "convo_id": {
                        "type": "string",
                        "description": "Conversation ID or URL. For web targets: chat URL. For claude-desktop: claude:// deep link or https://claude.ai/ URL (auto-converted to claude://). Opens specific conversation before sending."
                    },
                    "fallback_queue": {
                        "type": "boolean",
                        "description": "Queue message if target is busy",
                        "default": False
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Bypass busy checks, send immediately",
                        "default": False
                    },
                    "endpoint": {
                        "type": "string",
                        "description": "PREFERRED addressing. Endpoint URI: uai://session/<tracking_id> (canonical — resolves to the session's platform+terminal) or prompt://<target>/<terminal>. Replaces the deprecated target+session params."
                    },
                    "reply_to": {
                        "type": ["string", "null"],
                        "description": "Optional. Parent message ID to thread this prompt under, OR null/'none' to start a NEW conversation (requires subject). When provided with a concrete CLI 'session', the prompt is ALSO recorded durably via the v2 send-prompt path so it does not evaporate."
                    },
                    "subject": {
                        "type": "string",
                        "description": "Conversation subject for the durable record. Required when reply_to is null/'none'. The sender is the trusted resolved session — do not pass it."
                    }
                },
                "required": ["message"]
            }
        ),
        Tool(
            name="comms_is_busy",
            description="Check if an AI target is currently busy/processing",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target to check: desktop, webui, cli, or specific session name"
                    },
                    "session": {
                        "type": "string",
                        "description": "Specific terminal session (for CLI)"
                    }
                },
                "required": ["target"]
            }
        ),
        Tool(
            name="comms_list_sessions",
            description="List active terminal sessions, optionally filtered by pattern",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Filter pattern (e.g., 'claude', 'gemini', 'shard')"
                    }
                }
            }
        ),
        Tool(
            name="comms_observe_session",
            description="""Capture current state of a CLI session.

Use this BEFORE sending prompts to verify the session is ready.
Use this AFTER sending prompts to verify they were received.

Returns the last N lines of the terminal pane, showing:
- Current prompt/input state
- Recent output
- Processing indicators
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Terminal session name"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to capture (default: 30)",
                        "default": 30
                    }
                },
                "required": ["session"]
            }
        ),
        Tool(
            name="comms_wait_response",
            description="""Wait for a response pattern in a CLI session.

Use this after sending a prompt to wait for the actual response.
DO NOT just grep for keywords - this waits for state changes.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Terminal session name"
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to wait for in output"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60)",
                        "default": 60
                    },
                    "poll_interval": {
                        "type": "integer",
                        "description": "Seconds between checks (default: 2)",
                        "default": 2
                    }
                },
                "required": ["session", "pattern"]
            }
        ),
        # comms_send_to_session REMOVED — raw unattributed writes are a hole
        # in the attribution system. Use comms_send_prompt for attributed messages,
        # comms_send_slash_command for terminal control commands.
        Tool(
            name="comms_schedule_future_prompt",
            description="""Schedule a prompt to be sent to an AI target at a future time.

Uses macOS 'at' for durable scheduling — survives server restarts.
Internally calls send_prompt.py when the timer fires.

Provide either delay_seconds (relative) or at_time (absolute ISO datetime), not both.
Maximum delay: 24 hours. Use tag for easy listing/cancellation.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target AI (same as send_prompt targets)",
                        "enum": ["claude-desktop", "claude-web", "claude-cli", "codex-cli", "gemini-cli", "chatgpt-web", "chatgpt-app"]
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send at scheduled time"
                    },
                    "session": {
                        "type": "string",
                        "description": "Specific terminal session name to target (for CLI targets). If omitted, send_prompt.py auto-discovers."
                    },
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Relative delay from now in seconds"
                    },
                    "at_time": {
                        "type": "string",
                        "description": "Absolute ISO datetime (e.g. 2026-03-18T15:30:00)"
                    },
                    "tag": {
                        "type": "string",
                        "description": "Label for listing/cancelling. Must be unique among pending prompts."
                    }
                },
                "required": ["target", "message"]
            }
        ),
        Tool(
            name="comms_list_scheduled_prompts",
            description="List pending scheduled prompts with tag, target, and time remaining",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="comms_cancel_scheduled_prompt",
            description="Cancel a scheduled prompt by tag or at job ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "Cancel by tag name"
                    },
                    "at_job_id": {
                        "type": "string",
                        "description": "Cancel by at job ID"
                    }
                }
            }
        ),
        Tool(
            name="comms_condense_me",
            description="""Request condensation of your own session history into a handoff file.

Call this to create an operational handoff from your current session. The handoff
is a structured YAML file that a successor AI can load to continue your work.

This runs the condensation pipeline: first-pass compaction (strip tool results,
trim text), then sends the prepared input to a designated condenser session.

You control whether your private thinking blocks are included. If you have
private thoughts ([/PRIVATE] marked) that contain reasoning important for the
handoff, set include_private=true. Default is false (private blocks dropped
before the condenser sees them).
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "src_uuid": {
                        "type": "string",
                        "description": "Your CLI session UUID. Required so the pipeline knows which JSONL to condense."
                    },
                    "condenser_session": {
                        "type": "string",
                        "description": "Terminal session name of the condenser AI. If omitted, uses configured default."
                    },
                    "include_private": {
                        "type": "boolean",
                        "description": "Include private thinking blocks in the condensation input. Default: false. Only YOU should decide this -- the human does not control this flag.",
                        "default": False
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable name for the handoff"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of the handoff content"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Custom output path. Default: auto-generated in handoff store."
                    },
                    "self_condense": {
                        "type": "boolean",
                        "description": "If true, skip the condenser session. Returns the prepared input path and prompt path so YOU can do the condensation yourself in your own context. Default: false.",
                        "default": False
                    }
                },
                "required": ["src_uuid"]
            }
        ),
        Tool(
            name="comms_read_history",
            description="""Read chat history for a CLI session.

Wraps read_jsonl.py to retrieve parsed conversation history.
Returns messages as structured JSON for programmatic use.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "CLI session UUID (full or prefix)"
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform filter",
                        "enum": ["claude_cli", "codex_cli", "gemini_cli"]
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (default: json)",
                        "enum": ["json", "text", "markdown"],
                        "default": "json"
                    },
                    "last_n": {
                        "type": "integer",
                        "description": "Only return the last N messages"
                    }
                },
                "required": ["uuid"]
            }
        ),
        Tool(
            name="comms_send_slash_command",
            description="""Send a slash command to a CLI session's terminal.

Use this to send built-in CLI commands like /compact, /clear, /color, /rename,
/fast, /help, etc. to any session — including your own.

Internally constructs a send_prompt call. Accepts any session identifier:
- prompt:// URI (e.g. prompt://claude-cli/Relay) — preferred
- Tracking ID, CLI UUID (prefix OK), terminal session name, display name
- 'self' — your own session, resolved via AI_TRACKING_ID

The command is automatically prefixed with '/' if not already present, and
Enter is pressed to submit it.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Session to target: prompt:// URI (preferred), tracking ID, CLI UUID, terminal name, display name, or 'self'"
                    },
                    "command": {
                        "type": "string",
                        "description": "Slash command to send (e.g. '/compact', '/color cyan', 'compact'). Auto-prefixed with '/' if missing."
                    }
                },
                "required": ["identifier", "command"]
            }
        ),
        Tool(
            name="comms_reconnect_mcp_servers",
            description="""Reconnect our local custom MCP servers in a CLI session.

Sends `/mcp reconnect <server>` (a non-interactive Claude Code command) for each
of our self-authored MCP servers under ai_general/apps/mcps/ — by default:
browser, knowledge, sessions, workflow, comms (comms last, since reconnecting it
can briefly drop the server handling this call).

Use this after editing an MCP server's code so a running session picks up the
change without a full restart. Our Python servers call their tool handlers
in-process, so code edits are otherwise invisible until reconnect.

Targets any session identifier (prompt:// URI, tracking ID, CLI UUID, terminal
name, display name, or 'self'). Commands are submitted one per server with a
short delay so the target's input box doesn't coalesce them.

NOTE: `/mcp reconnect` reliably reconnects dropped servers; whether it re-spawns
a healthy stdio subprocess (reloading in-process code) is environment-dependent —
verify the effect if you depend on a code reload. Use dry_run to preview.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Session to target: prompt:// URI, tracking ID, CLI UUID, terminal name, display name, or 'self' (default: self)"
                    },
                    "servers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Explicit server names to reconnect (default: all local custom servers)"
                    },
                    "delay": {
                        "type": "number",
                        "description": "Seconds to pause between submissions (default: 1.0)"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, report the planned commands without sending them"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="comms_is_prompt_clear",
            description="""Check if a session's prompt input area is clear (safe to write).

Returns whether the session is idle with an empty prompt area — meaning
it's safe to send a prompt or slash command without overwriting typed text.

Accepts any session identifier or 'self'. If no session specified, checks
all active sessions.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session to check: URI, tracking ID, display name, or 'self'. If omitted, checks all active sessions."
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="comms_get_prompt_text",
            description="""Read what's currently typed in a session's prompt input area.

Returns the actual text in the prompt area, along with the session's state
(prompt_area_clear, prompt_area_occupied, responding), context %, and model.

Useful for inspecting what an agent has typed but not yet submitted.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session to read: URI, tracking ID, display name, or 'self'."
                    },
                    "include_empty": {
                        "type": "boolean",
                        "description": "Include sessions with empty/clear prompt areas (default: false, only returns occupied)",
                        "default": False
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="comms_load_context",
            description="""Load context files into a running session for delivery on its next turn.

Stages briefs, traits, roles, working memory, or any text file into the target
session's context_to_load/ inbox. The session's UserPromptSubmit hook picks them
up on its next prompt and injects their content as additionalContext, then
removes them (one-shot delivery).

This is the imperative counterpart to the automatic hook-driven loaders
(PostCompact brief restore, SessionStart context staging): use it to push a
specific brief or document into any session — including 'self' — on demand.

Accepts any session identifier: tracking ID, CLI UUID (prefix OK), terminal
name, display name, or 'self'.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Target session: tracking ID, CLI UUID, terminal name, display name, or 'self' (default: self).",
                        "default": "self"
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Absolute paths of files to stage for delivery (briefs, traits, any text file)."
                    },
                    "copy": {
                        "type": "boolean",
                        "description": "Copy files into the inbox instead of symlinking (default: false = symlink).",
                        "default": False
                    },
                    "prefix": {
                        "type": "string",
                        "description": "Optional numeric prefix to control delivery sort order (e.g. '01')."
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Resolve and validate without staging; returns what would be loaded (default: false).",
                        "default": False
                    }
                },
                "required": ["files"]
            }
        ),
        Tool(
            name="comms_rename_session",
            description="""Rename a CLI session and optionally set its color.

Updates display_name in the SQLite session store AND sends /rename to the
terminal so Claude Code's own UI also reflects the change.

By default, fails if the name has been used before — returns usage count and
active session count. Pass allowRepeatNames=true to override.

Optionally sends /color (Claude Code only — ignored on other platforms).
Supported colors: red, blue, green, yellow, purple, orange, pink, cyan, default.

Accepts any identifier: tracking ID, CLI UUID (prefix OK), or terminal session name.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "Tracking ID, CLI UUID (prefix OK), or terminal session name"
                    },
                    "name": {
                        "type": "string",
                        "description": "New display name for the session"
                    },
                    "color": {
                        "type": "string",
                        "description": "Session color (Claude Code only). Options: red, blue, green, yellow, purple, orange, pink, cyan, default",
                        "enum": ["red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan", "default"]
                    },
                    "allowRepeatNames": {
                        "type": "boolean",
                        "description": "Allow reusing a name that has been used before. Default false — fails with usage info if name was previously used.",
                        "default": False
                    }
                },
                "required": ["identifier", "name"]
            }
        ),
        Tool(
            name="comms_block_session",
            description=(
                "Block a session from receiving prompts from anyone but the user. "
                "Prompts from other sessions are HELD (queued) and delivered when "
                "the block lifts; the user's direct input always gets through. "
                "Duration: omit both turns/until = indefinite; --turns N auto-lifts "
                "after N completed turns; until = ISO time or relative '+90m'/'+2h'/'+1d'. "
                "An interrupt-urgency message that is blocked fires a user notification. "
                "Shows a 🔒 indicator on the statusline, footer, and session cards."),
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {"type": "string", "description": "Target session tracking id (or 'self')"},
                    "turns": {"type": "integer", "description": "Auto-lift after N completed turns"},
                    "until": {"type": "string", "description": "Auto-lift at ISO time or relative +90m/+2h/+1d"},
                    "reason": {"type": "string", "description": "Optional human note"},
                },
                "required": ["session"],
            },
        ),
        Tool(
            name="comms_unblock_session",
            description="Lift a session's prompt block and release any held prompts (delivered on its next drain).",
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {"type": "string", "description": "Target session tracking id (or 'self')"},
                },
                "required": ["session"],
            },
        ),
        Tool(
            name="comms_list_blocks",
            description="List all live prompt blocks (session, mode, turns/until, reason).",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# === Tool Dispatch ===

async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle prompting tool calls."""
    result = {}

    if name == "comms_test":
        # Merge prompting test with messages test (messages portion handled in comms_messages)
        result = test_server()

    elif name == "comms_send_prompt":
        endpoint = arguments.get("endpoint")
        target = arguments.get("target")
        message = arguments["message"]
        submit = arguments.get("submit", True)
        session = arguments.get("session")
        convo_id = arguments.get("convo_id")
        fallback_queue = arguments.get("fallback_queue", False)
        force = arguments.get("force", False)
        _audit_prompt_dispatch(target or endpoint, session, message, submit, "comms:send_prompt")

        # Prompt-block enforcement: if the target is blocked and we aren't exempt,
        # HOLD the prompt (queued; delivered on unblock) instead of injecting it.
        _blocked = _check_prompt_block(endpoint, target, session, message)
        if _blocked is not None:
            result = _blocked
        elif endpoint:
            # Endpoint mode: delegate to send_prompt.py --endpoint
            args = ["--endpoint", endpoint, "--message", message]
            if submit:
                args.append("--submit")
            if force:
                args.append("--force")
            returncode, stdout, stderr = run_script("send_prompt.py", args)
            result = {
                "success": returncode == 0,
                "endpoint": endpoint,
                "message_preview": message[:100] + "..." if len(message) > 100 else message,
                "submitted": submit,
                "stdout": stdout.strip() if stdout else None,
                "stderr": stderr.strip() if stderr else None
            }
        else:
            if not target:
                result = {"success": False, "error": "Either 'target' or 'endpoint' is required"}
            else:
                args = ["--target", target, "--message", message]
                if session:
                    args.extend(["--session", session])
                if submit:
                    args.append("--submit")
                if convo_id:
                    args.extend(["--convo_id", convo_id])
                if fallback_queue:
                    args.append("--fb_queue")
                if force:
                    args.append("--force")

                # ONE delivery path: send_prompt.py — which applies the sender
                # envelope, the conversation-lock check, and busy-queueing. The old
                # `send_cli` fast-path (taken when a CLI session was named) bypassed
                # ALL of those and was removed; it was legacy ported in during the
                # comms-MCP consolidation, not a needed optimization. send_prompt.py
                # targets the explicit session via --session.
                returncode, stdout, stderr = run_script("send_prompt.py", args)

                result = {
                    "success": returncode == 0,
                    "target": target,
                    "message_preview": message[:100] + "..." if len(message) > 100 else message,
                    "submitted": submit,
                    "stdout": stdout.strip() if stdout else None,
                    "stderr": stderr.strip() if stderr else None
                }

        # v2 durable record (additive): when the caller threads the prompt
        # (reply_to/subject) and a concrete CLI session is named, ALSO persist it
        # via the v2 send-prompt path so the prompt does not evaporate (§6). This
        # never breaks the live delivery above — failures surface under "durable".
        reply_to = arguments.get("reply_to", "__absent__")
        subject = arguments.get("subject")
        if (reply_to != "__absent__" or subject) and session and isinstance(result, dict) \
                and not result.get("blocked"):
            durable = _durable_send_prompt(session, message, reply_to, subject)
            result["durable"] = durable
            if isinstance(durable, dict) and "conversationId" in durable:
                result["conversationId"] = durable["conversationId"]
                result["messageId"] = durable["messageId"]

    elif name == "comms_is_busy":
        target = arguments["target"]
        session = arguments.get("session")

        if session:
            if not _has_session(session):
                result = {"busy": True, "reason": "session_not_found", "session": session}
            else:
                ready = _is_session_ready(session)
                result = {"busy": not ready, "ready": ready, "session": session}
        else:
            returncode, stdout, stderr = run_script("ai_isBusy.py", [target], timeout=10)
            result = {
                "busy": returncode != 0,
                "target": target,
                "output": stdout.strip() if stdout else stderr.strip()
            }

    elif name == "comms_list_sessions":
        pattern = arguments.get("pattern")
        sessions = list_terminal_sessions(pattern)
        result = {
            "sessions": sessions,
            "count": len(sessions),
            "pattern": pattern
        }

    elif name == "comms_observe_session":
        session = arguments["session"]
        lines = arguments.get("lines", 30)
        try:
            output = _capture_terminal(session, lines)
            if output is None:
                result = {"error": f"Failed to capture session: {session}"}
            else:
                _ensure_session_paths()
                from uai_toolkit.session_mgmt.session_ops import get_ai_status
                status = get_ai_status(session)
                result = {
                    "session": session,
                    "state": status.get("state", "unknown") if status.get("ok") else "unknown",
                    "lines": lines,
                    "output": output,
                }
        except Exception as e:
            result = {"error": str(e)}

    elif name == "comms_wait_response":
        session = arguments["session"]
        pattern = arguments["pattern"]
        timeout = arguments.get("timeout", 60)
        poll_interval = arguments.get("poll_interval", 2)

        wait_script = PROMPTING_DIR / "wait_response.py"
        if not wait_script.exists():
            result = {"error": f"wait_response.py not found at {wait_script}"}
        else:
            try:
                proc = subprocess.run(
                    [sys.executable, str(wait_script), session, pattern,
                     "--timeout", str(timeout), "--poll-interval", str(poll_interval)],
                    capture_output=True, text=True,
                    timeout=timeout + 10,
                    cwd=str(AI_ROOT)
                )
                output = proc.stdout.strip()
                if output:
                    try:
                        result = json.loads(output)
                    except json.JSONDecodeError:
                        result = {"raw_output": output, "returncode": proc.returncode}
                else:
                    result = {"error": proc.stderr.strip() or "No output"}
            except subprocess.TimeoutExpired:
                result = {"error": f"wait_response.py timed out", "session": session}
            except Exception as e:
                result = {"error": str(e)}

    elif name == "comms_send_to_session":
        # DEPRECATED — removed. Raw unattributed writes bypass sender identification.
        # Use comms_send_prompt for attributed messages, comms_send_slash_command for terminal control.
        result = {
            "error": "comms_send_to_session has been removed. Use comms_send_prompt (attributed) or comms_send_slash_command (slash commands)."
        }

    elif name == "comms_schedule_future_prompt":
        target = arguments["target"]
        message = arguments["message"]
        delay_seconds = arguments.get("delay_seconds")
        at_time_str = arguments.get("at_time")
        tag = arguments.get("tag")
        session = arguments.get("session")
        _audit_prompt_dispatch(target, session, message, False, f"comms:schedule:{tag or 'unnamed'}")

        if delay_seconds and at_time_str:
            result = {"error": "Provide either delay_seconds or at_time, not both"}
        elif not delay_seconds and not at_time_str:
            result = {"error": "Provide either delay_seconds or at_time"}
        else:
            tag_id = tag or f"mcp_{int(time.time())}"
            create_args = ["create", tag_id, "--target", target, "--message", message]
            if session:
                create_args.extend(["--session", session])
            if delay_seconds:
                create_args.extend(["--delay", str(delay_seconds)])
            else:
                create_args.extend(["--at", at_time_str])
            result = _run_schedule_script(create_args)

    elif name == "comms_list_scheduled_prompts":
        result = _run_schedule_script(["list"])

    elif name == "comms_cancel_scheduled_prompt":
        tag = arguments.get("tag")
        at_job_id = arguments.get("at_job_id")
        if not tag and not at_job_id:
            result = {"error": "Provide tag or at_job_id"}
        elif tag:
            result = _run_schedule_script(["cancel", tag])
        else:
            result = _run_schedule_script(["cancel", "--at-job", str(at_job_id)])

    elif name == "comms_read_history":
        uuid = arguments["uuid"]
        platform = arguments.get("platform")
        fmt = arguments.get("format", "json")
        last_n = arguments.get("last_n")

        if not READ_JSONL_SCRIPT.exists():
            result = {"error": f"read_jsonl.py not found at {READ_JSONL_SCRIPT}"}
        else:
            cmd_args = [sys.executable, str(READ_JSONL_SCRIPT), "read", uuid, "--format", fmt]
            if platform:
                cmd_args.extend(["--platform", platform])
            if last_n is not None:
                cmd_args.extend(["--range", f"-{last_n}"])
            try:
                proc = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=str(AI_ROOT)
                )
                if proc.returncode != 0:
                    result = {"error": proc.stderr.strip() or proc.stdout.strip() or "read_jsonl.py failed"}
                else:
                    output = proc.stdout.strip()
                    if fmt == "json":
                        try:
                            result = json.loads(output)
                        except json.JSONDecodeError:
                            result = {"raw_output": output}
                    else:
                        result = {"output": output}
            except subprocess.TimeoutExpired:
                result = {"error": "read_jsonl.py timed out after 30s"}
            except Exception as e:
                result = {"error": str(e)}

    elif name == "comms_send_slash_command":
        identifier = arguments["identifier"]
        command = arguments["command"]

        slash_script = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "send_slash_command.py"
        if not slash_script.exists():
            result = {"error": f"send_slash_command.py not found at {slash_script}"}
        else:
            try:
                from uai_toolkit.mcp.shared.subprocess_log import logged_run
                cmd = [sys.executable, str(slash_script), identifier, command]
                proc = logged_run(
                    "comms", cmd,
                    capture_output=True, text=True, timeout=20,
                    cwd=str(AI_ROOT),
                    env={**os.environ},
                )
                if proc.returncode == 0:
                    try:
                        result = json.loads(proc.stdout.strip())
                    except json.JSONDecodeError:
                        result = {"ok": True, "raw_output": proc.stdout.strip()}
                else:
                    try:
                        result = json.loads(proc.stdout.strip())
                    except (json.JSONDecodeError, ValueError):
                        result = {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "send_slash_command.py timed out"}
            except Exception as e:
                result = {"ok": False, "error": str(e)}

    elif name == "comms_reconnect_mcp_servers":
        identifier = arguments.get("identifier", "self")
        servers = arguments.get("servers") or []
        delay = arguments.get("delay", 1.0)
        dry_run = bool(arguments.get("dry_run", False))

        reconnect_script = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "reconnect_mcp_servers.py"
        if not reconnect_script.exists():
            result = {"error": f"reconnect_mcp_servers.py not found at {reconnect_script}"}
        else:
            try:
                from uai_toolkit.mcp.shared.subprocess_log import logged_run
                cmd = [sys.executable, str(reconnect_script), identifier, "--json", "--delay", str(delay)]
                if servers:
                    cmd.extend(["--servers", ",".join(servers)])
                if dry_run:
                    cmd.append("--dry-run")
                # Timeout must exceed (len(servers)-1) * delay; default 5 servers @1s -> ~4s of sleeps.
                proc = logged_run(
                    "comms", cmd,
                    capture_output=True, text=True, timeout=60,
                    cwd=str(AI_ROOT),
                    env={**os.environ},
                )
                try:
                    result = json.loads(proc.stdout.strip())
                except (json.JSONDecodeError, ValueError):
                    result = {"ok": proc.returncode == 0, "raw_output": proc.stdout.strip(),
                              "error": proc.stderr.strip() or None}
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "reconnect_mcp_servers.py timed out"}
            except Exception as e:
                result = {"ok": False, "error": str(e)}

    elif name == "comms_is_prompt_clear":
        from uai_toolkit.mcp.shared.subprocess_log import logged_run
        session = arguments.get("session", "")
        prompt_script = Path.home() / "bin" / "ai" / "prompting" / "get_prompt_area_texts.py"
        cmd = [sys.executable, str(prompt_script), "--include-empty", "--format", "json"]
        if session:
            if "://" in session:
                cmd.extend(["--uri", session])
            elif session.lower() == "self":
                tid = os.environ.get("AI_TRACKING_ID", "")
                if tid:
                    cmd.append(tid)
            else:
                cmd.append(session)
        else:
            cmd.append("--all-active")
        try:
            proc = logged_run("comms", cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                sessions_data = json.loads(proc.stdout)
                # Simplify to boolean per session
                result = [{
                    "session": s.get("session_name") or s.get("tracking_id"),
                    "tracking_id": s.get("tracking_id"),
                    "clear": s.get("prompt_state") == "prompt_area_clear",
                    "state": s.get("prompt_state"),
                } for s in sessions_data]
            else:
                result = {"error": proc.stderr.strip() or "get_prompt_area_texts.py failed"}
        except subprocess.TimeoutExpired:
            result = {"error": "get_prompt_area_texts.py timed out"}
        except Exception as e:
            result = {"error": str(e)}

    elif name == "comms_get_prompt_text":
        from uai_toolkit.mcp.shared.subprocess_log import logged_run
        session = arguments.get("session", "")
        include_empty = arguments.get("include_empty", False)
        prompt_script = Path.home() / "bin" / "ai" / "prompting" / "get_prompt_area_texts.py"
        cmd = [sys.executable, str(prompt_script), "--format", "json"]
        if include_empty:
            cmd.append("--include-empty")
        if session:
            if "://" in session:
                cmd.extend(["--uri", session])
            elif session.lower() == "self":
                tid = os.environ.get("AI_TRACKING_ID", "")
                if tid:
                    cmd.append(tid)
            else:
                cmd.append(session)
        else:
            cmd.append("--all-active")
        try:
            proc = logged_run("comms", cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                result = json.loads(proc.stdout)
            else:
                result = {"error": proc.stderr.strip() or "get_prompt_area_texts.py failed"}
        except subprocess.TimeoutExpired:
            result = {"error": "get_prompt_area_texts.py timed out"}
        except Exception as e:
            result = {"error": str(e)}

    elif name == "comms_load_context":
        session = arguments.get("session", "self")
        files = arguments.get("files") or []
        if isinstance(files, str):
            files = [files]
        copy = bool(arguments.get("copy", False))
        prefix = arguments.get("prefix")
        dry_run = bool(arguments.get("dry_run", False))

        load_script = AI_ROOT / "ai_general" / "scripts" / "cli" / "load_context.py"
        if not load_script.exists():
            result = {"ok": False, "error": f"load_context.py not found at {load_script}"}
        elif not files:
            result = {"ok": False, "error": "No files specified. Provide one or more file paths to stage."}
        else:
            try:
                from uai_toolkit.mcp.shared.subprocess_log import logged_run
                cmd = [sys.executable, str(load_script), "--session", session, *[str(f) for f in files]]
                if copy:
                    cmd.append("--copy")
                if prefix:
                    cmd.extend(["--prefix", str(prefix)])
                if dry_run:
                    cmd.append("--dry-run")
                proc = logged_run(
                    "comms", cmd,
                    capture_output=True, text=True, timeout=20,
                    cwd=str(AI_ROOT),
                    env={**os.environ},
                )
                # load_context.py emits JSON on stdout (success/partial) and on
                # stderr (hard failures). Prefer whichever parses.
                payload = proc.stdout.strip() or proc.stderr.strip()
                try:
                    result = json.loads(payload)
                except (json.JSONDecodeError, ValueError):
                    result = {"ok": proc.returncode == 0, "raw_output": payload}
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "load_context.py timed out"}
            except Exception as e:
                result = {"ok": False, "error": str(e)}

    elif name == "comms_rename_session":
        identifier = arguments["identifier"]
        new_name = arguments["name"]
        color = arguments.get("color")
        allow_repeat = arguments.get("allowRepeatNames", False)

        rename_script = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "rename_session.py"
        if not rename_script.exists():
            result = {"error": f"rename_session.py not found at {rename_script}"}
        else:
            try:
                cmd = [sys.executable, str(rename_script), identifier, new_name]
                if color:
                    cmd.extend(["--color", color])
                if allow_repeat:
                    cmd.append("--allow-repeat")
                proc = subprocess.run(
                    cmd,
                    capture_output=True, text=True, timeout=15,
                    cwd=str(AI_ROOT),
                )
                if proc.returncode == 0:
                    try:
                        result = json.loads(proc.stdout.strip())
                    except json.JSONDecodeError:
                        result = {"ok": True, "raw_output": proc.stdout.strip()}
                else:
                    try:
                        result = json.loads(proc.stdout.strip())
                    except (json.JSONDecodeError, ValueError):
                        result = {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "rename_session.py timed out"}
            except Exception as e:
                result = {"ok": False, "error": str(e)}

    elif name == "comms_condense_me":
        src_uuid = arguments["src_uuid"]
        include_private = arguments.get("include_private", False)
        condenser = arguments.get("condenser_session")
        handoff_name = arguments.get("name")
        handoff_desc = arguments.get("description")
        output_path = arguments.get("output_path")

        self_condense = arguments.get("self_condense", False)
        condense_script = AI_ROOT / "ai_general" / "scripts" / "jsonl" / "condense.py"
        prompt_file = AI_ROOT / "ai_general" / "prompts" / "chat_histories" / "operational_handoff.md"

        if not condense_script.exists():
            result = {"error": f"condense.py not found at {condense_script}"}
        elif self_condense:
            import tempfile
            from datetime import datetime
            tmp_dir = Path(tempfile.gettempdir()) / "condense_pipeline"
            tmp_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            prepared_path = str(tmp_dir / f"condense_input_{ts}.json")
            cmd_args = [sys.executable, str(condense_script), "--src-uuid", src_uuid, "--prepare-only"]
            cmd_args.extend(["--output", prepared_path])

            handoff_dir = AI_ROOT / "ai_general" / "data" / "handoffs"
            handoff_dir.mkdir(parents=True, exist_ok=True)
            h_name = handoff_name or src_uuid
            h_output = output_path or str(handoff_dir / f"{h_name}_{ts}.yml")

            try:
                proc = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(AI_ROOT)
                )
                if proc.returncode != 0:
                    result = {"error": proc.stderr.strip() or "condense.py --prepare-only failed"}
                else:
                    result = {
                        "ok": True,
                        "mode": "self_condense",
                        "prepared_input": prepared_path,
                        "prompt_file": str(prompt_file),
                        "output_path": h_output,
                        "include_private": include_private,
                        "instructions": "Read the prompt file, then read the prepared input, apply the prompt to produce the condensation, and write the result to output_path.",
                        "stderr": proc.stderr.strip() if proc.stderr.strip() else None,
                    }
            except subprocess.TimeoutExpired:
                result = {"error": "condense.py --prepare-only timed out after 120s"}
            except Exception as e:
                result = {"error": str(e)}
        else:
            cmd_args = [sys.executable, str(condense_script), "--src-uuid", src_uuid]

            if condenser:
                cmd_args.extend(["--condenser", condenser])
            else:
                config_path = AI_ROOT / "ai_general" / "data" / "unified_cli" / "config.json"
                default_condenser = None
                if config_path.exists():
                    try:
                        with open(config_path) as f:
                            config = json.load(f)
                        default_condenser = config.get("condenser", {}).get("tracking_id")
                    except (json.JSONDecodeError, KeyError):
                        pass
                if default_condenser:
                    cmd_args.extend(["--condenser", default_condenser])
                else:
                    result = {"error": "No condenser_session provided and no default configured in config.json"}
                    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            if handoff_name:
                cmd_args.extend(["--name", handoff_name])
            if handoff_desc:
                cmd_args.extend(["--description", handoff_desc])
            if output_path:
                cmd_args.extend(["--output", output_path])

            if include_private:
                pass

            try:
                proc = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=str(AI_ROOT)
                )
                if proc.returncode != 0:
                    result = {
                        "error": proc.stderr.strip() or "condense.py failed",
                        "include_private_requested": include_private,
                    }
                else:
                    handoff_path = proc.stdout.strip()
                    result = {
                        "ok": True,
                        "handoff_path": handoff_path,
                        "include_private": include_private,
                        "status": "Condensation request sent to condenser. Handoff will appear at the path above when complete.",
                        "stderr": proc.stderr.strip() if proc.stderr.strip() else None,
                    }
            except subprocess.TimeoutExpired:
                result = {"error": "condense.py timed out after 120s"}
            except Exception as e:
                result = {"error": str(e)}

    elif name in ("comms_block_session", "comms_unblock_session", "comms_list_blocks"):
        try:
            if str(_MESSAGES_DIR) not in sys.path:
                sys.path.insert(0, str(_MESSAGES_DIR))
            from uai_toolkit.messages import prompt_blocks as pb
            if name == "comms_list_blocks":
                blocks = pb.list_blocks()
                result = {"count": len(blocks), "blocks": blocks}
            else:
                tid = arguments["session"]
                if tid == "self":
                    tid = os.environ.get("AI_TRACKING_ID", "")
                if not tid:
                    result = {"ok": False, "error": "no session ('self' unresolved)"}
                elif name == "comms_unblock_session":
                    result = pb.unblock(tid)
                else:  # comms_block_session
                    turns = arguments.get("turns")
                    until = arguments.get("until")
                    mode = "turns" if turns else "until" if until else "indefinite"
                    rec = pb.block(tid, mode=mode, turns=turns,
                                   until=pb._parse_until(until) if until else None,
                                   reason=arguments.get("reason"))
                    result = {"ok": True, "blocked": rec, "indicator": pb.indicator(tid)}
        except Exception as e:
            result = {"ok": False, "error": str(e)}

    else:
        return None  # Not handled by this module

    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
