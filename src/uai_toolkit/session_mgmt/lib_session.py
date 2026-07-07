"""
lib_session.py — Shared session resolution and registry I/O for CLI wrappers.

All writes use atomic temp-file + rename. All JSON includes schema_version.
Paths are segmented: {base}/{platform}/{yyyy}/{zellij_name}.json

Spec reference: spec_session_identity_v3.md sections 4.1-4.4
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from uai_toolkit.cli.lib_paths import SESSION_REGISTRY_DIR, SESSIONS_DIR, UNIFIED_CLI_DIR

SCHEMA_VERSION = 1

# Registry identity fields
REGISTRY_FIELDS = (
    "schema_version", "zellij_session", "cli_session_id", "platform",
    "parent_zellij", "parent_cli_session_id", "created_at",
)

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _uuid8_from_dir(session_dir: Path) -> str:
    """Extract uuid8 from a session directory name (tracking ID format).

    Tracking ID format: YYYYMMDD_HHMMSS_uuid8_platform
    Falls back to first 8 chars of the directory name.
    """
    parts = session_dir.name.split("_")
    if len(parts) >= 4 and len(parts[2]) == 8:
        return parts[2]
    return session_dir.name[:8]


def instance_filename(base: str, ext: str, session_dir: Path) -> str:
    """Build per-instance filename: base.uuid8.ext"""
    return f"{base}.{_uuid8_from_dir(session_dir)}.{ext}"


def find_instance_file(session_dir: Path, base: str, ext: str) -> Path | None:
    """Find a per-instance file, trying discriminated name first, then legacy.

    Returns the Path if found, None otherwise.
    """
    discriminated = session_dir / instance_filename(base, ext, session_dir)
    if discriminated.exists():
        return discriminated
    legacy = session_dir / f"{base}.{ext}"
    if legacy.exists():
        return legacy
    return None


class SessionInfo(NamedTuple):
    """Resolved session identity."""
    zellij_session: str
    cli_session_id: str | None
    platform: str
    parent_zellij: str | None
    parent_cli_session_id: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write(filepath: Path, data: dict) -> None:
    """Write JSON atomically via temp-file + rename."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.rename(tmp, filepath)
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _segmented_path(base: Path, platform: str, created_at: str | None) -> Path:
    """Build {base}/{platform}/{yyyy}/ path."""
    year = (created_at or "")[:4] or str(datetime.now().year)
    return base / platform / year


def _create_uuid_symlink(directory: Path, cli_uuid: str, target_name: str, suffix: str = "") -> None:
    """Create UUID reverse-lookup symlink: {uuid}{suffix} -> {target_name}{suffix}."""
    if not cli_uuid:
        return
    link = directory / f"{cli_uuid}{suffix}"
    if link.exists() or link.is_symlink():
        return  # Don't overwrite
    try:
        link.symlink_to(f"{target_name}{suffix}")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Registry I/O (segmented: session_registry/{platform}/{yyyy}/{name}.json)
# ---------------------------------------------------------------------------

def write_registry(zellij_name: str, data: dict) -> Path:
    """Write a session registry JSON file with UUID symlink.

    Args:
        zellij_name: Session name (used as fallback filename if no tracking_id).
        data: Dict with registry fields. If tracking_id is present, it's used
              as the filename (v5 behavior). Otherwise falls back to zellij_name (v3 compat).

    Returns:
        Path to the written file.
    """
    platform = data.get("platform", "claude_cli")
    created_at = data.get("created_at")
    seg_dir = _segmented_path(SESSION_REGISTRY_DIR, platform, created_at)

    entry = {"schema_version": SCHEMA_VERSION}
    for field in REGISTRY_FIELDS:
        if field == "schema_version":
            continue
        entry[field] = data.get(field)
    entry["zellij_session"] = zellij_name

    # v5+: include additional fields if present
    for extra_field in ("tracking_id", "cli_pid", "display_name", "parent_tracking_id", "status"):
        if extra_field in data and data[extra_field] is not None:
            entry[extra_field] = data[extra_field]

    # Filename: use tracking_id if available (v5), else zellij_name (v3 compat)
    file_key = data.get("tracking_id") or zellij_name
    filepath = seg_dir / f"{file_key}.json"
    _atomic_write(filepath, entry)

    # UUID reverse-lookup symlink
    cli_uuid = data.get("cli_session_id")
    if cli_uuid:
        _create_uuid_symlink(seg_dir, cli_uuid, file_key, suffix=".json")

    # Terminal name reverse-lookup symlink (if different from file_key)
    if zellij_name != file_key:
        link = seg_dir / f"{zellij_name}.json"
        if not link.exists():
            try:
                link.symlink_to(f"{file_key}.json")
            except OSError:
                pass

    return filepath


