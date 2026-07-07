"""Shared metrics for estimating stop+resume token savings.

Combines file-based metrics (live transcript size/msgs, offload archive
size/blocks) with server-reported tokens/ctx% to estimate how many tokens a
stop+resume would shed, and a CAPACITY-based recommendation (hold/worth_it/urgent).
Fixed-rate plan: the decision keys off context-window pressure x sheddable
magnitude — NOT a token->$ cost model (that inverts the answer under caching).

Two producers feed this (see hooks):
  - SessionStart/03_snapshot_offload_metrics_async.py — writes metrics.snapshot
    (the post-resume baseline). File metrics are correct at start; token baseline
    is marked pending and backfilled by the first Stop (the resumed token count
    isn't known until the first turn renders).
  - Stop/04_store_session_data_async.py — writes the current archive.* metrics and
    computes metrics.resume (the estimate).

Model (why deltas, not absolutes): content offloaded BEFORE this session's resume
was already shed at that resume — it's not in current live memory. Only content
offloaded SINCE the snapshot is newly sheddable, so the estimate works off the
growth since the snapshot.
"""
import glob
import json
from pathlib import Path

ARCHIVE_SUFFIX = ".archive"

# Capacity-based bounce decision. This is a FIXED-RATE plan: there is NO token->$
# cost model here — the constraint is context-window CAPACITY, not price. (A dollar
# model actually inverts the answer: caching makes carrying context cheap, so it says
# "don't bounce" exactly when you're near the limit. See the 2026-07-03 rework.)
# Decision = context pressure (used_pct) x magnitude (sheddable). Tunable.
MIN_SHED_TOKENS = 20000   # below this, a bounce isn't worth the interruption
WORTH_USED_PCT = 60       # moderately full -> bounce if the shed is meaningful
WORTH_SHED_PCT = 0.10     # >= 10% of context sheddable counts as "meaningful"
URGENT_USED_PCT = 80      # near the auto-compact zone -> realize any meaningful shed now


def archive_stats(transcript_path):
    """Sum this session's offload archive(s) co-located with the transcript.

    Returns {file_bytes, blocks, orig_bytes}. orig_bytes = sum of manifest
    'bytes' (the on-wire size of content pulled OUT of the transcript) — the
    meaningful 'how much was shed' quantity.
    """
    out = {"file_bytes": 0, "blocks": 0, "orig_bytes": 0}
    try:
        p = Path(transcript_path)
        base, stem = p.parent, p.stem
        for d in base.glob(f"{stem}.*{ARCHIVE_SUFFIX}"):
            if not d.is_dir():
                continue
            for f in d.iterdir():
                try:
                    if f.is_file():
                        out["file_bytes"] += f.stat().st_size
                except OSError:
                    pass
            man = d / "offload_manifest.jsonl"
            if man.exists():
                try:
                    for line in man.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            out["blocks"] += 1
                            out["orig_bytes"] += int(rec.get("bytes", 0))
                        except (json.JSONDecodeError, ValueError, TypeError):
                            pass
                except OSError:
                    pass
    except (OSError, ValueError):
        pass
    return out


def jsonl_line_count(transcript_path):
    """Cheap msg proxy: number of lines in the JSONL."""
    try:
        n = 0
        with open(transcript_path, "rb") as f:
            for _ in f:
                n += 1
        return n
    except OSError:
        return 0


def estimate(snapshot, current, *, used_pct=None):
    """Capacity-based stop+resume recommendation (NO token->$ cost model — fixed-rate
    plan; the constraint is context-window capacity, not price).

    snapshot/current: dicts with jsonl_bytes, archive_orig_bytes, tokens, ctx_pct, ...
    used_pct: context-window fullness 0-100; falls back to current['ctx_pct'].
    Returns dict (sheddable_tokens, sheddable_pct, used_pct, recommend, indicator, ...),
    or None if there isn't enough data yet (no token baseline).

    recommend ∈ {hold, worth_it, urgent}; indicator maps it to a display color:
      hold -> green, worth_it -> blue, urgent -> red. Bounce iff worth_it/urgent.
    """
    if not snapshot or not current:
        return None
    tok_cur = int(current.get("tokens", 0) or 0)
    tok_snap = snapshot.get("tokens")
    if tok_cur <= 0 or tok_snap is None:
        return None
    tok_snap = int(tok_snap)

    if used_pct is None:
        used_pct = current.get("ctx_pct")
    try:
        used_pct = float(used_pct)
    except (TypeError, ValueError):
        used_pct = None

    jsonl_delta = int(current.get("jsonl_bytes", 0)) - int(snapshot.get("jsonl_bytes", 0))
    arch_delta = int(current.get("archive_orig_bytes", 0)) - int(snapshot.get("archive_orig_bytes", 0))
    denom = arch_delta + jsonl_delta
    arch_ratio = (arch_delta / denom) if denom > 0 else 0.0

    tok_growth = max(0, tok_cur - tok_snap)
    sheddable = int(tok_growth * arch_ratio)            # context tokens a resume would drop
    resumed_tokens = max(0, tok_cur - sheddable)
    sheddable_pct = (sheddable / tok_cur) if tok_cur else 0.0

    # Decision on CAPACITY, not cost: bounce when a resume meaningfully relieves
    # context pressure — enough to shed to matter, AND either near the auto-compact
    # zone (urgent) or moderately full with a meaningful shed (worth_it). Dollars
    # never enter it (see the constants block).
    if sheddable < MIN_SHED_TOKENS:
        recommend = "hold"
    elif used_pct is not None and used_pct >= URGENT_USED_PCT:
        recommend = "urgent"
    elif used_pct is not None and used_pct >= WORTH_USED_PCT and sheddable_pct >= WORTH_SHED_PCT:
        recommend = "worth_it"
    else:
        recommend = "hold"
    indicator = {"urgent": "red", "worth_it": "blue", "hold": "green"}[recommend]

    return {
        "sheddable_tokens": sheddable,
        "sheddable_pct": round(sheddable_pct, 3),
        "resumed_tokens": resumed_tokens,
        "token_growth": tok_growth,
        "archive_ratio": round(arch_ratio, 3),
        "used_pct": used_pct,
        "recommend": recommend,
        "indicator": indicator,
    }
