#!/usr/bin/env python3
"""broadcast_mcp_reconnect.py — reconnect our in-process MCP servers across sessions
when the MCP server code changes, safely and platform-aware.

WHY
---
Our Python MCP servers (comms/sessions/workflow) import their tool handlers IN-PROCESS,
so editing that code does NOT take effect in an already-running session until it runs
`/mcp reconnect`. A session that started before an MCP code change keeps executing the
OLD code — the "stale server" class (e.g. comms_send_prompt breaking after the
send_prompt.sh→.py port, because a running comms server still called the deleted .sh).

WHAT
----
Run periodically (scheduled). For each live session, if our MCP code has changed since
that session was last reconnected, reconnect its servers — but ONLY while the session is
IDLE. A reconnect is typed into the session's terminal; doing it mid-response would
interrupt the session's work, so busy sessions are skipped and retried on a later run.
No-ops entirely when the MCP code hasn't changed since a session was last reconnected.

PLATFORMS
---------
`/mcp reconnect` is Claude Code's non-interactive reconnect, so v1 reconnects `claude_cli`
sessions. Codex / Gemini / grok are reported and skipped — they need their own reconnect
(or full-restart) path, which is a follow-up.

USAGE
-----
    broadcast_mcp_reconnect.py            # reconnect idle claude sessions behind the latest MCP commit
    broadcast_mcp_reconnect.py --dry-run  # report what WOULD be reconnected; send nothing
    broadcast_mcp_reconnect.py --force    # ignore per-session markers; reconnect every eligible idle session
    broadcast_mcp_reconnect.py --json     # machine-readable summary

The trigger is change-based: it compares the latest commit touching ai_general/apps/mcps/
to a per-session marker, so a session is reconnected once per MCP code change (and busy
sessions are retried until they're idle). Intended to run on a short schedule.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Shared resolver (honor $AI_SCRIPTS override, else derive to ai_general/scripts).
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT, AI_DATA  # noqa: E402

# Sibling session_mgmt modules.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from uai_toolkit.session_mgmt.reconnect_mcp_servers import reconnect_servers  # noqa: E402
from uai_toolkit.session_mgmt.session_ops import _read_activity_state  # noqa: E402
from uai_toolkit.session_mgmt.session_store import SessionStore  # noqa: E402

_REPO = AI_ROOT / "ai_general"
_MCP_PATHSPEC = "apps/mcps"                       # git pathspec (relative to the ai_general repo)
_STATE_FILE = AI_DATA / "mcp_reconnect" / "reconnect_state.json"
# `/mcp reconnect` is Claude Code's mechanism; extend as other platforms gain a
# non-interactive reconnect path.
_RECONNECTABLE_PLATFORMS = {"claude_cli"}


def latest_mcp_commit() -> str | None:
    """The most recent commit touching ai_general/apps/mcps/ (our MCP server code)."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_REPO), "log", "-1", "--format=%H", "--", _MCP_PATHSPEC],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        return out or None
    except Exception:
        return None


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(exist_ok=True)       # AI_DATA exists; create only the leaf dir
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(_STATE_FILE)


def broadcast(dry_run: bool = False, force: bool = False, max_per_run: int = 0) -> dict:
    """Reconnect eligible sessions behind the latest MCP commit. Returns a summary.

    max_per_run > 0 caps how many sessions are reconnected in ONE call so a large
    backlog (e.g. the initial catch-up) drains over several scheduled runs instead of a
    simultaneous burst of MCP-server restarts. Deferred sessions are retried next run.
    """
    latest = latest_mcp_commit()
    if not latest:
        return {"ok": False, "error": "could not determine the latest MCP commit"}

    state = _load_state()                         # {tracking_id: last_reconnected_commit}
    # "active" = the store's derived-live status (from tmux/zellij + fs); "running" is
    # NOT a derived value here. Only live sessions can take a reconnect.
    sessions = SessionStore().list(status="active")

    reconnected: list[str] = []
    skipped_busy: list[dict] = []
    skipped_platform: list[dict] = []
    up_to_date: list[str] = []
    deferred: list[str] = []
    errors: list[dict] = []

    for s in sessions:
        tid = s.get("tracking_id")
        if not tid:
            continue
        plat = s.get("platform")
        if plat not in _RECONNECTABLE_PLATFORMS:
            skipped_platform.append({"tracking_id": tid, "platform": plat})
            continue
        if not force and state.get(tid) == latest:
            up_to_date.append(tid)                # already reconnected at this MCP commit
            continue
        # Only reconnect an IDLE session — a reconnect is typed into its terminal, so
        # doing it mid-response would interrupt the session. Busy/unknown → retry later.
        if _read_activity_state(s.get("session_dir")) != "idle":
            skipped_busy.append({"tracking_id": tid,
                                 "activity": _read_activity_state(s.get("session_dir"))})
            continue
        # Eligible (claude + idle + behind latest). Honor the per-run cap.
        if max_per_run and len(reconnected) >= max_per_run:
            deferred.append(tid)                  # over the cap this run; retried next run
            continue
        res = reconnect_servers(tid, dry_run=dry_run)
        if res.get("ok"):
            reconnected.append(tid)
            if not dry_run:
                state[tid] = latest
        else:
            errors.append({"tracking_id": tid, "error": res.get("error")})

    if not dry_run:
        live = {s.get("tracking_id") for s in sessions}
        state = {k: v for k, v in state.items() if k in live}   # prune dead sessions
        _save_state(state)

    return {
        "ok": True, "mcp_commit": latest, "dry_run": dry_run,
        "reconnected": reconnected, "skipped_busy": skipped_busy,
        "skipped_platform": skipped_platform, "up_to_date": up_to_date,
        "deferred": deferred, "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reconnect our MCP servers across IDLE sessions when the MCP code changes.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be reconnected; send nothing.")
    ap.add_argument("--force", action="store_true",
                    help="Ignore per-session markers; reconnect every eligible idle session.")
    ap.add_argument("--max", type=int, default=6, metavar="N",
                    help="Reconnect at most N sessions per run (0 = unlimited); the rest are "
                         "deferred to the next run so a backlog drains gradually. Default 6.")
    ap.add_argument("--json", action="store_true", help="Machine-readable summary.")
    args = ap.parse_args()

    r = broadcast(dry_run=args.dry_run, force=args.force, max_per_run=args.max)
    if args.json:
        print(json.dumps(r, indent=2))
        return 0 if r.get("ok") else 1
    if not r.get("ok"):
        print("error:", r.get("error"))
        return 1
    tag = "[dry-run] " if r["dry_run"] else ""
    print(f"{tag}MCP commit {r['mcp_commit'][:10]} — "
          f"reconnected {len(r['reconnected'])}, deferred {len(r['deferred'])}, "
          f"skipped-busy {len(r['skipped_busy'])}, skipped-platform {len(r['skipped_platform'])}, "
          f"up-to-date {len(r['up_to_date'])}, errors {len(r['errors'])}")
    for tid in r["reconnected"]:
        print(f"  reconnected: {tid}")
    for tid in r["deferred"]:
        print(f"  deferred (over --max this run): {tid}")
    for x in r["skipped_busy"]:
        print(f"  skipped (busy={x['activity']}): {x['tracking_id']}")
    for x in r["skipped_platform"]:
        print(f"  skipped (platform={x['platform']}): {x['tracking_id']}")
    for x in r["errors"]:
        print(f"  ERROR {x['tracking_id']}: {x['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
