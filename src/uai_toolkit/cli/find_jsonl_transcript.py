#!/usr/bin/env python3
import argparse
import subprocess
import json
import os
import sys
import re
from pathlib import Path

# Shared color library
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.common_utils.standard_colors import c, heading, format_help

# AI_ROOT (shared resolver)
from uai_toolkit.paths import AI_ROOT
SESSION_STORE_SCRIPT = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"

def get_session_info(identifier):
    """Get UUID and Platform from uai_toolkit.session_mgmt.session_store."""
    cmd = [str(SESSION_STORE_SCRIPT), "search", identifier]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Assuming output format: TrackingID Platform UUID ...
        # Based on user requirement:
        # cut -f5 gives UUID, cut -f3 gives platform
        # Note: 'cut -ws' in requirement implies splitting by whitespace
        lines = result.stdout.strip().splitlines()
        if not lines:
            return None, None
        
        # Taking the first data line (skip headers)
        lines = [l for l in result.stdout.strip().splitlines() if '[' in l]
        if not lines:
            return None, None
        
        line = lines[0]
        parts = line.split()
        
        # UUID is index 3 (4th column)
        # Platform is index 1 (2nd column)
        uuid = parts[3]
        platform = parts[1]
        if platform == "gemini": platform = "gemini_cli"
        elif platform == "claude": platform = "claude_cli"
        elif platform == "codex": platform = "codex_cli"
        return uuid, platform
    except Exception as e:
        return None, None

def compute_path(platform, cli_uuid):
    """Discovery logic ported from the launcher stack."""
    if platform == "claude_cli" and cli_uuid:
        projects = Path.home() / ".claude" / "projects"
        if projects.exists():
            for d in projects.iterdir():
                if d.is_dir():
                    f = d / f"{cli_uuid}.jsonl"
                    if f.exists():
                        return str(f)
    
    elif platform == "gemini_cli" and cli_uuid:
        uuid8 = cli_uuid[:8]
        gemini_tmp = Path.home() / ".gemini" / "tmp"
        if gemini_tmp.exists():
            # Check jsonl
            for f in gemini_tmp.rglob(f"session-*-{uuid8}.jsonl"):
                return str(f)
            # Check json
            for f in gemini_tmp.rglob(f"session-*-{uuid8}.json"):
                return str(f)
    
    elif platform == "codex_cli" and cli_uuid:
        codex_sessions = Path.home() / ".codex" / "sessions"
        if codex_sessions.exists():
            for f in codex_sessions.rglob(f"rollout-*-{cli_uuid}.jsonl"):
                return str(f)
            for f in sorted(codex_sessions.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    with open(f) as fh:
                        first_line = fh.readline()
                    data = json.loads(first_line)
                    if data.get("sessionId") == cli_uuid or data.get("id") == cli_uuid:
                        return str(f)
                except:
                    continue
    return None

def main():
    parser = argparse.ArgumentParser(
        description=c("Finds the transcript JSONL file for a given session.", "magenta", "bold"),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="General session identifier (TrackingId, CLI UUID, or terminal Id)")
    group.add_argument("--uuid", help="Direct CLI UUID")
    group.add_argument("--trackingId", help="Direct Tracking ID")
    group.add_argument("--terminalId", help="Direct terminal session ID")
    parser.add_argument("--platform", help="Platform name (claude_cli, codex_cli, gemini_cli)")
    args = parser.parse_args()

    identifier = args.id or args.uuid or args.trackingId or args.terminalId
    uuid = args.uuid
    platform = args.platform

    if not uuid:
        uuid, platform_from_store = get_session_info(identifier)
        if not uuid:
            print(f"Error: Could not resolve session: {identifier}", file=sys.stderr)
            sys.exit(1)
        if not platform:
            platform = platform_from_store

    transcript_path = compute_path(platform, uuid)
    if transcript_path:
        print(transcript_path)
    else:
        print(f"Error: Could not find transcript for {platform} / {uuid}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
