#!/usr/bin/env python3
"""Resume-note writer, reclaim projection, CAS validation, and wake-time verify.

Broken-Clock's half of the session-bounce (self-Stop & Resume) design — see
ai_general/research_and_reports/anthropic_memory_and_context/DESIGN_session_bounce_self_stop_resume.md
(Noctis owns the bouncer + that spec; this module owns the resume-note contract,
reclaim projection, the pre-kill CAS validator, and the wake-time verify step).

Hardened per Codex review (2026-06-23): the note carries CAS hashes + identity +
lifecycle so the bouncer's kill/rollback is compare-and-swap protected, never a
blind restore that could clobber records written after the snapshot (BLOCKER 1).

Yardstick note: the reclaim/verify metric is lib_engram.chain_size's
content_tokens_estimate — computable identically BEFORE the bounce and AFTER the
resume. It's a deterministic CONTRACT metric, NOT the true prefill/cache cost
(cache_creation_input_tokens is relaunch-only; /context buckets differently).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from uai_toolkit.jsonl import lib_engram

# Flat note fields, in emit order. (in_flight is a list-of-dicts; see below.)
RESUME_NOTE_FIELDS = (
    # identity / lifecycle
    "bounce_id", "session", "tracking_id", "cli_uuid", "terminal_session",
    "session_dir", "substrate", "substrate_context", "launcher_path",
    "reason", "armed_at", "stopped_at", "expires_at",
    "model", "model_fallback_policy", "cwd",
    # CAS transcript state (the BLOCKER-1 fix)
    "jsonl_path",
    "pre_trim_sha256", "pre_trim_size", "pre_trim_mtime_ns",
    "post_trim_sha256", "post_trim_size", "post_trim_mtime_ns",
    "expected_leaf_uuid",
    "pre_bounce_backup", "pre_bounce_backup_sha256", "trim_operation_id",
    # wake semantics
    "next_action", "resume_prompt",
    "context_before_tokens", "projected_reclaim_tokens", "expected_chain_tokens",
    "gate_policy_version", "rollback_policy", "state_path",
    "in_flight", "rehydrate_handles", "verify_on_wake",
    "wake_at", "wake_on",
)
VALID_REASONS = ("context-reclaim", "timed", "event", "blocked")
VALID_MODEL_FALLBACK = ("none", "same-family", "configured-default")
GATE_POLICY_VERSION = "1"
DEFAULT_TTL_SECONDS = 3600          # expired note = fail-closed (Codex MAJOR 4)

# Cost-gate defaults (calibrate against DESIGN §8.5).
GATE_MIN_USED_PCT = 75.0
GATE_MIN_RECLAIM_TOKENS = 40_000
GATE_MIN_RECLAIM_FRAC = 0.15

# Wake-verify allowance: the resumed chain carries the <<<SESSION RESUMED>>> marker
# + injected continuation note + harness deferred-tool/skill catalog + first turn,
# on top of the trimmed base. Measured ~7–9k in-situ (2026-06-24); 10k default band.
DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000


# ── transcript state (CAS) ──────────────────────────────────────────────────
def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chain_tokens(jsonl_path, *, leaf_uuid: str | None = None,
                  leaf_policy: str = "conversational") -> int:
    return int(lib_engram.chain_size(
        jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy
    ).get("content_tokens_estimate", 0))


def capture_jsonl_state(path, *, leaf_uuid: str | None = None,
                        leaf_policy: str = "conversational") -> dict:
    """CAS fingerprint of a transcript: sha256 + size + mtime_ns + active leaf.

    The leaf is lib_engram.chain_size's selected leaf_uuid — the live tip the
    bouncer must see unchanged before it kills/restores.

    HIGH 3: pass an explicit `leaf_uuid` (+ `leaf_policy`) to fingerprint the
    SAME fork branch a fork-aware reclaim trimmed. With no leaf the default
    conversational leaf is used, which on a forked transcript may be a
    DIFFERENT branch than the one that was trimmed.
    """
    path = str(path)
    st = os.stat(path)
    cs = lib_engram.chain_size(path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
    return {
        "jsonl_path": path,
        "sha256": _sha256_file(path),
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "leaf_uuid": cs.get("leaf_uuid"),
        "chain_tokens": int(cs.get("content_tokens_estimate", 0)),
    }


# ── reclaim projection + cost gate ──────────────────────────────────────────
def project_reclaim(pre_trim_path, post_trim_path) -> dict:
    """Projected context reclaim from a trim, at ARM time (the session has both)."""
    before = _chain_tokens(pre_trim_path)
    after = _chain_tokens(post_trim_path)
    return {"before_tokens": before, "after_tokens": after,
            "reclaim_tokens": max(0, before - after)}


def should_bounce(used_pct: float, reclaim_tokens: int, before_tokens: int, *,
                  min_used_pct: float = GATE_MIN_USED_PCT,
                  min_reclaim_tokens: int = GATE_MIN_RECLAIM_TOKENS,
                  min_reclaim_frac: float = GATE_MIN_RECLAIM_FRAC) -> dict:
    """DESIGN §5 cost gate — CONJUNCTION: bounce only when under pressure AND the
    reclaim earns the full KV re-prefill. Big reclaim + low pressure ⇒ defer."""
    pressure = used_pct >= min_used_pct
    reclaim_floor = max(min_reclaim_tokens, int(min_reclaim_frac * max(1, before_tokens)))
    reclaim_ok = reclaim_tokens >= reclaim_floor
    bounce = pressure and reclaim_ok
    if bounce:
        reason = "pressure high and reclaim clears the re-prefill"
    elif not pressure:
        reason = f"defer: not under pressure ({used_pct:.0f}% < {min_used_pct:.0f}%)"
    else:
        reason = f"defer: reclaim {reclaim_tokens:,} < floor {reclaim_floor:,}"
    return {"bounce": bounce, "pressure": pressure, "reclaim_ok": reclaim_ok,
            "reclaim_floor": reclaim_floor, "gate_policy_version": GATE_POLICY_VERSION,
            "reason": reason}


# ── in_flight safety (Codex MINOR 1) ────────────────────────────────────────
def _normalize_inflight(in_flight) -> list:
    """Accept structured entries; coerce a bare string to a fail-closed entry."""
    out = []
    for e in (in_flight or []):
        if isinstance(e, str):
            out.append({"action": e, "external_side_effect": True,
                        "persisted": False, "safe_to_retry": False,
                        "verification": "unspecified (coerced from free text)"})
        elif isinstance(e, dict):
            out.append({
                "action": e.get("action", ""),
                "external_side_effect": bool(e.get("external_side_effect", False)),
                "persisted": bool(e.get("persisted", False)),
                "safe_to_retry": bool(e.get("safe_to_retry", False)),
                "verification": e.get("verification", ""),
            })
    return out


def inflight_blocks_bounce(note: dict) -> list:
    """Return the in_flight entries that FAIL CLOSED (external side effect not
    marked safe_to_retry). Non-empty ⇒ the bounce must abort."""
    return [e for e in (note.get("in_flight") or [])
            if e.get("external_side_effect") and not e.get("safe_to_retry")]


# ── note writer ─────────────────────────────────────────────────────────────
def write_resume_note(path, *, session: str, reason: str, model: str, cwd: str,
                      backup_path, live_jsonl_path,
                      next_action: str, resume_prompt: str,
                      context_before_tokens: int, projected_reclaim_tokens: int,
                      expected_chain_tokens: int,
                      tracking_id: str | None = None, cli_uuid: str | None = None,
                      terminal_session: str | None = None, session_dir: str | None = None,
                      substrate: str | None = None, substrate_context: str | None = None,
                      launcher_path: str | None = None,
                      model_fallback_policy: str = "none",
                      trim_operation_id: str | None = None,
                      in_flight=None, rehydrate_handles: list | None = None,
                      verify_on_wake: bool = True, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                      rollback_policy: str = "cas-restore-or-alert",
                      state_path: str | None = None, wake_at: str | None = None,
                      wake_on: str | None = None, bounce_id: str | None = None,
                      armed_at: str | None = None, stopped_at: str | None = None) -> dict:
    """Emit the hardened resume-note (YAML). Computes the CAS fingerprints of the
    pre-trim backup and the post-trim live transcript itself, so the caller just
    passes the two paths. Returns the note dict (also written to PATH)."""
    if reason not in VALID_REASONS:
        raise ValueError(f"reason must be one of {VALID_REASONS}, got {reason!r}")
    if model_fallback_policy not in VALID_MODEL_FALLBACK:
        raise ValueError(f"model_fallback_policy must be one of {VALID_MODEL_FALLBACK}")

    pre = capture_jsonl_state(backup_path)        # pre-trim snapshot
    post = capture_jsonl_state(live_jsonl_path)   # post-trim live transcript
    armed = armed_at or datetime.now().isoformat(timespec="seconds")
    expires = (datetime.fromisoformat(armed) + timedelta(seconds=ttl_seconds)
               ).isoformat(timespec="seconds")

    note = {
        "bounce_id": bounce_id or uuid.uuid4().hex[:12],
        "session": session,
        "tracking_id": tracking_id or session,
        "cli_uuid": cli_uuid,
        "terminal_session": terminal_session,
        "session_dir": session_dir,
        "substrate": substrate,
        "substrate_context": substrate_context,
        "launcher_path": launcher_path,
        "reason": reason,
        "armed_at": armed,
        "stopped_at": stopped_at or armed,
        "expires_at": expires,
        "model": model,
        "model_fallback_policy": model_fallback_policy,
        "cwd": cwd,
        "jsonl_path": post["jsonl_path"],
        "pre_trim_sha256": pre["sha256"],
        "pre_trim_size": pre["size"],
        "pre_trim_mtime_ns": pre["mtime_ns"],
        "post_trim_sha256": post["sha256"],
        "post_trim_size": post["size"],
        "post_trim_mtime_ns": post["mtime_ns"],
        "expected_leaf_uuid": post["leaf_uuid"],
        "pre_bounce_backup": str(backup_path),
        "pre_bounce_backup_sha256": pre["sha256"],
        "trim_operation_id": trim_operation_id,
        "next_action": next_action,
        "resume_prompt": resume_prompt,
        "context_before_tokens": int(context_before_tokens),
        "projected_reclaim_tokens": int(projected_reclaim_tokens),
        "expected_chain_tokens": int(expected_chain_tokens),
        "gate_policy_version": GATE_POLICY_VERSION,
        "rollback_policy": rollback_policy,
        "state_path": state_path,
        "in_flight": _normalize_inflight(in_flight),
        "rehydrate_handles": list(rehydrate_handles or []),
        "verify_on_wake": bool(verify_on_wake),
    }
    if wake_at:
        note["wake_at"] = wake_at
    if wake_on:
        note["wake_on"] = wake_on
    Path(path).write_text(_dump_yaml(note), encoding="utf-8")
    return note


def _dump_yaml(note: dict) -> str:
    """Emit in RESUME_NOTE_FIELDS order. Prefer PyYAML; else a small emitter."""
    ordered = {k: note[k] for k in RESUME_NOTE_FIELDS if k in note}
    try:
        import yaml
        return yaml.safe_dump(ordered, sort_keys=False, default_flow_style=False,
                              allow_unicode=True)
    except Exception:
        return _flat_yaml(ordered)


def _flat_yaml(d: dict) -> str:
    def scalar(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        s = str(v)
        if s == "" or any(ch in s for ch in ':#\n"') or s.strip() != s:
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        return s
    lines = []
    for k, v in d.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            elif all(isinstance(x, dict) for x in v):
                lines.append(f"{k}:")
                for x in v:
                    first = True
                    for kk, vv in x.items():
                        prefix = "  - " if first else "    "
                        lines.append(f"{prefix}{kk}: {scalar(vv)}")
                        first = False
            else:
                lines.append(f"{k}:")
                lines.extend(f"  - {scalar(x)}" for x in v)
        else:
            lines.append(f"{k}: {scalar(v)}")
    return "\n".join(lines) + "\n"


def _load_note(path) -> dict:
    """Read a resume-note (PyYAML preferred; flat fallback for simple notes)."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except Exception:
        out, cur_list_key = {}, None
        for raw in text.splitlines():
            if not raw.strip():
                continue
            if raw.startswith("  - ") and cur_list_key:
                out[cur_list_key].append(raw[4:].strip().strip('"'))
                continue
            cur_list_key = None
            if ":" not in raw:
                continue
            k, _, v = raw.partition(":")
            k, v = k.strip(), v.strip()
            if v == "":
                out[k] = []
                cur_list_key = k
            elif v == "[]":
                out[k] = []
            elif v in ("true", "false"):
                out[k] = (v == "true")
            elif v.lstrip("-").isdigit():
                out[k] = int(v)
            else:
                out[k] = v.strip('"')
        return out


