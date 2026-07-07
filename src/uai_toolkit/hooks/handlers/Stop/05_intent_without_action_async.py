#!/usr/bin/env python3
"""Stop hook (ASYNC, evaluation mode) — flag intent stated without action taken.

Reinstates the retired 05_block_intent_without_action_sync with three changes
(PianoMan, 2026-07-07):
  1. ASYNC — it never blocks the turn. Async handlers are fire-and-forget (the
     dispatcher doesn't wait on their exit code, so they *can't* block); this one
     evaluates and LOGS. A future `push_back: true` (config) makes it deliver an
     async self-prompt nudge instead of blocking — but for now it only observes.
  2. LOGS every evaluated candidate as JSONL: {ts, result, reason, message}
     (+ matched phrase, evaluator verdict) to settings.log_path.
  3. CONFIG-DRIVEN — intent_without_action.config.yml holds the evaluator
     settings, the regex pre-filter, and positive/negative examples used BOTH as
     LLM few-shot AND (via --selftest) to grade the regex.

Flow: should_evaluate → action-evidence? allow → intent pre-filter? no-match allow
→ ask the evaluator (few-shot from config) → result = would_push_back | allow →
LOG → (if push_back) deliver self-prompt, else nothing. Async: always allows.

`--selftest` runs the regex pre-filter over the config examples and reports recall
on positives / false-positives on negatives (no LLM, no stdin).

Python 3.9 compatible.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_stop_hooks import (should_evaluate, get_response_tail,
                            get_response_text, get_last_user_message)

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
PYTHON = "/opt/homebrew/bin/python3"
LLLM_PROMPT = AI_ROOT / "ai_general/scripts/lllm/lllm_prompt.py"
SEND_PROMPT = AI_ROOT / "ai_general/scripts/prompting/send_prompt.py"
CONFIG_PATH = Path(__file__).resolve().parent / "intent_without_action.config.yml"


# ─── Config ──────────────────────────────────────────────────────────────────

def load_config():
    """Load the YAML config, tolerant of a missing/broken file (fail-safe)."""
    cfg = {"settings": {}, "intent_patterns": [], "action_evidence": [], "wait_evidence": [],
           "act_now_evidence": [],
           "examples": {"positive": [], "negative": []}}
    try:
        import yaml
        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for k in cfg:
            if k in loaded and loaded[k] is not None:
                cfg[k] = loaded[k]
    except Exception:
        pass
    cfg["settings"] = cfg.get("settings") or {}
    ex = cfg.get("examples") or {}
    cfg["examples"] = {"positive": ex.get("positive") or [],
                       "negative": ex.get("negative") or []}
    return cfg


def _compile(patterns):
    out = []
    for p in patterns or []:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            pass
    return out


def _expand(path_str):
    return os.path.expandvars(str(path_str)) if path_str else ""


# ─── Logging (requirement #2) ────────────────────────────────────────────────

def log_evaluation(cfg, result, reason, message, extra=None):
    """Append one JSONL record: ts, result, reason, message (+ extras)."""
    path = _expand(cfg["settings"].get(
        "log_path", "$AI_ROOT/ai_general/logs/hooks/intent_without_action.jsonl"))
    if not path:
        return
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "result": result, "reason": reason, "message": message}
    if extra:
        rec.update(extra)
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break the hook


# ─── Evaluator (few-shot from config) ────────────────────────────────────────

def lllm_running():
    try:
        r = subprocess.run([PYTHON, str(LLLM_PROMPT), "--status"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and json.loads(r.stdout).get("state") == "running"
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return False


def _few_shot(cfg):
    pos = cfg["examples"]["positive"]
    neg = cfg["examples"]["negative"]
    if not pos and not neg:
        return ""
    lines = ["\nCalibration examples — judge new cases the same way:\n"]
    for e in pos:
        lines.append('  act now  <- "{}"'.format(e))
    for e in neg:
        lines.append('  wait     <- "{}"'.format(e))
    return "\n".join(lines) + "\n"


def assess(cfg, last_sentences, user_message=""):
    """('act now'|'wait', reasoning) or None on failure."""
    prompt = (
        "An AI agent ended its response with the text below. Decide whether it "
        "needs more input before proceeding, or has enough to act now.\n\n"
        "'wait' if: it's a design discussion presenting options/tradeoffs or "
        "asking the user's preference; OR it depends on an outcome that hasn't "
        "happened (waiting on a subagent, background task, other session, build, "
        "or the user's confirmation) - conditional intent like 'I'll proceed once "
        "X' is a wait, not intent to act now; OR the work is already DONE and the "
        "response is a COMPLETION REPORT summarizing what was accomplished; OR the "
        "intent is a STANDING / ONGOING commitment, not a discrete task ('I'll keep "
        "an eye on', 'I'll monitor', 'I'll watch for', 'I'll flag if') - there is no "
        "single action to perform now.\n"
        "'act now' if: it states a clear intent to do a specific, discrete action "
        "it could just perform, and that action is not already done.\n"
        + _few_shot(cfg) +
        "\nAnswer EXACTLY 'act now' or 'wait' on line 1, brief reasoning on line 2.\n\n")
    body = ""
    if user_message:
        body += "User's last message:\n{}\n\n".format(user_message)
    body += "Agent's last sentences:\n{}".format(last_sentences)
    try:
        r = subprocess.run([PYTHON, str(LLLM_PROMPT), prompt, "--text", body],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        parts = r.stdout.strip().split("\n", 1)
        decision = parts[0].strip().lower()
        reasoning = parts[1].strip() if len(parts) > 1 else ""
        if "act now" in decision:
            return ("act now", reasoning)
        if "wait" in decision:
            return ("wait", reasoning)
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _last_sentences(text, n=3):
    s = re.split(r'(?<=[.!?])\s+', text.strip())
    return " ".join(s[-n:]) if s else text[-500:]


# ─── Push-back delivery (only when settings.push_back is true) ────────────────

_COOLDOWN_DIR = Path(__file__).resolve().parent.parent / "data" / ".intent_nudge_cooldown"


def _recently_nudged(tid, cooldown_min):
    """True if this session was nudged within cooldown_min — loop guard so a
    nudge → response → nudge chain can't run away across the fleet."""
    if not tid or cooldown_min <= 0:
        return False
    try:
        import time
        f = _COOLDOWN_DIR / str(tid)
        return f.exists() and (time.time() - f.stat().st_mtime) < cooldown_min * 60
    except OSError:
        return False


