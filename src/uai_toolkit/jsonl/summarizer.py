#!/usr/bin/env python3
"""Dual-path consolidation summarizer (shadow mode).

The Stage-2 author for lib_engram.consolidate. Per PianoMan's call (2026-06-23):
run BOTH summarizer paths, USE the Claude one, and LOG both for later comparison
(would the configured model have been good enough? would an instruction tweak help?).

- Claude path: a subagent the orchestrating SESSION spawns (reads the turn-range
  off disk, applies SUMMARY_INSTRUCTION, returns the recall). Pure-Python code
  can't spawn a Claude agent, so the session passes that result into
  shadow_summarize(); see PROCEDURE below.
- Model path: the ``consolidation_summary`` feature's independently configured
  endpoint (local or hosted). It remains only the shadow candidate: logged for
  comparison, never consolidated with. Unconfigured is the safe default.

PROCEDURE (agent-driven, for the immediate self-bounce / consolidation loop):
  1. pick first_uuid (oldest consolidatable turn; never the live tail)
  2. rng = extract_turn_range(jsonl, first_uuid)
  3. claude_summary = <spawn subagent: read rng, follow SUMMARY_INSTRUCTION>
  4. used = shadow_summarize(jsonl, first_uuid, claude_summary)  # runs model + logs both
  5. lib_engram.consolidate(jsonl, first_uuid, used)             # consolidate with Claude's
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from uai_toolkit.jsonl import lib_engram

# Shared instruction — IDENTICAL for both paths so the comparison is apples-to-apples.
SUMMARY_INSTRUCTION = (
    "You are writing a CONSOLIDATION MEMORY — a note from you to your FUTURE SELF that "
    "will REPLACE a stretch of your own earlier turns in this session (the raw turns are "
    "archived byte-exact and recallable on demand). When you read it back later it must "
    "feel like YOUR OWN RECOLLECTION of what you did and worked out — not a report about "
    "a conversation.\n\n"
    "VOICE — this is the whole point, get it right:\n"
    "- First person singular throughout: 'I decided…', 'I'd worked out…', 'I was in the "
    "middle of…', 'I'm still chewing on…'. It is an inner self-dialogue / continuity note.\n"
    "- NEVER refer to yourself in the third person ('the assistant', 'the session', "
    "'Claude') and NEVER narrate the human as an outside observer ('the user asked', "
    "'they wanted'). Fold what was asked of you into your own context: 'I was asked to X, "
    "so I…'.\n"
    "- Do NOT write a compaction-style report or meeting minutes — no 'Summary:', no "
    "'Files modified:' roster, no third-person play-by-play. This is a memory, not a "
    "transcript.\n"
    "- Keep the texture of my own thinking — the reasoning and the open questions I was "
    "turning over — not just a flat outcome list.\n\n"
    "PRESERVE, faithfully and concretely (this is what makes the memory usable later):\n"
    "- the decisions I made AND my reasoning (the WHY, not just the WHAT);\n"
    "- concrete outcomes, file paths, identifiers, numbers, and commands that matter;\n"
    "- open threads / unfinished work / what I was about to do next;\n"
    "- any load-bearing fact a later turn of mine would rely on.\n\n"
    "Be compressed but complete — favor density. Do NOT invent or embellish; if something "
    "is uncertain, say so. This is a memory I will read as my own."
)

# Comparison log (shadow A/B store).
SHADOW_LOG = Path(__file__).resolve().parents[2] / "data" / "summarizer_shadow" / "comparisons.jsonl"


def _content_text(rec: dict) -> str:
    """Render one record's message.content to plain text for summarization input."""
    msg = rec.get("message") or {}
    role = msg.get("role") or rec.get("type") or "?"
    content = msg.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", ""))
            elif t == "thinking":
                parts.append("[thinking] " + (b.get("thinking", "") or ""))
            elif t == "tool_use":
                parts.append(f"[tool_use {b.get('name','')}] "
                             + json.dumps(b.get("input", {}), ensure_ascii=False)[:2000])
            elif t == "tool_result":
                c = b.get("content", "")
                parts.append("[tool_result] " + (c if isinstance(c, str) else json.dumps(c)[:2000]))
    body = "\n".join(p for p in parts if p)
    return f"### {role}\n{body}" if body else ""


