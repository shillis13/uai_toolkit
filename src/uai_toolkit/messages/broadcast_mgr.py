#!/usr/bin/env python3
"""
broadcast_mgr.py — engine for the broadcast-family commands.

One operation — "broadcast X to all active sessions" — over four channels that
share the same axes (target filter, stagger, occupied-policy, urgency). Business
logic lives HERE; the comms MCP tools are thin faces (reference_mcp_thin_wrapper).

Channels
  context : stage a Context ref / note / file into each session's context_to_load/
            (fed on the session's next prompt). Optional staggered nudge.
  message : write to each session's inbox. urgency=async => silent (no nudge);
            prompt/interrupt => inbox + staggered nudge.
  prompt  : write text into each session's Prompt Area (scaffolding-level terminal
            input; the in-app UAI Prompt Box is out of scope). submit default False.
  slash   : send a slash command to each session's Prompt Area (always submits).

Shared axes
  filter       : platform=, sessions=csv, exclude_self (default True)
  stagger_ms   : gap between per-session PUSHes (nudge/prompt/slash). Default 500.
  on_occupied  : prompt area already has text -> 'hold' (queue, delivered when it
                 clears) or 'skip' (report busy). Never overwrites. Default 'hold'.
  urgency      : async | prompt | interrupt  (message channel; = nudge intensity)

Every run returns/emits a delivered/held/skipped/failed report, sent on TWO paths:
  1. Notification (send_user_notification.py done)
  2. Message-to-user  (NEW path, built EOD 2026-07-01 — wired at _emit_report's
     MESSAGE_TO_USER hook; no-ops cleanly until it lands)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS  # noqa: E402

AI_GENERAL = AI_ROOT / "ai_general"
_SESSION_MGMT = AI_GENERAL / "scripts" / "session_mgmt"
for _d in (str(_SESSION_MGMT),):
    if _d not in sys.path:
        sys.path.insert(0, _d)

try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity  # canonical "Name (tracking_id)"
except Exception:  # pragma: no cover - degrade to raw identity if unavailable
    def format_identity(identity, *, unknown="unknown"):  # type: ignore
        return identity if identity else unknown

NOTIFY = AI_GENERAL / "scripts" / "notifications" / "send_user_notification.py"
MESSAGING = AI_SCRIPTS / "messages" / "messaging.py"
DEFAULT_STAGGER_MS = 500

# --- Message-to-user path (built EOD 2026-07-01). Set when the interface lands. ---
MESSAGE_TO_USER_CLI: Path | None = AI_GENERAL / "scripts" / "messages" / "message_user.py"


# ─────────────────────────── targets ───────────────────────────

def _self_tid() -> str:
    return os.environ.get("AI_TRACKING_ID", "")


def active_targets(platform: str | None = None, sessions: list[str] | None = None,
                   exclude_self: bool = True, recipients=None) -> list[dict]:
    """Live, active sessions with a terminal, as SessionStore rows.

    Targeting is EITHER by recipient spec (preferred: a tracking id, a
    group://<alias>, the literal 'all', or a list — resolved recursively through
    the group registry) OR by the legacy platform/sessions filters. A group is
    just a named recipient set; projects/teams are groups (recursive resolution).
    """
    from uai_toolkit.session_mgmt.session_store import SessionStore
    from uai_toolkit.session_mgmt import session_ops
    live = {s["name"] for s in session_ops.list_sessions() if s.get("running", True)}
    rows = SessionStore().list()
    me = _self_tid()

    # Recipient-spec path (the redesign): resolve via the central uri_mappings
    # authority. A spec is a tid, a uai://<type>/<id> (open type; fan_out or
    # session), 'all', or a list — resolved recursively, live-filtered.
    if recipients is not None:
        from uai_toolkit.messages import recipient_uris
        want = set(recipient_uris.resolve(recipients, live=True, exclude_self=exclude_self))
        return [r for r in rows if not r.get("archived")
                and r.get("terminal_session") in live and r.get("tracking_id") in want]

    allow = set(sessions or [])
    out = []
    for r in rows:
        if r.get("archived"):
            continue
        term = r.get("terminal_session")
        if not term or term not in live:
            continue
        if platform and r.get("platform") != platform:
            continue
        if exclude_self and me and r.get("tracking_id") == me:
            continue
        if allow and not (r.get("tracking_id") in allow or term in allow
                          or r.get("display_name") in allow):
            continue
        out.append(r)
    return out


# ─────────────────────────── prompt-area state ───────────────────────────

_PROMPT_TEXTS = AI_SCRIPTS / "prompting" / "get_prompt_area_texts.py"


def prompt_state(terminal: str) -> str:
    """'clear' | 'occupied' | 'responding' | 'unknown' for a terminal session.
    Uses get_prompt_area_texts.py — the same source comms_is_prompt_clear uses."""
    try:
        r = subprocess.run(["python3", str(_PROMPT_TEXTS), "--include-empty",
                            "--format", "json", terminal],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return "unknown"
        data = json.loads(r.stdout or "[]")
        row = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        ps = row.get("prompt_state") or ""
        if ps == "prompt_area_clear":
            return "clear"
        if ps == "prompt_area_occupied":
            return "occupied"
        if row.get("activity_state") == "responding" or ps == "responding":
            return "responding"
    except Exception:
        pass
    return "unknown"


# ─────────────────────────── delivery legs ───────────────────────────

def _write_to(terminal: str, text: str, submit: bool) -> bool:
    try:
        from uai_toolkit.session_mgmt import session_ops
        session_ops.write_to(terminal, text, press_enter=submit)
        return True
    except Exception:
        return False


def _queue_prompt(tid: str, text: str, urgency: str = "prompt") -> bool:
    """Queue for delivery when the session next transacts (the hold path)."""
    try:
        r = subprocess.run(
            ["python3", str(MESSAGING), "queue-prompt", "--to", tid,
             "--content", text, "--urgency", urgency],
            capture_output=True, text=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _deliver_push(row: dict, text: str, *, submit: bool, on_occupied: str,
                  urgency: str) -> str:
    """Deliver text to a session's Prompt Area now, or hold/skip if occupied.
    Returns one of: 'delivered' | 'held' | 'skipped' | 'failed'."""
    term = row.get("terminal_session")
    tid = row.get("tracking_id")
    state = prompt_state(term)
    if state in ("occupied", "responding"):
        if on_occupied == "skip":
            return "skipped"
        # hold: queue for delivery on clear (submitted prompts/slashes only)
        if submit:
            return "held" if _queue_prompt(tid, text, urgency) else "failed"
        # submit=False can't meaningfully hold un-submitted keystrokes -> skip
        return "skipped"
    # clear (or unknown): write now
    return "delivered" if _write_to(term, text, submit) else "failed"


# ─────────────────────────── context staging ───────────────────────────

def _stage_context(session_dir: str, *, ref: str | None, note: str | None,
                   file: str | None) -> bool:
    """Drop one entry into <session_dir>/context_to_load/ for hook delivery."""
    if not session_dir:
        return False
    inbox = Path(session_dir) / "context_to_load"
    inbox.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        if ref:
            (inbox / f"bcast_{ref}.ref").write_text(
                json.dumps({"type": "context", "name": ref, "path": None}))
        elif note is not None:
            (inbox / f"bcast_note_{stamp}.md").write_text(note)
        elif file:
            src = Path(file)
            if not src.exists():
                return False
            shutil.copy2(src, inbox / f"bcast_{src.name}")
        else:
            return False
        return True
    except Exception:
        return False


# ─────────────────────────── report + emit ───────────────────────────

def _emit_report(action: str, report: dict, dry_run: bool) -> None:
    if dry_run:
        return
    n = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    summary = f"{action}: " + ", ".join(f"{v} {k}" for k, v in n.items() if v)
    # Path 1: Notification
    try:
        subprocess.run(["python3", str(NOTIFY), "done", summary or f"{action}: no targets"],
                       capture_output=True, text=True, timeout=15)
    except Exception:
        pass
    # Path 2: Message-to-user — persist a reviewable message (silent; Path 1 is the
    # popup). The user reviews it in their own channel (uai://user/<id>).
    if MESSAGE_TO_USER_CLI and MESSAGE_TO_USER_CLI.exists():
        try:
            subprocess.run(["python3", str(MESSAGE_TO_USER_CLI),
                            "--subject", summary or f"{action}: no targets",
                            "--content", json.dumps(report, indent=2),
                            "--silent"],
                           capture_output=True, text=True, timeout=15)
        except Exception:
            pass


# ─────────────────────────── channels ───────────────────────────

def _stagger(i: int, stagger_ms: int) -> None:
    if i > 0 and stagger_ms > 0:
        time.sleep(stagger_ms / 1000.0)


def broadcast_context(*, ref=None, note=None, file=None, nudge=False,
                      stagger_ms=DEFAULT_STAGGER_MS, on_occupied="hold",
                      platform=None, sessions=None, exclude_self=True,
                      recipients=None, dry_run=False) -> dict:
    targets = active_targets(platform, sessions, exclude_self, recipients=recipients)
    rep = {"staged": [], "nudged": [], "held": [], "skipped": [], "failed": []}
    NUDGE_TXT = "📥 New context was staged for you — it loads on this turn."
    push_i = 0
    for t in targets:
        label = t.get("display_name") or t.get("terminal_session")
        if dry_run:
            rep["staged"].append(label)
            if nudge:
                rep["nudged"].append(label)
            continue
        ok = _stage_context(t.get("session_dir"), ref=ref, note=note, file=file)
        if not ok:
            rep["failed"].append(label); continue
        rep["staged"].append(label)
        if nudge:
            _stagger(push_i, stagger_ms); push_i += 1
            res = _deliver_push(t, NUDGE_TXT, submit=True, on_occupied=on_occupied,
                                urgency="prompt")
            {"delivered": rep["nudged"], "held": rep["held"],
             "skipped": rep["skipped"], "failed": rep["failed"]}[res].append(label)
    _emit_report("broadcast_context", rep, dry_run)
    return rep


def broadcast_prompt(*, text, submit=False, stagger_ms=DEFAULT_STAGGER_MS,
                     on_occupied="hold", platform=None, sessions=None,
                     exclude_self=True, recipients=None, dry_run=False) -> dict:
    targets = active_targets(platform, sessions, exclude_self, recipients=recipients)
    rep = {"delivered": [], "held": [], "skipped": [], "failed": []}
    for i, t in enumerate(targets):
        label = t.get("display_name") or t.get("terminal_session")
        if dry_run:
            rep["delivered"].append(label); continue
        _stagger(i, stagger_ms)
        res = _deliver_push(t, text, submit=submit, on_occupied=on_occupied, urgency="prompt")
        rep[res].append(label)
    _emit_report("broadcast_prompt", rep, dry_run)
    return rep


def broadcast_slash(*, command, stagger_ms=DEFAULT_STAGGER_MS, on_occupied="hold",
                    platform=None, sessions=None, exclude_self=True, recipients=None, dry_run=False) -> dict:
    if not command.startswith("/"):
        command = "/" + command
    targets = active_targets(platform, sessions, exclude_self, recipients=recipients)
    rep = {"delivered": [], "held": [], "skipped": [], "failed": []}
    for i, t in enumerate(targets):
        label = t.get("display_name") or t.get("terminal_session")
        if dry_run:
            rep["delivered"].append(label); continue
        _stagger(i, stagger_ms)
        res = _deliver_push(t, command, submit=True, on_occupied=on_occupied, urgency="interrupt")
        rep[res].append(label)
    _emit_report("broadcast_slash", rep, dry_run)
    return rep


def broadcast_message(*, from_sender, content, urgency="async",
                      stagger_ms=DEFAULT_STAGGER_MS, on_occupied="hold",
                      platform=None, sessions=None, exclude_self=True, recipients=None, dry_run=False) -> dict:
    targets = active_targets(platform, sessions, exclude_self, recipients=recipients)
    rep = {"messaged": [], "nudged": [], "held": [], "skipped": [], "failed": []}
    nudge = urgency in ("prompt", "interrupt")
    NUDGE_TXT = f"📨 New message from {format_identity(from_sender)} — check your inbox."
    push_i = 0
    for t in targets:
        label = t.get("display_name") or t.get("terminal_session")
        tid = t.get("tracking_id")
        if dry_run:
            rep["messaged"].append(label)
            if nudge:
                rep["nudged"].append(label)
            continue
        try:
            r = subprocess.run(["python3", str(MESSAGING), "send", "--to", tid,
                                "--from", from_sender, "--content", content,
                                "--urgency", "async"],
                               capture_output=True, text=True, timeout=20)
            ok = r.returncode == 0
        except Exception:
            ok = False
        if not ok:
            rep["failed"].append(label); continue
        rep["messaged"].append(label)
        if nudge:
            _stagger(push_i, stagger_ms); push_i += 1
            # Route the nudge through the shared notification layer (block-safe,
            # always-stage-ref, policy-aware) instead of the prompt-area side
            # channel — so broadcast obeys the same batching/throttle as every
            # other send. Bulk fan-out uses the batched policy: <=1 nudge/window.
            try:
                from uai_toolkit.messages import notify_lib
                r2 = notify_lib.notify_recipient(tid, from_sender, NUDGE_TXT,
                                                 policy="batched", urgency=urgency,
                                                 sender=from_sender)
                mode = r2.get("mode")
            except Exception:
                mode = "failed"
            bucket = {"nudge_sent": "nudged", "inbox_ref_staged": "nudged",
                      "batched_suppressed": "held", "blocked": "skipped",
                      "silent": "held", "nudge_failed_ref_staged": "failed"}.get(mode, "failed")
            rep[bucket].append(label)
    _emit_report("broadcast_message", rep, dry_run)
    return rep


# ─────────────────────────── CLI ───────────────────────────

def _common(p):
    p.add_argument("--platform")
    p.add_argument("--sessions", help="comma-separated tracking ids / names")
    p.add_argument("--recipients", help="recipient spec: tid / group://alias / all / comma-list")
    p.add_argument("--include-self", action="store_true")
    p.add_argument("--stagger-ms", type=int, default=DEFAULT_STAGGER_MS)
    p.add_argument("--on-occupied", choices=["hold", "skip"], default="hold")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")


def main() -> int:
    ap = argparse.ArgumentParser(description="Broadcast to all active sessions.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("context", help="stage a ref/note/file into each context_to_load/")
    g = pc.add_mutually_exclusive_group(required=True)
    g.add_argument("--ref"); g.add_argument("--note"); g.add_argument("--file")
    pc.add_argument("--nudge", action="store_true")
    _common(pc)

    pp = sub.add_parser("prompt", help="write text into each Prompt Area")
    pp.add_argument("text"); pp.add_argument("--submit", action="store_true")
    _common(pp)

    ps = sub.add_parser("slash", help="send a slash command to each Prompt Area")
    ps.add_argument("command", nargs="+", help="slash command (may include args)")
    _common(ps)

    pm = sub.add_parser("message", help="write to each inbox (urgency = nudge intensity)")
    pm.add_argument("content"); pm.add_argument("--from", dest="from_sender", required=True)
    pm.add_argument("--urgency", choices=["async", "prompt", "interrupt"], default="async")
    _common(pm)

    a = ap.parse_args()
    sess = [s.strip() for s in a.sessions.split(",")] if getattr(a, "sessions", None) else None
    recips = ([r.strip() for r in a.recipients.split(',')] if getattr(a,'recipients',None) else None)
    recips = recips[0] if recips and len(recips)==1 else recips
    common = dict(stagger_ms=a.stagger_ms, on_occupied=a.on_occupied, platform=a.platform,
                  sessions=sess, exclude_self=not a.include_self, recipients=recips, dry_run=a.dry_run)
    if a.cmd == "context":
        rep = broadcast_context(ref=a.ref, note=a.note, file=a.file, nudge=a.nudge, **common)
    elif a.cmd == "prompt":
        rep = broadcast_prompt(text=a.text, submit=a.submit, **common)
    elif a.cmd == "slash":
        rep = broadcast_slash(command=" ".join(a.command), **common)
    elif a.cmd == "message":
        rep = broadcast_message(from_sender=a.from_sender, content=a.content, urgency=a.urgency, **common)
    else:
        return 2
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        for k, v in rep.items():
            if v:
                print(f"{k}: {len(v)}  ({', '.join(v)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