def _mark_nudged(tid):
    try:
        _COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
        (_COOLDOWN_DIR / str(tid)).touch()
    except OSError:
        pass


def deliver_self_prompt(context, matched, reasoning):
    """Async nudge back to THIS session (never a block). Best-effort."""
    tid = getattr(context, "tracking_id", None) or os.environ.get("AI_TRACKING_ID")
    if not tid:
        return False
    msg = ("[intent-without-action] You stated intent (\"{}\") but stopped without "
           "acting. If you don't need more input, do it now or schedule a self-prompt "
           "to begin. ({})".format(matched, reasoning[:160]))
    try:
        subprocess.Popen(
            [PYTHON, str(SEND_PROMPT), "--endpoint",
             "uai://session/{}?submit=true".format(tid), "--message", msg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# ─── Core decision (shared by the handler AND the test runner) ────────────────

def evaluate(response_text, user_message="", cfg=None):
    """Decide what to do about one assistant response ending.

    Pure function of the text (+ optional user message) — no hook_input, no
    stdin — so the test harness can drive it directly. Returns a dict:
      {result, reason, matched, verdict}
    result ∈ {"would_push_back", "allow"}. matched is the intent phrase (or None
    for a pre-filter allow); verdict is the evaluator's "act now"/"wait"/None.
    """
    if cfg is None:
        cfg = load_config()
    text = response_text or ""
    tail = text[-400:]

    if any(p.search(tail) for p in _compile(cfg["action_evidence"])):
        return {"result": "allow", "reason": "action evidence found",
                "matched": None, "verdict": None}
    if any(p.search(tail) for p in _compile(cfg.get("wait_evidence") or [])):
        return {"result": "allow", "reason": "wait evidence found",
                "matched": None, "verdict": None}

    matched = None
    for p in _compile(cfg["intent_patterns"]):
        m = p.search(tail)
        if m:
            matched = m.group(0)
            break
    if not matched:
        return {"result": "allow", "reason": "no intent phrase",
                "matched": None, "verdict": None}

    if any(p.search(tail) for p in _compile(cfg.get("act_now_evidence") or [])):
        return {"result": "would_push_back", "reason": "act-now evidence found",
                "matched": matched, "verdict": "act now"}

    if cfg["settings"].get("evaluator", "lllm") == "lllm" and not lllm_running():
        return {"result": "allow", "reason": "evaluator not running",
                "matched": matched, "verdict": None}

    a = assess(cfg, _last_sentences(text), user_message[:1000])
    if a is None:
        return {"result": "allow", "reason": "evaluator failed/unclear",
                "matched": matched, "verdict": None}
    decision, reasoning = a
    if decision == "act now":
        return {"result": "would_push_back", "reason": "evaluator: act now - {}".format(reasoning),
                "matched": matched, "verdict": "act now"}
    return {"result": "allow", "reason": "evaluator: wait - {}".format(reasoning),
            "matched": matched, "verdict": "wait"}


# ─── Handler ─────────────────────────────────────────────────────────────────

def handler(hook_input, context):
    cfg = load_config()
    settings = cfg["settings"]
    proceed, reason = should_evaluate(
        hook_input, min_length=int(settings.get("min_response_chars", 200)))
    if not proceed:
        return HookResult.skip(reason)

    full = get_response_text(hook_input)
    user_msg = get_last_user_message(hook_input)
    r = evaluate(full, user_msg, cfg)

    # Only candidates (intent matched) are logged; pre-filter allows are noise.
    if r["matched"] is None:
        return HookResult.allow(r["reason"])

    log_evaluation(cfg, r["result"], r["reason"], _last_sentences(full),
                   {"matched": r["matched"], "verdict": r["verdict"]})

    if r["result"] == "would_push_back" and settings.get("push_back"):
        tid = getattr(context, "tracking_id", None) or os.environ.get("AI_TRACKING_ID")
        if _recently_nudged(tid, int(settings.get("renudge_cooldown_min", 15))):
            return HookResult.allow("would_push_back; suppressed (re-nudge cooldown)")
        delivered = deliver_self_prompt(context, r["matched"], r["reason"])
        if delivered:
            _mark_nudged(tid)
        return HookResult.allow("would_push_back; self-prompt delivered={}".format(delivered))
    return HookResult.allow(r["reason"])


# ─── --selftest (grade the regex against the config examples) ─────────────────

def selftest():
    cfg = load_config()
    pats = _compile(cfg["intent_patterns"])
    ev = _compile(cfg["action_evidence"])
    wait = _compile(cfg.get("wait_evidence") or [])

    def is_candidate(text):
        if any(p.search(text) for p in ev):
            return False
        if any(p.search(text) for p in wait):
            return False
        return any(p.search(text) for p in pats)

    pos = cfg["examples"]["positive"]
    neg = cfg["examples"]["negative"]
    hit_pos = [e for e in pos if is_candidate(e)]
    hit_neg = [e for e in neg if is_candidate(e)]   # false positives
    print("intent-without-action regex pre-filter - self-test\n")
    print("positives caught (recall):     {}/{}".format(len(hit_pos), len(pos)))
    print("negatives flagged (false pos): {}/{}".format(len(hit_neg), len(neg)))
    missed = [e for e in pos if e not in hit_pos]
    if missed:
        print("\n  MISSED positives (regex should probably match these):")
        for e in missed:
            print("    - {}".format(e))
    if hit_neg:
        print("\n  FALSE positives (regex wrongly flags - add a guard):")
        for e in hit_neg:
            print("    - {}".format(e))
    if not missed and not hit_neg:
        print("\n  clean: every positive is a candidate, no negative wrongly flagged.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    sys.exit(run_hook("intent_without_action", "Stop", handler))
