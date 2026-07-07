#!/usr/bin/env python3
"""
fix_session_uuids.py — Verify and fix CLI session UUIDs via content matching.

Matches zellij terminal scrollback content against JSONL conversation files
to determine the correct UUID for each running session. Uses intersection
of 10+ unique long words — only one JSONL should contain all of them.

Usage:
  python3 ~/bin/ai/fix_session_uuids.py          # Verify and fix running sessions
  python3 ~/bin/ai/fix_session_uuids.py --verify  # Show results without fixing
  python3 ~/bin/ai/fix_session_uuids.py --all     # Include stopped sessions in report
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Import SessionRegistry from cli wrappers
_cli_scripts = Path(__file__).resolve().parent.parent / "scripts" / "cli"
if not _cli_scripts.exists():
    _cli_scripts = Path.home() / "AI/ai_root/ai_general/scripts/cli"
if str(_cli_scripts) not in sys.path:
    sys.path.insert(0, str(_cli_scripts))

from uai_toolkit.cli.lib_cli_common import SessionRegistry
from uai_toolkit.cli.lib_paths import UNIFIED_CLI_DIR

REGISTRY = UNIFIED_CLI_DIR / "session_metadata.json"
JSONL_DIR = Path.home() / ".claude/projects/-Users-shawnhillis-Documents-AI-ai-root"

# Words to exclude from matching (too common across sessions)
EXCLUDE_WORDS = {
    "shawnhillis", "documents", "unified", "interface", "projects",
    "application", "typescript", "javascript", "electron", "renderer",
    "component", "undefined", "processing", "downloading", "information",
    "permissions", "environment", "description", "condensed", "instructions",
    "anthropic", "scrollback", "transcript", "placeholder", "configuration",
    "dependencies", "notification", "orchestration", "infrastructure",
    "implementation", "communication", "documentation", "automatically",
    "functionality", "conversation", "organizations", "investigating",
    "approximately", "understanding", "unfortunately", "significantly",
    "comprehensive", "relationships", "considerations", "corresponding",
}

WORD_RE = re.compile(r'\b[a-zA-Z]{12,}\b')


def get_live_zellij() -> set[str]:
    try:
        r = subprocess.run(
            ["zellij", "list-sessions", "--short", "--no-formatting"],
            capture_output=True, text=True, timeout=5
        )
        return {n.strip() for n in r.stdout.strip().split('\n') if n.strip()}
    except Exception:
        return set()


def dump_scrollback(session: str) -> str | None:
    fd, path = tempfile.mkstemp(prefix=f"scroll_{session}_", suffix=".txt")
    os.close(fd)
    try:
        subprocess.run(
            ["zellij", "--session", session, "action", "dump-screen", "--full", path],
            capture_output=True, timeout=10
        )
        with open(path) as f:
            content = f.read()
        return content if len(content) > 500 else None
    except Exception:
        return None
    finally:
        os.unlink(path)


def extract_unique_words(text: str, count: int = 10) -> list[str]:
    """Extract long words that appear exactly once in the text (most distinctive)."""
    words = WORD_RE.findall(text)
    # Count occurrences
    freq = {}
    for w in words:
        wl = w.lower()
        if wl not in EXCLUDE_WORDS:
            freq[w] = freq.get(w, 0) + 1
    # Prefer words that appear exactly once (most unique to this session)
    unique = [w for w, c in freq.items() if c == 1]
    # Fall back to rare words if not enough unique ones
    if len(unique) < count:
        rare = sorted(freq.items(), key=lambda x: x[1])
        unique = [w for w, c in rare if w not in unique][:count - len(unique)] + unique
    import random
    random.shuffle(unique)
    return unique[:count]


def match_jsonl(words: list[str], jsonl_dir: Path) -> str | None:
    """Find the single JSONL that contains ALL given words."""
    candidates = None
    for word in words:
        try:
            r = subprocess.run(
                ["grep", "-rlF", word, str(jsonl_dir)],
                capture_output=True, text=True, timeout=30
            )
            hits = {line.strip() for line in r.stdout.strip().split('\n') if line.strip().endswith('.jsonl')}
        except Exception:
            continue
        if not hits:
            continue
        if candidates is None:
            candidates = hits
        else:
            candidates = candidates & hits
        # Early exit if narrowed to one
        if len(candidates) == 1:
            return Path(list(candidates)[0]).stem
        if len(candidates) == 0:
            return None
    if candidates and len(candidates) == 1:
        return Path(list(candidates)[0]).stem
    return None


def main():
    verify_only = "--verify" in sys.argv
    show_all = "--all" in sys.argv

    registry = SessionRegistry(REGISTRY)
    store = registry._load()
    sessions = store.get("sessions", {})
    live_zellij = get_live_zellij()

    print(f"Registry: {REGISTRY}")
    print(f"Sessions in registry: {len(sessions)}")
    print(f"Live zellij sessions: {len(live_zellij)}")
    print()

    # Find duplicates
    uuid_map = {}
    for sid, s in sessions.items():
        uuid = s.get("cli_session_id")
        if uuid:
            uuid_map.setdefault(uuid, []).append(s.get("name", sid[:8]))
    dupes = {u: n for u, n in uuid_map.items() if len(n) > 1}
    if dupes:
        print("DUPLICATE UUIDs in registry:")
        for uuid, names in dupes.items():
            print(f"  {uuid[:16]}... → {', '.join(names)}")
        print()

    # Match running sessions via content
    fixes = []
    print("Matching running sessions via scrollback content:")
    for sid, s in sorted(sessions.items(), key=lambda x: x[1].get("name", "")):
        zellij = s.get("zellij_session")
        if not zellij:
            continue

        is_running = zellij in live_zellij
        if not is_running and not show_all:
            continue

        name = s.get("name", sid[:8])
        reg_uuid = s.get("cli_session_id")
        status = "RUNNING" if is_running else "stopped"

        if not is_running:
            uuid_disp = reg_uuid[:16] + "..." if reg_uuid else "(none)"
            print(f"  · {name:30s}  [{status}]  {uuid_disp}")
            continue

        # Dump scrollback and match
        scrollback = dump_scrollback(zellij)
        if not scrollback:
            print(f"  ? {name:30s}  [{status}]  can't dump scrollback")
            continue

        words = extract_unique_words(scrollback)
        if len(words) < 3:
            print(f"  ? {name:30s}  [{status}]  too few unique words")
            continue

        matched = match_jsonl(words, JSONL_DIR)

        if matched:
            if matched == reg_uuid:
                print(f"  ✓ {name:30s}  [{status}]  {matched[:16]}...")
            else:
                old_disp = reg_uuid[:16] + "..." if reg_uuid else "(none)"
                print(f"  ✗ {name:30s}  [{status}]  {matched[:16]}... (was: {old_disp})")
                fixes.append((sid, name, matched))
        else:
            uuid_disp = reg_uuid[:16] + "..." if reg_uuid else "(none)"
            print(f"  ? {name:30s}  [{status}]  no unique match ({len(words)} words tried, registry: {uuid_disp})")

    print()

    if not fixes:
        print("No fixes needed.")
        return

    print(f"{len(fixes)} fix(es) to apply:")
    for sid, name, uuid in fixes:
        old = sessions[sid].get("cli_session_id", "(none)")
        old_disp = old[:16] + "..." if old != "(none)" else old
        print(f"  {name}: {old_disp} → {uuid[:16]}...")

    if verify_only:
        print("\nRun without --verify to apply.")
        return

    for sid, name, uuid in fixes:
        registry.update_uuid_by_id(sid, uuid)

    print(f"\nApplied {len(fixes)} fixes. Restart the app to pick up changes.")


if __name__ == "__main__":
    main()
