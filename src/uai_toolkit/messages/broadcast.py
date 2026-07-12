#!/usr/bin/env python3
"""
broadcast.py — Deliver a prompt or message to all active sessions.

Two modes:
  prompt:  Calls send_prompt.py for each active session. Queues if can't deliver.
  message: Calls messaging.py send for each active session's inbox.

Enumerates active sessions via session_store.py or tmux/zellij.

Usage:
    broadcast.py prompt --from SENDER --content "text" [--callback-endpoint URI]
    broadcast.py message --from SENDER --content "text"

    # Targeted: only specific platform or group
    broadcast.py prompt --from SENDER --content "text" --platform claude_cli
    broadcast.py message --from SENDER --content "text" --sessions ID1,ID2

Options:
    --from          Sender identifier
    --content       Message/prompt text
    --platform      Filter: only sessions on this platform
    --sessions      Filter: comma-separated tracking IDs
    --callback-endpoint URI  Sender gets notified per delivery
    --dry-run       List sessions that would receive, don't send
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS  # noqa: E402

SESSION_MGMT_DIR = AI_ROOT / "ai_general" / "scripts" / "session_mgmt"
if str(SESSION_MGMT_DIR) not in sys.path:
    sys.path.insert(0, str(SESSION_MGMT_DIR))

from uai_toolkit.session_mgmt.lib_session_substrate import build_tmux_command, sanitize_tmux_server_name
try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity  # canonical "Name (tracking_id)"
except Exception:  # pragma: no cover - degrade to raw identity if unavailable
    def format_identity(identity, *, unknown="unknown"):  # type: ignore
        return identity if identity else unknown

SEND_PROMPT = AI_ROOT / "ai_general" / "scripts" / "prompting" / "send_prompt.py"
MESSAGING = AI_SCRIPTS / "messages" / "messaging.py"
SESSION_STORE = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"
SESSION_OPS = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_ops.py"


def get_active_sessions(platform: Optional[str] = None) -> List[Dict]:
    """Get active sessions by enumerating live terminal sessions, then enriching from the store.

    Ground truth for 'alive' is the terminal (tmux), not the session store's
    status field. We enumerate tmux sessions, cross-reference the store for
    metadata (platform, display_name, etc.), and filter from there.
    """
    store_rows: List[Dict] = []
    try:
        cmd = [sys.executable, str(SESSION_STORE), "list", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            store_rows = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        store_rows = []

    tmux_servers = {None}
    for row in store_rows:
        if (row.get("substrate") or "").lower() == "tmux":
            tmux_servers.add(sanitize_tmux_server_name(row.get("tmux_server")))

    live_sessions: List[Dict[str, str | None]] = []
    for tmux_server in tmux_servers:
        try:
            result = subprocess.run(
                build_tmux_command(
                    ["list-sessions", "-F", "#{session_name}"],
                    server_name=tmux_server,
                ),
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.strip().splitlines():
                name = line.strip()
                if name:
                    live_sessions.append({
                        "terminal_session": name,
                        "tmux_server": tmux_server,
                    })
        except (OSError, subprocess.TimeoutExpired):
            continue

    if not live_sessions:
        return []

    # Enrich from session store for metadata
    store_index: Dict[tuple[str | None, str], Dict] = {}
    for row in store_rows:
        terminal_session = row.get("terminal_session", "")
        if terminal_session:
            store_index[(sanitize_tmux_server_name(row.get("tmux_server")), terminal_session)] = row

    sessions = []
    for live in live_sessions:
        terminal_session = str(live.get("terminal_session") or "")
        tmux_server = sanitize_tmux_server_name(live.get("tmux_server"))
        store_data = store_index.get((tmux_server, terminal_session), {})
        session = {
            "tracking_id": store_data.get("tracking_id", terminal_session),
            "terminal_session": terminal_session,
            "platform": store_data.get("platform", ""),
            "display_name": store_data.get("display_name", ""),
            "tmux_server": tmux_server,
        }
        sessions.append(session)

    if platform:
        sessions = [s for s in sessions if s.get("platform", "") == platform]

    return sessions


def send_prompt_to(session_id: str, content: str, sender: str) -> Dict:
    """Send a prompt to a session via send_prompt.py."""
    # Prepend sender identification
    message = f"[Broadcast from {format_identity(sender)}]\n{content}"

    cmd = [
        str(SEND_PROMPT), "--target", "claude-cli",
        "--session", session_id, "--message", message,
        "--submit", "--force"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return {
            "session": session_id,
            "delivered": result.returncode == 0,
            "detail": result.stdout.strip() if result.returncode == 0 else result.stderr.strip()
        }
    except subprocess.TimeoutExpired:
        return {"session": session_id, "delivered": False, "detail": "timeout"}
    except OSError as e:
        return {"session": session_id, "delivered": False, "detail": str(e)}


def send_message_to(session_id: str, content: str, sender: str) -> Dict:
    """Send an async message to a session's inbox."""
    cmd = [
        sys.executable, str(MESSAGING), "send",
        "--from", sender, "--to", session_id, "--content", content,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {"session": session_id, "delivered": True, "message_id": data.get("message_id", "")}
        return {"session": session_id, "delivered": False, "detail": result.stderr.strip()}
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"session": session_id, "delivered": False, "detail": str(e)}


