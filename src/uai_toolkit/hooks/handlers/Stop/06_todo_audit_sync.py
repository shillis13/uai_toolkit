#!/usr/bin/env python3
"""Stop hook — todo enforcement (todo_0333). Sync, so it CAN block.

Phased enforcement, switched by mode (default 'observe' — pure logging):
  - observe : log only, always allow. (current default)
  - warn    : log + a non-blocking systemMessage nudge on work-without-todo.
  - block   : log + BLOCK the stop on work-without-todo (forces a retry turn).

Every turn it logs to data/work/todo_audit.jsonl: whether file-mutating work
happened (deterministic — file_access_tracker Edit/Write entries scoped to the
turn), whether a todo was referenced (todo_NNNN in the turn), the verdict, the
active mode, and the last assistant message.

The mode switch (so enforcement can be turned on with NO code change):
  - Global default:  data/hooks/Stop/todo_audit.config.json  {"mode": "..."}
  - Per-session override:  <state>.json  "todo_audit.mode": "..."
  Missing/invalid → 'observe'.

Block has loop protection (honors stop_hook_active) and only fires on
work_without_todo. Sync (not async) so its exit code is actually honored.

Targets Python 3.9.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

sys.path.insert(0, "$AI_ROOT/ai_general/scripts/file_access")
try:
    from uai_toolkit.file_access.tracker import STATE_FILE as ACCESS_STATE_FILE
except Exception:
    ACCESS_STATE_FILE = None

AUDIT_LOG = Path("$AI_ROOT/ai_general/data/work/todo_audit.jsonl")
MODE_CONFIG = Path("$AI_ROOT/ai_general/data/hooks/Stop/todo_audit.config.json")
TODO_RE = re.compile(r"todo_\d{3,}")
VALID_MODES = ("observe", "warn", "block")
FALLBACK_WINDOW_SEC = 1800  # if turn start can't be found, look back 30m


def _resolve_mode(context):
    """observe | warn | block. Global config file is the switch; session state can override."""
    mode = "observe"
    try:
        if MODE_CONFIG.is_file():
            cfg = json.loads(MODE_CONFIG.read_text())
            if isinstance(cfg, dict) and cfg.get("mode") in VALID_MODES:
                mode = cfg["mode"]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    try:
        if context.tracking_id and context.session_dir:
            state_path = Path(context.session_dir) / (context.tracking_id + "_state.json")
            if state_path.is_file():
                state = json.loads(state_path.read_text())
                override = state.get("todo_audit.mode")
                if override in VALID_MODES:
                    mode = override
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return mode


def _analyze_turn(transcript_path):
    """From the transcript tail: (turn_start_epoch, last_assistant_text, turn_text)."""
    start_ts = 0.0
    last_text = ""
    turn_text = ""
    if not (transcript_path and os.path.isfile(transcript_path)):
        return start_ts, last_text, turn_text

    try:
        with open(transcript_path, errors="replace") as fh:
            lines = fh.readlines()[-250:]
    except OSError:
        return start_ts, last_text, turn_text

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # The last user message in the tail marks this turn's start.
    last_user_idx = -1
    for i, entry in enumerate(entries):
        role = entry.get("type") or (entry.get("message") or {}).get("role")
        if role == "user":
            last_user_idx = i

    if last_user_idx >= 0:
        ts_iso = entries[last_user_idx].get("timestamp")
        if ts_iso:
            try:
                start_ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError):
                start_ts = 0.0

    # last_text: most recent assistant message in the tail (robust to write timing).
    for entry in entries:
        if (entry.get("message") or {}).get("role") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                part.get("text", "") for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if text.strip():
            last_text = text.strip()

    # turn_text: assistant text + tool inputs since the last user message.
    turn = entries[last_user_idx:] if last_user_idx >= 0 else entries
    texts = []
    for entry in turn:
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "tool_use":
                    texts.append(json.dumps(part.get("input", {})))
    turn_text = "\n".join(texts)
    return start_ts, last_text, turn_text


def _writes_this_turn(session_id, start_ts):
    """Files written by this session since start_ts, per the file-access tracker."""
    files = []
    if not (ACCESS_STATE_FILE and session_id and os.path.isfile(str(ACCESS_STATE_FILE))):
        return files
    try:
        with open(str(ACCESS_STATE_FILE), errors="replace") as fh:
            tail = fh.readlines()[-4000:]
    except OSError:
        return files
    for line in tail:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("op") != "write" or entry.get("session") != session_id:
            continue
        try:
            if float(entry.get("ts", 0)) >= start_ts:
                path = entry.get("file")
                if path and path not in files:
                    files.append(path)
        except (ValueError, TypeError):
            continue
    return files


def handler(hook_input, context):
    stop_active = bool(hook_input.get("stop_hook_active"))
    session_id = hook_input.get("session_id", "")
    mode = "observe"
    verdict = "unknown"
    files = []
    todo_ids = []
    last_text = ""
    error = None

    # ── Evaluate (never raises out: capture the error, still log + fail open) ──
    try:
        transcript_path = hook_input.get("transcript_path", "")
        mode = _resolve_mode(context)
        start_ts, last_text, turn_text = _analyze_turn(transcript_path)
        window_start = start_ts if start_ts else (time.time() - FALLBACK_WINDOW_SEC)
        files = _writes_this_turn(session_id, window_start)
        todo_ids = sorted(set(TODO_RE.findall(turn_text)))
        if files and not todo_ids:
            verdict = "work_without_todo"
        elif files:
            verdict = "work_with_todo"
        else:
            verdict = "no_work"
    except Exception as exc:
        error = str(exc)[:160]

    # would_block = would this turn block if mode were 'block'? Mode-INDEPENDENT,
    # logged every firing so positives ("would block") and negatives can be counted
    # while still in observe. action = what actually happened given the live mode.
    would_block = (verdict == "work_without_todo") and not stop_active
    if error is not None:
        action = "allow-error"
    elif verdict != "work_without_todo" or mode == "observe":
        action = "allow"
    elif stop_active:
        action = "allow-loopguard"
    elif mode == "warn":
        action = "warn"
    else:
        action = "block"

    # ── Log EVERY firing — positive or negative, error or not ──
    entry = {
        "ts": datetime.now().isoformat(),
        "tracking_id": context.tracking_id,
        "session_id": session_id,
        "mode": mode,
        "verdict": verdict,
        "would_block": would_block,
        "action": action,
        "stop_hook_active": stop_active,
        "work_done": bool(files),
        "files_count": len(files),
        "files_written": files[:20],
        "todo_referenced": bool(todo_ids),
        "todo_ids": todo_ids,
        "last_message": last_text[:1000],
        "error": error,
    }
    try:
        if AUDIT_LOG.parent.is_dir():
            with open(AUDIT_LOG, "a") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass

    # ── Act per the resolved action (inert in observe; fails open on error) ──
    if action in ("allow", "allow-error", "allow-loopguard"):
        return HookResult.allow("audit[" + mode + "]: " + action + "/" + verdict)

    changed = ", ".join(os.path.basename(f) for f in files[:5])
    message = (
        "Todo check: this turn changed files (" + changed + ") with no linked todo. "
        "Link this work to a todo (todos-mgr) or `create-light` one, then continue. "
        "If this was operational/non-work (comms bookkeeping, a pointer bump), say so explicitly."
    )
    if action == "warn":
        return HookResult.output(json.dumps({"systemMessage": message}), "warn: work_without_todo")
    return HookResult.block(message, "block: work_without_todo")


if __name__ == "__main__":
    sys.exit(run_hook("todo_audit", "Stop", handler))