# ── lifecycle + pre-kill CAS validation (the bouncer reuses these) ───────────
def is_expired(note: dict, now: datetime | None = None) -> bool:
    exp = note.get("expires_at")
    if not exp:
        return False
    try:
        return (now or datetime.now()) > datetime.fromisoformat(exp)
    except ValueError:
        return True       # unparseable expiry ⇒ fail closed


def validate_pre_kill(note: dict, live_jsonl_path) -> dict:
    """CAS check the bouncer MUST pass before kill AND before restore (BLOCKER 1).

    Confirms the live transcript is exactly the post-trim file the note describes,
    the active leaf matches, the note hasn't expired, and no unsafe in-flight side
    effect is pending. Any False ⇒ do NOT kill/restore (abort or escalate).
    """
    st = capture_jsonl_state(live_jsonl_path)
    blockers = inflight_blocks_bounce(note)
    checks = {
        "hash_match": st["sha256"] == note.get("post_trim_sha256"),
        "size_match": st["size"] == note.get("post_trim_size"),
        "leaf_match": st["leaf_uuid"] == note.get("expected_leaf_uuid"),
        "not_expired": not is_expired(note),
        "inflight_safe": not blockers,
    }
    ok = all(checks.values())
    reasons = [k for k, v in checks.items() if not v]
    return {"ok": ok, "checks": checks, "failed": reasons,
            "inflight_blockers": blockers, "live_state": st}


