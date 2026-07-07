#!/usr/bin/env python3
"""Session identity resolution library.

Resolves between three CLI session identity layers:
  1. AI Session UUID — from ~/.claude/sessions/{PID}.json
  2. Zellij Session Name — from zellij list-sessions / session_registry.json
  3. Alias — human-readable name from electron-session-metadata.json

Data sources (in resolution priority):
  - ~/.claude/sessions/{PID}.json          (PID → UUID, fast)
  - ~/.claude/session_registry.json        (PID → zellij_session, metadata)
  - ~/.claude/electron-session-metadata.json (UUID → alias/name, zellij link)
  - zellij list-sessions                   (active session names)

Usage as library:
    from uai_toolkit.session_mgmt.lib_session_identity import SessionResolver
    resolver = SessionResolver()
    uuid = resolver.get_uuid(zellij_session="claude_cli_95993")
    zellij = resolver.get_zellij_session(alias="librarian-morning")
    alias = resolver.get_alias(zellij_session="claude_cli_95993")
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CLAUDE_DIR = Path.home() / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
REGISTRY_FILE = CLAUDE_DIR / "session_registry.json"
ELECTRON_META_FILE = CLAUDE_DIR / "electron-session-metadata.json"
_cli_scripts = Path(__file__).resolve().parent.parent / "scripts" / "cli"
if str(_cli_scripts) not in sys.path:
    sys.path.insert(0, str(_cli_scripts))
from uai_toolkit.cli.lib_paths import UNIFIED_CLI_DIR
UNIFIED_META_FILE = UNIFIED_CLI_DIR / "session_metadata.json"

# Zellij session name → platform mapping patterns
PLATFORM_PATTERNS = [
    (re.compile(r'^claude_cli[_-]'), "claude_cli"),
    (re.compile(r'^codex[_-]'), "codex_cli"),
    (re.compile(r'^gemini[_-]'), "gemini_cli"),
    (re.compile(r'^cli_task[_-]'), "claude_cli"),
    (re.compile(r'^shard[_-]'), "gemini_cli"),
]


@dataclass
class SessionInfo:
    """Unified session identity."""
    pid: Optional[int] = None
    uuid: Optional[str] = None
    zellij_session: Optional[str] = None
    alias: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    working_dir: Optional[str] = None
    claude_session_id: Optional[str] = None


class SessionResolver:
    """Resolves between session identity layers."""

    def __init__(self):
        self._registry: dict | None = None
        self._electron_meta: dict | None = None
        self._unified_meta: dict | None = None
        self._sessions_cache: dict[int, dict] | None = None

    # --- Data Loading (lazy) ---

    def _load_registry(self) -> dict:
        if self._registry is None:
            if REGISTRY_FILE.exists():
                try:
                    data = json.loads(REGISTRY_FILE.read_text())
                    self._registry = data.get("sessions", {})
                except (json.JSONDecodeError, OSError):
                    self._registry = {}
            else:
                self._registry = {}
        return self._registry

    def _load_electron_meta(self) -> dict:
        if self._electron_meta is None:
            if ELECTRON_META_FILE.exists():
                try:
                    data = json.loads(ELECTRON_META_FILE.read_text())
                    # Sessions are nested under "sessions" key
                    self._electron_meta = data.get("sessions", data)
                except (json.JSONDecodeError, OSError):
                    self._electron_meta = {}
            else:
                self._electron_meta = {}
        return self._electron_meta

    def _load_unified_meta(self) -> dict:
        if self._unified_meta is None:
            if UNIFIED_META_FILE.exists():
                try:
                    data = json.loads(UNIFIED_META_FILE.read_text())
                    self._unified_meta = data.get("sessions", data)
                except (json.JSONDecodeError, OSError):
                    self._unified_meta = {}
            else:
                self._unified_meta = {}
        return self._unified_meta

    @staticmethod
    def _infer_platform(zellij_name: str) -> Optional[str]:
        """Infer platform from zellij session name pattern."""
        for pattern, platform in PLATFORM_PATTERNS:
            if pattern.match(zellij_name):
                return platform
        return None

    def _load_session_file(self, pid: int) -> dict | None:
        path = SESSIONS_DIR / f"{pid}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _load_all_session_files(self) -> dict[int, dict]:
        if self._sessions_cache is None:
            self._sessions_cache = {}
            if SESSIONS_DIR.is_dir():
                for f in SESSIONS_DIR.glob("*.json"):
                    try:
                        pid = int(f.stem)
                        data = json.loads(f.read_text())
                        self._sessions_cache[pid] = data
                    except (ValueError, json.JSONDecodeError, OSError):
                        continue
        return self._sessions_cache

    # --- Active Zellij Sessions ---

    def list_zellij_sessions(self) -> list[str]:
        """List active zellij session names."""
        try:
            result = subprocess.run(
                ["zellij", "list-sessions", "--short", "--no-formatting"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return []

    # --- PID Extraction ---

    def _pid_from_zellij_name(self, name: str) -> Optional[int]:
        """Extract PID from zellij session name like 'claude_cli_95993'."""
        match = re.search(r'_(\d{4,6})$', name)
        if match:
            return int(match.group(1))
        return None

    # --- TTY-based UUID Discovery ---

    def _discover_uuid_by_tty(self, zellij_session: str) -> Optional[str]:
        """Discover Claude session UUID by matching TTY between zellij child and session files.

        Algorithm (ported from UnifiedCLI Electron app):
        1. Find the zellij-server process for this session
        2. Find its direct shell child process
        3. Get that child's TTY
        4. Check each PID in ~/.claude/sessions/ for the same TTY
        5. Return the matching UUID
        """
        try:
            # Step 1: Find zellij server PID for this session
            ps_result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            server_pid = None
            for line in ps_result.stdout.split("\n"):
                if "zellij" in line and zellij_session in line and "server" in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        server_pid = parts[1]
                        break

            if not server_pid:
                return None

            # Step 2: Find direct child of the server (the shell process)
            ppid_result = subprocess.run(
                ["ps", "-eo", "pid,ppid"], capture_output=True, text=True, timeout=5
            )
            child_pid = None
            for line in ppid_result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) == 2 and parts[1] == server_pid:
                    child_pid = parts[0].strip()
                    break

            if not child_pid:
                return None

            # Step 3: Get the child's TTY
            tty_result = subprocess.run(
                ["ps", "-o", "tty=", "-p", child_pid],
                capture_output=True, text=True, timeout=5
            )
            child_tty = tty_result.stdout.strip()
            if not child_tty or child_tty == "??":
                return None

            # Step 4: Check each session file PID for the same TTY
            sessions = self._load_all_session_files()
            for file_pid, data in sessions.items():
                try:
                    pid_tty_result = subprocess.run(
                        ["ps", "-o", "tty=", "-p", str(file_pid)],
                        capture_output=True, text=True, timeout=2
                    )
                    pid_tty = pid_tty_result.stdout.strip()
                    if pid_tty and pid_tty == child_tty:
                        return data.get("sessionId")
                except (subprocess.TimeoutExpired, OSError):
                    continue

        except (subprocess.TimeoutExpired, OSError):
            pass

        return None

    def _discover_uuid_from_transcript(self, zellij_session: str) -> Optional[str]:
        """Fallback: extract UUID from zellij transcript file."""
        transcript_dir = Path.home() / ".zellij" / "transcripts"
        transcript = transcript_dir / f"{zellij_session}.log"
        if not transcript.exists():
            return None

        uuid_re = re.compile(r'Session(?:\s+ID)?:\s*([0-9a-f-]{36})', re.IGNORECASE)
        try:
            # Read last 50KB — UUID from /status output should be near the end
            size = transcript.stat().st_size
            read_size = min(size, 50 * 1024)
            with open(transcript, "rb") as f:
                f.seek(max(0, size - read_size))
                data = f.read().decode("utf-8", errors="replace")
            match = uuid_re.search(data)
            if match:
                return match.group(1)
        except OSError:
            pass
        return None

    # --- Core Resolution ---

    def resolve(self, *,
                uuid: str | None = None,
                zellij_session: str | None = None,
                alias: str | None = None,
                pid: int | None = None) -> SessionInfo:
        """Resolve a session from any known identifier.

        Provide one of: uuid, zellij_session, alias, or pid.
        Returns a SessionInfo with as many fields populated as possible.
        """
        info = SessionInfo()

        # --- Start from PID ---
        if pid is not None:
            info.pid = pid
            # Get UUID from session file
            session_data = self._load_session_file(pid)
            if session_data:
                info.uuid = session_data.get("sessionId")
                info.working_dir = session_data.get("cwd")
            # Get zellij + metadata from registry
            registry = self._load_registry()
            reg_entry = registry.get(str(pid), {})
            if reg_entry:
                info.zellij_session = reg_entry.get("zellij_session")
                info.platform = reg_entry.get("platform")
                info.status = reg_entry.get("status")
                info.uuid = info.uuid or reg_entry.get("uuid")
                info.working_dir = info.working_dir or reg_entry.get("working_dir")

        # --- Start from Zellij Session Name ---
        if zellij_session is not None:
            info.zellij_session = zellij_session
            # Try to get PID from name
            extracted_pid = self._pid_from_zellij_name(zellij_session)
            if extracted_pid and not info.pid:
                info.pid = extracted_pid
                # Recurse with PID to fill more fields
                pid_info = self.resolve(pid=extracted_pid)
                info.uuid = info.uuid or pid_info.uuid
                info.platform = info.platform or pid_info.platform
                info.status = info.status or pid_info.status
                info.working_dir = info.working_dir or pid_info.working_dir

            # Also check registry by scanning for matching zellij_session
            if not info.pid:
                registry = self._load_registry()
                for reg_pid, entry in registry.items():
                    if entry.get("zellij_session") == zellij_session:
                        info.pid = int(reg_pid)
                        info.uuid = info.uuid or entry.get("uuid")
                        info.platform = info.platform or entry.get("platform")
                        info.status = info.status or entry.get("status")
                        break

        # --- Start from UUID ---
        if uuid is not None:
            info.uuid = uuid
            # Check session files for matching UUID
            if not info.pid:
                for file_pid, data in self._load_all_session_files().items():
                    if data.get("sessionId") == uuid:
                        info.pid = file_pid
                        info.working_dir = info.working_dir or data.get("cwd")
                        break
            # Check registry for matching UUID
            if not info.zellij_session:
                registry = self._load_registry()
                for reg_pid, entry in registry.items():
                    if entry.get("uuid") == uuid:
                        info.zellij_session = entry.get("zellij_session")
                        info.pid = info.pid or int(reg_pid)
                        info.platform = info.platform or entry.get("platform")
                        info.status = info.status or entry.get("status")
                        break

        # --- Metadata stores (electron + unified-cli) ---
        # Search both stores for matching session by zellij name or UUID
        for meta_store in (self._load_electron_meta(), self._load_unified_meta()):
            for meta_id, meta in meta_store.items():
                if not isinstance(meta, dict):
                    continue
                match = False
                if info.zellij_session and meta.get("zellij_session") == info.zellij_session:
                    match = True
                elif info.zellij_session and meta.get("name") == info.zellij_session:
                    match = True
                elif info.uuid and meta_id == info.uuid:
                    match = True
                if match:
                    info.alias = info.alias or meta.get("name")
                    info.claude_session_id = info.claude_session_id or meta.get("claude_session_id")
                    info.zellij_session = info.zellij_session or meta.get("zellij_session")
                    info.platform = info.platform or meta.get("platform")
                    info.working_dir = info.working_dir or meta.get("working_dir")
                    info.status = info.status or ("running" if meta.get("last_activity") else None)
                    break

        # --- Start from Alias ---
        if alias is not None and not info.zellij_session:
            for meta_store in (self._load_electron_meta(), self._load_unified_meta()):
                for meta_id, meta in meta_store.items():
                    if not isinstance(meta, dict):
                        continue
                    if meta.get("name") == alias:
                        info.alias = alias
                        info.zellij_session = meta.get("zellij_session")
                        info.claude_session_id = meta.get("claude_session_id")
                        info.platform = info.platform or meta.get("platform")
                        if info.zellij_session and not info.pid:
                            more = self.resolve(zellij_session=info.zellij_session)
                            info.pid = more.pid
                            info.uuid = info.uuid or more.uuid
                            info.platform = info.platform or more.platform
                            info.status = info.status or more.status
                            info.working_dir = info.working_dir or more.working_dir
                        break

        # --- Platform inference from zellij name ---
        if not info.platform and info.zellij_session:
            info.platform = self._infer_platform(info.zellij_session)

        # --- UUID discovery via TTY matching (non-intrusive) ---
        if not info.uuid and info.zellij_session:
            info.uuid = self._discover_uuid_by_tty(info.zellij_session)

        # --- UUID fallback: transcript parsing ---
        if not info.uuid and info.zellij_session:
            info.uuid = self._discover_uuid_from_transcript(info.zellij_session)

        return info

    # --- Convenience Methods ---

    def get_uuid(self, *, zellij_session: str | None = None,
                 alias: str | None = None, pid: int | None = None) -> str | None:
        """Get AI session UUID from any other identifier."""
        info = self.resolve(zellij_session=zellij_session, alias=alias, pid=pid)
        return info.uuid

    def get_zellij_session(self, *, uuid: str | None = None,
                           alias: str | None = None, pid: int | None = None) -> str | None:
        """Get zellij session name from any other identifier."""
        info = self.resolve(uuid=uuid, alias=alias, pid=pid)
        return info.zellij_session

    def get_alias(self, *, uuid: str | None = None,
                  zellij_session: str | None = None, pid: int | None = None) -> str | None:
        """Get alias (display name) from any other identifier."""
        info = self.resolve(uuid=uuid, zellij_session=zellij_session, pid=pid)
        return info.alias

    def get_self(self) -> SessionInfo:
        """Detect the current session's identity.

        Uses ZELLIJ_SESSION_NAME env var if inside zellij, otherwise
        tries to determine from parent PID chain.
        """
        zellij_name = os.environ.get("ZELLIJ_SESSION_NAME")
        if zellij_name:
            return self.resolve(zellij_session=zellij_name)

        # Fallback: try own PID or parent PID
        pid = os.getpid()
        ppid = os.getppid()
        for try_pid in (pid, ppid):
            info = self.resolve(pid=try_pid)
            if info.zellij_session or info.uuid:
                return info

        return SessionInfo()

    def get_parent(self, *, uuid: str | None = None,
                   zellij_session: str | None = None,
                   alias: str | None = None, pid: int | None = None) -> SessionInfo | None:
        """Get the parent session that spawned this one.

        Checks three sources for parent linkage:
        1. spawned_by field in unified-cli metadata (UUID → parent UUID)
        2. CLI_PARENT_PID env var (if resolving self)
        3. parent_pid in session registry

        Returns None if session has no parent (top-level / user-launched).
        """
        child = self.resolve(uuid=uuid, zellij_session=zellij_session, alias=alias, pid=pid)

        # Check unified-cli metadata for spawned_by (UUID linkage)
        for meta_store in (self._load_unified_meta(), self._load_electron_meta()):
            for meta_id, meta in meta_store.items():
                if not isinstance(meta, dict):
                    continue
                match = False
                if child.zellij_session and meta.get("zellij_session") == child.zellij_session:
                    match = True
                elif child.uuid and meta_id == child.uuid:
                    match = True
                if match:
                    parent_uuid = meta.get("spawned_by")
                    if parent_uuid:
                        return self.resolve(uuid=parent_uuid)
                    break

        # Check session registry for parent_pid
        if child.pid:
            registry = self._load_registry()
            reg_entry = registry.get(str(child.pid), {})
            parent_pid = reg_entry.get("parent_pid")
            if parent_pid:
                return self.resolve(pid=int(parent_pid))

        # Check env var as last resort (only meaningful for self)
        parent_env = os.environ.get("CLI_PARENT_PID")
        if parent_env and parent_env.isdigit():
            return self.resolve(pid=int(parent_env))

        return None

    def set_alias(self, zellij_session: str, alias: str) -> bool:
        """Set the display name (alias) for a session in the unified-cli metadata store."""
        if not UNIFIED_META_FILE.exists():
            return False
        try:
            data = json.loads(UNIFIED_META_FILE.read_text())
            sessions = data.get("sessions", {})
            for meta_id, meta in sessions.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("zellij_session") == zellij_session or meta.get("name") == zellij_session:
                    meta["name"] = alias
                    with open(UNIFIED_META_FILE, "w") as f:
                        json.dump(data, f, indent=2)
                    # Invalidate cache
                    self._unified_meta = None
                    return True
        except (json.JSONDecodeError, OSError):
            pass
        return False

    def list_all(self, active_only: bool = True) -> list[SessionInfo]:
        """List all known sessions, optionally filtered to active zellij sessions."""
        active_zellij = set(self.list_zellij_sessions()) if active_only else None
        results = []
        seen_zellij = set()

        registry = self._load_registry()
        for reg_pid, entry in registry.items():
            zs = entry.get("zellij_session")
            if active_only and zs and zs not in active_zellij:
                continue
            info = self.resolve(pid=int(reg_pid))
            if zs:
                seen_zellij.add(zs)
            results.append(info)

        # Add any active zellij sessions not in registry
        if active_zellij:
            for zs in active_zellij - seen_zellij:
                results.append(self.resolve(zellij_session=zs))

        return results


# --- CLI Interface ---

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="session_identity",
        description="Resolve CLI session identities between UUID, zellij session, and alias."
    )
    sub = parser.add_subparsers(dest="command")

    # resolve
    resolve_p = sub.add_parser("resolve", help="Resolve a session from any identifier")
    resolve_p.add_argument("--uuid", help="AI session UUID")
    resolve_p.add_argument("--zellij", help="Zellij session name")
    resolve_p.add_argument("--alias", help="Display name / alias")
    resolve_p.add_argument("--pid", type=int, help="Process ID")
    resolve_p.add_argument("--self", action="store_true", dest="detect_self", help="Detect own session")
    resolve_p.add_argument("--json", action="store_true", help="JSON output")

    # parent
    parent_p = sub.add_parser("parent", help="Get the parent session that spawned this one")
    parent_p.add_argument("--uuid", help="Child AI session UUID")
    parent_p.add_argument("--zellij", help="Child zellij session name")
    parent_p.add_argument("--alias", help="Child display name / alias")
    parent_p.add_argument("--pid", type=int, help="Child process ID")
    parent_p.add_argument("--self", action="store_true", dest="detect_self", help="Get parent of current session")
    parent_p.add_argument("--json", action="store_true", help="JSON output")

    # list
    list_p = sub.add_parser("list", help="List all sessions")
    list_p.add_argument("--all", action="store_true", help="Include stopped sessions")
    list_p.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    resolver = SessionResolver()

    if args.command == "resolve":
        if args.detect_self:
            info = resolver.get_self()
        elif args.uuid or args.zellij or args.alias or args.pid:
            info = resolver.resolve(
                uuid=args.uuid,
                zellij_session=args.zellij,
                alias=args.alias,
                pid=args.pid
            )
        else:
            parser.print_help()
            return 1

        if args.json:
            print(json.dumps(info.__dict__, indent=2, default=str))
        else:
            for k, v in info.__dict__.items():
                if v is not None:
                    print(f"{k}: {v}")
        return 0

    elif args.command == "parent":
        if args.detect_self:
            child = resolver.get_self()
            parent = resolver.get_parent(
                zellij_session=child.zellij_session, pid=child.pid, uuid=child.uuid)
        elif args.uuid or args.zellij or args.alias or args.pid:
            parent = resolver.get_parent(
                uuid=args.uuid, zellij_session=args.zellij,
                alias=args.alias, pid=args.pid)
        else:
            parser.print_help()
            return 1

        if parent is None:
            print("No parent session found (top-level session).", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps(parent.__dict__, indent=2, default=str))
        else:
            for k, v in parent.__dict__.items():
                if v is not None:
                    print(f"{k}: {v}")
        return 0

    elif args.command == "list":
        sessions = resolver.list_all(active_only=not args.all)
        if args.json:
            print(json.dumps([s.__dict__ for s in sessions], indent=2, default=str))
        else:
            fmt = "{:<8} {:<30} {:<40} {}"
            print(fmt.format("PID", "ZELLIJ", "UUID", "ALIAS"))
            print("-" * 100)
            for s in sessions:
                print(fmt.format(
                    str(s.pid or ""),
                    s.zellij_session or "",
                    s.uuid or "",
                    s.alias or ""
                ))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
