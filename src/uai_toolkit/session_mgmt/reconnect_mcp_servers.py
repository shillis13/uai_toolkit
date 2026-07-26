#!/usr/bin/env python3
"""
reconnect_mcp_servers.py — Send `/mcp reconnect <server>` to a CLI session for
each of our local custom MCP servers (the ones we build, under
ai_general/apps/mcps/), so a session picks up server code/tool changes without a
full restart.

Why this exists
---------------
Our Python MCP servers (workflow/comms/sessions) import their tool handlers
IN-PROCESS, so editing their code does not take effect in an already-running
session until that server is reconnected. `knowledge` is a partial exception —
its guidance tools subprocess to guidance_cli.py and so always run current code —
but its other tools are in-process like the rest. `/mcp reconnect <server>` is
Claude Code's non-interactive way to reconnect a single server; this script just
fans it out over our server list via send_slash_command.

Scope
-----
"Local custom" = any server in data/MCP.json whose `args_relative` path lives
under `ai_general/apps/mcps/`. Third-party servers (filesystem, github, fetch,
desktop-commander, etc.) are excluded — we don't own their code and reconnecting
them serves no purpose here.

CAVEAT (unverified): `/mcp reconnect` is documented as reconnecting a server;
whether it re-spawns a *healthy* stdio subprocess (and thus reloads changed
in-process code) is not documented. Verify with a live test before relying on it
for code reloads. It unambiguously helps for genuinely dropped/disconnected
servers.

Usage
-----
    reconnect_mcp_servers.py [identifier] [--servers a,b,c] [--delay SECONDS]
                             [--dry-run] [--json]

    reconnect_mcp_servers.py                 # reconnect all local servers in THIS session
    reconnect_mcp_servers.py Relay           # ... in session 'Relay'
    reconnect_mcp_servers.py self --servers knowledge,workflow
    reconnect_mcp_servers.py --dry-run       # show what would be sent, send nothing

Notes
-----
- Each `/mcp reconnect X` is a separate slash-command submission; we pause
  --delay seconds between them so the target's input box does not coalesce them.
- `comms` (if present) is reconnected LAST: when this runs as the comms MCP tool,
  reconnecting comms can briefly drop the very server handling the call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.session_mgmt.send_slash_command import send_slash_command  # noqa: E402

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402
MCP_CONFIG = AI_ROOT / "ai_general" / "data" / "MCP.json"

# Prefix that marks a server as one we author/own.
_LOCAL_PREFIX = "ai_general/apps/mcps/"


def local_custom_servers(config_path: Path = MCP_CONFIG) -> list[str]:
    """Return the names of MCP servers whose code lives under ai_general/apps/mcps/.

    Order: deterministic by MCP.json order, but with 'comms' moved to the end
    (see module docstring).
    """
    data = json.loads(config_path.read_text())
    servers = data.get("servers", {})
    names: list[str] = []
    for name, spec in servers.items():
        rels = spec.get("args_relative") or []
        if any(str(r).startswith(_LOCAL_PREFIX) for r in rels):
            names.append(name)
    # Reconnect comms last so we don't drop the server hosting this call mid-sweep.
    names.sort(key=lambda n: (n == "comms", n))
    return names


def reconnect_servers(
    identifier: str = "self",
    servers: list[str] | None = None,
    delay: float = 1.0,
    dry_run: bool = False,
) -> dict:
    """Send `/mcp reconnect <server>` to `identifier` for each server.

    Args:
        identifier: target session (tracking id, display name, terminal name,
            'self', or a prompt:// URI).
        servers: explicit server list; defaults to all local custom servers.
        delay: seconds to pause between submissions.
        dry_run: if True, do not send — just report the planned commands.

    Returns:
        Summary dict {ok, identifier, dry_run, results: [...]}.
    """
    targets = servers if servers is not None else local_custom_servers()
    summary: dict = {
        "ok": True,
        "identifier": identifier,
        "dry_run": dry_run,
        "servers": targets,
        "results": [],
    }
    for i, server in enumerate(targets):
        command = f"/mcp reconnect {server}"
        if dry_run:
            summary["results"].append({"server": server, "command": command, "sent": False, "dry_run": True})
            continue
        r = send_slash_command(identifier, command)
        summary["results"].append({
            "server": server,
            "command": command,
            "ok": r.get("ok", False),
            "sent": r.get("sent", False),
            "error": r.get("error"),
        })
        if not r.get("ok"):
            summary["ok"] = False
        # Pause between submissions so the input box doesn't coalesce them.
        if delay and i < len(targets) - 1:
            time.sleep(delay)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconnect our local custom MCP servers in a CLI session.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("identifier", nargs="?", default="self",
                        help="Target session (default: self)")
    parser.add_argument("--servers", default="",
                        help="Comma-separated server names (default: all local custom)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between submissions (default: 1.0)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be sent; send nothing")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    servers = [s.strip() for s in args.servers.split(",") if s.strip()] or None
    result = reconnect_servers(args.identifier, servers, args.delay, args.dry_run)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        verb = "Would reconnect" if args.dry_run else "Reconnecting"
        print(f"{verb} in '{result['identifier']}': {', '.join(result['servers'])}")
        for r in result["results"]:
            mark = "·" if args.dry_run else ("✓" if r.get("ok") else "✗")
            line = f"  {mark} {r['command']}"
            if r.get("error"):
                line += f"   ERROR: {r['error']}"
            print(line)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
