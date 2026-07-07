#!/usr/bin/env python3
"""
handle_new_session_file.py — Process a new Codex/Gemini session file.

Called by fswatch when a new file appears in ~/.codex/sessions/ or ~/.gemini/tmp/.
Reads the file, extracts the identity block (<<<SESSION_IDENTITY>>>), looks up
the Registry ID in the session registry, and writes the CLI UUID.

Usage:
  python3 handle_new_session_file.py <filepath>

Exit codes:
  0 — success (UUID updated or already correct)
  1 — error (file unreadable, no identity block, registry lookup failed)
  2 — skipped (not a session file, no identity block = not our session)
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import SessionRegistry
_cli_scripts = Path(__file__).resolve().parent.parent / "scripts" / "cli"
if not _cli_scripts.exists():
    _cli_scripts = Path.home() / "AI/ai_root/ai_general/scripts/cli"
if str(_cli_scripts) not in sys.path:
    sys.path.insert(0, str(_cli_scripts))

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
# Named `logger` (not `log`) — this module already defines a `log()` helper.
from uai_toolkit.common_utils.lib_logging import get_logger, configure_logging

logger = get_logger(__name__)

from uai_toolkit.cli.lib_paths import UNIFIED_CLI_DIR
from uai_toolkit.session_mgmt.lib_session import read_registry, write_registry, update_session_info

LOG_FILE = UNIFIED_CLI_DIR / "session_uuid_watcher.log"

IDENTITY_BLOCK_RE = re.compile(
    r'<<<SESSION_IDENTITY>>>(.*?)<<<END SESSION_IDENTITY>>>',
    re.DOTALL
)
CLI_SESSION_ID_RE = re.compile(r'CLI session ID:\s*([0-9a-f-]{36})')
ZELLIJ_RE = re.compile(r'Zellij session:\s*([a-zA-Z0-9][a-zA-Z0-9._-]+)')


def log(filepath: str, cli_uuid: str, zellij: str, action: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"{ts} | {filepath} | {cli_uuid} | {zellij} | {action}"
    logger.info(entry)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def extract_identity(text: str) -> dict | None:
    """Extract identity fields from within <<<SESSION_IDENTITY>>> markers."""
    block = IDENTITY_BLOCK_RE.search(text)
    if not block:
        return None
    content = block.group(1)
    result = {}
    m = CLI_SESSION_ID_RE.search(content)
    if m:
        result["cli_session_id"] = m.group(1)
    m = ZELLIJ_RE.search(content)
    if m:
        result["zellij_session"] = m.group(1)
    return result if result else None


def extract_cli_uuid_codex(filepath: Path) -> str | None:
    """Extract CLI UUID from Codex filename: rollout-DATE-UUID.jsonl"""
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', filepath.name)
    return m.group(1) if m else None


def extract_cli_uuid_gemini(filepath: Path) -> str | None:
    """Extract CLI UUID from Gemini session file (sessionId field)."""
    try:
        data = json.loads(filepath.read_text())
        return data.get("sessionId")
    except Exception:
        return None


def process_codex_file(filepath: Path) -> int:
    """Process a Codex JSONL session file."""
    cli_uuid = extract_cli_uuid_codex(filepath)
    if not cli_uuid:
        log(filepath.name, "-", "-", "Skip: can't extract UUID from filename")
        return 2

    # Search first 50 lines for identity block
    identity = None
    try:
        with open(filepath) as f:
            for i, line in enumerate(f):
                if i > 50:
                    break
                identity = extract_identity(line)
                if identity:
                    break
    except Exception as e:
        log(filepath.name, cli_uuid, "-", f"Error: can't read file: {e}")
        return 1

    if not identity:
        log(filepath.name, cli_uuid, "-", "Skip: no identity block (not launched via wrapper)")
        return 2

    return update_registry(filepath.name, cli_uuid, identity)


def process_gemini_file(filepath: Path) -> int:
    """Process a Gemini JSON session file."""
    cli_uuid = extract_cli_uuid_gemini(filepath)
    if not cli_uuid:
        log(filepath.name, "-", "-", "Skip: can't extract UUID from file")
        return 2

    # Search first 3 messages for identity block
    identity = None
    try:
        data = json.loads(filepath.read_text())
        for msg in data.get("messages", [])[:3]:
            content = str(msg.get("content", ""))
            identity = extract_identity(content)
            if identity:
                break
    except Exception as e:
        log(filepath.name, cli_uuid, "-", f"Error: can't read file: {e}")
        return 1

    if not identity:
        log(filepath.name, cli_uuid, "-", "Skip: no identity block (not launched via wrapper)")
        return 2

    return update_registry(filepath.name, cli_uuid, identity)


def update_registry(filename: str, cli_uuid: str, identity: dict) -> int:
    """Look up session in v3 registry and write CLI UUID."""
    zellij = identity.get("zellij_session", "?")

    reg_entry = read_registry(zellij) if zellij and zellij != "?" else None
    if not reg_entry:
        log(filename, cli_uuid, zellij, "Error: session not found in v3 registry")
        return 1

    existing = reg_entry.get("cli_session_id")
    if existing == cli_uuid:
        log(filename, cli_uuid, zellij, "No action: UUID already correct")
        return 0

    if existing:
        log(filename, cli_uuid, zellij, f"UUID updated (was: {existing[:16]}...)")
    else:
        log(filename, cli_uuid, zellij, "UUID discovered")

    # Update v3 registry file
    reg_entry["cli_session_id"] = cli_uuid
    write_registry(zellij, reg_entry)

    # Update sessionInfo.json with discovered UUID + create UUID symlink
    platform = reg_entry.get("platform", "claude_cli")
    update_session_info(
        platform=platform,
        zellij_name=zellij,
        created_at=reg_entry.get("created_at"),
        cli_session_id=cli_uuid,
    )

    return 0


def main():
    configure_logging()
    if len(sys.argv) < 2:
        print("Usage: handle_new_session_file.py <filepath>", file=sys.stderr)
        sys.exit(1)

    filepath = Path(sys.argv[1])

    if not filepath.exists():
        log(filepath.name, "-", "-", "Error: file does not exist")
        sys.exit(1)

    # Determine platform from path/filename
    if "rollout-" in filepath.name and filepath.suffix == ".jsonl":
        sys.exit(process_codex_file(filepath))
    elif filepath.name.startswith("session-") and filepath.suffix == ".json":
        sys.exit(process_gemini_file(filepath))
    else:
        log(filepath.name, "-", "-", "Skip: not a recognized session file format")
        sys.exit(2)


if __name__ == "__main__":
    main()