def read_registry(zellij_name: str, platform: str | None = None, year: str | None = None) -> dict | None:
    """Read one session's registry file.

    If platform/year known, does O(1) lookup. Otherwise scans.
    """
    if platform and year:
        filepath = SESSION_REGISTRY_DIR / platform / year / f"{zellij_name}.json"
        if filepath.exists():
            try:
                return json.loads(filepath.read_text())
            except (json.JSONDecodeError, OSError):
                return None

    # Scan all platform/year dirs
    if not SESSION_REGISTRY_DIR.exists():
        return None
    for plat_dir in SESSION_REGISTRY_DIR.iterdir():
        if not plat_dir.is_dir() or plat_dir.name.startswith("."):
            continue
        for yr_dir in plat_dir.iterdir():
            if not yr_dir.is_dir():
                continue
            filepath = yr_dir / f"{zellij_name}.json"
            if filepath.exists():
                try:
                    return json.loads(filepath.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
            # Check UUID symlink
            link = yr_dir / zellij_name
            if link.is_symlink():
                target = yr_dir / os.readlink(link)
                if target.exists():
                    try:
                        return json.loads(target.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue
    return None


def list_registry(platform: str | None = None) -> list[dict]:
    """Read all session registry files. Optionally filter by platform."""
    if not SESSION_REGISTRY_DIR.exists():
        return []
    results = []
    for plat_dir in sorted(SESSION_REGISTRY_DIR.iterdir()):
        if not plat_dir.is_dir() or plat_dir.name.startswith("."):
            continue
        if platform and plat_dir.name != platform:
            continue
        for yr_dir in sorted(plat_dir.iterdir()):
            if not yr_dir.is_dir():
                continue
            for f in sorted(yr_dir.iterdir()):
                if f.suffix != ".json" or f.is_symlink():
                    continue
                try:
                    results.append(json.loads(f.read_text()))
                except (json.JSONDecodeError, OSError):
                    continue
    return results


# ---------------------------------------------------------------------------
# Session resolution
# ---------------------------------------------------------------------------

def get_session_info(identifier: str) -> SessionInfo | None:
    """Search registry by zellij name, CLI UUID, partial match, or session_store.

    Accepts URIs (uai://session/<id>, prompt://target/<id>), display names,
    tracking IDs, CLI UUIDs, and terminal session names.

    Resolution order:
    1. Strip URI prefix if present
    2. Exact zellij name (scan registry dirs)
    3. Exact CLI UUID (try symlink, then scan)
    4. Prefix match on zellij name
    5. Fallback: session_store.resolve()
    """
    # Strip URI if present (centralized, action-aware — see lib_uri)
    if '://' in identifier:
        try:
            from uai_toolkit.session_mgmt.lib_uri import session_id_of
            identifier = session_id_of(identifier)
        except Exception:
            pass

    # 1. Exact zellij name
    entry = read_registry(identifier)
    if entry:
        return _to_session_info(entry)

    # 2. Exact CLI UUID (try symlink lookup first)
    if UUID_RE.match(identifier):
        # Try symlink in each platform/year
        if SESSION_REGISTRY_DIR.exists():
            for plat_dir in SESSION_REGISTRY_DIR.iterdir():
                if not plat_dir.is_dir():
                    continue
                for yr_dir in plat_dir.iterdir():
                    if not yr_dir.is_dir():
                        continue
                    link = yr_dir / f"{identifier}.json"
                    if link.exists():
                        try:
                            real = link.resolve()
                            return _to_session_info(json.loads(real.read_text()))
                        except (json.JSONDecodeError, OSError):
                            continue
        # Fallback: scan all
        for entry in list_registry():
            if entry.get("cli_session_id") == identifier:
                return _to_session_info(entry)

    # 3. Prefix match
    if SESSION_REGISTRY_DIR.exists():
        for plat_dir in sorted(SESSION_REGISTRY_DIR.iterdir()):
            if not plat_dir.is_dir():
                continue
            for yr_dir in sorted(plat_dir.iterdir()):
                if not yr_dir.is_dir():
                    continue
                for f in sorted(yr_dir.iterdir()):
                    if f.suffix == ".json" and not f.is_symlink() and f.stem.startswith(identifier):
                        try:
                            return _to_session_info(json.loads(f.read_text()))
                        except (json.JSONDecodeError, OSError):
                            continue

    # 4. Fallback: session_store.resolve() (handles display names, tracking IDs, etc.)
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
        row = store.resolve(identifier)
        if row:
            return SessionInfo(
                zellij_session=row.get("terminal_session", ""),
                cli_session_id=row.get("cli_session_id"),
                platform=row.get("platform", "unknown"),
                parent_zellij=None,
                parent_cli_session_id=row.get("parent_tracking_id"),
                created_at=row.get("created_at", ""),
            )
    except Exception:
        pass

    return None


def resolve_identifier(id_string: str) -> tuple[str | None, str | None]:
    """Flexible resolver → (zellij_name, cli_session_id)."""
    info = get_session_info(id_string)
    if info:
        return info.zellij_session, info.cli_session_id
    return None, None


# ---------------------------------------------------------------------------
# Project directory and history links
# ---------------------------------------------------------------------------

def get_project_dir(platform: str, cli_uuid: str) -> Path | None:
    """Find the JSONL chat history file and return its containing project dir."""
    if platform == "claude_cli":
        claude_projects = Path.home() / ".claude" / "projects"
        if claude_projects.exists():
            for project_dir in claude_projects.iterdir():
                jsonl = project_dir / f"{cli_uuid}.jsonl"
                if jsonl.exists():
                    return project_dir
    elif platform == "codex_cli":
        codex_dir = Path.home() / ".codex" / "sessions"
        if codex_dir.exists():
            for root, _, files in os.walk(codex_dir):
                for f in files:
                    if cli_uuid in f and f.endswith(".jsonl"):
                        return Path(root)
    elif platform == "gemini_cli":
        gemini_dir = Path.home() / ".gemini" / "tmp"
        if gemini_dir.exists():
            short_uuid = cli_uuid[:8]
            for root, _, files in os.walk(gemini_dir):
                for f in files:
                    if short_uuid in f and (f.endswith(".json") or f.endswith(".jsonl")):
                        return Path(root)
    return None


def make_history_link(src_dir: Path, uuid: str, target_dir: Path) -> Path | None:
    """Create chat_history.jsonl symlink + chat_history/{uuid}.jsonl symlink."""
    jsonl_file = None
    for f in src_dir.iterdir():
        if uuid in f.name and f.suffix in (".jsonl", ".json"):
            jsonl_file = f
            break
    if not jsonl_file:
        return None

    target_dir.mkdir(parents=True, exist_ok=True)

    # Top-level convenience symlink
    link = target_dir / "chat_history.jsonl"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(jsonl_file)

    # chat_history/ dir for multi-JSONL tracking
    history_dir = target_dir / "chat_history"
    history_dir.mkdir(exist_ok=True)
    uuid_link = history_dir / f"{uuid}.jsonl"
    if not uuid_link.exists():
        uuid_link.symlink_to(jsonl_file)

    return link


# ---------------------------------------------------------------------------
# Per-session directory management (sessions/{platform}/{yyyy}/{zellij_name}/)
# ---------------------------------------------------------------------------

def create_session_dir(
    platform: str,
    zellij_name: str,
    *,
    cli_session_id: str | None = None,
    parent_zellij: str | None = None,
    parent_cli_session_id: str | None = None,
    display_name: str | None = None,
    working_dir: str | None = None,
    model: str | None = None,
    roles: list[str] | None = None,
    name_origin: str = "wrapper",
    pid: int | None = None,
    created_at: str | None = None,
) -> Path:
    """Create a per-session directory with sessionInfo.json and PID file.

    sessionInfo.json is the source of truth — contains ALL fields.
    """
    ts = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seg_dir = _segmented_path(SESSIONS_DIR, platform, ts)
    session_dir = seg_dir / zellij_name
    session_dir.mkdir(parents=True, exist_ok=True)

    info = {
        "schema_version": SCHEMA_VERSION,
        "zellij_session": zellij_name,
        "cli_session_id": cli_session_id,
        "platform": platform,
        "parent_zellij": parent_zellij,
        "parent_cli_session_id": parent_cli_session_id,
        "created_at": ts,
        "display_name": display_name or zellij_name,
        "working_dir": working_dir,
        "model": model,
        "roles": roles or [],
        "name_origin": name_origin,
    }
    _atomic_write(session_dir / instance_filename("sessionInfo", "json", session_dir), info)

    # PID as zero-sized file in pids/ subdir
    if pid:
        pids_dir = session_dir / "pids"
        pids_dir.mkdir(exist_ok=True)
        pid_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (pids_dir / f"{pid}.{pid_ts}").touch()

    # UUID reverse-lookup symlink at session level
    if cli_session_id:
        _create_uuid_symlink(seg_dir, cli_session_id, zellij_name)

    return session_dir


def update_session_info(
    platform: str,
    zellij_name: str,
    *,
    created_at: str | None = None,
    pid: int | None = None,
    **updates: object,
) -> Path | None:
    """Update sessionInfo in an existing per-session directory. Atomic write."""
    seg_dir = _segmented_path(SESSIONS_DIR, platform, created_at)
    session_dir = seg_dir / zellij_name
    info_file = find_instance_file(session_dir, "sessionInfo", "json")

    if not info_file:
        return None

    try:
        info = json.loads(info_file.read_text())
    except (json.JSONDecodeError, OSError):
        info = {}

    info["schema_version"] = SCHEMA_VERSION
    if pid is not None:
        pids_dir = session_dir / "pids"
        pids_dir.mkdir(exist_ok=True)
        pid_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (pids_dir / f"{pid}.{pid_ts}").touch()
    for k, v in updates.items():
        info[k] = v

    # Write to discriminated name (may migrate from legacy on first update)
    target = session_dir / instance_filename("sessionInfo", "json", session_dir)
    _atomic_write(target, info)
    # Remove legacy file if we migrated
    if info_file != target and info_file.exists():
        info_file.unlink(missing_ok=True)

    # Create UUID symlink if cli_session_id was just set
    cli_uuid = updates.get("cli_session_id") or info.get("cli_session_id")
    if cli_uuid:
        _create_uuid_symlink(seg_dir, str(cli_uuid), zellij_name)

    return session_dir


def read_session_info(platform: str, zellij_name: str, year: str | None = None) -> dict | None:
    """Read sessionInfo from a per-session directory (discriminated or legacy name)."""
    if year:
        session_dir = SESSIONS_DIR / platform / year / zellij_name
        info_file = find_instance_file(session_dir, "sessionInfo", "json")
        if info_file:
            try:
                return json.loads(info_file.read_text())
            except (json.JSONDecodeError, OSError):
                return None

    # Scan years
    plat_dir = SESSIONS_DIR / platform
    if not plat_dir.exists():
        return None
    for yr_dir in sorted(plat_dir.iterdir(), reverse=True):
        if not yr_dir.is_dir():
            continue
        session_dir = yr_dir / zellij_name
        info_file = find_instance_file(session_dir, "sessionInfo", "json")
        if info_file:
            try:
                return json.loads(info_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return None


def add_child_symlink(parent_dir: Path, child_dir: Path, child_name: str) -> None:
    """Add a symlink in parent's children/ directory pointing to child session dir."""
    children_dir = parent_dir / "children"
    children_dir.mkdir(exist_ok=True)
    link = children_dir / child_name
    if not link.exists():
        link.symlink_to(child_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_session_info(entry: dict) -> SessionInfo:
    return SessionInfo(
        zellij_session=entry.get("zellij_session", ""),
        cli_session_id=entry.get("cli_session_id"),
        platform=entry.get("platform", "claude_cli"),
        parent_zellij=entry.get("parent_zellij"),
        parent_cli_session_id=entry.get("parent_cli_session_id"),
        created_at=entry.get("created_at", ""),
    )
