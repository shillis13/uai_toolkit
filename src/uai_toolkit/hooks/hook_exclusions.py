#!/usr/bin/env python3
"""
hook_exclusions.py — Manage per-directory hook exclusions.

Each hook event-type directory (Stop, PreToolUse, ...) has an optional
exclusions.yml mapping handler name -> [tracking IDs to skip]. The dispatcher
reads it and skips the listed handlers for those sessions.

  Handler key  = filename with NN_ prefix and _sync/_async suffix stripped
                 (e.g. 08_auto_self_compact_sync.py -> auto_self_compact).
  "*"          = exclude the session from EVERY handler in that directory.
  Value        = tracking IDs (authoritative). Display-name comments are
                 regenerated from the session store on every write.

Usage:
  hook_exclusions.py add <EventType> <handler|*> <session>
  hook_exclusions.py remove <EventType> <handler|*> <session>
  hook_exclusions.py list [EventType]
  hook_exclusions.py validate [EventType]

  <session> accepts a tracking ID, display name, CLI UUID, or URI.

add/remove run a schema preflight and refuse to touch a structurally broken
file (so a bad hand-edit isn't silently rewritten). 'validate' checks the file
the way the dispatcher reads it and reports anything it would silently ignore.

Examples:
  hook_exclusions.py add Stop auto_self_compact Cadence
  hook_exclusions.py add Stop '*' Meridian
  hook_exclusions.py remove Stop auto_self_compact Cadence
  hook_exclusions.py list Stop
  hook_exclusions.py validate          # check every exclusions.yml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
HOOKS_DIR = AI_ROOT / "ai_general" / "data" / "hooks"
_SM = AI_ROOT / "ai_general" / "scripts" / "session_mgmt"
if str(_SM) not in sys.path:
    sys.path.insert(0, str(_SM))

WILDCARD = "*"
WILDCARD_SYNC = "*sync"    # every sync (blocking/behavioral) handler
WILDCARD_ASYNC = "*async"  # every async (fire-and-forget) handler
# Keys that select a set of handlers rather than one by name. Kept in sync with
# dispatch.py's is_excluded(). Any key starting with "*" must be quoted in YAML
# (an unquoted "*sync:" is parsed as an alias reference, not a string key).
WILDCARD_KEYS = {WILDCARD, WILDCARD_SYNC, WILDCARD_ASYNC}

import re as _re
# Canonical tracking-id shape: YYYYMMDD_HHMMSS_<id8>_<plat>. The id8 segment is
# alphanumeric, NOT strictly hex (e.g. app-sourced ids like 'app3020c'). The file
# stores tracking IDs (authoritative) — a display name hand-written here won't
# match at dispatch time, so we warn on anything that isn't tracking-id-shaped.
_TRACKING_RE = _re.compile(r"^\d{8}_\d{6}_[0-9a-z]{8}_[a-z0-9]{2,4}$")

HEADER = """\
# {event} hook exclusions.
#
# Sessions listed here are skipped for the given handler when the dispatcher
# runs {event} hooks. Keyed by handler name (filename with the NN_ prefix and
# _sync/_async suffix stripped — matches the run_hook() name).
#
#   "*"      = exclude the session from EVERY handler in this directory.
#   "*sync"  = exclude from every SYNC handler (blocking/behavioral — gates,
#              compaction, reminders). Passive async telemetry keeps running.
#   "*async" = exclude from every ASYNC handler (fire-and-forget telemetry/logging).
#   else     = exclude only from that named handler.
#
# Tracking IDs are authoritative; the trailing comment is the display name
# (auto-regenerated on edit). Manage with scripts/hooks/hook_exclusions.py.
"""


def _store():
    from uai_toolkit.session_mgmt.session_store import SessionStore
    return SessionStore()


def _resolve(session: str) -> str | None:
    """Resolve a session identifier to a tracking ID."""
    if session == WILDCARD:
        return WILDCARD
    try:
        s = _store().resolve(session)
        if s:
            return s.get("tracking_id")
    except Exception:
        pass
    # Fall back to using the literal value if it looks like a tracking ID
    return session if session and "_" in session else None


def _display_name(tracking_id: str) -> str:
    try:
        s = _store().resolve(tracking_id)
        if s:
            return s.get("display_name") or tracking_id
    except Exception:
        pass
    return tracking_id


def _valid_event(event: str) -> bool:
    return (HOOKS_DIR / event).is_dir()


def _path(event: str) -> Path:
    return HOOKS_DIR / event / "exclusions.yml"


def load(event: str) -> dict:
    """Read exclusions.yml -> {handler: [tracking_ids]} (order-preserving)."""
    p = _path(event)
    if not p.is_file():
        return {}
    import yaml
    data = yaml.safe_load(p.read_text()) or {}
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                out[str(k)] = [str(i).strip() for i in v if i]
    return out


def _handler_keys(event: str) -> set[str]:
    """Normalized handler names present in the event dir (mirrors the dispatcher:
    strip the NN_ prefix and the _sync/_async suffix)."""
    keys = set()
    d = HOOKS_DIR / event
    if d.is_dir():
        for f in d.glob("*.py"):
            stem = _re.sub(r"^\d+_", "", f.stem)
            stem = _re.sub(r"_(sync|async)$", "", stem)
            keys.add(stem)
    return keys


def validate(event: str) -> tuple[list[str], list[str]]:
    """Strict schema/semantic check of an exclusions.yml. Returns (errors, warnings).

    Surfaces exactly what the dispatcher will SILENTLY tolerate and then ignore —
    a hand-edit can look fine yet be quietly inert. Errors mean the file (or an
    entry) is structurally broken and will be dropped by the dispatcher; warnings
    mean an entry is probably a mistake but is still well-formed.
    """
    errors: list[str] = []
    warnings: list[str] = []
    p = _path(event)
    if not p.is_file():
        return errors, warnings  # absent file is valid — all handlers run
    import yaml
    try:
        data = yaml.safe_load(p.read_text())
    except Exception as e:
        return [f"YAML parse error: {e}"], warnings
    if data is None:
        return errors, warnings  # empty file is valid
    if not isinstance(data, dict):
        return ([f"top-level must be a mapping of handler -> [tracking_ids]; got "
                 f"{type(data).__name__} — the dispatcher ignores the ENTIRE file."],
                warnings)

    valid_keys = _handler_keys(event)
    seen: set[tuple[str, str]] = set()
    for key, val in data.items():
        kstr = str(key)
        if not isinstance(val, list):
            errors.append(
                f"key '{kstr}': value is {type(val).__name__}, not a list — the "
                f"dispatcher SILENTLY DROPS this key (handler keeps running). "
                f"Write it as a YAML list (one '- <tracking_id>' per line).")
            continue
        if kstr not in WILDCARD_KEYS and valid_keys and kstr not in valid_keys:
            warnings.append(
                f"key '{kstr}': no handler by that name in {event}/ — exclusion is "
                f"inert. Known handlers: {', '.join(sorted(valid_keys)) or '(none)'}.")
        for item in val:
            tid = "" if item is None else str(item).strip()
            if not tid:
                errors.append(f"key '{kstr}': empty/blank list item.")
                continue
            if (kstr, tid) in seen:
                warnings.append(f"key '{kstr}': duplicate id '{tid}'.")
            seen.add((kstr, tid))
            if not _TRACKING_RE.match(tid):
                warnings.append(
                    f"key '{kstr}': '{tid}' is not tracking-id-shaped — the file "
                    f"stores tracking IDs, so a display name won't match at dispatch.")
    return errors, warnings


def _preflight(event: str) -> int:
    """Block a write if the existing file is structurally broken (avoids
    silently rewriting/clobbering a hand-edit). Returns 0 ok, 1 abort."""
    errors, warnings = validate(event)
    for w in warnings:
        print(f"warning [{event}]: {w}", file=sys.stderr)
    if errors:
        print(f"error: {_path(event)} is malformed — refusing to modify it until fixed:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    return 0


def save(event: str, data: dict) -> None:
    """Write exclusions.yml with header + display-name comments."""
    p = _path(event)
    lines = [HEADER.format(event=event)]
    # Wildcards first (in a stable order), then the named handlers sorted.
    wildcards = [k for k in (WILDCARD, WILDCARD_SYNC, WILDCARD_ASYNC) if k in data]
    keys = wildcards + sorted(k for k in data if k not in WILDCARD_KEYS)
    for key in keys:
        ids = data.get(key) or []
        if not ids:
            continue
        # Quote any "*"-prefixed key so YAML doesn't treat it as an alias.
        yaml_key = f'"{key}"' if key.startswith("*") else key
        lines.append(f"\n{yaml_key}:")
        for tid in ids:
            name = _display_name(tid)
            comment = f"   # {name}" if name and name != tid else ""
            lines.append(f"  - {tid}{comment}")
    p.write_text("\n".join(lines) + "\n")


def cmd_add(args) -> int:
    if not _valid_event(args.event):
        print(f"error: unknown event type '{args.event}' (no dir {_path(args.event).parent})", file=sys.stderr)
        return 1
    if _preflight(args.event):
        return 1
    tid = _resolve(args.session)
    if not tid:
        print(f"error: could not resolve session '{args.session}'", file=sys.stderr)
        return 1
    data = load(args.event)
    ids = data.setdefault(args.handler, [])
    if tid in ids:
        print(f"already excluded: {args.event}/{args.handler} <- {tid} ({_display_name(tid)})")
        return 0
    ids.append(tid)
    save(args.event, data)
    print(f"added: {args.event}/{args.handler} <- {tid} ({_display_name(tid)})")
    return 0


def cmd_remove(args) -> int:
    if not _valid_event(args.event):
        print(f"error: unknown event type '{args.event}'", file=sys.stderr)
        return 1
    tid = _resolve(args.session)
    if not tid:
        print(f"error: could not resolve session '{args.session}'", file=sys.stderr)
        return 1
    if _preflight(args.event):
        return 1
    data = load(args.event)
    ids = data.get(args.handler, [])
    if tid not in ids:
        print(f"not present: {args.event}/{args.handler} has no {tid}")
        return 0
    ids.remove(tid)
    if not ids:
        del data[args.handler]
    save(args.event, data)
    print(f"removed: {args.event}/{args.handler} -/-> {tid} ({_display_name(tid)})")
    return 0


def cmd_list(args) -> int:
    events = [args.event] if args.event else sorted(
        d.name for d in HOOKS_DIR.iterdir()
        if d.is_dir() and (d / "exclusions.yml").is_file()
    )
    if not events:
        print("(no exclusions defined)")
        return 0
    for event in events:
        data = load(event)
        if not data:
            continue
        print(f"\n{event}:")
        for handler, ids in data.items():
            label = {
                WILDCARD: "* (all handlers)",
                WILDCARD_SYNC: "*sync (all sync handlers)",
                WILDCARD_ASYNC: "*async (all async handlers)",
            }.get(handler, handler)
            print(f"  {label}:")
            for tid in ids:
                print(f"    - {tid}  ({_display_name(tid)})")
    return 0


def cmd_validate(args) -> int:
    events = [args.event] if args.event else sorted(
        d.name for d in HOOKS_DIR.iterdir()
        if d.is_dir() and (d / "exclusions.yml").is_file()
    )
    if args.event and not _valid_event(args.event):
        print(f"error: unknown event type '{args.event}'", file=sys.stderr)
        return 1
    if not events:
        print("(no exclusions.yml files to validate)")
        return 0
    total_err = 0
    for event in events:
        errors, warnings = validate(event)
        if not errors and not warnings:
            print(f"{event}: OK")
            continue
        print(f"{event}:")
        for e in errors:
            print(f"  ERROR:   {e}")
        for w in warnings:
            print(f"  warning: {w}")
        total_err += len(errors)
    return 1 if total_err else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="hook_exclusions",
        description="Manage per-directory hook exclusions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Exclude a session from a handler")
    p_add.add_argument("event", help="Event type (Stop, PreToolUse, ...)")
    p_add.add_argument("handler", help="Handler name or '*' for all")
    p_add.add_argument("session", help="Tracking ID, display name, UUID, or URI")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="Remove an exclusion")
    p_rm.add_argument("event")
    p_rm.add_argument("handler")
    p_rm.add_argument("session")
    p_rm.set_defaults(func=cmd_remove)

    p_ls = sub.add_parser("list", help="List exclusions")
    p_ls.add_argument("event", nargs="?", default=None, help="Optional event type filter")
    p_ls.set_defaults(func=cmd_list)

    p_val = sub.add_parser("validate", help="Schema-check exclusions.yml (all, or one event)")
    p_val.add_argument("event", nargs="?", default=None, help="Optional event type filter")
    p_val.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
