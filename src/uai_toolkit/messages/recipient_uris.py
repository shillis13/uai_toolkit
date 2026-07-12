#!/usr/bin/env python3
"""
recipient_uris.py — recipient sets over the CENTRAL uri_mappings authority.

Thin convenience over session_store's uri_mappings (the cross-entity URI
authority). NOT a parallel store. A recipient spec resolves to tracking ids:
  - a bare tracking id
  - a uai://<type>/<id>  (the type is OPEN — myfavs / team / project / alias …;
    resolved via session_store resolve-uri, session or fan_out)
  - the literal 'all'    (every live session — true broadcast)
  - a list of any of the above

Registration (option A: snapshot): flatten a selection into a fan_out list of
tracking ids and store it under a uai://<type>/<id>. Membership currency is
handled at RESOLVE time — resolve(live=True) filters to currently-active
sessions, so dead members drop out silently.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402

_SESSION_MGMT = AI_ROOT / "ai_general" / "scripts" / "session_mgmt"
if str(_SESSION_MGMT) not in sys.path:
    sys.path.insert(0, str(_SESSION_MGMT))


def _store():
    from uai_toolkit.session_mgmt.session_store import SessionStore
    return SessionStore()


def _is_uri(s: str) -> bool:
    return isinstance(s, str) and s.startswith("uai://")


def live_active() -> dict:
    """tracking_id -> session row, for currently-live, non-archived sessions."""
    from uai_toolkit.session_mgmt import session_ops
    from uai_toolkit.session_mgmt.session_store import SessionStore
    live = {s["name"] for s in session_ops.list_sessions() if s.get("running", True)}
    out = {}
    for r in SessionStore().list():
        if not r.get("archived") and r.get("terminal_session") in live:
            out[r.get("tracking_id")] = r
    return out


def resolve_ids(spec, _seen: set | None = None) -> list[str]:
    """Expand a spec to tracking ids (or the '__ALL__' sentinel). Recurses through
    uai:// mappings via the central resolver; cycle-safe."""
    if _seen is None:
        _seen = set()
    if isinstance(spec, (list, tuple)):
        out: list[str] = []
        for s in spec:
            for t in resolve_ids(s, _seen):
                if t not in out:
                    out.append(t)
        return out
    spec = str(spec).strip()
    if not spec:
        return []
    if spec == "all":
        return ["__ALL__"]
    if _is_uri(spec):
        if spec in _seen:
            return []
        _seen.add(spec)
        targets = _store().resolve_uri(spec)  # flat tids or nested uai:// (rare)
        out = []
        for t in targets:
            for r in (resolve_ids(t, _seen) if _is_uri(t) else [t]):
                if r not in out:
                    out.append(r)
        return out
    return [spec]  # bare tracking id


def resolve(spec, live: bool = True, exclude_self: bool = True) -> list[str]:
    """Resolve a spec to tracking ids, filtered to live sessions by default."""
    ids = resolve_ids(spec)
    me = os.environ.get("AI_TRACKING_ID", "")
    if "__ALL__" in ids or live:
        active = live_active()
        ids = list(active.keys()) if "__ALL__" in ids else [t for t in ids if t in active]
    if exclude_self and me:
        ids = [t for t in ids if t != me]
    seen, out = set(), []
    for t in ids:
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


def register(uri: str, members: list[str], source_id: str | None = None,
             expires_at: str | None = None) -> dict:
    """Register a uai://<type>/<id> recipient set as a fan_out snapshot. Members
    (bare tids and/or uai:// URIs) are recursively flattened to tracking ids.
    expires_at (ISO local) makes it a temporary registration (auto-swept)."""
    if not _is_uri(uri):
        raise ValueError(f"recipient-set uri must be uai://<type>/<id>, got {uri!r}")
    tids = [t for t in resolve_ids(members) if t != "__ALL__"]
    sid = source_id or uri.rstrip("/").split("/")[-1]
    _store().set_uri_mapping(uri, "fan_out", json.dumps(tids), "recipient_set", sid,
                             expires_at=expires_at)
    return {"uri": uri, "members": tids, "source_id": sid, "expires_at": expires_at}


def _ttl_to_expires(ttl_hours: float) -> str:
    """Local ISO timestamp `ttl_hours` from now (for temporary registrations)."""
    import datetime
    return (datetime.datetime.now() + datetime.timedelta(hours=ttl_hours)).isoformat(timespec="seconds")


def unregister(uri: str) -> int:
    sid = uri.rstrip("/").split("/")[-1]
    return _store().delete_uri_mappings("recipient_set", sid)


def list_sets() -> list[dict]:
    return _store().list_uri_mappings(source_type="recipient_set")


def prune(dry_run: bool = True) -> dict:
    """Drop dead member tids from each recipient set; report empties."""
    from uai_toolkit.session_mgmt.session_store import SessionStore
    known = {r.get("tracking_id") for r in SessionStore().list()}
    report = {"pruned": {}, "empty": [], "expired": 0}
    # temporary registrations past their TTL: report (dry) or sweep
    st = _store()
    expired = [m["uri"] for m in list_sets() if st._iso_is_past(m.get("expires_at"))]
    report["expired"] = len(expired)
    if not dry_run and expired:
        _store().delete_expired_uri_mappings()
    for m in list_sets():
        try:
            members = json.loads(m["target_value"])
        except Exception:
            continue
        kept = [t for t in members if _is_uri(t) or t in known]
        dropped = [t for t in members if t not in kept]
        if dropped:
            report["pruned"][m["uri"]] = dropped
            if not dry_run:
                _store().set_uri_mapping(m["uri"], "fan_out", json.dumps(kept),
                                         "recipient_set", m["source_id"])
        if not resolve(m["uri"], live=True, exclude_self=False):
            report["empty"].append(m["uri"])
    return report


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Recipient URI sets over uri_mappings.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("register"); pr.add_argument("uri"); pr.add_argument("members", nargs="+")
    pr.add_argument("--expires-at", help="ISO local time (temporary registration)")
    pr.add_argument("--ttl-hours", type=float, help="expire this many hours from now")
    pv = sub.add_parser("resolve"); pv.add_argument("spec", nargs="+")
    pv.add_argument("--no-live", action="store_true"); pv.add_argument("--include-self", action="store_true")
    sub.add_parser("list")
    pu = sub.add_parser("unregister"); pu.add_argument("uri")
    pp = sub.add_parser("prune"); pp.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.cmd == "register":
        exp = a.expires_at or (_ttl_to_expires(a.ttl_hours) if a.ttl_hours else None)
        out = register(a.uri, a.members, expires_at=exp)
    elif a.cmd == "resolve":
        spec = a.spec if len(a.spec) > 1 else a.spec[0]
        out = resolve(spec, live=not a.no_live, exclude_self=not a.include_self)
    elif a.cmd == "list":
        out = list_sets()
    elif a.cmd == "unregister":
        out = {"deleted": unregister(a.uri)}
    elif a.cmd == "prune":
        out = prune(dry_run=not a.apply)
    else:
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
