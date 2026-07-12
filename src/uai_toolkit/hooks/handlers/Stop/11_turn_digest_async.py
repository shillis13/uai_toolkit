#!/usr/bin/env python3
"""STAGED (not yet live) Stop hook — write the just-closed turn's digest.

Activate (FLEET-WIDE — every session — requires PianoMan's explicit go):
    install -m 755 ai_general/scripts/jsonl/turn_digest_stop_hook.py \
        ai_general/data/hooks/Stop/11_turn_digest_async.py
  IMPORTANT: dispatch.py IGNORES non-executable handlers (os.access X_OK) — a plain `cp` of a
  mode-644 file would create a live hook that SILENTLY never runs (Codex review, blocker 1).
  This file is committed mode 755, so `cp -p` preserves it, but `install -m 755` is explicit.

Placement note: this file lives in scripts/jsonl/ ON PURPOSE — dispatch.py only runs
top-level .py/.sh files inside an EVENT dir (hooks/Stop/…), so sitting here it CANNOT
fire. It becomes live only when copied into hooks/Stop/ under an `NN_..._async.py` name.

Behavior once live:
  * Runs `turn_digest.py --session <transcript> --turns all` for the session that just
    stopped — a CATCH-UP: it (re)digests every un-digested turn into <uuid>/int##_br##.yml,
    so gaps a 'last'-only run would miss (a turn whose Stop was skipped) get backfilled.
  * DE-BOUNCE: a non-blocking per-transcript lock — if a digest run is already in progress
    (a catch-up can span the endpoint calls), this Stop skips rather than double the work;
    the next successful run catches up the skipped turns.
  * `_async` => dispatch backgrounds it: the model turn NEVER waits on the digest (or its
    endpoint), even if the endpoint is the local LLM.
  * Endpoint policy lives in turn_digest (DEFAULT_ENDPOINT = $TURN_DIGEST_ENDPOINT, else the
    fleet default chain `llm,claude,extractive`): local LLM every turn, a cheap headless Claude
    (`claudeCli --print`) only when the local LLM is DOWN, extractive only if both are. So the
    per-turn cost is normally just the local LLM; claude/extractive are fallbacks, not per-turn.
  * Idempotent: turn_digest SKIPS turns already digested, so re-firing is harmless.
  * Best-effort: any failure is logged via HookResult.error and never blocks/errors the turn.
  * CANARY ALLOW-LIST: the hook fires for every session (dispatch runs it fleet-wide) but
    immediately NO-OPS for any session whose tracking_id is not in turn_digest_allowlist.yml.
    Default-off rollout — a missing/empty allow-list means NOBODY digests; add '*' to enable
    for ALL sessions. Grow the list as confidence grows.
"""
import fcntl
import os
import subprocess
import sys
from pathlib import Path

# AI_ROOT-absolute so the import resolves the SAME whether this file sits in scripts/jsonl/
# (staged) or in data/hooks/Stop/ (live) — do NOT use a __file__-relative path here.
AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
sys.path.insert(0, str(AI_ROOT / "ai_general" / "data" / "hooks" / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult  # noqa: E402

TURN_DIGEST = AI_ROOT / "ai_general" / "scripts" / "jsonl" / "turn_digest.py"
# Canary allow-list — a stable path (NOT relative to this file's location) so it's read the
# same whether the hook is staged or live. Edit it to enroll/remove sessions; '*' = all.
ALLOWLIST = AI_ROOT / "ai_general" / "data" / "hooks" / "Stop" / "turn_digest_allowlist.yml"
PYTHON = os.environ.get("AI_PYTHON") or sys.executable  # was hardcoded /opt/homebrew/bin/python3 (WSL fix)


def _allowed(tracking_id):
    """Canary gate: only sessions in ALLOWLIST run the digest. Missing/empty/unreadable list =>
    NOBODY (fail-safe off); a list containing '*' => everybody."""
    try:
        import yaml
        data = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) if ALLOWLIST.exists() else None
    except Exception:
        return False
    ids = [str(x).strip() for x in data] if isinstance(data, list) else []
    return "*" in ids or (bool(tracking_id) and tracking_id in ids)


def handler(hook_input, context):
    if not TURN_DIGEST.exists():
        return HookResult.error(f"turn_digest not found: {TURN_DIGEST}")
    # Canary gate FIRST — cheap check, no-op for non-enrolled sessions (default-off rollout).
    if not _allowed(getattr(context, "tracking_id", None)):
        return HookResult.skip("session not in turn_digest allow-list")
    # Prefer the explicit transcript path the hook provides; fall back to the CLI session id
    # (turn_digest --session accepts an ID | 'self' | PATH).
    transcript = hook_input.get("transcript_path", "") or os.environ.get("AI_CLI_SESSION_ID", "")
    if not transcript:
        return HookResult.error("no transcript_path / AI_CLI_SESSION_ID")
    # DE-BOUNCE: at most one digest run per transcript at a time. We use `--turns all` — a
    # CATCH-UP that (re)digests every UN-digested turn, so it backfills internal gaps a 'last'-only
    # run structurally misses (e.g. a turn whose Stop was skipped while an earlier async run was
    # mid-endpoint). But a catch-up run can span the endpoint calls, so two Stops firing close
    # together must NOT both run and double the endpoint work. A NON-BLOCKING per-transcript lock:
    # if a run is already in progress, skip — the next successful run catches up the skipped turns.
    lock_path = Path(str(transcript) + ".digestrun.lock")
    try:
        lf = open(lock_path, "w")
    except OSError:
        lf = None
    if lf is not None:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            lf.close()
            return HookResult.skip("digest run already in progress — de-bounced")
    # No --endpoint here: turn_digest uses its own DEFAULT_ENDPOINT ($TURN_DIGEST_ENDPOINT, else
    # the fleet default chain llm,claude,extractive). Wrapper timeout is kept WELL ABOVE the
    # worst-case chain so it never kills the parent mid-endpoint and orphans a child (Codex b3).
    try:
        try:
            r = subprocess.run(
                [PYTHON, str(TURN_DIGEST), "--session", str(transcript), "--turns", "all"],
                capture_output=True, text=True, timeout=300,
            )
        except Exception as e:  # pragma: no cover - infra-dependent
            return HookResult.error(f"{type(e).__name__}: {e}")
    finally:
        if lf is not None:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            finally:
                lf.close()
    if r.returncode == 0:
        return HookResult.allow("digested (catch-up: all un-digested turns)")
    return HookResult.error(f"turn_digest rc={r.returncode}: {(r.stderr or '').strip()[:160]}")


if __name__ == "__main__":
    sys.exit(run_hook("turn_digest", "Stop", handler))
