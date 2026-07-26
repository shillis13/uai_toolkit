"""
session_key_values.py — a session's mutable key-value variables (class SessionKeyValues).

Per-session key/value state with triggers. This is the session's VARIABLES, not its
identity (identity lives in session_store.py -> session_registry.py).

Disk-backed: every read/write goes through a JSON file. No in-memory cache
trusted across calls. File locking via fcntl.flock (shared for reads,
exclusive for writes). Atomic write via tmp file + rename for crash safety.

Values can be strings, numbers, or lists (for role, features).
Triggers fire callbacks when values change.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import get_logger

log = get_logger(__name__)


# --- Reserved key registry loading ---

_RESERVED_KEYS = None       # type: Optional[List[str]]
_RESERVED_NAMESPACES = None  # type: Optional[List[str]]
_REGISTRY_BY_NS = None       # type: Optional[Dict[str, List[str]]]

# Path to the main ai_root's reserved key registry (never the devTree copy)
_AI_ROOT_MAIN = Path.home() / "AI" / "ai_root"
_REGISTRY_PATH = (
    _AI_ROOT_MAIN / "ai_general" / "ai_context_files" / "knowledge"
    / "schemas" / "schema_session_state_keys.yml"
)


def _load_registry():
    # type: () -> None
    """Load the reserved key registry YAML (lazy, once per process)."""
    global _RESERVED_KEYS, _RESERVED_NAMESPACES, _REGISTRY_BY_NS

    if _RESERVED_KEYS is not None:
        return

    _RESERVED_KEYS = []
    _RESERVED_NAMESPACES = []
    _REGISTRY_BY_NS = {}

    if not _REGISTRY_PATH.exists():
        return

    try:
        import yaml
        with open(_REGISTRY_PATH) as f:
            data = yaml.safe_load(f)
    except ImportError:
        # Fallback: crude YAML parse for the fields we need
        data = _parse_registry_fallback(_REGISTRY_PATH)
    except Exception:
        return

    if not data:
        return

    # Extract reserved keys
    for entry in data.get("reserved_keys", []):
        key = entry.get("key", "")
        if key:
            _RESERVED_KEYS.append(key)

    # Extract reserved namespaces
    for ns in data.get("validation", {}).get("namespaces", []):
        ns_str = str(ns).strip()
        if ns_str:
            _RESERVED_NAMESPACES.append(ns_str)

    # Build namespace -> keys index
    for key in _RESERVED_KEYS:
        if "." in key:
            ns = key.split(".")[0] + "."
            _REGISTRY_BY_NS.setdefault(ns, []).append(key)


def _parse_registry_fallback(path):
    # type: (Path) -> dict
    """Minimal YAML-like parser for the reserved key registry.

    Only extracts 'reserved_keys' entries (lines starting with '  - key:')
    and 'namespaces' entries (lines starting with '    - "').
    """
    data = {"reserved_keys": [], "validation": {"namespaces": []}}
    in_reserved = False
    in_namespaces = False
    current_entry = None  # type: Optional[dict]

    with open(path) as f:
        for line in f:
            stripped = line.strip()

            if stripped == "reserved_keys:":
                in_reserved = True
                in_namespaces = False
                continue
            if stripped == "namespaces:":
                in_namespaces = True
                in_reserved = False
                continue
            # End of current section on encountering another top-level key
            if stripped and not stripped.startswith("-") and not stripped.startswith("#") and ":" in stripped:
                bare = stripped.split(":")[0].strip()
                if bare in ("validation", "mcp_tool", "change_management", "related"):
                    if bare != "validation":
                        in_reserved = False
                    in_namespaces = False

            if in_reserved:
                if stripped.startswith("- key:"):
                    if current_entry is not None:
                        data["reserved_keys"].append(current_entry)
                    key_val = stripped.split(":", 1)[1].strip()
                    current_entry = {"key": key_val}
                elif current_entry is not None and ":" in stripped:
                    parts = stripped.split(":", 1)
                    k = parts[0].strip().lstrip("- ")
                    v = parts[1].strip()
                    current_entry[k] = v

            if in_namespaces:
                if stripped.startswith('- "') and stripped.endswith('"'):
                    ns = stripped[3:-1]
                    data["validation"]["namespaces"].append(ns)

    if current_entry is not None:
        data["reserved_keys"].append(current_entry)

    return data


def _validate_namespace(key):
    # type: (str) -> None
    """Validate a namespaced key against the reserved key registry.

    Rules:
    - Key contains no dot -> no validation (free-form or legacy reserved)
    - Key matches a reserved key exactly -> OK
    - Key's namespace is reserved but key is unknown -> ValueError
    - Key's namespace is not reserved -> OK (custom namespace)
    """
    if "." not in key:
        return

    _load_registry()

    if _RESERVED_KEYS is None:
        return

    # Exact match in registry -> OK
    if key in _RESERVED_KEYS:
        return

    # Check if the namespace prefix is reserved
    ns_prefix = key.split(".")[0] + "."
    if ns_prefix in (_RESERVED_NAMESPACES or []):
        valid_keys = (_REGISTRY_BY_NS or {}).get(ns_prefix, [])
        valid_list = ", ".join(sorted(valid_keys))
        raise ValueError(
            "Unknown key '{}' in reserved namespace '{}'. "
            "Valid keys: {}".format(key, ns_prefix, valid_list)
        )

    # Not a reserved namespace -> OK (custom namespace)


# --- Instance filename helpers (inlined to avoid import issues) ---

def _uuid8_from_dir(session_dir_path):
    # type: (str) -> str
    """Extract uuid8 from a session directory name (tracking ID format).

    Tracking ID format: YYYYMMDD_HHMMSS_uuid8_platform
    Falls back to first 8 chars of the directory name.
    """
    name = os.path.basename(session_dir_path)
    parts = name.split("_")
    if len(parts) >= 4 and len(parts[2]) == 8:
        return parts[2]
    return name[:8]


def _instance_filename(session_dir_path):
    # type: (str) -> str
    """Build the state file name: state.{uuid8}.json"""
    uuid8 = _uuid8_from_dir(session_dir_path)
    return "state.{}.json".format(uuid8)


def _find_state_file(session_dir_path):
    # type: (str) -> Optional[str]
    """Find the state file, trying discriminated name first, then legacy."""
    discriminated = os.path.join(session_dir_path, _instance_filename(session_dir_path))
    if os.path.exists(discriminated):
        return discriminated
    legacy = os.path.join(session_dir_path, "state.json")
    if os.path.exists(legacy):
        return legacy
    return None


class SessionKeyValues:
    """Per-session mutable key-value store with change triggers.

    Disk-backed: every operation reads from and writes to a JSON file.
    No in-memory cache is trusted across calls.
    """

    # List-typed keys with merge/remove semantics
    LIST_KEYS = ("role", "features")

    def __init__(
        self,
        tracking_id=None,   # type: Optional[str]
        session_data_dir=None,  # type: Optional[str]
        session_id=None,     # type: Optional[str]
    ):
        # tracking_id is the primary identifier; session_id is deprecated alias
        self.tracking_id = tracking_id or session_id  # type: Optional[str]
        self._session_data_dir = str(session_data_dir) if session_data_dir else None
        self.triggers = {}  # type: Dict[str, List[Callable]]

    @property
    def session_id(self):
        # type: () -> Optional[str]
        """Backward-compatible alias for tracking_id."""
        return self.tracking_id

    @session_id.setter
    def session_id(self, value):
        # type: (Optional[str]) -> None
        self.tracking_id = value

    def _state_file_path(self):
        # type: () -> Optional[str]
        """Return the path to the state JSON file (discriminated name)."""
        if not self._session_data_dir:
            return None
        return os.path.join(self._session_data_dir, _instance_filename(self._session_data_dir))

    def _read_legacy_hook_state(self):
        # type: () -> Dict[str, Any]
        """Read the legacy hooks' state file ({tracking_id}_state.json) for the
        state-consolidation UNION read (todo_0495).

        The hooks still own and write that file, and they store keys FLAT at the
        top level (no {"state": ...} wrapper). Surfacing it here lets accessor
        readers (the footer, sessions_state_list) see hook-written keys before the
        writer cutover. READ-ONLY: this is merged only in _read_state (get /
        list_all), never in _read_mutate_write — so a mutation never copies legacy
        keys into the canonical file (which would create stale third copies).
        """
        if not self._session_data_dir:
            return {}
        tid = self.tracking_id or os.path.basename(self._session_data_dir)
        legacy = os.path.join(self._session_data_dir, "{}_state.json".format(tid))
        if not os.path.exists(legacy):
            return {}
        try:
            with open(legacy, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (json.JSONDecodeError, OSError, IOError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_state(self):
        # type: () -> Dict[str, Any]
        """Read state from disk with shared lock. Returns state dict or empty dict.

        UNION read during the state-consolidation migration (todo_0495): the
        canonical state.{uuid8}.json is merged OVER the legacy hooks'
        {tracking_id}_state.json, so accessor readers see hook-written keys too.
        Canonical wins on key conflict (it is the migration target). Read-only —
        writes go through _read_mutate_write, which reads canonical-only.
        """
        filepath = _find_state_file(self._session_data_dir) if self._session_data_dir else None
        canonical = {}  # type: Dict[str, Any]
        if filepath and os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        data = json.load(f)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                canonical = data.get("state", {})
            except (json.JSONDecodeError, OSError, IOError):
                canonical = {}

        legacy = self._read_legacy_hook_state()
        if not legacy:
            return canonical
        merged = dict(legacy)
        merged.update(canonical)   # canonical wins on conflict
        return merged

    def _write_state(self, state):
        # type: (Dict[str, Any]) -> None
        """Write state to disk via atomic tmp+rename (crash safety).

        NOTE: This is a low-level write helper. Cross-process coordination
        is handled by _read_mutate_write()'s .lock file. Do not call this
        directly outside of _read_mutate_write() or persist().
        """
        filepath = self._state_file_path()
        if not filepath:
            return

        dir_path = os.path.dirname(filepath)
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        now = datetime.now(timezone.utc).astimezone()
        data = {
            "tracking_id": self.tracking_id,
            "persisted_at": now.isoformat(),
            "state": state,
        }
        content = json.dumps(data, indent=2) + "\n"

        # Atomic write: tmp file + rename under exclusive lock
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            # Acquire exclusive lock on tmp file
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = None
            os.rename(tmp_path, filepath)
            tmp_path = None
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def _read_mutate_write(self, mutator):
        # type: (Callable[[Dict[str, Any]], Any]) -> Any
        """Read state under exclusive lock, apply mutator, write back.

        The mutator receives the state dict and can modify it in place.
        Returns whatever the mutator returns.

        Uses a lock file alongside the state file for atomicity.
        """
        filepath = self._state_file_path()
        if not filepath:
            return None

        dir_path = os.path.dirname(filepath)
        lock_path = filepath + ".lock"

        if not os.path.isdir(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            # Read current state (raw, no shared lock needed — we hold exclusive)
            state = {}
            actual_file = _find_state_file(self._session_data_dir)
            if actual_file and os.path.exists(actual_file):
                try:
                    with open(actual_file, "r") as f:
                        data = json.load(f)
                    state = data.get("state", {})
                except (json.JSONDecodeError, OSError, IOError):
                    state = {}

            result = mutator(state)

            # Write back
            self._write_state(state)

            return result
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()

    def get(self, key):
        # type: (str) -> Any
        """Get a value by key. Reads from disk with shared lock."""
        state = self._read_state()
        return state.get(key)

    def set(self, key, value):
        # type: (str, Any) -> Dict[str, Any]
        """Set a value. List keys (role, features) accept comma-separated strings and merge.

        Validates namespaced keys against the reserved key registry.
        """
        _validate_namespace(key)

        def mutator(state):
            # type: (Dict[str, Any]) -> Dict[str, Any]
            old = state.get(key)

            if key in self.LIST_KEYS:
                if isinstance(value, str):
                    new_values = [v.strip() for v in value.split(",") if v.strip()]
                elif isinstance(value, list):
                    new_values = value
                else:
                    new_values = [value]
                existing = state.get(key, [])
                if not isinstance(existing, list):
                    existing = [existing]
                merged = list(dict.fromkeys(existing + new_values))
                state[key] = merged
                final_value = merged
            else:
                state[key] = value
                final_value = value

            changed = old != final_value
            return {"key": key, "value": final_value, "changed": changed, "_old": old}

        result = self._read_mutate_write(mutator)

        if result and result.get("changed"):
            self._fire_triggers(key, result.pop("_old", None), result["value"])
        elif result:
            result.pop("_old", None)

        return result

    def delete(self, key):
        # type: (str) -> Dict[str, Any]
        """Delete a key from state."""

        def mutator(state):
            # type: (Dict[str, Any]) -> Dict[str, Any]
            if key in state:
                old = state.pop(key)
                return {"key": key, "deleted": True, "_old": old}
            return {"key": key, "deleted": False, "_old": None}

        result = self._read_mutate_write(mutator)

        if result and result.get("deleted"):
            self._fire_triggers(key, result.pop("_old", None), None)
        elif result:
            result.pop("_old", None)

        return result

    def increment(self, key, amount=1):
        # type: (str, Union[int, float]) -> Dict[str, Any]
        """Increment a numeric key by amount. Initializes to 0 if absent.

        Raises ValueError if existing value is not numeric.
        """

        def mutator(state):
            # type: (Dict[str, Any]) -> Dict[str, Any]
            old = state.get(key)
            if old is None:
                current = 0
            elif isinstance(old, (int, float)) and not isinstance(old, bool):
                current = old
            else:
                raise ValueError(
                    "Cannot increment non-numeric key '{}' (current value: {!r})".format(key, old)
                )
            new_value = current + amount
            state[key] = new_value
            changed = old != new_value
            return {"key": key, "value": new_value, "changed": changed, "_old": old}

        result = self._read_mutate_write(mutator)

        if result and result.get("changed"):
            self._fire_triggers(key, result.pop("_old", None), result["value"])
        elif result:
            result.pop("_old", None)

        return result

    def decrement(self, key, amount=1):
        # type: (str, Union[int, float]) -> Dict[str, Any]
        """Decrement a numeric key. Alias for increment(key, -amount)."""
        return self.increment(key, -amount)

    def update(self, updates=None, deletes=None, validate=True):
        # type: (Optional[Dict[str, Any]], Optional[List[str]], bool) -> Dict[str, Any]
        """Apply a batch of key sets + deletes under a SINGLE exclusive lock.

        The multi-key write primitive for callers migrating off hand-rolled
        read-modify-write (the todo_0495 hook-writer migration): one lock for the
        whole batch instead of N per-key locks. Values are set directly — NO
        list-merge (unlike set()'s role/features semantics); this is a plain
        multi-key write. Fires change triggers after the write. Returns
        {"changed": [keys], "deleted": [keys]}.

        validate=True (default) checks each updated key against the reserved
        registry — for untrusted callers (the sessions_state_set MCP). TRUSTED
        writers (hooks/scaffolding, via write_session_state) pass validate=False:
        they write their own runtime keys and must not be blocked by an
        unregistered-key rejection (mirrors seed_from_env's trusted bypass).
        """
        updates = updates or {}
        deletes = deletes or []
        if validate:
            for k in updates:
                _validate_namespace(k)

        changes = []   # type: List[tuple]   # (key, old, new)
        removed = []   # type: List[tuple]   # (key, old)

        def mutator(state):
            # type: (Dict[str, Any]) -> None
            for k, v in updates.items():
                old = state.get(k)
                state[k] = v
                if old != v:
                    changes.append((k, old, v))
            for k in deletes:
                if k in state:
                    removed.append((k, state.pop(k)))

        self._read_mutate_write(mutator)

        for k, old, new in changes:
            self._fire_triggers(k, old, new)
        for k, old in removed:
            self._fire_triggers(k, old, None)

        return {"changed": [k for k, _, _ in changes],
                "deleted": [k for k, _ in removed]}

    def list_all(self, prefix=None):
        # type: (Optional[str]) -> Dict[str, Any]
        """Return all state as a dict, optionally filtered by key prefix."""
        state = self._read_state()
        if prefix:
            return {k: v for k, v in state.items() if k.startswith(prefix)}
        return dict(state)

    def remove(self, key, value):
        # type: (str, str) -> Dict[str, Any]
        """Remove values from a list key (role, features)."""
        if key not in self.LIST_KEYS:
            return {"error": "remove only works on list keys (role, features), not '{}'".format(key)}

        def mutator(state):
            # type: (Dict[str, Any]) -> Dict[str, Any]
            current = state.get(key, [])
            if not isinstance(current, list):
                current = [current]
            values_to_remove = [v.strip() for v in value.split(",") if v.strip()]
            updated = [v for v in current if v not in values_to_remove]
            old = list(current)
            state[key] = updated
            return {"key": key, "value": updated, "_old": old, "_changed": old != updated}

        result = self._read_mutate_write(mutator)

        if result and result.get("_changed"):
            self._fire_triggers(key, result.pop("_old", None), result["value"])
        elif result:
            result.pop("_old", None)
        if result:
            result.pop("_changed", None)

        return result

    def seed_from_env(self, var_names):
        # type: (List[str]) -> Dict[str, Any]
        """Seed env.* keys from current environment. Single exclusive lock for entire batch.

        Bypasses namespace validation (seeding is a trusted launcher operation).
        """
        seeded = []   # type: List[str]
        missing = []  # type: List[str]

        env_values = {}  # type: Dict[str, str]
        for name in var_names:
            val = os.environ.get(name)
            if val is not None:
                env_values[name] = val
            else:
                missing.append(name)

        def mutator(state):
            # type: (Dict[str, Any]) -> None
            for name, val in env_values.items():
                state["env.{}".format(name)] = val
                seeded.append(name)

        self._read_mutate_write(mutator)

        return {"seeded": seeded, "missing": missing}

    def persist(self):
        # type: () -> str
        """Create initial state file with defaults. Returns file path.

        For initial file creation only. Subsequent mutations auto-persist.
        Uses the same exclusive lock as all other mutations to prevent
        lost updates from concurrent writers.
        """
        filepath = self._state_file_path()
        if not filepath:
            return "No session_data_dir set -- cannot persist"

        # Build defaults
        ai_root_default = os.environ.get(
            "AI_ROOT",
            str(Path.home() / "AI" / "ai_root"),
        )
        defaults = {
            "role": ["chat"],
            "features": [],
            "ai_root": ai_root_default,
            "ai_root_main": str(Path.home() / "AI" / "ai_root"),
        }

        def mutator(state):
            # type: (Dict[str, Any]) -> None
            for k, v in defaults.items():
                state.setdefault(k, v)

        self._read_mutate_write(mutator)

        return filepath

    def register_trigger(self, key, callback):
        # type: (str, Callable) -> None
        """Register a callback to fire when key changes: callback(key, old, new, store)."""
        self.triggers.setdefault(key, []).append(callback)

    def _fire_triggers(self, key, old_value, new_value):
        # type: (str, Any, Any) -> None
        """Fire registered triggers for a key."""
        for callback in self.triggers.get(key, []):
            try:
                callback(key, old_value, new_value, self)
            except Exception as e:
                log.error("Error in %s trigger: %s", key, e)
