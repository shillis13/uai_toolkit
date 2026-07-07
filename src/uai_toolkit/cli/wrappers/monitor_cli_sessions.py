#!/usr/bin/env python3
"""
Desktop Claude CLI Session Monitor
Polls CLI output files and detects completion/errors
"""

import os
import time
import glob
import json
from pathlib import Path
from datetime import datetime

SESSION_DIR = Path.home() / ".claude" / "cli_sessions"
POLL_INTERVAL = 1.5  # seconds
STATE_FILE = Path.home() / ".claude" / ".monitor_state.json"

def load_state():
    """Load monitoring state (file positions)"""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    """Save monitoring state"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def get_active_sessions():
    """Find all active CLI sessions"""
    sessions = []
    if not SESSION_DIR.exists():
        return sessions

    for status_file in SESSION_DIR.glob("*.status"):
        try:
            with open(status_file, 'r') as f:
                info = {}
                for line in f:
                    if ':' in line:
                        key, value = line.strip().split(':', 1)
                        info[key.strip()] = value.strip()

                if info.get('status') == 'running':
                    sessions.append({
                        'session': info.get('session'),
                        'pid': info.get('pid'),
                        'output': info.get('output'),
                        'started': info.get('started'),
                        'status_file': str(status_file)
                    })
        except Exception as e:
            print(f"⚠️  Error reading {status_file}: {e}")

    return sessions

def read_new_content(output_file, last_position):
    """Read new content from output file since last position"""
    try:
        with open(output_file, 'r') as f:
            f.seek(last_position)
            new_content = f.read()
            new_position = f.tell()
            return new_content, new_position
    except FileNotFoundError:
        return "", last_position
    except Exception as e:
        print(f"⚠️  Error reading {output_file}: {e}")
        return "", last_position

def detect_completion(content):
    """Simple completion detection"""
    if not content:
        return None

    # Check for error patterns
    if 'Error:' in content or 'error:' in content or 'ERROR' in content:
        return 'error'

    # Check for completion markers
    if 'CLI_EXITED' in content or 'exit' in content.lower():
        return 'completed'

    return None

def monitor_sessions():
    """Main monitoring loop"""
    print("🔍 Desktop CLI Session Monitor Starting")
    print(f"   Watching: {SESSION_DIR}")
    print(f"   Poll interval: {POLL_INTERVAL}s")
    print("")

    state = load_state()

    try:
        while True:
            sessions = get_active_sessions()

            if not sessions:
                print(f"💤 No active sessions ({datetime.now().strftime('%H:%M:%S')})", end='\r')
                time.sleep(POLL_INTERVAL)
                continue

            for session in sessions:
                session_name = session['session']
                output_file = session['output']

                # Get last read position
                last_pos = state.get(session_name, {}).get('position', 0)

                # Read new content
                new_content, new_pos = read_new_content(output_file, last_pos)

                if new_content:
                    # Display new content
                    print(f"\n📋 [{session_name}] New output:")
                    print("─" * 60)
                    print(new_content.rstrip())
                    print("─" * 60)

                    # Check for completion
                    status = detect_completion(new_content)
                    if status:
                        print(f"🔔 Session {session_name}: {status.upper()}")

                    # Update state
                    state[session_name] = {
                        'position': new_pos,
                        'last_update': datetime.now().isoformat()
                    }
                    save_state(state)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n🛑 Monitor stopped by user")
        save_state(state)

if __name__ == "__main__":
    # Ensure session directory exists
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    monitor_sessions()
