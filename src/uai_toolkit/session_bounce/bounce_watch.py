#!/usr/bin/env python3
"""bounce_watch.py — observer side of a live self-bounce (BC's watch role).

Pairs with reclaim_and_stage.py + self_restart.py. While the test-subject session
runs plan→summarize→enact (trim) → self_restart (launchd --resume + /exit), this
gives the WATCHER (a different session) three read-only checks:

  snapshot <jsonl>            → pre-trim baseline: sha256 + size + leaf + chain_tokens
  verify   <jsonl> --expected → did the reclaim take? compares the resumed
                                transcript's live chain_tokens to the expected
                                post-trim tokens (tolerance max(2000, 5%) + a
                                resume-overhead band).
  delta    <pre.json> <jsonl> → before→after chain_tokens drop (pre snapshot vs live)

The no-kill architecture stages NO continuation note. `verify` therefore REQUIRES
the expected post-trim chain tokens to be passed in via `--expected` — sourced from
the enact/reclaim return JSON (reclaim.after_tokens). There is no note to read.

--tid <tracking_id> resolves a session's jsonl_path for you.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_JSONL = _HERE.parents[1] / "jsonl"
_SMGMT = _HERE.parents[1] / "session_mgmt"
for _p in (_JSONL, _SMGMT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from uai_toolkit.jsonl import lib_engram          # noqa: E402
from uai_toolkit.jsonl import resume_note         # noqa: E402


def snapshot(jsonl_path, *, leaf_uuid=None,
             leaf_policy: str = "conversational") -> dict:
    """Pre-trim baseline (reuses resume_note's CAS fingerprint).

    HIGH 3: thread an explicit `leaf_uuid` (+ `leaf_policy`) so the baseline
    measures the SAME fork branch a fork-aware reclaim trims — on a forked
    transcript the default leaf may be a different branch entirely.
    """
    return resume_note.capture_jsonl_state(
        jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)


DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000


def verify(jsonl_path, *, expected_tokens=None, before_tokens=None,
           resume_overhead_tokens: int = DEFAULT_RESUME_OVERHEAD_TOKENS,
           tolerance_frac: float = 0.05, tolerance_floor: int = 2000,
           leaf_uuid=None, leaf_policy: str = "conversational") -> dict:
    """Wake-verify: is the resumed transcript's live chain_tokens within the
    expected post-trim base + resume overhead?

    `expected_tokens` is REQUIRED (no note is staged to read it from) — pass it from
    the enact/reclaim return JSON (reclaim.after_tokens). If None, returns a clear
    error telling the caller to pass --expected.
    FINDING 2 (resume overhead): the resumed chain = expected + marker + harness
    tool catalog + first turn (~7–9k). Allow resume_overhead_tokens above expected;
    set 0 for the strict pre-resume check. See [[project_session_bounce_validated]]."""
    if expected_tokens is None:
        return {"error": "expected_tokens is required (no note is staged) — "
                "pass --expected <reclaim.after_tokens from the enact JSON>"}
    expected = int(expected_tokens or 0)
    actual = int(lib_engram.chain_size(
        jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy
    ).get("content_tokens_estimate", 0))
    tol = max(tolerance_floor, int(tolerance_frac * max(1, expected)))
    allowance = expected + resume_overhead_tokens + tol
    took = actual <= allowance
    return {
        "took": took,
        "expected_chain_tokens": expected,
        "actual_chain_tokens": actual,
        "delta": actual - expected,
        "tolerance": tol,
        "resume_overhead_tokens": resume_overhead_tokens,
        "allowance": allowance,
        "before_tokens": before_tokens,
        "reclaimed_vs_before": (before_tokens - actual) if before_tokens else None,
        "leaf_uuid": leaf_uuid,
        "advice": "continue" if took
        else "reclaim did NOT take — resumed chain exceeds expected + resume overhead; "
             "recheck trim / rehydrate handles",
    }


def delta(pre_snapshot_path, jsonl_path, *, leaf_uuid=None,
          leaf_policy: str = "conversational") -> dict:
    """before→after chain_tokens drop: a saved pre-trim snapshot vs the live transcript.

    HIGH 3: measure the live side on the same fork branch the snapshot captured.
    If `leaf_uuid` is omitted it defaults to the leaf recorded in the snapshot,
    so before/after stay branch-equivalent on forked transcripts.
    """
    pre = json.loads(Path(pre_snapshot_path).read_text())
    before = int(pre.get("chain_tokens", 0))
    if leaf_uuid is None:
        leaf_uuid = pre.get("leaf_uuid")
    cs = lib_engram.chain_size(jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
    after = int(cs.get("content_tokens_estimate", 0))
    return {"before_tokens": before, "after_tokens": after,
            "reclaimed_tokens": before - after,
            "leaf_uuid": cs.get("leaf_uuid"),
            "leaf_changed": pre.get("leaf_uuid") != cs.get("leaf_uuid")}


def _resolve_tid(tid):
    """Resolve a tracking_id → jsonl_path (or None). Best-effort."""
    from uai_toolkit.session_mgmt.session_store import SessionStore
    sess = SessionStore().resolve(tid)
    if not sess:
        return None
    # Claude transcript path from cli_uuid under the project dir.
    jsonl = None
    cli = sess.get("cli_uuid") or sess.get("cli_session_id")
    if cli:
        proj = Path.home() / ".claude" / "projects" / "-Users-shawnhillis-AI-ai-root"
        cand = proj / f"{cli}.jsonl"
        jsonl = str(cand) if cand.exists() else None
    return jsonl


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Watch a live self-bounce (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("snapshot", "verify", "delta"):
        sp = sub.add_parser(name)
        sp.add_argument("args", nargs="*")
        sp.add_argument("--tid", help="resolve jsonl from a tracking_id")
        sp.add_argument("--expected", type=int, default=None,
                        help="(verify) expected post-trim chain tokens from the enact JSON "
                             "(reclaim.after_tokens) — REQUIRED for verify")
        sp.add_argument("--resume-overhead", type=int, default=DEFAULT_RESUME_OVERHEAD_TOKENS,
                        help="(verify) token band above expected for the resume's own overhead")
        sp.add_argument("--leaf", default=None, metavar="UUID",
                        help="explicit fork leaf uuid — measure the SAME branch "
                             "the reclaim trimmed (disambiguates forks)")
        sp.add_argument("--leaf-policy", choices=("conversational", "raw"),
                        default="conversational",
                        help="leaf selection policy when --leaf is omitted")
    a = ap.parse_args()

    jsonl = None
    if a.tid:
        jsonl = _resolve_tid(a.tid)

    if a.cmd == "snapshot":
        jsonl = jsonl or (a.args[0] if a.args else None)
        print(json.dumps(snapshot(jsonl, leaf_uuid=a.leaf,
                                  leaf_policy=a.leaf_policy), indent=2))
    elif a.cmd == "verify":
        jsonl = jsonl or (a.args[0] if a.args else None)
        print(json.dumps(verify(jsonl, expected_tokens=a.expected,
                                resume_overhead_tokens=a.resume_overhead,
                                leaf_uuid=a.leaf, leaf_policy=a.leaf_policy), indent=2))
    elif a.cmd == "delta":
        pre = a.args[0]
        jsonl = jsonl or (a.args[1] if len(a.args) > 1 else None)
        print(json.dumps(delta(pre, jsonl, leaf_uuid=a.leaf,
                               leaf_policy=a.leaf_policy), indent=2))