def notify_sender(callback_endpoint: str, delivery: Dict) -> None:
    """Notify sender of a delivery result via callback endpoint."""
    try:
        cb_path = AI_SCRIPTS / "callbacks"
        if str(cb_path) not in sys.path:
            sys.path.insert(0, str(cb_path))
        from uai_toolkit.callbacks.callback_lib import execute_uri
        msg = json.dumps(delivery)
        execute_uri(callback_endpoint, msg)
    except Exception:
        pass


def cmd_prompt(args) -> int:
    """Broadcast a prompt to active sessions."""
    if args.sessions:
        session_ids = [s.strip() for s in args.sessions.split(",")]
        sessions = [{"tracking_id": sid} for sid in session_ids]
    else:
        sessions = get_active_sessions(platform=args.platform)

    if not sessions:
        print(json.dumps({"success": False, "error": "No active sessions found"}))
        return 1

    if args.dry_run:
        ids = [s.get("tracking_id", s.get("terminal_session", "?")) for s in sessions]
        print(json.dumps({"dry_run": True, "session_count": len(ids), "sessions": ids}, indent=2))
        return 0

    results = []
    for i, session in enumerate(sessions):
        sid = session.get("tracking_id", session.get("terminal_session", ""))
        if not sid:
            continue
        # Throttle: 3s delay between sends to avoid short-duration rate limits
        if i > 0:
            import time
            time.sleep(3)
        delivery = send_prompt_to(sid, args.content, args.from_sender)
        results.append(delivery)
        if args.callback_endpoint:
            notify_sender(args.callback_endpoint, delivery)
        # Queue failed deliveries for later
        if not delivery["delivered"]:
            queue_cmd = [
                sys.executable, str(MESSAGING), "queue-prompt",
                "--to", sid, "--content", args.content,
                "--urgency", "prompt", "--delivery", "post-prompt",
                "--source", args.from_sender,
            ]
            try:
                subprocess.run(queue_cmd, capture_output=True, text=True, timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                pass

    delivered = sum(1 for r in results if r["delivered"])
    queued = sum(1 for r in results if not r["delivered"])
    print(json.dumps({
        "success": True,
        "mode": "prompt",
        "total": len(results),
        "delivered": delivered,
        "queued": queued,
        "results": results,
    }, indent=2))
    return 0


def cmd_message(args) -> int:
    """Broadcast a message to active sessions' inboxes."""
    if args.sessions:
        session_ids = [s.strip() for s in args.sessions.split(",")]
        sessions = [{"tracking_id": sid} for sid in session_ids]
    else:
        sessions = get_active_sessions(platform=args.platform)

    if not sessions:
        print(json.dumps({"success": False, "error": "No active sessions found"}))
        return 1

    if args.dry_run:
        ids = [s.get("tracking_id", s.get("terminal_session", "?")) for s in sessions]
        print(json.dumps({"dry_run": True, "session_count": len(ids), "sessions": ids}, indent=2))
        return 0

    results = []
    for i, session in enumerate(sessions):
        sid = session.get("tracking_id", session.get("terminal_session", ""))
        if not sid:
            continue
        # Throttle: 3s delay between sends to avoid short-duration rate limits
        if i > 0:
            import time
            time.sleep(3)
        delivery = send_message_to(sid, args.content, args.from_sender)
        results.append(delivery)
        if args.callback_endpoint:
            notify_sender(args.callback_endpoint, delivery)

    delivered = sum(1 for r in results if r["delivered"])
    print(json.dumps({
        "success": True,
        "mode": "message",
        "total": len(results),
        "delivered": delivered,
        "results": results,
    }, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Broadcast prompt or message to active sessions")
    sub = parser.add_subparsers(dest="command", required=True)

    # Common args
    for name, help_text, func in [
        ("prompt", "Broadcast a prompt (delivered via send_prompt, queued if busy)", cmd_prompt),
        ("message", "Broadcast a message (written to inbox, no prompt injection)", cmd_message),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--from", dest="from_sender", required=True, help="Sender identifier")
        p.add_argument("--content", required=True, help="Message/prompt text")
        p.add_argument("--platform", help="Filter: only this platform (claude_cli, codex_cli, etc)")
        p.add_argument("--sessions", help="Filter: comma-separated tracking IDs")
        p.add_argument("--callback-endpoint", help="URI: sender gets notified per delivery")
        p.add_argument("--dry-run", action="store_true", help="List targets, don't send")
        p.set_defaults(func=func)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
