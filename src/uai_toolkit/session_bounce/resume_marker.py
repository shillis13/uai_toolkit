#!/usr/bin/env python3
"""Passive resume marker — the inert record a Bounce leaves in the transcript.

Design (PianoMan, 2026-07-04): a resumed session lands IDLE and stays idle until the
first real prompt — re-activation was only ever for an instant token/context readout,
which can wait. So instead of the old send_raw/positional prompt that WOKE the session,
a Bounce appends a PASSIVE `isMeta:true` user record. It persists in the JSONL (so the
model sees "I was resumed" on its next real turn, and tooling can grep the boundary) but,
being isMeta, it is NOT a turn Claude Code responds to and NOT read as an instruction —
so it can't make the session run off and continue work (the pre-/self-compact hazard).

Load-bearing runtime premise (MUST be validated on a session launched for the test before
this replaces the live launcher path): a trailing isMeta record leaves CC idle on resume.

Record shape mirrors a real CC isMeta user record (envelope fields cloned from the
transcript's tail for max version-compatibility); stdlib-only so it unit-tests in isolation.
"""
import json
import os
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path


def _read_tail_record(jsonl_path):
    """Return the last dict record bearing a uuid (the leaf to chain onto), or None."""
    last = None
    with open(jsonl_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and r.get("uuid"):
                last = r
    return last


def build_marker_record(leaf, *, cli_uuid=None, tracking_id=None, platform=None, cwd=None):
    """Build a passive isMeta resume-marker record chained onto `leaf`.

    Envelope fields (version/gitBranch/cwd/userType/entrypoint/sessionId) are cloned from
    `leaf` when present so the record matches whatever CC version wrote the file.
    """
    ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    ident = "tracking_id={}".format(tracking_id or "?")
    if platform:
        ident += " · platform={}".format(platform)
    if cli_uuid:
        ident += " · cli_session={}".format(cli_uuid)
    text = (
        "<<<SESSION RESUMED>>>{local} · context reloaded from a trimmed transcript; "
        "session is idle, awaiting the first prompt. Passive marker — not an "
        "instruction, infer no work from it. Identity: {ident} <<<END SESSION RESUMED>>>"
    ).format(local=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ident=ident)
    leaf = leaf or {}
    return {
        "parentUuid": leaf.get("uuid"),
        "isSidechain": False,
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        "isMeta": True,
        "uuid": str(_uuid.uuid4()),
        "timestamp": ts_iso,
        "userType": leaf.get("userType", "external"),
        "entrypoint": leaf.get("entrypoint", "cli"),
        "cwd": leaf.get("cwd") or cwd or os.getcwd(),
        "sessionId": leaf.get("sessionId") or cli_uuid,
        "version": leaf.get("version", ""),
        "gitBranch": leaf.get("gitBranch", ""),
    }


def write_passive_resume_marker(jsonl_path, *, cli_uuid=None, tracking_id=None,
                                platform=None, cwd=None):
    """Append a passive isMeta resume marker to the transcript (fsync'd). Returns the
    new record's uuid, or None if the transcript is missing/empty.

    SAFETY: only call when the prior CC process has EXITED (autonomous relaunch) — never
    while a live process may be writing the same file.
    """
    # accept a plain path, a Python list, or a JSON list-string '["…"]' (transcript_path
    # is stored JSON-encoded in the registry) — Path() needs a plain path str.
    if isinstance(jsonl_path, (list, tuple)):
        jsonl_path = jsonl_path[0] if jsonl_path else None
    elif isinstance(jsonl_path, str) and jsonl_path.strip().startswith("["):
        try:
            _parsed = json.loads(jsonl_path)
            jsonl_path = _parsed[0] if _parsed else None
        except Exception:
            pass
    if not jsonl_path:
        return None
    p = Path(jsonl_path)
    if not p.exists():
        return None
    leaf = _read_tail_record(p)
    if leaf is None:
        return None
    rec = build_marker_record(leaf, cli_uuid=cli_uuid, tracking_id=tracking_id,
                              platform=platform, cwd=cwd)
    with open(p, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec["uuid"]
