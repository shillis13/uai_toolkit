#!/usr/bin/env python3
"""reclaim_and_stage.py — the reclaim VALUE layer for self-Stop/Resume (BC's half).

Sits between "the session decides to bounce" and self_restart.py's lifecycle
(schedule launchd --resume → clean /exit). Its single responsibility is RECLAIM,
INERT until the resume actually re-reads the trimmed transcript:

  RECLAIM — shrink the live chain BEFORE the exit by consolidating the oldest
            evictable turn-ranges (lib_engram.plan_eviction → consolidate), each
            summarized via summarizer.shadow_summarize (the Claude summary is
            supplied by the caller; the local-LLM shadow is logged for the A/B
            comparison). Byte-exact reversible — every collapsed range is archived
            and recall()-able by first_uuid on the other side.

NO note is staged. A stop/resume is invisible to a session: without injected
messaging a resumed session doesn't notice it was bounced, so a continuation note
would only matter if it carried a "what to do next" reminder. But the live tail /
most-recent turns are NEVER consolidated (lib_engram.plan_eviction refuses to
summarize the present and protects the keep_recent_turns window), so the resumed
session always retains its recent context and needs no next_action reminder.
Therefore nothing is injected into context_to_load.

Wake-verify, if used, does NOT depend on any note: bounce_watch `verify --expected
<N>` takes the expected post-trim chain tokens straight from THIS module's
enact/reclaim return JSON (before_tokens/after_tokens).

Architecture note (2026-06-24 pivot, co-designed with Noctis): there is NO kill
and NO external bouncer process — the session schedules its own launchd --resume
then exits cleanly via /exit. That dissolves the kill-race, so the heavy CAS
machinery in resume_note.py relaxes to a pre-bounce sanity gate (should_bounce)
+ a wake-verify.

Why a caller-supplied `summarize` callback: the Claude summary path is a subagent
the LIVE session spawns; pure Python cannot. Tests pass a fake; the live agent
passes a spawn-a-subagent fn. This mirrors summarizer.py's documented PROCEDURE.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_JSONL = _HERE.parents[1] / "jsonl"
_CLI = _HERE.parents[1] / "cli"
for _p in (_JSONL, _CLI):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from uai_toolkit.jsonl import lib_engram          # noqa: E402
from uai_toolkit.jsonl import resume_note         # noqa: E402
from uai_toolkit.jsonl import summarizer as SM    # noqa: E402


def reclaim(jsonl_path, *, need_tokens: int, summarize,
            keep_recent_turns: int = 3, strategy: str = "oldest",
            run_local_llm: bool = True, dry_run: bool = False,
            leaf_uuid: str | None = None) -> dict:
    """Consolidate the oldest evictable turn-ranges to free ~need_tokens.

    `summarize(range_text, candidate) -> str` is the CLAUDE summary callback (the
    live agent spawns a subagent; tests pass a fake). For each selected range we
    run summarizer.shadow_summarize (logs the local-LLM shadow + the Claude one,
    returns the Claude one), then lib_engram.consolidate with that summary.

    Oldest-first is the safe enactment order: each candidate is a later human-turn
    start that remains a valid human-turn start on the active chain after the
    earlier ones collapse (consolidate re-points the successor TO first_uuid).

    Returns {plan, before_tokens, after_tokens, reclaimed_tokens, consolidated[],
             handles[], dry_run, errors[]}.
    """
    jsonl_path = Path(jsonl_path)
    plan = lib_engram.plan_eviction(jsonl_path, need_tokens=need_tokens,
                                    keep_recent_turns=keep_recent_turns,
                                    strategy=strategy, leaf_uuid=leaf_uuid)
    before = lib_engram.chain_size(jsonl_path, leaf_uuid=leaf_uuid)
    before_tokens = int(before.get("content_tokens_estimate", 0))

    consolidated, handles, errors = [], [], []
    for cand in plan["selected"]:
        first_uuid = cand["first_uuid"]
        try:
            rng = SM.extract_turn_range(jsonl_path, first_uuid, leaf_uuid=leaf_uuid)
        except Exception as e:                       # range no longer resolves (chain moved)
            errors.append({"first_uuid": first_uuid, "stage": "extract", "error": str(e)})
            continue
        try:
            claude_summary = summarize(rng["text"], cand)
        except Exception as e:                       # missing summary / subagent failure
            errors.append({"first_uuid": first_uuid, "stage": "summarize", "error": str(e)})
            continue
        used = SM.shadow_summarize(jsonl_path, first_uuid, claude_summary,
                                   leaf_uuid=leaf_uuid, run_local_llm=run_local_llm)
        handle = {"first_uuid": first_uuid, "turn_index": cand["turn_index"],
                  "tokens": cand["tokens"], "summary_preview": _preview(used)}
        if dry_run:
            handle["dry_run"] = True
            handles.append(handle)
            continue
        res = lib_engram.consolidate(jsonl_path, first_uuid, used, leaf_uuid=leaf_uuid)
        if res.get("ok"):
            # consolidate returns the engram METADATA dict directly (engram_id,
            # range_uuids, tokens, …), NOT a transcript record — read the id off it.
            eng = res.get("engram") or {}
            handle["engram_id"] = eng.get("engram_id")
            consolidated.append(handle)
            handles.append(handle)
        else:
            errors.append({"first_uuid": first_uuid, "stage": "consolidate",
                           "error": res.get("error") or res})

    after = lib_engram.chain_size(jsonl_path, leaf_uuid=leaf_uuid)
    after_tokens = int(after.get("content_tokens_estimate", 0))
    return {
        "plan": plan,
        "before_tokens": before_tokens,
        "after_tokens": after_tokens if not dry_run else before_tokens,
        "reclaimed_tokens": max(0, before_tokens - after_tokens) if not dry_run else 0,
        "consolidated": consolidated,
        "handles": handles,
        "errors": errors,
        "dry_run": dry_run,
    }


def _preview(text: str, n: int = 160) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def reclaim_and_stage(jsonl_path, session, *, used_pct: float, need_tokens: int,
                      summarize, next_action: str, keep_recent_turns: int = 3,
                      strategy: str = "oldest", run_local_llm: bool = True,
                      dry_run: bool = False, reason: str = "context_pressure",
                      leaf_uuid: str | None = None) -> dict:
    """Full pre-exit step self_restart.py calls: gate → reclaim.

    1. GATE  — project the reclaim (plan_eviction.total_freed) and run the
       should_bounce conjunction (pressure AND reclaim clears the re-prefill).
       If the gate defers, NOTHING is consolidated — return early so
       self_restart.py can skip the bounce entirely.
    2. RECLAIM — consolidate the planned ranges (skipped under dry_run).

    No note is staged (the resume is invisible and the tail is never consolidated,
    so no next_action reminder is needed). `next_action`/`reason` are accepted for
    call-site compatibility but ignored. `staged` in the result is always None.

    Returns {bounced, gate, reclaim?, staged (always None)}.
    """
    jsonl_path = Path(jsonl_path)
    plan = lib_engram.plan_eviction(jsonl_path, need_tokens=need_tokens,
                                    keep_recent_turns=keep_recent_turns,
                                    strategy=strategy, leaf_uuid=leaf_uuid)
    before_tokens = int(plan.get("chain_tokens_before", 0))
    projected = int(plan.get("total_freed_tokens", 0))
    gate = resume_note.should_bounce(used_pct, projected, before_tokens)
    if not gate["bounce"]:
        return {"bounced": False, "gate": gate, "reclaim": None, "staged": None}

    rec = reclaim(jsonl_path, need_tokens=need_tokens, summarize=summarize,
                  keep_recent_turns=keep_recent_turns, strategy=strategy,
                  run_local_llm=run_local_llm, dry_run=dry_run, leaf_uuid=leaf_uuid)

    return {"bounced": True, "gate": gate, "reclaim": rec, "staged": None}


# ── agent-composable CLI seam (Noctis's preferred shape: plan → enact) ───────
# The live agent's flow, per the bounce playbook:
#   1. `reclaim_and_stage.py plan  <jsonl> --used-pct P --need-tokens N`  (pure python)
#        → JSON {bounce, ranges:[{first_uuid, text}], ...}. If bounce=false, STOP.
#   2. agent spawns ONE subagent per range to write the Claude summary
#        (only the live agent can — see summarizer.py PROCEDURE), collects
#        {first_uuid: summary} into a JSON file.
#   3. `reclaim_and_stage.py enact <jsonl> --session self --summaries S.json`
#        (pure python) → consolidates (trim only; no note staged),
#        prints JSON with `bounced: bool` (the single signal self_restart needs)
#        plus reclaim.before_tokens/after_tokens (the wake-verify yardstick,
#        passed to bounce_watch `verify --expected <after_tokens>`).
#   4. if bounced → run self_restart.py (schedule launchd --resume + /exit).
#
# WHY the gate floor already covers summarization cost (Noctis's flag): the
# summaries are written in SUBAGENT contexts (separate windows), so they cost
# *usage* tokens, not *main-context* tokens — a different currency from the
# main-context re-prefill the reclaim saves. And should_bounce's floor
# (max 40k tokens / 15%) means we never bounce for a small reclaim, so the few
# small summaries that return to main context are always dwarfed by the reclaim.
# No need to fold a token-cost term into the gate; documenting the reasoning here.

def plan_ranges(jsonl_path, *, used_pct: float, need_tokens: int,
                keep_recent_turns: int = 3, strategy: str = "oldest",
                leaf_uuid: str | None = None) -> dict:
    """Step 1: gate + extract the range texts the agent must summarize.
    Returns {bounce, gate, ranges:[{first_uuid, turn_index, tokens, text}],
             before_tokens, projected_freed}. Pure read — never mutates."""
    jsonl_path = Path(jsonl_path)
    plan = lib_engram.plan_eviction(jsonl_path, need_tokens=need_tokens,
                                    keep_recent_turns=keep_recent_turns,
                                    strategy=strategy, leaf_uuid=leaf_uuid)
    before_tokens = int(plan.get("chain_tokens_before", 0))
    projected = int(plan.get("total_freed_tokens", 0))
    gate = resume_note.should_bounce(used_pct, projected, before_tokens)
    ranges = []
    if gate["bounce"]:
        for c in plan["selected"]:
            try:
                rng = SM.extract_turn_range(jsonl_path, c["first_uuid"], leaf_uuid=leaf_uuid)
            except Exception:
                continue
            ranges.append({"first_uuid": c["first_uuid"], "turn_index": c["turn_index"],
                           "tokens": c["tokens"], "text": rng["text"]})
    return {"bounce": gate["bounce"], "gate": gate, "ranges": ranges,
            "before_tokens": before_tokens, "projected_freed": projected}


def enact(jsonl_path, session, summaries: dict, *, next_action: str = "",
          need_tokens: int, keep_recent_turns: int = 3, strategy: str = "oldest",
          run_local_llm: bool = True, reason: str = "context_pressure",
          leaf_uuid: str | None = None) -> dict:
    """Step 3: consolidate (trim only) using the agent-supplied {first_uuid:
    summary} map. `summaries` must cover the same first_uuids the matching plan
    selected (a missing one drops that range to errors[], non-fatal). No note is
    staged; `next_action`/`reason` are accepted for compatibility but ignored, and
    `staged` in the result is always None. Wake-verify reads the yardstick from
    reclaim.after_tokens (pass it to bounce_watch `verify --expected`).
    Returns {bounced, reclaim, staged (always None)}."""
    def _summarize(_text, cand):
        s = summaries.get(cand["first_uuid"])
        if s is None:
            raise KeyError(f"no summary supplied for {cand['first_uuid']}")
        return s
    rec = reclaim(jsonl_path, need_tokens=need_tokens, summarize=_summarize,
                  keep_recent_turns=keep_recent_turns, strategy=strategy,
                  run_local_llm=run_local_llm, leaf_uuid=leaf_uuid)
    return {"bounced": bool(rec["consolidated"]), "reclaim": rec, "staged": None}


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(
        description="Agent-composable reclaim seam: plan → enact. Two summary "
                    "sources: --summaries (Claude-quality, agent-supplied; the "
                    "default posture per PianoMan's 'use Claude's summary') OR "
                    "--summarizer local-llm (headless one-command fallback).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("plan", help="gate + extract range texts to summarize (read-only)")
    pp.add_argument("jsonl")
    pp.add_argument("--used-pct", type=float, required=True)
    pp.add_argument("--need-tokens", type=int, default=60000)
    pp.add_argument("--keep-recent", type=int, default=3)
    pp.add_argument("--strategy", default="oldest", choices=["oldest", "largest"])
    pp.add_argument("--leaf", default=None,
                    help="leaf_uuid: tip of the live chain — REQUIRED on a forked "
                         "transcript so consolidation follows the right branch")

    pe = sub.add_parser("enact", help="consolidate/trim (Claude or LLLM summaries); no note staged")
    pe.add_argument("jsonl")
    pe.add_argument("--session", default="self")
    pe.add_argument("--summaries", help="JSON file {first_uuid: summary} — the Claude-quality "
                                        "path (agent pre-spawned subagents per `plan`)")
    pe.add_argument("--summarizer", choices=["supplied", "local-llm"], default="supplied",
                    help="supplied=use --summaries (default); local-llm=headless fallback "
                         "summaries (loud notice; not Claude-quality)")
    pe.add_argument("--used-pct", type=float, default=None,
                    help="if given, run the should_bounce gate inline before trimming "
                         "(makes local-llm a true one-command gate→trim→stage)")
    pe.add_argument("--need-tokens", type=int, default=60000)
    pe.add_argument("--keep-recent", type=int, default=3)
    pe.add_argument("--strategy", default="oldest", choices=["oldest", "largest"])
    pe.add_argument("--no-local-llm-shadow", action="store_true",
                    help="(supplied path) skip the LLLM shadow A/B log")
    pe.add_argument("--leaf", default=None,
                    help="leaf_uuid: tip of the live chain — REQUIRED on a forked "
                         "transcript so consolidation follows the right branch")

    a = ap.parse_args()
    # --used-pct is PERCENTAGE POINTS (0–100), not a 0–1 fraction. A value in
    # (0, 1] is almost certainly the fraction mistake (e.g. 0.70 meaning 70) and
    # would silently fail the pressure gate (0.70 < 75 → defer) — error loudly.
    if getattr(a, "used_pct", None) is not None and 0 < a.used_pct <= 1.0:
        ap.error(f"--used-pct is in percentage points 0–100, not a fraction; "
                 f"got {a.used_pct} — did you mean {a.used_pct * 100:g}?")
    if a.cmd == "plan":
        out = plan_ranges(a.jsonl, used_pct=a.used_pct, need_tokens=a.need_tokens,
                          keep_recent_turns=a.keep_recent, strategy=a.strategy,
                          leaf_uuid=a.leaf)
    elif a.summarizer == "local-llm":
        # Noctis's headless fallback: LLLM summaries, optional inline gate, one command.
        print("NOTICE: using local-LLM summaries (headless fallback — NOT Claude-quality; "
              "PianoMan's directive is to prefer Claude summaries when an agent is present).",
              file=sys.stderr)
        def _llm_summary(text, _cand):
            r = SM.summarize_via_local_llm(text)
            if not r.get("ok"):
                raise RuntimeError(f"local-llm summarize failed: {r.get('error')}")
            return r["summary"]
        if a.used_pct is not None:
            out = reclaim_and_stage(a.jsonl, a.session, used_pct=a.used_pct,
                                    need_tokens=a.need_tokens, summarize=_llm_summary,
                                    next_action="", keep_recent_turns=a.keep_recent,
                                    strategy=a.strategy, leaf_uuid=a.leaf)
        else:
            rec = reclaim(a.jsonl, need_tokens=a.need_tokens, summarize=_llm_summary,
                          keep_recent_turns=a.keep_recent, strategy=a.strategy,
                          leaf_uuid=a.leaf)
            out = {"bounced": bool(rec["consolidated"]), "reclaim": rec, "staged": None}
    else:
        if not a.summaries:
            ap.error("enact --summarizer supplied requires --summaries (or use --summarizer local-llm)")
        summaries = json.loads(Path(a.summaries).read_text())
        out = enact(a.jsonl, a.session, summaries,
                    need_tokens=a.need_tokens, keep_recent_turns=a.keep_recent,
                    strategy=a.strategy, run_local_llm=not a.no_local_llm_shadow,
                    leaf_uuid=a.leaf)
    print(json.dumps(out, indent=2, default=str))