def matches_backup(note: dict) -> dict:
    """Confirm the pre_bounce_backup file is intact (its hash matches the note)
    before it is ever used as a restore source."""
    bk = note.get("pre_bounce_backup")
    if not bk or not os.path.exists(bk):
        return {"ok": False, "reason": "backup missing"}
    actual = _sha256_file(bk)
    ok = actual == note.get("pre_bounce_backup_sha256")
    return {"ok": ok, "reason": "" if ok else "backup sha256 mismatch",
            "actual": actual, "expected": note.get("pre_bounce_backup_sha256")}


def verify_on_wake(note_path, jsonl_path, *, tolerance_frac: float = 0.05,
                   tolerance_floor: int = 2000,
                   resume_overhead_tokens: int = DEFAULT_RESUME_OVERHEAD_TOKENS) -> dict:
    """Wake-time self-verify: did the reclaim actually take? (tolerance per
    Codex MAJOR 5: max(2000, 5%).)

    expected_chain_tokens in the note is the PRE-resume post-trim base. The resumed
    chain is ALWAYS expected + resume_overhead — the <<<SESSION RESUMED>>> marker,
    the injected continuation note, the harness's deferred-tool/skill catalog, and
    the first turn's work all land on top of the trimmed base (validated in-situ
    2026-06-24: ~7–9k overhead → a strict tol gives a FALSE took=False). So allow a
    resume_overhead_tokens band above expected; set it to 0 to recover the strict
    pre-resume check. The unambiguous reclaim yardstick is baseline→post-trim, not
    baseline→resumed — see [[project_session_bounce_validated]]."""
    note = _load_note(note_path)
    expected = int(note.get("expected_chain_tokens", 0))
    actual = _chain_tokens(jsonl_path)
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
        "rehydrate_handles": [] if took else list(note.get("rehydrate_handles", [])),
        "advice": ("continue" if took
                   else "reclaim did not take as expected — recheck trim / rehydrate handles"),
    }