def extract_turn_range(jsonl_path, first_uuid: str, leaf_uuid: str | None = None) -> dict:
    """Chain-native turn-range starting at first_uuid (mirrors consolidate's selection):
    from first_uuid through the record before the next human prompt on the active chain.
    Returns {text, records, turns, content_chars}."""
    _s0, _s1, _raw, records = lib_engram._load(Path(jsonl_path))
    chain, _leaf, _lt, _br = lib_engram._chain_records(records, leaf_uuid=leaf_uuid)
    uuids = [r.get("uuid") for r in chain]
    if first_uuid not in uuids:
        raise ValueError(f"first_uuid not on active chain: {first_uuid}")
    ci = uuids.index(first_uuid)
    if not lib_engram._is_human_prompt(chain[ci]):
        raise ValueError(f"first_uuid is not a human-turn start: {first_uuid}")
    nexti = next((j for j in range(ci + 1, len(chain))
                  if lib_engram._is_human_prompt(chain[j])), len(chain))
    segment = chain[ci:nexti]
    rendered = "\n\n".join(t for t in (_content_text(r) for r in segment) if t)
    turns = sum(1 for r in segment if lib_engram._is_human_prompt(r))
    return {"text": rendered, "records": len(segment), "turns": turns,
            "content_chars": len(rendered)}


def summarize_via_local_llm(range_text: str, instruction: str = SUMMARY_INSTRUCTION) -> dict:
    """Summarize a turn-range with the model configured for `consolidation_summary`.

    Endpoint comes from this feature's own entry in the LLM endpoint config, so it
    can point at the local LLLM, a hosted API, or nothing at all. Unconfigured is
    the default and is not an error: the caller gets ok=False and carries on.
    (Kept under the historical name so existing callers need no change.)
    """
    from uai_toolkit.llm import complete_with_endpoint, is_configured

    if not is_configured("consolidation_summary"):
        return {"ok": False, "summary": "", "model": "",
                "error": "no endpoint configured for feature 'consolidation_summary'"}
    try:
        result = complete_with_endpoint(
            "consolidation_summary", instruction, range_text, max_tokens=1000,
        )
    except Exception as e:                      # defensive: complete() shouldn't raise
        return {"ok": False, "summary": "", "model": "", "error": f"{type(e).__name__}: {e}"}
    if not result:
        return {"ok": False, "summary": "", "model": "",
                "error": "no endpoint in the chain returned a summary"}
    out, endpoint = result
    return {"ok": True, "summary": out, "model": endpoint.get("model", "")}


def log_comparison(entry: dict, log_path: Path = SHADOW_LOG) -> Path:
    """Append one shadow-comparison record (JSONL)."""
    log_path = Path(log_path)
    os.makedirs(log_path.parent, exist_ok=True)   # deliberate feature data dir
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path


def shadow_summarize(jsonl_path, first_uuid: str, claude_summary: str, *,
                     leaf_uuid: str | None = None, run_local_llm: bool = True,
                     log_path: Path = SHADOW_LOG, ts: str | None = None) -> str:
    """Run the local-LLM shadow path, log BOTH summaries + metadata, and return the
    Claude summary (the one consolidate should use). Logging never blocks the return."""
    rng = extract_turn_range(jsonl_path, first_uuid, leaf_uuid=leaf_uuid)
    lllm = summarize_via_local_llm(rng["text"]) if run_local_llm else {"ok": False, "summary": "", "model": "", "error": "skipped"}
    entry = {
        "ts": ts or datetime.now().isoformat(timespec="seconds"),
        "jsonl_path": str(jsonl_path),
        "first_uuid": first_uuid,
        "range_turns": rng["turns"],
        "range_records": rng["records"],
        "range_content_chars": rng["content_chars"],
        "used": "claude",
        "claude_summary": claude_summary,
        "claude_chars": len(claude_summary or ""),
        "lllm_ok": lllm.get("ok"),
        "lllm_model": lllm.get("model", ""),
        "lllm_summary": lllm.get("summary", ""),
        "lllm_chars": len(lllm.get("summary", "") or ""),
        "lllm_error": lllm.get("error", ""),
        "instruction_sha8": __import__("hashlib").sha256(SUMMARY_INSTRUCTION.encode()).hexdigest()[:8],
    }
    try:
        log_comparison(entry, log_path)
    except Exception:
        pass   # shadow logging must never block the real consolidation
    return claude_summary


