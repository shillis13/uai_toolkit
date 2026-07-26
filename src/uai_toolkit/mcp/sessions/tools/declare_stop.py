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
    "Call this at the end of your turn, before you stop. PREFERRED: fill in the "
    "`checklist` — a short yes/no turn self-review (did you address the prompt, "
    "was it logical, claims verified, work finished, more work now, waiting on "
    "anything, want a break/switch, a note to send PianoMan or Hamilton, etc.). "
    "It records your review to session state for the Stop gate + Live Board and "
    "returns a terse end/continue decision. (Legacy: `reasons`/`note` are still "
    "accepted during phase-in, but prefer the checklist.)"
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
                    "checklist": {
                        "type": "object",
                        "description": "PREFERRED. Your end-of-turn self-review. Answer every field explicitly (no defaults).",
                        "additionalProperties": False,
                        "properties": {
                            "addressed_prompt": {"type": "boolean", "description": "Did your response address what the prompt actually asked?"},
                            "logical": {"type": "boolean", "description": "Were your responses logical and internally consistent?"},
                            "claims_verified": {"type": "boolean", "description": "Are your factual claims verified / evidence-backed, not just asserted?"},
                            "did_what_i_said": {"type": "boolean", "description": "Did you do everything you said you'd do this turn (nothing said-but-skipped)?"},
                            "work_finished": {"type": "boolean", "description": "Is all work you touched finished and saved/committed (nothing half-done)?"},
                            "errors_handled": {"type": "boolean", "description": "Were any errors this turn resolved or flagged (none silently dropped)?"},
                            "asking_needless_question": {"type": "boolean", "description": "Are you asking the user something you could answer or move forward without?"},
                            "want_to_revisit": {"type": "boolean", "description": "Do you want a chance to re-think or revise your response before ending?"},
                            "more_work_now": {"type": "boolean", "description": "Is there more work you can start right now without new input?"},
                            "waiting_on": {"type": "string", "description": "If waiting on a person/response/dependency, what? Empty string if not waiting."},
                            "told_to_stop": {"type": "boolean", "description": "Were you told to stop at this point?"},
                            "want_break": {"type": "boolean", "description": "Do you want to pause / take a break?"},
                            "want_switch": {"type": "boolean", "description": "Would you rather switch to different work?"},
                            "start_next_now": {"type": "boolean", "description": "Should the next turn start immediately?"},
                            "schedule_next_min": {"type": "integer", "description": "Schedule the next turn in N minutes (0 = don't schedule)."},
                            "note_to_user": {"type": "string", "description": "A note to send PianoMan now, or empty string."},
                            "note_to_hamilton": {"type": "string", "description": "A note to send Hamilton now, or empty string."},
                        },
                        "required": [
                            "addressed_prompt", "logical", "claims_verified",
                            "did_what_i_said", "work_finished", "errors_handled",
                            "asking_needless_question", "want_to_revisit",
                            "more_work_now", "waiting_on", "told_to_stop",
                            "want_break", "want_switch", "start_next_now",
                            "schedule_next_min", "note_to_user", "note_to_hamilton",
                        ],
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
        "checklist": a.get("checklist"),   # None → script uses the legacy reason path
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
