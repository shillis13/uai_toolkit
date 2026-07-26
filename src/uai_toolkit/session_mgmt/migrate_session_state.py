#!/usr/bin/env python3
"""migrate_session_state.py — enroll/unenroll sessions into the todo_0495 state
writer migration (phase-gated rollout).

The hooks all write session key-value state through write_session_state()
(data/hooks/common/lib_session_state_union.py). ENROLLED sessions (listed in
data/hooks/state_writer_allowlist.txt) write the LOCKED canonical accessor
(state.<uuid8>.json); everyone else uses the legacy {tracking_id}_state.json.

enroll:   migrate a session's legacy state INTO canonical (via the locked
          accessor), move the legacy file aside (.pre_migration backup), then add
          the tracking_id to the allowlist. Result: the session is cleanly
          canonical (reads return canonical, writes go to canonical).
unenroll: reverse it — write canonical state back to a legacy file and remove the
          tracking_id from the allowlist (rollback to the legacy path).
status:   show the allowlist and each enrolled session's file state.

Flags (not subcommands — this is a non-REPL tool, per scripts/DESIGN.md §1):
    migrate_session_state.py --status
    migrate_session_state.py --enroll   <tracking_id>
    migrate_session_state.py --unenroll <tracking_id>
    migrate_session_state.py --enroll <tracking_id> --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402
from uai_toolkit.common_utils.standard_colors import c  # noqa: E402

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from uai_toolkit.session_mgmt.session_key_values import SessionKeyValues, _instance_filename  # noqa: E402

ALLOWLIST = AI_ROOT / "ai_general" / "data" / "hooks" / "state_writer_allowlist.txt"


def _resolve_session_dir(tracking_id: str) -> Path | None:
    """Session dir for a tracking_id, via SessionStore then a filesystem fallback."""
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        rec = SessionStore().resolve(tracking_id)
        if rec and rec.get("session_dir"):
            p = Path(rec["session_dir"])
            if p.is_dir():
                return p
    except Exception:
        pass
    hits = list((AI_ROOT / "ai_general" / "data" / "sessions").glob(f"*/*/*/{tracking_id}"))
    return hits[0] if hits else None


def _legacy_path(sdir: Path, tid: str) -> Path:
    return sdir / f"{tid}_state.json"


def _read_allowlist() -> list[str]:
    if not ALLOWLIST.exists():
        return []
    out = []
    for line in ALLOWLIST.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _write_allowlist_entries(entries: list[str]) -> None:
    """Rewrite the allowlist keeping the header comment block, replacing entries."""
    header = []
    if ALLOWLIST.exists():
        for line in ALLOWLIST.read_text().splitlines():
            if line.strip().startswith("#") or not line.strip():
                header.append(line)
            else:
                break
    body = "\n".join(entries)
    ALLOWLIST.write_text("\n".join(header) + ("\n" + body if body else "") + "\n")


def cmd_status() -> int:
    entries = _read_allowlist()
    print(f"  {c('State writer allowlist', 'heading')}  {c(str(ALLOWLIST), 'muted')}")
    if not entries:
        print(f"  {c('(empty — every session uses the legacy path)', 'muted')}")
        return 0
    if "*" in entries:
        print(f"  {c('* — ALL sessions enrolled (phase 2)', 'ok')}")
    for tid in entries:
        if tid == "*":
            continue
        sdir = _resolve_session_dir(tid)
        if not sdir:
            print(f"  {c(tid, 'value')}  {c('(session dir not found)', 'error')}")
            continue
        legacy = _legacy_path(sdir, tid)
        canon = sdir / _instance_filename(str(sdir))
        print(f"  {c(tid, 'value')}  canonical={c('yes' if canon.exists() else 'no', 'ok' if canon.exists() else 'error')}"
              f"  legacy={c('present' if legacy.exists() else 'removed', 'warning' if legacy.exists() else 'ok')}")
    return 0


def cmd_enroll(tid: str, dry_run: bool) -> int:
    if tid in _read_allowlist():
        print(f"  {c(tid, 'value')} already enrolled")
        return 0
    sdir = _resolve_session_dir(tid)
    if not sdir:
        print(f"{c(f'ERROR: session dir not found for {tid}', 'error')}", file=sys.stderr)
        return 1
    legacy = _legacy_path(sdir, tid)
    legacy_state = {}
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text())
            if isinstance(data, dict):
                legacy_state = data
        except (OSError, ValueError) as e:
            print(f"{c(f'ERROR: could not read legacy state: {e}', 'error')}", file=sys.stderr)
            return 1
    if dry_run:
        print(f"  [dry-run] would migrate {len(legacy_state)} legacy key(s) into canonical, "
              f"move {legacy.name} → {legacy.name}.pre_migration, and enroll {tid}")
        return 0
    # 1. migrate legacy keys into the canonical (locked) accessor. validate=False:
    # the legacy file holds trusted hook-written runtime keys, some of which live in
    # reserved namespaces without a registry entry (same reason write_session_state
    # writes trusted) — a migration must not be blocked by an unregistered key.
    kv = SessionKeyValues(tracking_id=tid, session_data_dir=str(sdir))
    if legacy_state:
        kv.update(legacy_state, validate=False)
    # 2. move the legacy file aside (keep a backup rather than hard-delete)
    if legacy.exists():
        legacy.rename(legacy.with_suffix(".json.pre_migration"))
    # 3. enroll
    _write_allowlist_entries(_read_allowlist() + [tid])
    print(f"  {c('Enrolled', 'ok')} {c(tid, 'value')}: migrated {len(legacy_state)} key(s) → canonical; "
          f"legacy moved to {legacy.name}.pre_migration")
    return 0


def cmd_unenroll(tid: str, dry_run: bool) -> int:
    entries = _read_allowlist()
    if tid not in entries:
        print(f"  {c(tid, 'value')} not enrolled")
        return 0
    sdir = _resolve_session_dir(tid)
    if dry_run:
        print(f"  [dry-run] would write canonical state back to a legacy file and unenroll {tid}")
        return 0
    # write canonical state back to the legacy file so the legacy path has current data
    if sdir:
        kv = SessionKeyValues(tracking_id=tid, session_data_dir=str(sdir))
        state = kv.list_all()
        _legacy_path(sdir, tid).write_text(json.dumps(state, indent=2))
    _write_allowlist_entries([e for e in entries if e != tid])
    print(f"  {c('Unenrolled', 'warning')} {c(tid, 'value')}: canonical state written back to legacy")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Enroll/unenroll sessions into the todo_0495 state writer migration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  migrate_session_state.py --status\n"
               "  migrate_session_state.py --enroll 20260621_121002_16b176f5_cla\n"
               "  migrate_session_state.py --unenroll 20260621_121002_16b176f5_cla\n",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="Show the allowlist and enrolled sessions")
    g.add_argument("--enroll", metavar="TID", help="Enroll a session (migrate legacy→canonical)")
    g.add_argument("--unenroll", metavar="TID", help="Unenroll a session (canonical→legacy, rollback)")
    ap.add_argument("--dry-run", "-n", action="store_true", help="Preview without changing anything")
    a = ap.parse_args()

    if a.status:
        return cmd_status()
    if a.enroll:
        return cmd_enroll(a.enroll, a.dry_run)
    if a.unenroll:
        return cmd_unenroll(a.unenroll, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