_USAGE = """\
summarizer.py — Stage-2 author for the Summarize lever (dual-path, shadow mode)

WHAT IT DOES
  Builds the summary text (the "Engram" note) for ONE consolidatable turn-range on a
  session's active chain. This is the Summarize rung of the context-reclaim ladder
  (Offload < Bounce < Summarize < self-compact < compact): a LOSSY-but-REVERSIBLE
  compression that replaces a stretch of earlier turns with a single first-person
  recollection Stub, while the raw turns are archived off-chain byte-exact and can be
  brought back via Recall (live page-in) or Restore (disk-undo).

  It runs BOTH summarizer paths and USES the Claude one, LOGGING both for A/B compare
  (PianoMan, 2026-06-23):
    - Claude path  — a subagent the orchestrating session spawns reads the range off
                     disk, applies SUMMARY_INSTRUCTION, and returns the recall. Pure
                     Python can't spawn a Claude agent, so the session feeds that text
                     into shadow_summarize() (see the module PROCEDURE docstring).
    - Model shadow — the ``consolidation_summary`` feature's configured endpoint.
                     It may be local or hosted; absent config contacts nothing.

  Run directly, this module is a DEMO: it extracts the range at <first_uuid> and runs
  ONLY the configured shadow path (it prints range stats + that model's candidate). It
  does NOT consolidate and does NOT write the transcript — real consolidation is
  lib_engram.consolidate(), driven by the session, not this CLI.

USAGE
  summarizer.py <jsonl> <first_uuid> [leaf_uuid]
  summarizer.py -h | --help

POSITIONAL ARGS
  <jsonl>        path to the Claude Code transcript .jsonl to read (required).
  <first_uuid>   uuid of the OLDEST turn to summarize — must be a human-turn START on
                 the active chain, and never the live tail. The range runs from here
                 through the record just before the next human prompt on the chain.
  [leaf_uuid]    optional active-chain leaf to disambiguate a FORKED transcript (which
                 branch's chain to walk). Omit to use the default conversational leaf.
                 (Accepted by the library extract_turn_range(); the demo path uses
                 <jsonl> <first_uuid> only.)

EXAMPLES
  # Show rich help:
  summarizer.py --help

  # DEMO: extract the range at a first_uuid and print the configured shadow candidate:
  summarizer.py ~/.claude/projects/foo/SESSION.jsonl 4b1e...c9

  # Same, disambiguating a forked transcript by explicit leaf (library-level):
  summarizer.py SESSION.jsonl 4b1e...c9 9f2a...d0

CAVEATS
  * This CLI is a shadow/demo probe — it writes NOTHING to the transcript and performs
    NO consolidation. To actually Summarize, the session calls shadow_summarize() then
    lib_engram.consolidate(jsonl, first_uuid, claude_summary).
  * <first_uuid> must be a human-turn start ON the active chain; otherwise the library
    raises ("first_uuid not on active chain" / "not a human-turn start").
  * The model path is best-effort: if the configured service is unavailable it returns
    {ok: false, error: ...} rather than raising — the demo still prints that result.
  * Every real shadow run appends an A/B record to
    ai_general/data/summarizer_shadow/comparisons.jsonl (created on demand); shadow
    logging is wrapped so it NEVER blocks the returned Claude summary.
  * Summarize is LOSSY but reversible: originals archive off-chain; bring back via
    Recall (live) or Restore (disk-undo). The reclaim effect lands on --resume.
"""

if __name__ == "__main__":
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print(_USAGE)
        raise SystemExit(0)
    # Demo: extract a range and run the configured shadow path (no consolidation).
    if len(sys.argv) >= 3:
        rng = extract_turn_range(sys.argv[1], sys.argv[2])
        print(f"range: {rng['turns']} turns, {rng['records']} records, {rng['content_chars']} chars")
        print(json.dumps(summarize_via_local_llm(rng["text"]), indent=2)[:1500])
    else:
        print("usage: summarizer.py <jsonl> <first_uuid>")
