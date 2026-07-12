#!/usr/bin/env python3
from __future__ import annotations
"""
resume_into.py — Rehome a CLI session into a new project directory and resume it.

Flow:
1. Resolve a session identifier (tracking ID, terminal session name, or CLI UUID)
2. Stop the running session if needed
3. Move/rehome the transcript file when the platform stores transcripts per-project
4. Update session registry paths to the new project directory
5. cd into the new project directory and resume the session

Usage:
  resume_into.py --session-id <session_id> --new-dir <new_dir>
  resume_into.py --session-id <session_id> --new-dir <new_dir> --dry-run
  resume_into.py --session-id <session_id> --new-dir <new_dir> --overwrite
"""

import argparse
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT
SCRIPTS_DIR = AI_ROOT / "ai_general" / "scripts"
CLI_DIR = SCRIPTS_DIR / "cli"
SESSION_MGMT_DIR = SCRIPTS_DIR / "session_mgmt"
for _path in (str(CLI_DIR), str(SESSION_MGMT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from uai_toolkit.cli.lib_session_mgr import compute_transcript_path  # type: ignore
from uai_toolkit.session_mgmt.session_store import SessionStore, DB_PATH  # type: ignore
from uai_toolkit.session_mgmt.lib_session_substrate import get_substrate, SubstrateError  # type: ignore

WRAPPERS = {
    "claude_cli": CLI_DIR / "claudeCli",
    "codex_cli": CLI_DIR / "codexCli",
    "gemini_cli": CLI_DIR / "geminiCli",
}


def sanitize_claude_project_dir(dir_path: str) -> str:
    normalized = os.path.realpath(os.path.expanduser(dir_path)).rstrip("/")
    return "-" + re.sub(r"[^a-zA-Z0-9]", "-", normalized.lstrip("/"))



def slugify_gemini_project(project_path: str) -> str:
    base = Path(project_path).name or "project"
    slug = re.sub(r"[^a-z0-9]", "-", base.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "project"



def first_existing_transcript(entry: dict[str, Any]) -> Path | None:
    history_file = entry.get("history_file")
    if history_file:
        path = Path(str(history_file))
        if path.exists():
            return path

    transcript_path = entry.get("transcript_path")
    if transcript_path:
        paths: list[str] = []
        if isinstance(transcript_path, list):
            paths = [str(p) for p in transcript_path]
        elif isinstance(transcript_path, str):
            try:
                parsed = json.loads(transcript_path)
                if isinstance(parsed, list):
                    paths = [str(p) for p in parsed]
                elif isinstance(parsed, str):
                    paths = [parsed]
            except json.JSONDecodeError:
                paths = [transcript_path]
        for raw in paths:
            path = Path(raw)
            if path.exists():
                return path

    cli_uuid = entry.get("cli_session_id")
    project_dir = entry.get("project_dir") or entry.get("working_dir") or str(AI_ROOT)
    platform = entry.get("platform")
    if cli_uuid and platform:
        computed = compute_transcript_path(platform, cli_uuid, project_dir)
        if computed:
            try:
                raw_paths = json.loads(computed)
            except json.JSONDecodeError:
                raw_paths = [computed]
            for raw in raw_paths:
                path = Path(str(raw))
                if path.exists():
                    return path
    return None



def ensure_gemini_project_dir(new_dir: str) -> Path:
    tmp_root = Path.home() / ".gemini" / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    normalized = str(Path(new_dir).resolve())
    registry_path = Path.home() / ".gemini" / "projects.json"
    slug: str | None = None

    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text())
            if isinstance(data, dict):
                projects = data.get("projects", {})
                if isinstance(projects, dict):
                    existing = projects.get(normalized)
                    if isinstance(existing, str) and existing:
                        slug = existing
        except json.JSONDecodeError:
            pass

    if not slug:
        base_slug = slugify_gemini_project(normalized)
        counter = 0
        while True:
            candidate = base_slug if counter == 0 else f"{base_slug}-{counter}"
            marker = tmp_root / candidate / ".project_root"
            if not marker.exists():
                slug = candidate
                break
            owner = marker.read_text().strip()
            if owner == normalized:
                slug = candidate
                break
            counter += 1

    assert slug is not None
    project_dir = tmp_root / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / ".project_root").write_text(normalized)
    chats_dir = project_dir / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)

    data = {"projects": {}}
    if registry_path.exists():
        try:
            loaded = json.loads(registry_path.read_text())
            if isinstance(loaded, dict) and isinstance(loaded.get("projects"), dict):
                data = loaded
        except json.JSONDecodeError:
            pass
    data.setdefault("projects", {})[normalized] = slug
    registry_path.write_text(json.dumps(data, indent=2) + "\n")
    return chats_dir



