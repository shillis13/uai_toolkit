#!/usr/bin/env python3
"""Quality Gate Stop Hook — Observe Mode.

Evaluates AI responses against a quality checklist. Logs findings but NEVER
blocks (OBSERVE_ONLY).

Two outputs per evaluation:
  - hook_events.jsonl  : one-line outcome summary (via lib_hook_base).
  - quality_findings.jsonl : full detail of every evaluation (pass AND fail) —
        what was evaluated, what was decided, and WHY (the full findings array,
        the evaluating endpoint, latency, and the evaluated request/response
        text). This lets us tell true positives from false positives.

The evaluator is a CONFIGURABLE ORDERED ENDPOINT CHAIN: endpoints are tried in
order until one returns a valid verdict. Supports OpenAI-compatible endpoints
(local LLM, remote LLMs, Codex/OpenAI-served) and Anthropic endpoints. Config
comes from the shared ``quality_gate`` feature in uai_toolkit.llm. If absent,
the hook skips; there is no built-in endpoint.
"""

import glob
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_stop_hooks import should_evaluate

# ─── Config ──────────────────────────────────────────────────────────────

OBSERVE_ONLY = True
MIN_RESPONSE_TOKENS = 80
MAX_CONTEXT_TURNS = 3
EVALUATOR_PROMPT = """You are a quality gate evaluating an AI assistant's response.

You receive the last few turns of conversation: user messages and assistant responses.
The FINAL assistant message is what you are evaluating.

Check for these issues ONLY. Return ONLY issues you actually find. If the response
is fine, return an empty findings array.

1. REQUEST_MISMATCH: The response doesn't address what the user asked.

2. INTENT_WITHOUT_ACTION: The response says "I'll do X" but ends without doing it.
   Tool calls that perform the action count as action taken.

3. CLAIMS_WITHOUT_EVIDENCE: Factual assertions about code, files, state, or behavior
   that should be verified but weren't. Hedged language is fine.

Return STRICTLY this JSON format, nothing else:
{"pass": true, "findings": []}

or:

{"pass": false, "findings": [
  {"type": "REQUEST_MISMATCH", "detail": "brief explanation"}
]}"""


def find_jsonl(session_id):
    """Find the JSONL transcript for a Claude Code session."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None
    pattern = str(claude_dir / "*" / f"{session_id}.jsonl")
    matches = glob.glob(pattern)
    if matches:
        return Path(matches[0])
    pattern = str(claude_dir / "*" / f"{session_id[:8]}*.jsonl")
    matches = glob.glob(pattern)
    if matches:
        return Path(sorted(matches, key=lambda p: Path(p).stat().st_mtime, reverse=True)[0])
    return None


def extract_last_turns(jsonl_path, n_turns=MAX_CONTEXT_TURNS):
    """Extract last N user/assistant text exchanges from JSONL."""
    messages = []
    try:
        with open(jsonl_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 512_000))
            lines = f.read().decode('utf-8', errors='replace').strip().split('\n')

        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type")
            role = entry.get("message", {}).get("role") if isinstance(entry.get("message"), dict) else None

            if msg_type == "user" and role == "user":
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, str) and content.strip():
                    messages.append({"role": "user", "text": content[:2000]})
                elif isinstance(content, list):
                    text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    combined = "\n".join(text_parts).strip()
                    if combined:
                        messages.append({"role": "user", "text": combined[:2000]})

            elif msg_type == "assistant" and role == "assistant":
                content = entry.get("message", {}).get("content", [])
                if isinstance(content, str) and content.strip():
                    messages.append({"role": "assistant", "text": content[:4000]})
                elif isinstance(content, list):
                    text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    combined = "\n".join(text_parts).strip()
                    if combined:
                        messages.append({"role": "assistant", "text": combined[:4000]})
    except Exception:
        return []

    result = []
    count = 0
    for msg in reversed(messages):
        result.insert(0, msg)
        if msg["role"] == "user":
            count += 1
            if count >= n_turns:
                break
    return result


# ─── Evaluator: shared configurable endpoint chain ────────────────────────


def load_endpoints():
    """Load this hook's independently configured shared-client endpoint chain."""
    try:
        from uai_toolkit.llm import load_endpoints as shared_load_endpoints
        return shared_load_endpoints("quality_gate")
    except Exception:
        return []


def load_context_config():
    """Judge-context settings from the same JSON config file.

    Returns {"turns": int, "max_chars": int}. `turns` = how many user/assistant
    exchanges are fed to the judge; `max_chars` caps the assembled conversation
    (0 = uncapped, keeping the most-recent tail). This is the knob for sweeping
    how much data the judge sees during the eval phase.
    """
    cfg = {"turns": MAX_CONTEXT_TURNS, "max_chars": 0}
    # Compatibility-only context knob. Endpoint selection never comes from this
    # legacy file; it always goes through uai_toolkit.llm above.
    path = os.environ.get("QUALITY_GATE_ENDPOINTS")
    if not path:
        return cfg
    try:
        data = json.loads(Path(path).read_text())
        ctx = data.get("context") if isinstance(data, dict) else None
        if isinstance(ctx, dict):
            if isinstance(ctx.get("turns"), int) and ctx["turns"] > 0:
                cfg["turns"] = ctx["turns"]
            if isinstance(ctx.get("max_chars"), int) and ctx["max_chars"] >= 0:
                cfg["max_chars"] = ctx["max_chars"]
    except Exception:
        pass
    return cfg


