#!/usr/bin/env python3
"""
Session Registry - Discovers running and historical AI agent sessions.

Usage:
    session_registry.py list [--json] [--running] [--historical] [--limit N]
"""

import subprocess
import json
import re
import os
import sys
from dataclasses import dataclass, asdict, field
from typing import Optional
from pathlib import Path
from datetime import datetime

# Shared color library
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bin", "ai"))
from uai_toolkit.common_utils.standard_colors import c, bold, dim, heading, format_help, colors_enabled


@dataclass
class ChatSession:
    """A chat session (running or historical)."""
    id: str
    platform: str
    running: bool
    last_activity: str  # ISO timestamp
    zellij_session: Optional[str] = None
    agent_pid: Optional[int] = None
    working_dir: Optional[str] = None
    role: Optional[str] = None
    task_path: Optional[str] = None
    resumable: bool = True  # False if server has purged the conversation


# Cache file for tracking non-resumable sessions
NON_RESUMABLE_CACHE = Path.home() / '.claude' / 'non_resumable_sessions.json'


def load_non_resumable_cache() -> set[str]:
    """Load the set of session IDs known to be non-resumable."""
    try:
        if NON_RESUMABLE_CACHE.exists():
            with open(NON_RESUMABLE_CACHE) as f:
                data = json.load(f)
                return set(data.get('sessions', []))
    except Exception:
        pass
    return set()


def mark_non_resumable(session_id: str) -> None:
    """Mark a session as non-resumable in the cache."""
    cache = load_non_resumable_cache()
    cache.add(session_id)
    try:
        NON_RESUMABLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(NON_RESUMABLE_CACHE, 'w') as f:
            json.dump({'sessions': list(cache)}, f)
    except Exception:
        pass


def get_last_message_timestamp(jsonl_path: Path) -> Optional[str]:
    """
    Get the timestamp of the last message in a Claude CLI jsonl file.
    Returns ISO timestamp string, or None if not found.
    
    Handles both top-level timestamps and nested ones (e.g., snapshot.timestamp).
    """
    try:
        # Read the last non-empty line (efficient reverse read for large files)
        with open(jsonl_path, 'rb') as f:
            # Seek to end
            f.seek(0, 2)
            file_size = f.tell()
            
            # Read last chunk (typically enough for one line)
            chunk_size = min(4096, file_size)
            f.seek(file_size - chunk_size)
            chunk = f.read().decode('utf-8', errors='ignore')
            
            # Get last non-empty line
            lines = chunk.strip().split('\n')
            for line in reversed(lines):
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        # Try top-level timestamp first
                        ts = data.get('timestamp')
                        if ts:
                            return ts
                        # Try nested snapshot.timestamp (file-history-snapshot entries)
                        if 'snapshot' in data and isinstance(data['snapshot'], dict):
                            ts = data['snapshot'].get('timestamp')
                            if ts:
                                return ts
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return None


# --- Running session discovery (process tree) ---

