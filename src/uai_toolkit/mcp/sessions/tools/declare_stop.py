"""MCP tool: declare_stop — a session declares WHY it is ending its turn (todo_0520).

Thin subprocess wrapper around scripts/session_mgmt/declare_stop.py (the logic
lives there — MCP-thin-wrapper principle). The session calls this before it
stops; the Stop handler (require_stop_declaration) validates the declaration.

Identity is ambient: the sessions MCP server is a per-session stdio child that
inherits AI_SESSION_DIR / AI_TRACKING_ID from its launching session, so the
subprocess writes THIS session's state. Verified for Claude sessions; Codex
identity handling (its server child may not carry the tracking id) is a known
follow-up tracked in todo_0520 — until resolved, the script fails loudly rather
than misattribute, which is the safe behavior.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
SCRIPT = AI_ROOT / "ai_general/scripts/session_mgmt/declare_stop.py"

_DESC = (
    "Declare WHY you are ending your turn, before you stop. Select one or more "
    "reason ids from the taxonomy (Stop/declare_stop.config.yml), plus optional "
    "per-reason params and a free-text note. This is the structured replacement "
    "for the heuristic stop-checkers: it records your intent to session state for "
    "the Stop gate, the Live Board, and downstream effects. For a reason not in "
    "the taxonomy, pass no reasons and use `note`. Common ids: awaiting_user "
    "(default), more_work, finished_todo, need_decision, context_pressure, "
    "waiting_on, blocked, no_more_work, wake_me, break, switch_work, discuss_soonest."
)


def tools():
    return [
        Tool(
            name="declare_stop",
            description=_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "reasons": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Taxonomy reason ids that apply. May be empty for a note-only custom stop.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Per-reason parameters, e.g. {\"todo_id\":\"todo_0520\"}, {\"after_min\":15}, {\"pct\":90}, {\"source\":\"Relay\"}.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Free-text note. Always allowed; REQUIRED if `reasons` is empty (a fully custom reason).",
                    },
                },
                "required": [],
            },
        )
    ]


async def call_tool(name, arguments):
    if name != "declare_stop":
        return None
    a = arguments or {}
    payload = json.dumps({
        "reasons": a.get("reasons") or [],
        "params": a.get("params") or {},
        "note": a.get("note") or "",
    })
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--stdin"],
            input=payload, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        res = {"ok": False, "error": "declare_stop timed out"}
    else:
        if p.returncode == 0:
            try:
                res = json.loads(p.stdout)
            except json.JSONDecodeError:
                res = {"ok": True, "output": p.stdout.strip()}
        else:
            res = {"ok": False, "error": (p.stderr or p.stdout or f"exit {p.returncode}").strip()}
    return [TextContent(type="text", text=json.dumps(res, indent=2))]
