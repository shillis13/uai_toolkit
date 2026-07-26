"""lib_session_state_union.py — UNION read of a session's mutable state during the
state-consolidation migration (todo_0495).

A session may have mutable key-value state in TWO files in its session dir during
the migration:
  - `<tracking_id>_state.json` — the hooks' own file, keys stored FLAT at the top
    level. In phase 2 this is a legacy value fallback; deletes tombstone it too.
  - `state.<uuid8>.json` — the canonical accessor file (SessionKeyValues), keys
    stored under a `"state"` object. In phase 2 every normal bridge write lands
    here; MCP tools and state-setting skills use it too.

`read_union()` returns the merge — canonical OVER legacy — so readers see both
pre-cutover legacy values and canonical values while the fleet converges. A
canonical delete also clears the requested legacy key so the fallback cannot
resurrect deleted state.

Best-effort and stdlib-only (json/os/glob) so it is safe to import from any hook
and NEVER raises: on any error it degrades to whatever it could read (empty →
the hook falls back to its defaults). This mirrors SessionKeyValues._read_state.
"""

from __future__ import annotations

import json
import os
import sys


def _uuid8_from_tracking_id(tracking_id):
    # type: (str) -> str
    parts = (tracking_id or "").split("_")
    if len(parts) >= 4 and len(parts[2]) == 8:
        return parts[2]
    return (tracking_id or "")[:8]


_RECOVER_DEFAULT = object()


def _loads_recover(text, invalid=_RECOVER_DEFAULT):
    # type: (str, object) -> dict
    """Parse a JSON object, RECOVERING the valid leading object if the file is torn
    — a second write's tail appended after valid JSON, the lost-update race this
    migration removes (ThroughLine, 2026-07-20). A torn legacy state file must not
    permanently brick a session's writes (a torn file made declare_stop fail every
    turn and the stop-gate block the session): recover the prefix via raw_decode
    instead of losing everything, so the next write heals the file. `invalid` lets
    the write path distinguish "no recoverable object" from a valid empty object;
    reads retain their historical {} fallback."""
    fallback = {} if invalid is _RECOVER_DEFAULT else invalid
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else fallback
    except ValueError:
        try:
            d, _ = json.JSONDecoder().raw_decode(text.lstrip())
            return d if isinstance(d, dict) else fallback
        except ValueError:
            return fallback


def _read_legacy(session_dir, tracking_id):
    # type: (str, str) -> dict
    path = os.path.join(session_dir, "{}_state.json".format(tracking_id))
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return _loads_recover(f.read())
    except OSError:
        return {}


def _read_canonical(session_dir, tracking_id):
    # type: (str, str) -> dict
    """Read this session's canonical state.<uuid8>.json "state" object."""
    try:
        path = os.path.join(session_dir, "state.{}.json".format(_uuid8_from_tracking_id(tracking_id)))
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            data = _loads_recover(f.read())
        return (data.get("state", {}) or {}) if isinstance(data, dict) else {}
    except OSError:
        return {}


def read_union(session_dir, tracking_id):
    # type: (str, str) -> dict
    """Return the legacy hooks' state merged UNDER the canonical accessor state.
    Canonical wins on key conflict (it is the migration target). Never raises."""
    if not session_dir or not tracking_id:
        return {}
    legacy = _read_legacy(session_dir, tracking_id)
    canonical = _read_canonical(session_dir, tracking_id)
    if not canonical:
        return legacy
    merged = dict(legacy)
    merged.update(canonical)
    return merged


# ── writer bridge (todo_0495 stage 3) ──────────────────────────────────────
# Every hook/script writes session state through write_session_state(). ENROLLED
# sessions (allowlist) write the LOCKED canonical accessor; everyone else uses the
# legacy hand-rolled file. The checked-in '*' is the phase-2 global enrollment;
# exact-ID and empty/unreadable modes remain for pilots, tests, and rollback.

_ALLOWLIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "state_writer_allowlist.txt")


def accessor_enabled(tracking_id):
    # type: (str) -> bool
    """Phase gate for the writer migration. True if this session should write
    through the locked canonical accessor instead of the legacy hooks' file.
    Reads data/hooks/state_writer_allowlist.txt: a line '*' enrolls EVERYONE
    (phase 2); otherwise an exact tracking_id line enrolls that session (phase-1
    pilots). Blank / '#'-comment lines are ignored. Unreadable file or no match
    → False (legacy path). Never raises."""
    if not tracking_id:
        return False
    try:
        with open(_ALLOWLIST) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line == "*" or line == tracking_id:
                    return True
    except OSError:
        pass
    return False