def get_zellij_sessions() -> set[str]:
    """Get active zellij session names."""
    sessions = set()
    commands = [
        ['zellij', 'list-sessions', '--short', '--no-formatting'],
        ['zellij', 'list-sessions', '--short'],
        ['zellij', 'list-sessions', '--no-formatting'],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                continue

            for raw_line in result.stdout.strip().split('\n'):
                line = raw_line.strip()
                if not line:
                    continue
                # list-sessions may include metadata like:
                # "session_name [Created 1m 2s ago] (current)"
                name_end = line.find(' [')
                session_name = line if name_end == -1 else line[:name_end].strip()
                if session_name:
                    sessions.add(session_name)

            if sessions:
                break
        except Exception:
            continue

    return sessions


def get_ppid(pid: int) -> int:
    try:
        result = subprocess.run(['ps', '-o', 'ppid=', '-p', str(pid)],
                                capture_output=True, text=True, check=True)
        return int(result.stdout.strip())
    except Exception:
        return 0


def get_command(pid: int) -> str:
    try:
        result = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return ''


def identify_platform(cmd: str) -> Optional[str]:
    if '/claude' in cmd or 'claude ' in cmd:
        return 'claude_cli'
    if '/codex' in cmd or 'codex ' in cmd:
        return 'codex_cli'
    if '/gemini' in cmd or 'gemini ' in cmd:
        return 'gemini_cli'
    return None


def identify_platform_from_zellij_session(session_name: str) -> Optional[str]:
    if session_name.startswith('claude_cli_'):
        return 'claude_cli'
    if session_name.startswith('codex_cli_'):
        return 'codex_cli'
    if session_name.startswith('gemini_cli_'):
        return 'gemini_cli'
    return None


def extract_role(cmd: str) -> Optional[str]:
    match = re.search(r'--agent[=\s]+([^\s]+)', cmd)
    return match.group(1) if match else None


def extract_task_path(cmd: str) -> Optional[str]:
    match = re.search(r"(ai_comms/[^'\"]+/tasks/[^'\"]+\.md)", cmd)
    return match.group(1) if match else None


def extract_working_dir(cmd: str) -> Optional[str]:
    match = re.search(r"cd\s+'([^']+)'", cmd)
    return match.group(1) if match else None


def extract_zellij_session_from_cmd(cmd: str) -> Optional[str]:
    """Extract zellij session name from a command line."""
    patterns = [
        r'(?:^|\s)(?:-s|--session)\s+[\'"]?([A-Za-z0-9_.:-]+)[\'"]?',
        r'/\.zellij/transcripts/([A-Za-z0-9_.:-]+)\.log',
    ]
    for pattern in patterns:
        match = re.search(pattern, cmd)
        if match:
            return match.group(1)
    return None


def walk_to_zellij_session(pid: int, zellij_sessions: set[str]) -> Optional[str]:
    visited = set()
    current = pid
    while current > 1 and current not in visited:
        visited.add(current)
        cmd = get_command(current)
        session_name = extract_zellij_session_from_cmd(cmd)
        if session_name and session_name in zellij_sessions:
            return session_name
        current = get_ppid(current)
    return None


def find_agent_processes() -> list[tuple[int, str]]:
    agents = []
    patterns = [
        r'/ai/cli/claude_cli\.py\b',
        r'/ai/cli/codex_cli\.py\b',
        r'/ai/cli/gemini_cli\.py\b',
        r'\.local/bin/claude\b',
        r'/bin/codex\b',
        r'/bin/gemini\b',
    ]
    try:
        result = subprocess.run(['ps', '-eo', 'pid,command'], capture_output=True, text=True, check=True)
        for line in result.stdout.strip().split('\n')[1:]:
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                continue
            pid_str, cmd = parts[0], parts[1]
            if cmd.startswith('bash -c'):
                continue
            for pattern in patterns:
                if re.search(pattern, cmd):
                    try:
                        agents.append((int(pid_str), cmd))
                    except ValueError:
                        pass
                    break
    except Exception:
        pass
    return agents


def extract_session_id_from_cmd(cmd: str) -> Optional[str]:
    """
    Extract session ID from Claude CLI command line.
    Looks for -r/--resume <uuid> pattern.
    """
    # Pattern: -r <uuid> or --resume <uuid>
    match = re.search(r'(?:-r|--resume)\s+([a-f0-9-]{36})', cmd)
    if match:
        return match.group(1)
    return None


def find_jsonl_for_session(session_id: str) -> Optional[Path]:
    """Find the jsonl file for a given session ID."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return None
    
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            jsonl_path = project_dir / f'{session_id}.jsonl'
            if jsonl_path.exists():
                return jsonl_path
    return None


def find_session_id_from_cmd_or_fallback(cmd: str, zellij_session: str, platform: str, working_dir: Optional[str] = None, agent_pid: Optional[int] = None) -> tuple[str, str]:
    """
    Find session ID from command line, or fall back to heuristics.
    Returns (session_id, last_activity) tuple.
    """
    # First: try to extract from command line (most reliable)
    session_id = extract_session_id_from_cmd(cmd)
    if session_id:
        # Try to get last activity from jsonl
        jsonl_path = find_jsonl_for_session(session_id)
        if jsonl_path:
            msg_ts = get_last_message_timestamp(jsonl_path)
            if msg_ts:
                return session_id, msg_ts
            return session_id, datetime.fromtimestamp(jsonl_path.stat().st_mtime).isoformat()
        return session_id, datetime.now().isoformat()
    
    # Fallback for new sessions (no -r flag): try to find by working directory
    # But ONLY if there's just one running process - otherwise we can't know which jsonl belongs to which
    wd = working_dir or extract_working_dir(cmd)
    if wd:
        # Convert working_dir to project folder name
        # Claude CLI encodes: / -> - and _ -> -
        project_name = wd.replace('/', '-').replace('_', '-')
        if not project_name.startswith('-'):
            project_name = '-' + project_name
        
        projects_dir = Path.home() / '.claude' / 'projects' / project_name
        if projects_dir.exists():
            # Try to match by process start time if we have PID
            # Find jsonl files modified recently (within last hour)
            now = datetime.now().timestamp()
            recent_jsonl = [(f, f.stat().st_mtime) for f in projects_dir.glob('*.jsonl')
                           if not f.name.startswith('agent-') and (now - f.stat().st_mtime) < 3600]
            
            # If there's only ONE recent jsonl, it's likely ours
            if len(recent_jsonl) == 1:
                newest = recent_jsonl[0][0]
                session_id = newest.stem
                msg_ts = get_last_message_timestamp(newest)
                if msg_ts:
                    return session_id, msg_ts
                return session_id, datetime.fromtimestamp(newest.stat().st_mtime).isoformat()
    
    # Last resort: use zellij session name (ensures unique ID per running session)
    # For timestamp, try to get process start time
    last_activity = datetime.now().isoformat()
    if agent_pid:
        try:
            result = subprocess.run(['ps', '-o', 'lstart=', '-p', str(agent_pid)],
                                    capture_output=True, text=True, check=True)
            # Parse lstart format: "Wed Mar  5 22:44:18 2026"
            from datetime import datetime as dt
            start_str = result.stdout.strip()
            if start_str:
                start_dt = dt.strptime(start_str, "%a %b %d %H:%M:%S %Y")
                last_activity = start_dt.isoformat()
        except Exception:
            pass
    
    return zellij_session, last_activity


def discover_running_sessions() -> list[ChatSession]:
    sessions = []
    zellij_sessions = get_zellij_sessions()
    if not zellij_sessions:
        return sessions
    
    # Track which session IDs we've already added (to avoid duplicates)
    seen_ids = set()
    seen_zellij_sessions = set()
    
    for pid, cmd in find_agent_processes():
        zellij_session = walk_to_zellij_session(pid, zellij_sessions)
        if not zellij_session:
            continue
        seen_zellij_sessions.add(zellij_session)

        platform = identify_platform(cmd)
        if not platform:
            platform = identify_platform_from_zellij_session(zellij_session)
        if not platform:
            continue
        
        working_dir = extract_working_dir(cmd)
        if not working_dir:
            parent_cmd = get_command(get_ppid(pid))
            working_dir = extract_working_dir(parent_cmd)
        
        # Extract session ID from command line (most reliable) or fall back
        session_id, last_activity = find_session_id_from_cmd_or_fallback(cmd, zellij_session, platform, working_dir, pid)
        
        # Skip if we've already seen this session ID
        if session_id in seen_ids:
            continue
        seen_ids.add(session_id)
        
        sessions.append(ChatSession(
            id=session_id,
            platform=platform,
            running=True,
            last_activity=last_activity,
            zellij_session=zellij_session,
            agent_pid=pid,
            role=extract_role(cmd),
            task_path=extract_task_path(cmd),
            working_dir=working_dir
        ))

    # Include live zellij sessions that do not currently map to an agent process.
    # This preserves visibility for idle sessions and still filters to known patterns.
    for zellij_session in sorted(zellij_sessions):
        if zellij_session in seen_zellij_sessions:
            continue

        platform = identify_platform_from_zellij_session(zellij_session)
        if not platform:
            continue
        if zellij_session in seen_ids:
            continue
        seen_ids.add(zellij_session)

        sessions.append(ChatSession(
            id=zellij_session,
            platform=platform,
            running=True,
            last_activity=datetime.now().isoformat(),
            zellij_session=zellij_session
        ))
    
    return sessions


# --- Historical session discovery (native storage) ---

def discover_claude_historical(limit: int = 20) -> list[ChatSession]:
    """Discover recent Claude CLI sessions from .jsonl files."""
    sessions = []
    
    # Find project directories
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return sessions
    
    # Get all .jsonl files across all project dirs
    # Use last message timestamp for sorting (more accurate than file mtime)
    all_jsonl = []
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            for f in project_dir.glob('*.jsonl'):
                # Skip agent-* files (seem to be subconversations)
                if f.name.startswith('agent-'):
                    continue
                
                # Get last message timestamp from file content
                msg_ts = get_last_message_timestamp(f)
                if msg_ts:
                    # Parse ISO timestamp to datetime for sorting
                    try:
                        ts_dt = datetime.fromisoformat(msg_ts.replace('Z', '+00:00'))
                        all_jsonl.append((f, ts_dt.timestamp(), msg_ts))
                    except ValueError:
                        # Fall back to file mtime
                        mtime = f.stat().st_mtime
                        all_jsonl.append((f, mtime, datetime.fromtimestamp(mtime).isoformat()))
                else:
                    # Fall back to file mtime
                    mtime = f.stat().st_mtime
                    all_jsonl.append((f, mtime, datetime.fromtimestamp(mtime).isoformat()))
    
    all_jsonl.sort(key=lambda x: x[1], reverse=True)
    
    for f, _, last_activity_str in all_jsonl[:limit]:
        session_id = f.stem  # UUID from filename
        
        # Extract working dir from project path
        # e.g., -Users-shawnhillis-Documents-AI-ai_root -> $AI_ROOT
        # Note: Claude encodes path separators as '-', but preserves underscores in names
        project_name = f.parent.name
        # Strip leading dash (represents root /), then replace remaining dashes with /
        if project_name.startswith('-'):
            working_dir = '/' + project_name[1:].replace('-', '/')
        else:
            working_dir = '/' + project_name.replace('-', '/')
        
        # Check if this session is known to be non-resumable
        non_resumable = load_non_resumable_cache()
        is_resumable = session_id not in non_resumable
        
        sessions.append(ChatSession(
            id=session_id,
            platform='claude_cli',
            running=False,
            last_activity=last_activity_str,
            working_dir=working_dir,
            resumable=is_resumable
        ))
    
    return sessions


def discover_codex_historical(limit: int = 20) -> list[ChatSession]:
    """Discover recent Codex CLI sessions from history.jsonl."""
    sessions = []
    
    history_file = Path.home() / '.codex' / 'history.jsonl'
    if not history_file.exists():
        return sessions
    
    # Parse unique session_ids with most recent timestamp
    session_times: dict[str, int] = {}
    try:
        with open(history_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    sid = entry.get('session_id')
                    ts = entry.get('ts', 0)
                    if sid:
                        if sid not in session_times or ts > session_times[sid]:
                            session_times[sid] = ts
                except json.JSONDecodeError:
                    pass
    except Exception:
        return sessions
    
    # Sort by timestamp, take most recent
    sorted_sessions = sorted(session_times.items(), key=lambda x: x[1], reverse=True)
    
    for sid, ts in sorted_sessions[:limit]:
        last_activity = datetime.fromtimestamp(ts).isoformat()
        sessions.append(ChatSession(
            id=sid,
            platform='codex_cli',
            running=False,
            last_activity=last_activity
        ))
    
    return sessions


def discover_historical_sessions(limit: int = 20) -> list[ChatSession]:
    """Discover all historical sessions across platforms."""
    sessions = []
    
    # Get from each platform
    sessions.extend(discover_claude_historical(limit))
    sessions.extend(discover_codex_historical(limit))
    # TODO: discover_gemini_historical(limit)
    
    # Sort by last_activity descending
    sessions.sort(key=lambda s: s.last_activity, reverse=True)
    
    return sessions[:limit]


# --- Combined discovery ---

def discover_all_sessions(limit: int = 50) -> list[ChatSession]:
    """Discover all sessions, running first, then historical."""
    running = discover_running_sessions()
    running_ids = {s.id for s in running}
    
    historical = discover_historical_sessions(limit)
    # Filter out any historical that are currently running
    historical = [s for s in historical if s.id not in running_ids]
    
    return running + historical[:limit - len(running)]


# --- Session History Parsing ---

def find_jsonl_path(session_id: str) -> Optional[Path]:
    """Find the jsonl file for a Claude CLI session."""
    projects_dir = Path.home() / '.claude' / 'projects'
    if not projects_dir.exists():
        return None
    
    # Search all project directories for the session
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir():
            jsonl_path = project_dir / f'{session_id}.jsonl'
            if jsonl_path.exists():
                return jsonl_path
    
    return None


@dataclass
class ChatMessage:
    """A message in a chat session."""
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str


def extract_text_from_content(content) -> str:
    """
    Extract plain text from message content, which can be:
    - A string (simple text message)
    - A list of blocks (text, tool_use, tool_result, etc.)
    Returns only the text portions concatenated.
    """
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get('type', '')
                if block_type == 'text':
                    text = block.get('text', '')
                    if text:
                        text_parts.append(text)
                # Skip tool_use, tool_result, thinking, image, etc.
            elif isinstance(block, str):
                text_parts.append(block)
        return '\n'.join(text_parts)
    
    return ''


def parse_session_history(session_id: str) -> list[ChatMessage]:
    """
    Parse the jsonl file for a session and extract user/assistant messages.
    Returns list of ChatMessage objects in chronological order.
    """
    jsonl_path = find_jsonl_path(session_id)
    if not jsonl_path:
        return []
    
    messages = []
    
    try:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    entry_type = entry.get('type')
                    timestamp = entry.get('timestamp', '')
                    
                    if entry_type == 'user':
                        msg = entry.get('message', {})
                        content = msg.get('content', '')
                        text = extract_text_from_content(content)
                        if text:
                            messages.append(ChatMessage(
                                role='user',
                                content=text,
                                timestamp=timestamp
                            ))
                    
                    elif entry_type == 'assistant':
                        msg = entry.get('message', {})
                        content = msg.get('content', [])
                        text = extract_text_from_content(content)
                        if text:
                            messages.append(ChatMessage(
                                role='assistant',
                                content=text,
                                timestamp=timestamp
                            ))
                
                except json.JSONDecodeError:
                    continue
    
    except Exception:
        pass
    
    return messages


_HELP_RAW = """\
session_registry — Discover running and historical AI agent sessions.

Usage:
    session_registry [options]          List all sessions (default)
    session_registry <command> [args]   Run a subcommand

Commands:
    list                     List sessions (default if no command given)
    history <session_id>     Show conversation messages for a session
    mark-non-resumable <id>  Mark a session as non-resumable
    delete-session <id>      Delete a session's JSONL file and cache entry

List options:
    --running        Only show currently running sessions
    --historical     Only show stopped/historical sessions
    --limit N        Maximum sessions to show (default: 20)
    --json           Output as JSON array

History options:
    --json           Output messages as JSON array

What it does:
    Discovery combines two sources:
    1. Running sessions: scans process tree for AI CLI agents (claude, codex,
       gemini) running inside zellij/tmux sessions.
    2. Historical sessions: reads .jsonl transcript files from ~/.claude/projects/
       and ~/.codex/history.jsonl to find recent past sessions.

    Running sessions show platform, PID, role, working dir, and zellij session.
    Historical sessions show platform, last activity, and resumability.
"""


def main():
    import sys

    if '--help' in sys.argv or '-h' in sys.argv:
        print(format_help(_HELP_RAW))
        return

    # Handle subcommands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        # mark-non-resumable <session_id>
        if cmd == 'mark-non-resumable' and len(sys.argv) > 2:
            session_id = sys.argv[2]
            mark_non_resumable(session_id)
            print(json.dumps({'success': True, 'session_id': session_id}))
            return
        
        # history <session_id> [--json]
        if cmd == 'history' and len(sys.argv) > 2:
            session_id = sys.argv[2]
            output_json = '--json' in sys.argv
            
            messages = parse_session_history(session_id)
            
            if output_json:
                print(json.dumps([asdict(m) for m in messages]))
            else:
                for m in messages:
                    role_label = "USER" if m.role == 'user' else "ASSISTANT"
                    print(f"\n[{role_label}] {m.timestamp}")
                    print(m.content[:500] + ('...' if len(m.content) > 500 else ''))
            return
        
        # delete-session <session_id>
        if cmd == 'delete-session' and len(sys.argv) > 2:
            session_id = sys.argv[2]
            deleted_file = False
            
            # Find and delete the jsonl file
            jsonl_path = find_jsonl_path(session_id)
            if jsonl_path and jsonl_path.exists():
                try:
                    jsonl_path.unlink()
                    deleted_file = True
                except Exception:
                    pass
            
            # Remove from non-resumable cache
            cache = load_non_resumable_cache()
            if session_id in cache:
                cache.discard(session_id)
                try:
                    with open(NON_RESUMABLE_CACHE, 'w') as f:
                        json.dump({'sessions': list(cache)}, f)
                except Exception:
                    pass
            
            print(json.dumps({'success': True, 'session_id': session_id, 'deleted_file': deleted_file}))
            return
    
    output_json = '--json' in sys.argv
    only_running = '--running' in sys.argv
    only_historical = '--historical' in sys.argv
    
    limit = 20
    for i, arg in enumerate(sys.argv):
        if arg == '--limit' and i + 1 < len(sys.argv):
            try:
                limit = int(sys.argv[i + 1])
            except ValueError:
                pass
    
    if only_running:
        sessions = discover_running_sessions()
    elif only_historical:
        sessions = discover_historical_sessions(limit)
    else:
        sessions = discover_all_sessions(limit)
    
    if output_json:
        print(json.dumps([asdict(s) for s in sessions], indent=2))
    else:
        if not sessions:
            print("No sessions found.")
            return
        
        for s in sessions:
            status = c("RUNNING", "green", "bold") if s.running else c("stopped", "dim")
            resumable_indicator = "" if s.resumable else c(" [NON-RESUMABLE]", "yellow")
            print(f"\n[{status}] {s.id}{resumable_indicator}")
            print(f"  Platform: {s.platform}")
            if s.zellij_session and s.zellij_session != s.id:
                print(f"  zellij: {s.zellij_session}")
            if s.agent_pid:
                print(f"  PID: {s.agent_pid}")
            if s.role:
                print(f"  Role: {s.role}")
            if s.task_path:
                print(f"  Task: {s.task_path}")
            if s.working_dir:
                print(f"  Dir: {s.working_dir}")
            print(f"  Last: {s.last_activity}")


if __name__ == '__main__':
    main()
