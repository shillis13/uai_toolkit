#!/usr/bin/env python3
"""
resolve_missing_uuids.py — Find CLI UUIDs for registry entries that are missing them.

Stateless: queries registry for entries without cli_session_id, then searches
session files (Codex/Gemini) for their Registry ID within the identity block.

Bounded search: only searches files created on or after the registry entry's
created_at timestamp. No log state needed.

Usage:
  python3 resolve_missing_uuids.py          # Find and fix missing UUIDs
  python3 resolve_missing_uuids.py --verify # Show what would be fixed
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import SessionRegistry from cli wrappers
CLI_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "cli"
if str(CLI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CLI_SCRIPTS))
# Fallback: try the known absolute path
if not CLI_SCRIPTS.exists():
    _fallback = Path.home() / "AI/ai_root/ai_general/scripts/cli"
    if str(_fallback) not in sys.path:
        sys.path.insert(0, str(_fallback))

from uai_toolkit.cli.lib_paths import UNIFIED_CLI_DIR
from uai_toolkit.session_mgmt.lib_session import list_registry, write_registry, update_session_info

LOG_FILE = UNIFIED_CLI_DIR / "session_uuid_watcher.log"

CODEX_SESSIONS_DIR = Path.home() / ".codex/sessions"
GEMINI_TMP_DIR = Path.home() / ".gemini/tmp"

IDENTITY_BLOCK_RE = re.compile(
    r'<<<SESSION_IDENTITY>>>(.*?)<<<END SESSION_IDENTITY>>>',
    re.DOTALL
)
# Match current identity block format: "CLI session ID: <uuid>"
CLI_SESSION_ID_RE = re.compile(r'CLI session ID:\s*([0-9a-f-]{36})')
ZELLIJ_RE = re.compile(r'Zellij session:\s*([a-zA-Z0-9][a-zA-Z0-9._-]+)')


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"{ts} | resolve_missing | {message}"
    print(entry)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def extract_uuid_from_codex_filename(filename: str) -> str | None:
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', filename)
    return m.group(1) if m else None


def extract_uuid_from_gemini_file(filepath: Path) -> str | None:
    try:
        data = json.loads(filepath.read_text())
        return data.get("sessionId")
    except Exception:
        return None


def find_zellij_in_file(filepath: Path, target_zellij: str) -> bool:
    """Check if a session file contains the target zellij session name within identity markers."""
    try:
        if filepath.suffix == '.jsonl':
            with open(filepath) as f:
                for i, line in enumerate(f):
                    if i > 50:
                        break
                    block = IDENTITY_BLOCK_RE.search(line)
                    if block:
                        m = ZELLIJ_RE.search(block.group(1))
                        if m and m.group(1) == target_zellij:
                            return True
        elif filepath.suffix == '.json':
            data = json.loads(filepath.read_text())
            for msg in data.get("messages", [])[:3]:
                content = str(msg.get("content", ""))
                block = IDENTITY_BLOCK_RE.search(content)
                if block:
                    m = ZELLIJ_RE.search(block.group(1))
                    if m and m.group(1) == target_zellij:
                        return True
        return False
    except Exception:
        return False


def get_session_files_since(created_at: str) -> list[tuple[Path, str]]:
    """Get Codex and Gemini session files created on or after the given timestamp.

    Returns list of (filepath, platform) tuples.
    """
    try:
        cutoff = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
    except Exception:
        cutoff = 0  # If we can't parse, search all

    files = []

    if CODEX_SESSIONS_DIR.exists():
        for f in CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"):
            if f.stat().st_mtime >= cutoff:
                files.append((f, "codex_cli"))

    if GEMINI_TMP_DIR.exists():
        for f in GEMINI_TMP_DIR.rglob("session-*.json"):
            if f.stat().st_mtime >= cutoff:
                files.append((f, "gemini_cli"))

    return files


def main():
    verify_only = "--verify" in sys.argv

    # Read from v3 registry (individual files)
    all_entries = list_registry()

    # Find entries missing CLI UUID (Codex/Gemini only — Claude uses --session-id)
    missing = []
    for entry in all_entries:
        if entry.get("cli_session_id"):
            continue
        platform = entry.get("platform", "")
        if platform not in ("codex_cli", "gemini_cli"):
            continue
        missing.append(entry)

    if not missing:
        print("No missing UUIDs for Codex/Gemini sessions.")
        return

    print(f"Found {len(missing)} session(s) missing CLI UUID:")
    for entry in missing:
        name = entry.get("zellij_session", "?")
        print(f"  {name} ({entry.get('platform')}, created {entry.get('created_at', '?')[:10]})")
    print()

    # For each missing entry, search session files
    fixes = []
    for entry in missing:
        name = entry.get("zellij_session", "?")
        created = entry.get("created_at", "2020-01-01T00:00:00Z")
        platform = entry.get("platform")

        candidates = get_session_files_since(created)
        candidates = [(f, p) for f, p in candidates if p == platform]

        matched_files = []
        for filepath, _ in candidates:
            if find_zellij_in_file(filepath, name):
                matched_files.append(filepath)

        if len(matched_files) == 1:
            f = matched_files[0]
            if platform == "codex_cli":
                cli_uuid = extract_uuid_from_codex_filename(f.name)
            else:
                cli_uuid = extract_uuid_from_gemini_file(f)

            if cli_uuid:
                fixes.append((entry, cli_uuid, f.name))
                print(f"  + {name} -> {cli_uuid[:16]}... (from {f.name})")
            else:
                print(f"  ? {name} — found file but can't extract UUID: {f.name}")
        elif len(matched_files) > 1:
            print(f"  ! {name} — multiple matches ({len(matched_files)} files). Skipping.")
        else:
            print(f"  - {name} — no matching session file found ({len(candidates)} candidates searched)")

    print()

    if not fixes:
        print("No fixes to apply.")
        return

    if verify_only:
        print(f"{len(fixes)} fix(es) would be applied. Run without --verify to apply.")
        return

    # Apply fixes to v3 registry + sessionInfo
    for entry, cli_uuid, filename in fixes:
        zellij = entry.get("zellij_session", "?")
        platform = entry.get("platform", "claude_cli")
        entry["cli_session_id"] = cli_uuid
        write_registry(zellij, entry)
        update_session_info(
            platform=platform,
            zellij_name=zellij,
            created_at=entry.get("created_at"),
            cli_session_id=cli_uuid,
        )
        log(f"{filename} | {cli_uuid} | {zellij} | UUID resolved")

    print(f"Applied {len(fixes)} fix(es).")


if __name__ == "__main__":
    main()