def _parse_verdict(text):
    """Parse a verdict dict from raw model text, tolerating prose/markdown."""
    if not isinstance(text, str) or not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to extracting the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def evaluate(messages):
    """Use the shared client; return a strict verdict and actual endpoint label.

    Returns (verdict_dict, endpoint_label) on first success, else (None, None).
    """
    conversation = "\n\n".join(
        f"{str(m.get('role', 'user')).upper()}: {m.get('content', '')}"
        for m in messages if isinstance(m, dict)
    )
    try:
        from uai_toolkit.llm import complete_with_endpoint
        result = complete_with_endpoint(
            "quality_gate", EVALUATOR_PROMPT, conversation, max_tokens=500,
        )
    except Exception:
        result = None
    if not result:
        return None, None
    text, endpoint = result
    verdict = _parse_verdict(text)
    if not isinstance(verdict, dict) or not isinstance(verdict.get("pass"), bool):
        return None, None
    findings = verdict.get("findings")
    if not isinstance(findings, list) or not all(
        isinstance(f, dict)
        and isinstance(f.get("type"), str)
        and isinstance(f.get("detail"), str)
        for f in findings
    ):
        return None, None
    label = f"{endpoint.get('name', '?')}:{endpoint.get('model', '?')}"
    return verdict, label


# ─── Findings persistence ─────────────────────────────────────────────────

def _findings_log_path(session_dir, tracking_id):
    """Path for the detailed findings log (mirrors lib_hook_base logic)."""
    if session_dir and Path(session_dir).is_dir():
        return Path(session_dir) / "quality_findings.jsonl"
    if tracking_id:
        return Path("/tmp") / f"quality_findings_{tracking_id}.jsonl"
    return Path("/tmp") / "quality_findings_unknown.jsonl"


def _write_finding(session_dir, tracking_id, record):
    """Append one findings record; never raise."""
    try:
        path = _findings_log_path(session_dir, tracking_id)
        with open(path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def handler(hook_input, context):
    proceed, reason = should_evaluate(hook_input, min_length=MIN_RESPONSE_TOKENS)
    if not proceed:
        return HookResult.skip(reason)

    # Use transcript_path from stdin if available (works across Claude + Codex)
    transcript_path = hook_input.get("transcript_path", "")
    jsonl_path = None
    if transcript_path:
        tp = Path(transcript_path)
        if tp.exists():
            jsonl_path = tp
    if not jsonl_path:
        session_id = hook_input.get("session_id", "")
        jsonl_path = find_jsonl(session_id)
    if not jsonl_path:
        return HookResult.skip("jsonl not found")

    ctx_cfg = load_context_config()
    turns = extract_last_turns(jsonl_path, n_turns=ctx_cfg["turns"])
    if not turns:
        return HookResult.skip("no turns extracted")

    last_assistant = None
    for t in reversed(turns):
        if t["role"] == "assistant":
            last_assistant = t
            break
    if not last_assistant or len(last_assistant["text"].split()) < MIN_RESPONSE_TOKENS:
        return HookResult.skip("last response too short for evaluation")

    last_user_text = ""
    for t in reversed(turns):
        if t["role"] == "user":
            last_user_text = t["text"]
            break

    conversation = "\n\n".join(
        f"{'USER' if t['role'] == 'user' else 'ASSISTANT'}: {t['text']}" for t in turns
    )
    if ctx_cfg["max_chars"] > 0 and len(conversation) > ctx_cfg["max_chars"]:
        conversation = conversation[-ctx_cfg["max_chars"]:]  # keep most-recent tail
    messages = [{"role": "user", "content": conversation}]

    eval_start = time.time()
    verdict, evaluator_name = evaluate(messages)
    latency_ms = int((time.time() - eval_start) * 1000)

    if not verdict:
        return HookResult.skip("no evaluator available")

    would_block = not verdict.get("pass", True)
    findings = verdict.get("findings", [])

    # Persist full detail on EVERY evaluation (pass and fail).
    tracking_id = getattr(context, "tracking_id", "") if context else os.environ.get("AI_TRACKING_ID", "")
    session_dir = getattr(context, "session_dir", "") if context else os.environ.get("AI_SESSION_DIR", "")
    _write_finding(session_dir, tracking_id, {
        "ts": datetime.now().isoformat(),
        "tracking_id": tracking_id,
        "session_id": hook_input.get("session_id", ""),
        "verdict": "fail" if would_block else "pass",
        "would_block": would_block,
        "findings": findings,
        "evaluator": evaluator_name,
        "latency_ms": latency_ms,
        "evaluated_response": last_assistant["text"][:2000],
        "evaluated_request": last_user_text[:500],
        "ctx_turns": ctx_cfg["turns"],
        "ctx_max_chars": ctx_cfg["max_chars"],
    })

    if OBSERVE_ONLY:
        reason = f"observe: {'FAIL' if would_block else 'PASS'} ({len(findings)} findings)"
        return HookResult.allow(reason)

    if would_block:
        detail = "; ".join(f"{f['type']}: {f['detail']}" for f in findings)
        return HookResult.block(f"Quality gate: {detail}", reason=f"{len(findings)} findings")

    return HookResult.allow()


if __name__ == "__main__":
    sys.exit(run_hook("quality_gate", "Stop", handler))