def target_transcript_path(entry: dict[str, Any], new_dir: str, source: Path | None) -> Path | None:
    platform = entry["platform"]
    cli_uuid = entry.get("cli_session_id")

    if platform == "claude_cli":
        if not cli_uuid:
            raise ValueError("Claude resume_into requires a known CLI UUID")
        target_dir = Path.home() / ".claude" / "projects" / sanitize_claude_project_dir(new_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{cli_uuid}.jsonl"

    if platform == "codex_cli":
        return source

    if platform == "gemini_cli":
        chats_dir = ensure_gemini_project_dir(new_dir)
        if source is not None:
            return chats_dir / source.name
        if cli_uuid:
            uuid8 = cli_uuid[:8]
            return chats_dir / f"session-{uuid8}.jsonl"
        raise ValueError("Gemini resume_into requires a source transcript or CLI UUID")

    raise ValueError(f"Unsupported platform: {platform}")


def discover_cli_uuid_from_transcript(platform: str, source: Path | None) -> str | None:
    """Best-effort recovery of CLI UUID from an existing transcript file."""
    if source is None or not source.exists():
        return None
    try:
        if platform == "claude_cli":
            if source.name.endswith(".jsonl"):
                return source.stem
        elif platform == "codex_cli":
            with source.open() as handle:
                first_line = handle.readline().strip()
            if first_line:
                data = json.loads(first_line)
                if isinstance(data, dict):
                    payload = data.get("payload", {}) or {}
                    return payload.get("id") or data.get("sessionId") or data.get("id")
        elif platform == "gemini_cli":
            if source.suffix == ".jsonl":
                with source.open() as handle:
                    first_line = handle.readline().strip()
                if first_line:
                    data = json.loads(first_line)
                    if isinstance(data, dict):
                        return data.get("sessionId")
            elif source.suffix == ".json":
                data = json.loads(source.read_text())
                if isinstance(data, dict):
                    return data.get("sessionId")
    except (OSError, json.JSONDecodeError):
        return None
    return None



def pid_alive(pid: Any) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False



def stop_session(entry: dict[str, Any], timeout: float = 10.0) -> None:
    terminal_name = entry.get("terminal_session")
    pid = entry.get("cli_pid")
    substrate = None

    if terminal_name:
        try:
            substrate = get_substrate()
            if substrate.session_exists(terminal_name):
                substrate.kill_session(terminal_name)
        except Exception:
            pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        terminal_gone = True
        if terminal_name and substrate is not None:
            try:
                terminal_gone = not substrate.session_exists(terminal_name)
            except Exception:
                terminal_gone = True
        process_gone = not pid_alive(pid)
        if terminal_gone and process_gone:
            return
        time.sleep(0.25)

    if pid_alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + 3
        while time.time() < deadline and pid_alive(pid):
            time.sleep(0.25)
        if pid_alive(pid):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass



def update_registry_for_rehome(store: SessionStore, entry: dict[str, Any], new_dir: str, transcript_target: Path | None) -> None:
    tracking_id = entry["tracking_id"]
    transcript_json = json.dumps([str(transcript_target)]) if transcript_target else entry.get("transcript_path")
    history_file = str(transcript_target) if transcript_target else entry.get("history_file")

    store.update(
        tracking_id,
        working_dir=str(Path(new_dir).resolve()),
        transcript_path=transcript_json,
        history_file=history_file,
        status="stopped",
        cli_pid=None,
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE sessions SET project_dir = ? WHERE tracking_id = ?",
            (str(Path(new_dir).resolve()), tracking_id),
        )
        conn.commit()



def resume_command(entry: dict[str, Any]) -> list[str]:
    platform = entry["platform"]
    wrapper = WRAPPERS.get(platform)
    if wrapper is None or not wrapper.exists():
        raise FileNotFoundError(f"Launcher entrypoint not found for {platform}: {wrapper}")
    return [sys.executable, str(wrapper), "--resume", entry["tracking_id"]]



def main() -> int:
    parser = argparse.ArgumentParser(description="Rehome a session into a new directory and resume it")
    parser.add_argument("--session-id", required=True, dest="session_id", help="Tracking ID, terminal session name, or CLI UUID")
    parser.add_argument("--new-dir", required=True, dest="new_dir", help="Target project directory")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without making changes")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing target transcript if present")
    args = parser.parse_args()

    new_dir = str(Path(os.path.realpath(os.path.expanduser(args.new_dir))))
    new_dir_path = Path(new_dir)
    if not new_dir_path.exists() or not new_dir_path.is_dir():
        print(f"Error: target directory does not exist: {new_dir_path}", file=sys.stderr)
        return 1

    store = SessionStore()
    entry = store.resolve(args.session_id)
    if entry is None:
        print(f"Error: could not resolve session: {args.session_id}", file=sys.stderr)
        return 1

    source = first_existing_transcript(entry)
    if not entry.get("cli_session_id"):
        discovered_uuid = discover_cli_uuid_from_transcript(entry["platform"], source)
        if discovered_uuid:
            store.update(entry["tracking_id"], cli_session_id=discovered_uuid)
            entry = store.resolve(entry["tracking_id"]) or entry
    target = target_transcript_path(entry, new_dir, source)

    if source and target and source.resolve() != target.resolve() and target.exists() and not args.overwrite:
        print(f"Error: target transcript already exists: {target} (use --overwrite to replace)", file=sys.stderr)
        return 1

    cmd = resume_command(entry)

    print(f"Resolved tracking_id: {entry['tracking_id']}")
    print(f"Platform: {entry['platform']}")
    print(f"Current project_dir: {entry.get('project_dir')}")
    print(f"New project_dir: {new_dir}")
    if source:
        print(f"Source transcript: {source}")
    else:
        print("Source transcript: (not found — registry update only)")
    if target:
        print(f"Target transcript: {target}")
    else:
        print("Target transcript: (unchanged)")
    print(f"Resume command: {' '.join(cmd)}")

    if args.dry_run:
        return 0

    stop_session(entry)

    if source and target and source.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and args.overwrite:
            if target.is_file():
                target.unlink()
        shutil.move(str(source), str(target))
        print(f"Moved transcript to {target}")
    elif target and source and source.resolve() == target.resolve():
        print("Transcript already in the target project location")
    elif entry["platform"] == "codex_cli":
        print("Codex transcript location is global; no transcript move required")

    update_registry_for_rehome(store, entry, new_dir, target)

    os.chdir(new_dir)
    os.execvpe(sys.executable, cmd, os.environ.copy())
    return 0


if __name__ == "__main__":
    sys.exit(main())
