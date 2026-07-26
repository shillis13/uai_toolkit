#!/usr/bin/env python3
"""deliver_stalled_prompts.py — the detect-and-deliver watcher for stalled prompts
(todo_0602). Closes the gap where a session sits IDLE with an owed prompt that
never gets delivered because the delivery hooks only fire when a session ACTS.

TWO STALL MODES, two jobs:

  JOB A — queued-while-idle. A prompt queued to a session's inbox is delivered by
    the Stop hook (after the session responds) or the UserPromptSubmit hook (when
    the user submits). A session that goes idle BEFORE the prompt is queued fires
    neither, so the queue entry sits. This job delivers ready queue entries to
    idle sessions via send_prompt.py (--submit), then marks them delivered. Safe
    and always on: it only acts when there is a genuinely-owed queue entry.

  JOB B — long-stuck input-box draft. SURFACE-ONLY, never submit. An unsent draft in
    a session's input box is usually the USER's deliberate hold (PianoMan stops to
    check or change approach, and watches the unsent-draft indicators in Recent
    Sessions). Auto-submitting would override that intent, so this job only NOTES an
    idle session whose input box has held the SAME non-empty draft past a long
    threshold — it NEVER presses Enter. (Confirmed by PianoMan, todo_0602.)

Job A types into a terminal, so a busy/responding session is skipped and retried
next run (idle-only). Job B never writes at all. Modeled on
broadcast_mcp_reconnect.py; all session reads go through session_ops / get_prompt_area_texts
and session_store per this dir's DESIGN.md.

USAGE
    deliver_stalled_prompts.py            # run one sweep
    deliver_stalled_prompts.py --dry-run  # report only; type/submit nothing
    deliver_stalled_prompts.py --json     # machine-readable summary
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT, AI_DATA  # noqa: E402

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from uai_toolkit.session_mgmt.session_store import SessionStore  # noqa: E402
from uai_toolkit.session_mgmt.session_ops import _read_activity_state  # noqa: E402

# Reuse the exact queue mechanics the delivery hooks use — one drain path.
sys.path.insert(0, str(AI_ROOT / "ai_general" / "data" / "hooks" / "common"))
from uai_toolkit.hooks.common.lib_hook_scripts import (  # noqa: E402
    PROMPTS_INBOX, SEND_PROMPT, load_queue_entries, filter_ready,
    drop_blocked_sources, compose_context, mark_all_delivered, is_locked,
)

_STATE_FILE = AI_DATA / "prompt_delivery" / "watcher_state.json"
# A draft must persist this long before Job B SURFACES it. Deliberately long: an
# unsent draft is usually the user's intentional hold (they stop to check or change
# approach and watch the unsent-draft indicators in Recent Sessions), so we only
# note the truly long-forgotten ones — and NEVER submit them (PianoMan, todo_0602).
_DRAFT_STALE_SECONDS = 900

# send_prompt.py target per platform; platforms absent here get no CLI delivery.
_TARGET = {
    "claude_cli": "claude-cli", "codex_cli": "codex-cli", "gemini_cli": "gemini-cli",
    "grok_cli": "grok-cli", "antigravity_cli": "antigravity-cli",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(_STATE_FILE.parent),
        prefix=".%s." % _STATE_FILE.name,
        suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(_STATE_FILE))
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _deliver_queue(tid: str, session_name: str, target: str, dry_run: bool) -> dict | None:
    """JOB A: deliver ready queue entries for a session. None if nothing to do."""
    entries = load_queue_entries(PROMPTS_INBOX / tid)
    if not entries:
        return None
    ready = drop_blocked_sources(tid, filter_ready(entries))
    if not ready:
        return None
    prompt, included, overflow = compose_context(ready)
    if not included:
        return None
    if dry_run:
        return {"tracking_id": tid, "delivered": 0, "would_deliver": len(included), "overflow": len(overflow)}
    ok = False
    if SEND_PROMPT.exists():
        try:
            r = subprocess.run(
                [sys.executable, str(SEND_PROMPT), "--target", target,
                 "--session", session_name, "--message", prompt, "--submit", "--force"],
                capture_output=True, text=True, timeout=90,
            )
            ok = r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            ok = False
    if ok:
        mark_all_delivered(included)
        return {"tracking_id": tid, "delivered": len(included), "overflow": len(overflow)}
    return {"tracking_id": tid, "delivered": 0, "error": "send_prompt failed", "overflow": len(overflow)}


def _read_drafts(tids: list) -> dict:
    """Map tracking_id → current non-empty input-box draft text (occupied only)."""
    if not tids:
        return {}
    script = AI_ROOT / "ai_general" / "scripts" / "prompting" / "get_prompt_area_texts.py"
    try:
        r = subprocess.run(
            [sys.executable, str(script), *tids, "--format", "flat"],
            capture_output=True, text=True, timeout=45,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    drafts = {}
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        tid = obj.get("tracking_id") or obj.get("session")
        text = (obj.get("prompt_text") or obj.get("text") or "").strip()
        if tid and text:
            drafts[tid] = text
    return drafts


def sweep(dry_run: bool = False) -> dict:
    state = _load_json(_STATE_FILE, {})               # {tid: {"draft_hash", "since"}}
    if not isinstance(state, dict):
        state = {}
    sessions = SessionStore().list(status="active")

    idle = []
    for s in sessions:
        tid = s.get("tracking_id")
        if not tid or s.get("platform") not in _TARGET:
            continue
        if is_locked(tid):
            continue
        if _read_activity_state(s.get("session_dir")) != "idle":
            continue
        idle.append(s)

    delivered_queue = []
    for s in idle:
        tid = s.get("tracking_id")
        name = s.get("terminal_session") or tid
        res = _deliver_queue(tid, name, _TARGET[s["platform"]], dry_run)
        if res:
            delivered_queue.append(res)

    # JOB B — long-stuck draft detection over the idle sessions. SURFACE-ONLY:
    # we track how long the SAME draft has sat and note the long-forgotten ones.
    # We NEVER press Enter — an unsent draft is the user's deliberate hold.
    idle_tids = [s["tracking_id"] for s in idle]
    drafts = _read_drafts(idle_tids)
    new_state = {}
    observed_stuck = []
    now = _now()
    for tid, text in drafts.items():
        h = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]
        prev = state.get(tid) if isinstance(state.get(tid), dict) else None
        since = prev["since"] if prev and prev.get("draft_hash") == h else now.isoformat()
        try:
            since_dt = datetime.fromisoformat(since)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            age = max(0, (now - since_dt).total_seconds())
        except (TypeError, ValueError):
            # Corrupt/old watcher state must not abort queue delivery. Reset this
            # draft's observation window and heal the state on the next save.
            since = now.isoformat()
            age = 0
        new_state[tid] = {"draft_hash": h, "since": since}
        if age >= _DRAFT_STALE_SECONDS:
            observed_stuck.append({"tracking_id": tid, "age_s": int(age), "preview": text[:80]})

    if not dry_run:
        live = {s.get("tracking_id") for s in sessions}
        _save_state({k: v for k, v in new_state.items() if k in live})

    return {
        "ok": True, "dry_run": dry_run,
        "idle_sessions": len(idle),
        "queue_delivered": delivered_queue,
        "drafts_stuck_observed": observed_stuck,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect + deliver stalled prompts to idle sessions (todo_0602).")
    ap.add_argument("--dry-run", action="store_true", help="Report only; type/submit nothing.")
    ap.add_argument("--json", action="store_true", help="Machine-readable summary.")
    args = ap.parse_args()

    r = sweep(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(r, indent=2))
        return 0
    tag = "[dry-run] " if r["dry_run"] else ""
    dq = sum(x.get("delivered", 0) for x in r["queue_delivered"])
    print(f"{tag}idle {r['idle_sessions']} | queue-delivered {dq} across {len(r['queue_delivered'])} sessions | "
          f"long-stuck drafts surfaced {len(r['drafts_stuck_observed'])} (never submitted)")
    for x in r["queue_delivered"]:
        print(f"  queue -> {x['tracking_id']}: delivered={x.get('delivered', x.get('would_deliver', 0))}"
              + (f" ERROR {x['error']}" if x.get("error") else ""))
    for x in r["drafts_stuck_observed"]:
        print(f"  draft long-held -> {x['tracking_id']} ({x['age_s']}s): {x['preview']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