_USAGE = """\
resume_note.py — reclaim projection + resume-note contract for the Bounce lever

WHAT IT DOES
  Broken-Clock's half of the session-bounce (self-Stop & Resume) design. A Bounce is a
  self-induced stop->resume of the SAME session/transcript — INVISIBLE to the model
  (the same thread continues), whose ONLY job is to REALIZE on-disk reclaim, because an
  Offload/Summarize page-out takes effect only on --resume. This module owns the pieces
  around that bounce: the resume-note contract, the reclaim PROJECTION, the pre-kill
  compare-and-swap (CAS) validator, and the wake-time verify step.

  Run directly, it is the reclaim PROJECTOR: it diffs a PRE-trim transcript against a
  POST-trim transcript and reports how many context tokens the trim/offload would shed
  once the session resumes on the lighter chain. It prints project_reclaim() as JSON:
  before_tokens, after_tokens, and reclaim_tokens (= max(0, before - after)). It reads
  both files read-only and writes NOTHING.

  The yardstick is lib_engram.chain_size's content_tokens_estimate — a deterministic
  CONTRACT metric computable identically before the bounce and after the resume. It is
  NOT the true prefill/KV-cache cost (that's relaunch-only and bucketed differently).

USAGE
  resume_note.py <pre_trim.jsonl> <post_trim.jsonl>
  resume_note.py -h | --help

POSITIONAL ARGS
  <pre_trim.jsonl>    the transcript BEFORE the trim/offload — i.e. the pre-bounce
                      backup snapshot (the heavier chain). Both files exist at ARM time.
  <post_trim.jsonl>   the transcript AFTER the trim/offload — the lighter chain the
                      session will reload on resume. reclaim = pre_tokens - post_tokens.

EXAMPLES
  # Show rich help:
  resume_note.py --help

  # Project how much context a trim would reclaim on resume (backup vs live post-trim):
  resume_note.py ~/.claude/projects/foo/SESSION.jsonl.bak \\
                 ~/.claude/projects/foo/SESSION.jsonl
  # -> {"before_tokens": 128340, "after_tokens": 74102, "reclaim_tokens": 54238}

CAVEATS
  * Token counts are content_tokens_estimate — a deterministic CONTRACT yardstick, NOT
    the real prefill/cache cost. Use it to COMPARE before vs after, not to bill tokens.
  * reclaim_tokens floors at 0: if the "post" file is not actually lighter you get 0,
    never a negative number.
  * This CLI only PROJECTS. The bounce itself (kill/resume) is Noctis's bouncer; the
    cost gate (should_bounce), CAS validation (validate_pre_kill / matches_backup),
    and wake verify (verify_on_wake) are library functions here, not CLI subcommands.
  * The gate is a CONJUNCTION (DESIGN §5): bounce only when under pressure AND the
    reclaim clears the KV re-prefill — a big reclaim at low pressure defers.
  * A resume note fails CLOSED: an expired/unparseable note or an unsafe in-flight side
    effect blocks the bounce rather than risking a blind restore.
"""

if __name__ == "__main__":
    import sys
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print(_USAGE)
        raise SystemExit(0)
    if len(sys.argv) >= 3:
        print(json.dumps(project_reclaim(sys.argv[1], sys.argv[2]), indent=2))
    else:
        print("usage: resume_note.py <pre_trim.jsonl> <post_trim.jsonl>")