def _legacy_write(session_dir, tracking_id, updates, deletes):
    # type: (str, str, dict, list) -> bool
    """Hand-rolled read-modify-write on the legacy {tid}_state.json (flat keys),
    atomic tmp+rename — the pre-migration behavior. Best-effort; never raises."""
    path = os.path.join(session_dir, "{}_state.json".format(tracking_id))
    try:
        cur = {}
        if os.path.exists(path):
            with open(path) as f:
                cur = _loads_recover(
                    f.read(), invalid=None
                )  # recover a torn file's valid prefix, don't fail
            if cur is None:
                # A file with no leading JSON object is not the recoverable
                # append-tail shape. Preserve it for diagnosis rather than
                # silently replacing all state with only this update.
                return False
        cur.update(updates or {})
        for k in (deletes or []):
            cur.pop(k, None)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cur, f, indent=2)
        os.replace(tmp, path)                    # atomic rewrite HEALS a previously-torn file
        return True
    except OSError:
        return False


def _legacy_delete(session_dir, tracking_id, deletes):
    # type: (str, str, list) -> bool
    """Remove keys from an EXISTING legacy {tid}_state.json — the tombstone half of
    a canonical delete. read_union merges legacy UNDER canonical, so a key deleted
    from the canonical file alone would resurrect from an un-migrated session's
    legacy file (GG, 2026-07-23). A delete must therefore clear BOTH stores. Only
    touches a legacy file that already exists and actually holds one of the keys —
    never CREATES a legacy file (that would undo a migrated session's cleanup) and
    never rewrites when nothing matched. Best-effort; never raises. Returns False
    only when an existing fallback could not be safely inspected or rewritten, so
    the caller can report that the cross-store tombstone was incomplete."""
    if not deletes:
        return True
    path = os.path.join(session_dir, "{}_state.json".format(tracking_id))
    if not os.path.exists(path):
        return True
    tmp = path + ".tmp"
    try:
        with open(path) as f:
            cur = _loads_recover(f.read(), invalid=None)
        if not isinstance(cur, dict):
            return False  # torn/garbage — leave for diagnosis, same as _legacy_write
        removed = False
        for k in deletes:
            if k in cur:
                del cur[k]
                removed = True
        if not removed:
            return True
        with open(tmp, "w") as f:
            json.dump(cur, f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        return False


def _session_mgmt_dir():
    # type: () -> str
    # this file: ai_general/data/hooks/common/ → up 4 → ai_general
    ai_general = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(ai_general, "scripts", "session_mgmt")


def write_session_state(session_dir, tracking_id, updates=None, deletes=None):
    # type: (str, str, dict, list) -> bool
    """Persist key updates/deletes for a session — the single write path every
    hook/script routes through during the todo_0495 consolidation.

    ENROLLED (allowlist) sessions write through the LOCKED canonical accessor
    (SessionKeyValues: fcntl lock + atomic + validation) — fixes the lost-update
    race and consolidates onto one file. Everyone else uses the legacy hand-rolled
    RMW. Falls back to legacy if the accessor can't be imported/used, so a hook is
    never broken. Best-effort; returns True on a successful write.

    Invariant on the enrolled path — legacy is a read-only fallback for VALUES, but
    a DELETE tombstones across BOTH stores: an update lands only in canonical (which
    wins in read_union, shadowing any legacy value), but a delete also clears the
    key from the legacy file, or read_union would resurrect a legacy-only key that
    a canonical-only delete never touched (un-migrated sessions; GG 2026-07-23)."""
    if not session_dir or not tracking_id:
        return False
    updates = updates or {}
    deletes = deletes or []
    if accessor_enabled(tracking_id):
        try:
            sm = _session_mgmt_dir()
            if sm not in sys.path:
                sys.path.insert(0, sm)
            from uai_toolkit.session_mgmt.session_key_values import SessionKeyValues
            # validate=False: hooks/scaffolding are TRUSTED writers of their own
            # runtime keys — an unregistered key must not block the write (only the
            # MCP sessions_state_set path, untrusted AI input, validates).
            SessionKeyValues(tracking_id=tracking_id,
                             session_data_dir=session_dir).update(updates, deletes, validate=False)
            # Tombstone deletes in the legacy fallback too, so read_union can't
            # resurrect a legacy-only key that the canonical delete didn't reach.
            return _legacy_delete(session_dir, tracking_id, deletes)
        except Exception:
            pass   # fall through to legacy — never break a hook
    return _legacy_write(session_dir, tracking_id, updates, deletes)
