#!/usr/bin/env python3
"""
discover_sessions.py — Build v3 session data from ground-truth platform sources.

Scans Claude/Codex/Gemini session files, extracts identity blocks, and writes
sessionInfo.json + registry files. Does NOT read session_metadata.json for
identity — only for supplementary display_name enrichment.

Modes: (default) skip existing, --upsert fill blanks, --force rebuild,
       --verify compare v3 to sources, --dry-run report only.

Spec: spec_discovery_process.md, spec_session_identity_v3.md sections 4.1-4.4
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_cli_scripts = Path(__file__).resolve().parent.parent / "scripts" / "cli"
if not _cli_scripts.exists():
    _cli_scripts = Path(__file__).resolve().parent.parent / "cli"
if str(_cli_scripts) not in sys.path:
    sys.path.insert(0, str(_cli_scripts))

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import get_logger, configure_logging

log = get_logger(__name__)

from uai_toolkit.cli.lib_paths import UNIFIED_CLI_DIR, SESSION_REGISTRY_DIR, SESSIONS_DIR
from uai_toolkit.session_mgmt.lib_session import (
    SCHEMA_VERSION,
    _atomic_write,
    _create_uuid_symlink,
    _segmented_path,
    create_session_dir,
    find_instance_file,
    instance_filename,
    write_registry,
    update_session_info,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCKFILE = UNIFIED_CLI_DIR.parent / ".discovery.lock"
QUARANTINE_FILE = UNIFIED_CLI_DIR.parent / "discovery_quarantine.json"

MODE_DEFAULT = "default"
MODE_UPSERT = "upsert"
MODE_FORCE = "force"

IDENTITY_RE = re.compile(
    r'<<<SESSION_IDENTITY>>>(.*?)<<<END SESSION_IDENTITY>>>', re.DOTALL
)
ZELLIJ_RE = re.compile(r'Zellij session:\s*([a-zA-Z0-9][a-zA-Z0-9._-]+)')
CLI_UUID_RE = re.compile(r'CLI session ID:\s*([0-9a-f-]{36})')
PARENT_ZELLIJ_RE = re.compile(r'Parent zellij:\s*([a-zA-Z0-9][a-zA-Z0-9._-]+)')
UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)

KNOWN_ROLES = frozenset({
    "dev_lead", "librarian", "researcher", "custodian",
    "peer_review", "tester", "validator",
})

# Only discover sessions from March 2026 onward (identity blocks didn't exist before)
MIN_DATE = "2026-03"


# ---------------------------------------------------------------------------
# Report (counts derived from lists — no redundant fields)
# ---------------------------------------------------------------------------

@dataclass
class Report:
    sessions: list[str] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)
    zellij_orphans: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    parents_unresolved: list[str] = field(default_factory=list)
    symlink_errors: list[str] = field(default_factory=list)
    subagent_count: int = 0
    multi_file_count: int = 0
    with_uuid: int = 0
    generated: int = 0
    matched: int = 0
    skipped: int = 0
    written: int = 0
    parents_resolved: int = 0


def _print_section(label: str, items: list, limit: int = 20, fmt=str) -> None:
    """Print a labeled count + optional item list."""
    print(f"  {label + ':':<42} {len(items)}")
    shown = items[:limit]
    for item in shown:
        print(f"    - {fmt(item)}")
    if len(items) > limit:
        print(f"    ({len(items) - limit} more...)")


# ---------------------------------------------------------------------------
# Identity extraction (single function, two axes: format x depth)
# ---------------------------------------------------------------------------

def _parse_identity(text: str) -> dict | None:
    """Extract identity fields from text containing SESSION_IDENTITY markers."""
    m = IDENTITY_RE.search(text)
    if not m:
        return None
    content = m.group(1)
    zellij_m = ZELLIJ_RE.search(content)
    if not zellij_m:
        return None
    uuid_m = CLI_UUID_RE.search(content)
    parent_m = PARENT_ZELLIJ_RE.search(content)
    result = {
        "zellij_session": zellij_m.group(1),
        "cli_session_id": uuid_m.group(1) if uuid_m else None,
        "parent_zellij": parent_m.group(1) if parent_m else None,
    }
    return result


def scan_for_identity(
    path: Path,
    max_lines: int | None = 200,
    match_zellij: str | None = None,
) -> tuple[dict | None, int]:
    """
    Scan a file for an identity block.

    Args:
        path: JSONL or JSON file.
        max_lines: Line/message limit. None = unbounded.
        match_zellij: If set, only accept blocks matching this zellij name.

    Returns:
        (identity_dict, layer) where layer is 1 (bounded) or 2 (deep).
    """
    layer = 1 if max_lines else 2
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text())
            for i, msg in enumerate(data.get("messages", [])):
                if max_lines and i >= max_lines:
                    break
                ib = _parse_identity(str(msg.get("content", "")))
                if ib and (not match_zellij or ib["zellij_session"] == match_zellij):
                    return ib, layer
        else:
            with open(path) as f:
                for i, line in enumerate(f):
                    if max_lines and i >= max_lines:
                        break
                    ib = _parse_identity(line)
                    if ib and (not match_zellij or ib["zellij_session"] == match_zellij):
                        return ib, layer
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return None, 0


def _layer4_pid_match(file_uuid: str | None, pid_metadata: dict[str, dict]) -> dict | None:
    """
    Layer 4: Match Claude sessions via PID -> process tree -> zellij server name.

    For each live PID whose sessionId matches file_uuid, walk up the process
    tree via pstree to find the zellij --server ancestor. The session name is
    the last path component of the server socket path.
    """
    if not file_uuid:
        return None
    for _pid_str, meta in pid_metadata.items():
        if meta.get("sessionId") != file_uuid:
            continue
        pid = meta.get("pid")
        if not pid:
            continue
        try:
            result = subprocess.run(
                ["pstree", "-p", str(pid)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            for line in result.stdout.split("\n"):
                if "zellij --server" in line:
                    # Extract session name: last component of the server path
                    parts = line.strip().split("/")
                    if parts:
                        zellij_name = parts[-1]
                        return {
                            "zellij_session": zellij_name,
                            "cli_session_id": file_uuid,
                            "parent_zellij": None,
                        }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    return None


def extract_identity(
    pf: dict,
    zellij_sessions: dict[str, str],
    pid_metadata: dict[str, dict],
) -> tuple[dict | None, int]:
    """
    Layered identity extraction.

    Claude: first record ONLY (deeper records contain quoted specs/examples).
    Codex/Gemini: bounded -> deep -> transcript.
    All platforms: Layer 4 PID/pstree for live sessions.

    Returns (identity_dict, layer) or (None, 0).
    """
    path = pf["path"]
    platform = pf.get("platform", "")
    file_uuid = pf.get("uuid")

    if platform == "claude_cli":
        # Claude: FIRST RECORD ONLY. The wrapper injects the identity block
        # as the very first thing. Deeper records contain conversation content
        # that may include quoted identity blocks from specs, plans, and other
        # sessions — scanning beyond the first record produces false matches.
        ib, _ = scan_for_identity(path, max_lines=3)
        if ib:
            return ib, 1

        # Layer 4: live PID/process-tree matching
        ib = _layer4_pid_match(file_uuid, pid_metadata)
        if ib:
            return ib, 4

        return None, 0

    # Codex/Gemini: identity block may appear deeper (bootstrap prompt
    # is not always first record). Safe to deep-scan because these files
    # don't contain quoted specs with fake identity blocks.

    # Layer 1: bounded
    ib, _ = scan_for_identity(path, max_lines=200)
    if ib:
        return ib, 1

    # Layer 2: deep (full file)
    ib, _ = scan_for_identity(path, max_lines=None)
    if ib:
        return ib, 2

    # Layer 3: transcript fallback
    transcripts = Path.home() / ".zellij" / "transcripts"
    if transcripts.exists() and file_uuid:
        uuid8 = file_uuid.replace("-", "")[:8]
        for zname in zellij_sessions:
            if uuid8 in zname:
                for t in transcripts.iterdir():
                    if t.is_file() and zname in t.name:
                        ib, _ = scan_for_identity(t, max_lines=None, match_zellij=zname)
                        if ib:
                            return ib, 3

    return None, 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_before_cutoff(ts: str | None) -> bool:
    """True if timestamp predates MIN_DATE."""
    if not ts:
        return False
    return ts[:7] < MIN_DATE


def _read_first_jsonl(path: Path) -> dict | None:
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return None


def _claude_timestamp(path: Path) -> str | None:
    """Earliest timestamp from Claude JSONL content."""
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                try:
                    return json.loads(line.strip()).get("timestamp")
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeDecodeError):
        pass
    return None


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _derive_display_name(zellij_name: str) -> str:
    m = re.match(r'^(.+)_([0-9a-f]{8})$', zellij_name)
    return m.group(1) if m else zellij_name


def _derive_roles(zellij_name: str) -> list[str]:
    lower = zellij_name.lower()
    for role in KNOWN_ROLES:
        if role.replace("-", "_") in lower:
            return [role]
    return ["chat"]


def _extract_model(path: Path) -> str | None:
    try:
        with open(path) as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                try:
                    model = json.loads(line).get("model")
                    if model:
                        return model
                except json.JSONDecodeError:
                    continue
    except (OSError, UnicodeDecodeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Phase 1: Enumerate platform files
# ---------------------------------------------------------------------------

def enumerate_claude() -> tuple[list[dict], int]:
    """Returns (primary_files, subagent_count). Subagents filtered out."""
    files = []
    subagents = 0
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return files, 0

    for proj in projects.iterdir():
        if not proj.is_dir() or proj.name.startswith("."):
            continue
        for jsonl in proj.rglob("*.jsonl"):
            rel = jsonl.relative_to(proj)
            parts = rel.parts
            stem = jsonl.stem

            # Classify: subagent if nested under subagents/, or agent-* filename,
            # or content has isSidechain/agentId
            is_sub = "subagents" in parts or stem.startswith("agent-")
            if not is_sub:
                first = _read_first_jsonl(jsonl)
                if first and (first.get("isSidechain") or first.get("agentId")):
                    is_sub = True

            if is_sub:
                subagents += 1
                continue

            # UUID from path or content
            file_uuid = None
            if len(parts) == 1 and UUID_RE.match(stem):
                file_uuid = stem
            elif len(parts) >= 2 and UUID_RE.match(parts[0]):
                file_uuid = parts[0]
            if not file_uuid:
                first = first if not is_sub and 'first' in dir() else _read_first_jsonl(jsonl)
                if first:
                    sid = first.get("sessionId")
                    if sid and UUID_RE.match(sid):
                        file_uuid = sid

            ts = _claude_timestamp(jsonl) or _mtime(jsonl)
            if _is_before_cutoff(ts):
                continue
            files.append({
                "path": jsonl, "platform": "claude_cli",
                "uuid": file_uuid, "created_at": ts, "cwd": str(proj),
            })

    return files, subagents


def enumerate_codex() -> list[dict]:
    files = []
    base = Path.home() / ".codex" / "sessions"
    if not base.exists():
        return files

    for jsonl in base.rglob("rollout-*.jsonl"):
        parts = jsonl.stem.split("-")
        file_uuid = None
        ts = None

        # UUID from filename (last 5 groups)
        if len(parts) >= 5:
            candidate = "-".join(parts[-5:])
            if UUID_RE.match(candidate):
                file_uuid = candidate

        # Content fallback for UUID + timestamp + source (single read)
        first = _read_first_jsonl(jsonl)
        if first and first.get("type") == "session_meta":
            payload = first.get("payload", {})
            ts = payload.get("timestamp")
            # Skip MCP-spawned sessions (Codex tool calls from Desktop Claude)
            if payload.get("source") == "mcp":
                continue
            if not file_uuid:
                cid = payload.get("id")
                if cid and UUID_RE.match(cid):
                    file_uuid = cid

        if not file_uuid:
            continue

        if not ts:
            ts = _mtime(jsonl)

        if _is_before_cutoff(ts):
            continue

        files.append({
            "path": jsonl, "platform": "codex_cli",
            "uuid": file_uuid, "created_at": ts, "cwd": None,
        })

    return files


def enumerate_gemini() -> list[dict]:
    files = []
    base = Path.home() / ".gemini" / "tmp"
    if not base.exists():
        return files

    for jf in base.rglob("session-*.json"):
        file_uuid = None
        ts = None
        try:
            data = json.loads(jf.read_text())
            file_uuid = data.get("sessionId")
            ts = data.get("startTime")
        except (json.JSONDecodeError, OSError):
            pass
        if not ts:
            ts = _mtime(jf)

        if _is_before_cutoff(ts):
            continue

        files.append({
            "path": jf, "platform": "gemini_cli",
            "uuid": file_uuid, "created_at": ts, "cwd": None,
        })

    return files


def enumerate_claude_pids() -> dict[str, dict]:
    pids = {}
    base = Path.home() / ".claude" / "sessions"
    if not base.exists():
        return pids
    for f in base.iterdir():
        if f.suffix != ".json":
            continue
        try:
            d = json.loads(f.read_text())
            sid = d.get("sessionId")
            if sid:
                pids[str(d.get("pid"))] = d
        except (json.JSONDecodeError, OSError):
            continue
    return pids


# ---------------------------------------------------------------------------
# Phase 0: Conflicts
# ---------------------------------------------------------------------------

def check_conflicts(identities: dict[str, dict]) -> list[str]:
    """Fail-fast on duplicate zellij names with conflicting UUIDs, or shared UUIDs."""
    conflicts = []

    # By zellij: multiple files OK only if same CLI UUID
    by_zellij: dict[str, list[tuple[str, str | None]]] = {}
    for path, ib in identities.items():
        by_zellij.setdefault(ib["zellij_session"], []).append(
            (path, ib.get("cli_session_id"))
        )
    for zname, entries in by_zellij.items():
        uuids = {u for _, u in entries if u}
        if len(uuids) > 1:
            conflicts.append(
                f"zellij '{zname}' has conflicting UUIDs {uuids} "
                f"in {[p for p, _ in entries]}"
            )

    # By UUID: should map to exactly one zellij
    by_uuid: dict[str, set[str]] = {}
    for _, ib in identities.items():
        if ib.get("cli_session_id"):
            by_uuid.setdefault(ib["cli_session_id"], set()).add(ib["zellij_session"])
    for uid, znames in by_uuid.items():
        if len(znames) > 1:
            conflicts.append(f"UUID '{uid}' claimed by {znames}")

    return conflicts


# ---------------------------------------------------------------------------
# Phase 4: Build sessions
# ---------------------------------------------------------------------------

def _generate_zellij_name(platform: str, uuid: str, existing: set[str]) -> str:
    """Generate a discoverable zellij name from platform + UUID.

    Format: {platform}_disc_{uuid8}. On collision, extend with more UUID chars.
    """
    uuid8 = uuid.replace("-", "")[:8]
    candidate = f"{platform}_disc_{uuid8}"
    if candidate not in existing:
        return candidate
    # Extend on collision (extremely unlikely)
    for length in (12, 16, 32):
        candidate = f"{platform}_disc_{uuid.replace('-', '')[:length]}"
        if candidate not in existing:
            return candidate
    return candidate


def build_sessions(
    files: list[dict],
    identities: dict[str, dict],
    pids: dict[str, dict],
    zellij_sessions: dict[str, str],
    report: Report,
) -> dict[str, dict]:
    """Group files by zellij session, resolve parents, build session dicts."""
    supplementary = _load_supplementary_names()

    # Group files with identity blocks by zellij_session
    grouped: dict[str, list[tuple[dict, dict]]] = {}
    # Files without identity blocks, grouped by {platform, uuid} for name generation
    no_identity: dict[str, list[dict]] = {}

    for pf in files:
        key = str(pf["path"])
        ib = identities.get(key)
        if ib:
            grouped.setdefault(ib["zellij_session"], []).append((pf, ib))
        elif pf.get("uuid"):
            group_key = f"{pf['platform']}:{pf['uuid']}"
            no_identity.setdefault(group_key, []).append(pf)
        else:
            report.quarantined.append({
                "path": str(pf["path"]), "platform": pf["platform"],
                "uuid": None, "reason": "no_identity_block_no_uuid",
            })

    sessions = {}

    # Build sessions from identity-block matches
    for zname, entries in grouped.items():
        entries.sort(key=lambda x: x[0].get("created_at") or "")
        first_pf, first_ib = entries[0]
        latest_pf = entries[-1][0]

        cli_uuid = next(
            (ib.get("cli_session_id") for _, ib in entries if ib.get("cli_session_id")),
            first_pf.get("uuid"),
        )

        cwd = next((pf.get("cwd") for pf, _ in entries if pf.get("cwd")), None)
        if not cwd and cli_uuid:
            for meta in pids.values():
                if meta.get("sessionId") == cli_uuid:
                    cwd = meta.get("cwd")
                    break

        sessions[zname] = {
            "zellij_session": zname,
            "cli_session_id": cli_uuid,
            "platform": first_pf["platform"],
            "parent_zellij": first_ib.get("parent_zellij"),
            "parent_cli_session_id": None,
            "created_at": first_pf.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "display_name": supplementary.get(zname) or _derive_display_name(zname),
            "working_dir": cwd,
            "model": _extract_model(latest_pf["path"]),
            "roles": _derive_roles(zname),
            "name_origin": "wrapper",
            "files": [pf["path"] for pf, _ in entries],
            "primary_file": latest_pf["path"],
        }
        report.sessions.append(zname)
        if cli_uuid:
            report.with_uuid += 1
        if len(entries) > 1:
            report.multi_file_count += 1

    # Step 3: Match orphaned zellij names to unmatched UUIDs BEFORE generating names.
    # Two methods: uuid8 correlation (strong) and session_metadata.json fallback (weak).
    matched_uuids = {s["cli_session_id"] for s in sessions.values() if s.get("cli_session_id")}
    orphan_znames = [z for z in zellij_sessions if z not in sessions]
    meta_map = _load_supplementary_uuid_map()  # zellij_name -> cli_session_id from session_metadata.json

    for zname in orphan_znames:
        # Extract uuid8(s) from zellij name — last _[0-9a-f]{8} segment(s)
        uuid8s = re.findall(r'_([0-9a-f]{8})(?=_|$)', zname)

        matched_key = None
        matched_pfs = None

        # Try uuid8 correlation first (strong signal)
        for uuid8 in reversed(uuid8s):  # last uuid8 is the session's own
            for group_key, pf_list in no_identity.items():
                _, cli_uuid = group_key.split(":", 1)
                if cli_uuid in matched_uuids:
                    continue
                if cli_uuid.replace("-", "").startswith(uuid8):
                    matched_key = group_key
                    matched_pfs = pf_list
                    break
            if matched_key:
                break

        # Fallback: session_metadata.json mapping
        if not matched_key and zname in meta_map:
            meta_uuid = meta_map[zname]
            candidate_key = None
            for group_key, pf_list in no_identity.items():
                _, cli_uuid = group_key.split(":", 1)
                if cli_uuid == meta_uuid and cli_uuid not in matched_uuids:
                    candidate_key = group_key
                    matched_pfs = pf_list
                    break
            if candidate_key:
                matched_key = candidate_key

        if matched_key and matched_pfs:
            _, cli_uuid = matched_key.split(":", 1)
            platform = matched_pfs[0]["platform"]
            matched_uuids.add(cli_uuid)
            del no_identity[matched_key]

            matched_pfs.sort(key=lambda x: x.get("created_at") or "")
            first_pf = matched_pfs[0]
            latest_pf = matched_pfs[-1]

            cwd = next((pf.get("cwd") for pf in matched_pfs if pf.get("cwd")), None)
            if not cwd:
                for meta in pids.values():
                    if meta.get("sessionId") == cli_uuid:
                        cwd = meta.get("cwd")
                        break

            # Derive parent from name structure: parent_uuid8_child_uuid8
            parent_zellij = None
            if len(uuid8s) >= 2:
                # Name has parent lineage: everything before the last _uuid8 is the parent name
                last_suffix = f"_{uuid8s[-1]}"
                if zname.endswith(last_suffix):
                    parent_zellij = zname[:-len(last_suffix)]

            sessions[zname] = {
                "zellij_session": zname,
                "cli_session_id": cli_uuid,
                "platform": platform,
                "parent_zellij": parent_zellij,
                "parent_cli_session_id": None,
                "created_at": first_pf.get("created_at") or datetime.now(timezone.utc).isoformat(),
                "display_name": supplementary.get(zname) or _derive_display_name(zname),
                "working_dir": cwd,
                "model": _extract_model(latest_pf["path"]),
                "roles": _derive_roles(zname),
                "name_origin": "matched",
                "files": [pf["path"] for pf in matched_pfs],
                "primary_file": latest_pf["path"],
            }
            report.sessions.append(zname)
            report.with_uuid += 1
            report.matched += 1
            if len(matched_pfs) > 1:
                report.multi_file_count += 1

    # Step 4: Generate names for remaining unmatched UUIDs
    existing_names = set(sessions.keys())
    for group_key, pf_list in no_identity.items():
        platform, cli_uuid = group_key.split(":", 1)

        # Skip if this UUID already has a session
        if cli_uuid in matched_uuids:
            continue

        zname = _generate_zellij_name(platform, cli_uuid, existing_names)
        existing_names.add(zname)

        pf_list.sort(key=lambda x: x.get("created_at") or "")
        first_pf = pf_list[0]
        latest_pf = pf_list[-1]

        cwd = next((pf.get("cwd") for pf in pf_list if pf.get("cwd")), None)
        if not cwd:
            for meta in pids.values():
                if meta.get("sessionId") == cli_uuid:
                    cwd = meta.get("cwd")
                    break

        sessions[zname] = {
            "zellij_session": zname,
            "cli_session_id": cli_uuid,
            "platform": platform,
            "parent_zellij": None,
            "parent_cli_session_id": None,
            "created_at": first_pf.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "display_name": supplementary.get(zname) or _derive_display_name(zname),
            "working_dir": cwd,
            "model": _extract_model(latest_pf["path"]),
            "roles": ["chat"],
            "name_origin": "generated",
            "files": [pf["path"] for pf in pf_list],
            "primary_file": latest_pf["path"],
        }
        report.sessions.append(zname)
        report.with_uuid += 1
        report.generated += 1
        if len(pf_list) > 1:
            report.multi_file_count += 1

    # Second pass: resolve parent UUIDs
    for s in sessions.values():
        if s["parent_zellij"]:
            parent = sessions.get(s["parent_zellij"])
            if parent:
                s["parent_cli_session_id"] = parent["cli_session_id"]
                report.parents_resolved += 1
            else:
                report.parents_unresolved.append(
                    f"{s['zellij_session']} -> {s['parent_zellij']}"
                )

    return sessions


def _load_supplementary_names() -> dict[str, str]:
    meta = UNIFIED_CLI_DIR / "session_metadata.json"
    if not meta.exists():
        return {}
    try:
        data = json.loads(meta.read_text())
        result = {}
        for entry in data.get("sessions", {}).values():
            z = entry.get("zellij_session")
            d = entry.get("display_name")
            if z and d:
                result[z] = d
        return result
    except (json.JSONDecodeError, OSError):
        return {}


def _load_supplementary_uuid_map() -> dict[str, str]:
    """Load zellij_name -> cli_session_id from session_metadata.json.

    Used as fallback for matching orphaned zellij names to unmatched UUIDs
    when uuid8 correlation fails (pre-correlated-naming sessions).
    """
    meta = UNIFIED_CLI_DIR / "session_metadata.json"
    if not meta.exists():
        return {}
    try:
        data = json.loads(meta.read_text())
        result = {}
        for entry in data.get("sessions", {}).values():
            z = entry.get("zellij_session")
            u = entry.get("cli_session_id")
            if z and u:
                result[z] = u
        return result
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Phase 5: Write (delegates to lib_session)
# ---------------------------------------------------------------------------

def write_session(session: dict, mode: str, dry_run: bool, report: Report) -> None:
    zname = session["zellij_session"]
    platform = session["platform"]
    year = (session.get("created_at") or "")[:4] or str(datetime.now().year)
    session_dir = SESSIONS_DIR / platform / year / zname
    info_file = find_instance_file(session_dir, "sessionInfo", "json")

    if info_file and mode == MODE_DEFAULT:
        report.skipped += 1
        return

    if info_file and mode == MODE_UPSERT:
        try:
            existing = json.loads(info_file.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
        changed = False
        updates = {}
        if not existing.get("cli_session_id") and session["cli_session_id"]:
            updates["cli_session_id"] = session["cli_session_id"]
            changed = True
        if not existing.get("parent_cli_session_id") and session["parent_cli_session_id"]:
            updates["parent_cli_session_id"] = session["parent_cli_session_id"]
            changed = True
        if changed and not dry_run:
            update_session_info(platform, zname, created_at=session.get("created_at"), **updates)
            write_registry(zname, session)
        if changed:
            report.written += 1
        else:
            report.skipped += 1
        return

    if dry_run:
        report.written += 1
        return

    # Full write via lib_session
    session_dir = create_session_dir(
        platform, zname,
        cli_session_id=session["cli_session_id"],
        parent_zellij=session.get("parent_zellij"),
        parent_cli_session_id=session.get("parent_cli_session_id"),
        display_name=session["display_name"],
        working_dir=session.get("working_dir"),
        model=session.get("model"),
        roles=session.get("roles"),
        name_origin=session.get("name_origin", "wrapper"),
        created_at=session.get("created_at"),
    )

    # Chat history symlinks
    primary = session.get("primary_file")
    if primary and primary.exists():
        link = session_dir / "chat_history.jsonl"
        if link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(primary)
        except OSError as e:
            report.symlink_errors.append(f"{link}: {e}")

    all_files = session.get("files", [])
    if all_files:
        hist = session_dir / "chat_history"
        hist.mkdir(exist_ok=True)
        for fp in all_files:
            if fp.exists():
                lnk = hist / f"{fp.stem}{fp.suffix}"
                if not lnk.exists():
                    try:
                        lnk.symlink_to(fp)
                    except OSError as e:
                        report.symlink_errors.append(f"{lnk}: {e}")

    # Registry (derived from session identity fields)
    write_registry(zname, session)
    report.written += 1


# ---------------------------------------------------------------------------
# Phase 6: Report + quarantine persistence
# ---------------------------------------------------------------------------

def print_report(report: Report, dry_run: bool = False) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Discovery Report")
    print("=" * 60)
    print(f"  {'Sessions discovered:':<42} {len(report.sessions)}")
    print(f"  {'With confirmed UUID:':<42} {report.with_uuid}")
    print(f"  {'Matched (zellij name <-> UUID):':<42} {report.matched}")
    print(f"  {'Generated names (remaining):':<42} {report.generated}")
    _print_section("Quarantined (no UUID, no identity)", report.quarantined,
                   fmt=lambda q: f"{Path(q['path']).name}: {q['reason']}")
    _print_section("Zellij orphans", report.zellij_orphans)
    print(f"  {'Subagent files classified:':<42} {report.subagent_count}")
    print(f"  {'Parent refs resolved:':<42} {report.parents_resolved}")
    _print_section("Parent refs unresolved", report.parents_unresolved)
    print(f"  {'Multi-file sessions:':<42} {report.multi_file_count}")
    print(f"  {'Skipped (existing):':<42} {report.skipped}")
    print(f"  {'Written:':<42} {report.written}")
    if report.symlink_errors:
        _print_section("Symlink errors", report.symlink_errors)


def write_quarantine(report: Report) -> None:
    if not report.quarantined:
        return
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(report.quarantined),
        "entries": report.quarantined,
    }
    try:
        _atomic_write(QUARANTINE_FILE, data)
        print(f"  Quarantine report: {QUARANTINE_FILE}")
    except OSError as e:
        log.warning("quarantine write failed: %s", e)


# ---------------------------------------------------------------------------
# Verify mode
# ---------------------------------------------------------------------------

def verify_stores(identities: dict[str, dict]) -> bool:
    """Compare v3 stores against ground-truth identity blocks."""
    issues = 0
    total = 0

    # Ground truth: zellij -> cli_uuid
    gt = {}
    for _, ib in identities.items():
        if ib["zellij_session"] not in gt:
            gt[ib["zellij_session"]] = ib.get("cli_session_id")

    for plat in sorted(SESSIONS_DIR.iterdir()) if SESSIONS_DIR.exists() else []:
        if not plat.is_dir() or plat.name.startswith("."):
            continue
        for yr in sorted(plat.iterdir()):
            if not yr.is_dir():
                continue
            for sd in sorted(yr.iterdir()):
                if not sd.is_dir() or sd.is_symlink():
                    continue
                total += 1
                info_f = find_instance_file(sd, "sessionInfo", "json")
                if not info_f:
                    print(f"  MISSING sessionInfo: {sd.name}")
                    issues += 1
                    continue
                try:
                    info = json.loads(info_f.read_text())
                except (json.JSONDecodeError, OSError) as e:
                    print(f"  CORRUPT: {sd.name}: {e}")
                    issues += 1
                    continue
                if info.get("schema_version") != SCHEMA_VERSION:
                    print(f"  BAD schema: {sd.name}")
                    issues += 1
                gt_uuid = gt.get(sd.name)
                if gt_uuid and info.get("cli_session_id") != gt_uuid:
                    print(f"  UUID MISMATCH: {sd.name} v3={info.get('cli_session_id')} src={gt_uuid}")
                    issues += 1
                reg = SESSION_REGISTRY_DIR / plat.name / yr.name / f"{sd.name}.json"
                if not reg.exists():
                    print(f"  MISSING registry: {sd.name}")
                    issues += 1
                link = sd / "chat_history.jsonl"
                if link.is_symlink() and not link.resolve().exists():
                    print(f"  BROKEN link: {sd.name}/chat_history.jsonl")
                    issues += 1

    print(f"\nVerified {total} sessions, {issues} issues")
    return issues == 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def acquire_lock() -> int:
    LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCKFILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Lock held — another discovery running.")
        os.close(fd)
        sys.exit(1)
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def main():
    configure_logging()
    ap = argparse.ArgumentParser(description="Build v3 session data from platform sources.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--upsert", action="store_true", help="Fill missing fields only")
    g.add_argument("--force", action="store_true", help="Rebuild all (destructive)")
    g.add_argument("--verify", action="store_true", help="Read-only source comparison")
    ap.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    args = ap.parse_args()

    lock_fd = acquire_lock()
    try:
        _run(args)
    finally:
        os.close(lock_fd)
        try:
            os.unlink(str(LOCKFILE))
        except OSError:
            pass


def _run(args):
    mode = MODE_FORCE if args.force else (MODE_UPSERT if args.upsert else MODE_DEFAULT)
    dry_run = args.dry_run
    report = Report()

    # Phase 1
    print("Phase 1: Enumerating...")
    claude_files, sub_count = enumerate_claude()
    codex_files = enumerate_codex()
    gemini_files = enumerate_gemini()
    pids = enumerate_claude_pids()
    all_files = claude_files + codex_files + gemini_files
    report.subagent_count = sub_count
    print(f"  Claude: {len(claude_files)} primary, {sub_count} subagent")
    print(f"  Codex:  {len(codex_files)}  Gemini: {len(gemini_files)}  PIDs: {len(pids)}")

    # Phase 2
    print("Phase 2: Extracting identity...")
    zellij = {}
    try:
        r = subprocess.run(
            ["zellij", "list-sessions", "--no-formatting"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.strip().split()
            if parts:
                zellij[parts[0]] = "exited" if "EXITED" in line else "running"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    print(f"  Zellij: {len(zellij)}")

    identities: dict[str, dict] = {}
    for pf in all_files:
        ib, layer = extract_identity(pf, zellij, pids)
        if ib:
            identities[str(pf["path"])] = ib

    print(f"  Identity blocks: {len(identities)}/{len(all_files)}")

    # Verify mode
    if args.verify:
        ok = verify_stores(identities)
        sys.exit(0 if ok else 1)

    # Phase 0: conflicts (BEFORE any writes)
    print("Checking conflicts...")
    conflicts = check_conflicts(identities)
    report.conflicts = conflicts
    if conflicts:
        print(f"\nFATAL: {len(conflicts)} conflict(s). No writes.")
        for c in conflicts:
            print(f"  {c}")
        sys.exit(1)
    print("  Clean.")

    # Force: wipe AFTER conflict check
    if mode == MODE_FORCE and not dry_run:
        print("Force: clearing v3 data...")
        for base in [SESSION_REGISTRY_DIR, SESSIONS_DIR]:
            for sub in ["claude_cli", "codex_cli", "gemini_cli"]:
                t = base / sub
                if t.exists():
                    shutil.rmtree(t)

    # Phase 4
    print("Building sessions...")
    sessions = build_sessions(all_files, identities, pids, zellij, report)

    # Zellij orphans
    for z in zellij:
        if z not in sessions:
            report.zellij_orphans.append(z)

    # Phase 5
    label = "(dry run)" if dry_run else ""
    print(f"Writing {label}...")
    for s in sessions.values():
        write_session(s, mode, dry_run, report)

    # Phase 6
    print_report(report, dry_run)
    if not dry_run:
        write_quarantine(report)


if __name__ == "__main__":
    main()
