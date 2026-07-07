"""
Comms tool module: recipient-set management (engine-backed).

Thin faces over scripts/messages/recipient_uris.py — register / list / unregister
named recipient sets in the central uri_mappings authority. This is the
scaffolding the session-picker calls: select sessions -> save as
uai://<type>/<id>. Sets can be temporary (ttl_hours / expires_at) and are
auto-swept once past (see sweep_expired).

Exports tools() and call_tool().
"""

import json
import os
from typing import Any

from mcp.types import Tool, TextContent

RECIPIENT_URIS = os.path.expanduser("~/AI/ai_root/ai_general/scripts/messages/recipient_uris.py")


def _run(args: list[str]) -> dict:
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    try:
        r = logged_run("comms", ["python3", RECIPIENT_URIS] + args,
                       capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
        if out:
            return json.loads(out)
        return {"ok": False, "error": f"recipient_uris exited {r.returncode}",
                "stderr": (r.stderr or "").strip()[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def tools() -> list[Tool]:
    return [
        Tool(
            name="comms_register_recipients",
            description="Save a selection of recipients as a named set at uai://<type>/<id> (open type — "
                        "e.g. uai://myfavs/relay-crew). Members are tracking ids and/or other uai:// URIs "
                        "(recursively flattened). Optionally temporary via ttl_hours or expires_at (auto-swept). "
                        "Broadcast tools then target it via recipients=uai://<type>/<id>.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uri": {"type": "string", "description": "uai://<type>/<id> to register, e.g. uai://myfavs/relay-crew"},
                    "members": {"type": "array", "items": {"type": "string"},
                                "description": "Tracking ids and/or uai:// URIs to include"},
                    "ttl_hours": {"type": "number", "description": "Expire this many hours from now (temporary set)"},
                    "expires_at": {"type": "string", "description": "ISO local expiry time (alternative to ttl_hours)"},
                },
                "required": ["uri", "members"],
            },
        ),
        Tool(
            name="comms_list_recipient_sets",
            description="List registered recipient sets (uri, members, expires_at) from the central uri_mappings.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="comms_unregister_recipients",
            description="Delete a registered recipient set by its uai://<type>/<id> uri.",
            inputSchema={
                "type": "object",
                "properties": {"uri": {"type": "string", "description": "uai://<type>/<id> to remove"}},
                "required": ["uri"],
            },
        ),
    ]


def call_tool(name: str, arguments: dict) -> list[TextContent]:
    a = arguments or {}
    if name == "comms_register_recipients":
        args = ["register", str(a.get("uri", ""))] + [str(m) for m in a.get("members", [])]
        if a.get("ttl_hours") is not None:
            args += ["--ttl-hours", str(a["ttl_hours"])]
        if a.get("expires_at"):
            args += ["--expires-at", str(a["expires_at"])]
        result = _run(args)
    elif name == "comms_list_recipient_sets":
        result = _run(["list"])
        if isinstance(result, list):
            result = {"sets": result}
    elif name == "comms_unregister_recipients":
        result = _run(["unregister", str(a.get("uri", ""))])
    else:
        result = {"ok": False, "error": f"unknown tool: {name}"}
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
