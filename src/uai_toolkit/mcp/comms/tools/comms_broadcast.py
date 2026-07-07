"""
Comms tool module: broadcast suite (engine-backed).

Thin subprocess wrapper around scripts/messages/broadcast_mgr.py — the broadcast
engine. Business logic lives in the engine; these are thin faces that assemble
params (per the scripts-are-engine principle).

One operation — send X to a resolved recipient set — over four channels:
  comms_broadcast_context : stage a Context ref / note / file into each
                            recipient's context_to_load/ (fed on their next
                            prompt). Optional staggered nudge.
  comms_broadcast_message : write to each recipient's inbox. urgency=async is
                            silent (no nudge); prompt/interrupt add a staggered
                            nudge.
  comms_broadcast_prompt  : write text into each recipient's Prompt Area.
                            submit default false.
  comms_broadcast_slash   : send a slash command to each Prompt Area.

Recipients (the redesign): a spec resolved via the central uri_mappings
authority — a tracking id, a uai://<type>/<id> (open type; fan_out or session,
recursive), the literal 'all' (true broadcast), or a comma-list. Falls back to
legacy platform/sessions filters when no recipients given.

Shared: stagger_ms (gap between per-recipient pushes; default 500), on_occupied
('hold' = queue, delivered when the prompt clears; 'skip' = report busy; never
overwrites), dry_run (preview, mutates nothing).

Exports tools() and call_tool().
"""

import json
import os
from typing import Any

from mcp.types import Tool, TextContent

BROADCAST_MGR = os.path.expanduser("~/AI/ai_root/ai_general/scripts/messages/broadcast_mgr.py")

# Shared recipient/targeting/behaviour properties reused by every channel.
_COMMON_PROPS = {
    "recipients": {"type": "string",
                   "description": "Recipient spec: a tracking id, uai://<type>/<id> (open type; "
                                  "resolved recursively via uri_mappings), 'all' (true broadcast), "
                                  "or a comma-separated list. Preferred over platform/sessions."},
    "platform": {"type": "string", "description": "Legacy filter: only this platform (claude_cli, codex_cli, …)"},
    "sessions": {"type": "string", "description": "Legacy filter: comma-separated tracking ids / names"},
    "include_self": {"type": "boolean", "description": "Include the calling session (default false)"},
    "stagger_ms": {"type": "integer", "description": "Gap in ms between per-recipient pushes (default 500)"},
    "on_occupied": {"type": "string", "enum": ["hold", "skip"],
                    "description": "Prompt area already has text: 'hold' (queue, delivered when it clears) "
                                   "or 'skip' (report busy). Never overwrites. Default hold."},
    "dry_run": {"type": "boolean", "description": "Preview who would be targeted / what would happen; mutates nothing"},
}


def _run(args: list[str]) -> dict:
    """Run broadcast_mgr.py with the given argv; return parsed JSON (always --json)."""
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    cmd = ["python3", BROADCAST_MGR] + args + ["--json"]
    try:
        result = logged_run("comms", cmd, capture_output=True, text=True, timeout=120)
        out = (result.stdout or "").strip()
        if out:
            return json.loads(out)
        return {"ok": False, "error": f"broadcast_mgr exited {result.returncode}",
                "stderr": (result.stderr or "").strip()[:500]}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"bad JSON from uai_toolkit.messages.broadcast_mgr: {e}", "stdout": out[:500]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _common_args(a: dict) -> list[str]:
    """Translate shared arguments into broadcast_mgr flags."""
    out: list[str] = []
    if a.get("recipients"):
        out += ["--recipients", str(a["recipients"])]
    if a.get("platform"):
        out += ["--platform", str(a["platform"])]
    if a.get("sessions"):
        out += ["--sessions", str(a["sessions"])]
    if a.get("include_self"):
        out += ["--include-self"]
    if a.get("stagger_ms") is not None:
        out += ["--stagger-ms", str(int(a["stagger_ms"]))]
    if a.get("on_occupied"):
        out += ["--on-occupied", str(a["on_occupied"])]
    if a.get("dry_run"):
        out += ["--dry-run"]
    return out


def tools() -> list[Tool]:
    return [
        Tool(
            name="comms_broadcast_context",
            description="Stage a Context reference / note / file into each recipient's context_to_load/ "
                        "(loaded on their next prompt). Optionally send a staggered nudge so they process it now.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "A Context reference id (resolved via get_context)"},
                    "note": {"type": "string", "description": "Freeform note text to stage"},
                    "file": {"type": "string", "description": "Path to a file to stage"},
                    "nudge": {"type": "boolean", "description": "Also send a staggered nudge-prompt (default false)"},
                    **_COMMON_PROPS,
                },
            },
        ),
        Tool(
            name="comms_broadcast_message",
            description="Write a message to each recipient's inbox. urgency=async is silent (pull-only); "
                        "prompt/interrupt add a staggered nudge (= priority/nudge intensity).",
            inputSchema={
                "type": "object",
                "properties": {
                    "from_sender": {"type": "string", "description": "Sender identifier"},
                    "content": {"type": "string", "description": "Message text"},
                    "urgency": {"type": "string", "enum": ["async", "prompt", "interrupt"],
                                "description": "async=silent inbox; prompt=inbox+staggered nudge; interrupt=inbox+immediate. Default async."},
                    **_COMMON_PROPS,
                },
                "required": ["from_sender", "content"],
            },
        ),
        Tool(
            name="comms_broadcast_prompt",
            description="Write text into each recipient's Prompt Area. submit=false types it for review; "
                        "submit=true submits. Occupied prompts are held (or skipped) per on_occupied — never overwritten.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Prompt text"},
                    "submit": {"type": "boolean", "description": "Submit (press enter) vs type-only. Default false."},
                    **_COMMON_PROPS,
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="comms_broadcast_slash",
            description="Send a slash command to each recipient's Prompt Area (always submits). "
                        "Occupied prompts are held (or skipped) per on_occupied.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Slash command, e.g. '/color cyan'"},
                    **_COMMON_PROPS,
                },
                "required": ["command"],
            },
        ),
    ]


def call_tool(name: str, arguments: dict) -> list[TextContent]:
    a = arguments or {}
    if name == "comms_broadcast_context":
        args = ["context"]
        if a.get("ref"):
            args += ["--ref", str(a["ref"])]
        elif a.get("note"):
            args += ["--note", str(a["note"])]
        elif a.get("file"):
            args += ["--file", str(a["file"])]
        else:
            return [TextContent(type="text", text=json.dumps(
                {"ok": False, "error": "one of ref / note / file is required"}))]
        if a.get("nudge"):
            args += ["--nudge"]
        args += _common_args(a)
        result = _run(args)
    elif name == "comms_broadcast_message":
        args = ["message", str(a.get("content", "")),
                "--from", str(a.get("from_sender", "")),
                "--urgency", str(a.get("urgency", "async"))] + _common_args(a)
        result = _run(args)
    elif name == "comms_broadcast_prompt":
        args = ["prompt", str(a.get("text", ""))]
        if a.get("submit"):
            args += ["--submit"]
        args += _common_args(a)
        result = _run(args)
    elif name == "comms_broadcast_slash":
        args = ["slash", str(a.get("command", ""))] + _common_args(a)
        result = _run(args)
    else:
        result = {"ok": False, "error": f"unknown tool: {name}"}
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
