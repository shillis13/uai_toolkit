#!/usr/bin/env python3
"""
Task Coordination library.

Extracted from task-coord MCP server.py to follow
"thin wrapper around scripts" pattern.

Provides:
- Task lifecycle operations (find, move, generate, cancel)
- Playbook management (list, get, start, stop)
- Template listing
- Callback logic (save, execute, watcher setup)
- Task number generation
- YAML loading
- Watcher management (start, stop, list, cleanup)
"""

import os
import sys
import json
import yaml
import subprocess
import shutil
import signal
import fnmatch
import uuid
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Any


# === Configuration ===
AI_ROOT = Path(os.path.expanduser("~/AI/ai_root"))
PLAYBOOKS_DIR = AI_ROOT / "ai_general/data/playbooks"
TEMPLATES_DIR = AI_ROOT / "ai_general/templates"
COMMS_DIR = AI_ROOT / "ai_comms"
TASK_ROOT = Path(os.environ.get("TASK_ROOT", AI_ROOT / "ai_general" / "work" / "tasks"))
GEN_TASK_SCRIPT = Path(os.path.expanduser("~/bin/ai/tasks/gen-task"))
WATCH_DIR_SCRIPT = AI_ROOT / "ai_general/scripts/orchestration/watch_dir.sh"

# Directory layout: TASK_ROOT/{status}/{platform}/{task_id}/
KNOWN_PLATFORMS = ["claude_cli", "codex_cli", "gemini_cli", "chatgpt_cli"]
STATUSES = ["staged", "to_execute", "in_progress", "completed", "error", "cancelled"]


def _task_path(status: str, platform: str) -> Path:
    """Resolve a task directory path: TASK_ROOT/{status}/{platform}/."""
    return TASK_ROOT / status / platform

SERVER_VERSION = "1.2.0"

# Active file watchers: {watcher_id: {path, pattern, callback, pid, status, found_file, started_at}}
WATCHERS: dict[str, dict] = {}


# === Shared Callbacks Import ===
# The MCP server adds the shared module to sys.path before importing this lib.
# We import lazily to avoid path issues when used standalone.

_callbacks_imported = False
_CallbackInfo = None
_shared_execute_callback = None
_shared_save_callback_config = None
_load_callback_config = None
_CALLBACK_SCHEMA = None
_SEND_PROMPT_SCRIPT = None


def _ensure_callbacks():
    """Lazy import of shared callbacks module."""
    global _callbacks_imported, _CallbackInfo, _shared_execute_callback
    global _shared_save_callback_config, _load_callback_config
    global _CALLBACK_SCHEMA, _SEND_PROMPT_SCRIPT

    if _callbacks_imported:
        return

    # Try importing from shared (MCP server adds parent to path)
    try:
        from uai_toolkit.mcp.shared.callbacks import (
            CallbackInfo,
            CallbackResult,
            execute_callback as shared_exec_cb,
            save_callback_config as shared_save_cb,
            load_callback_config as load_cb,
            CALLBACK_SCHEMA,
            SEND_PROMPT_SCRIPT,
        )
        _CallbackInfo = CallbackInfo
        _shared_execute_callback = shared_exec_cb
        _shared_save_callback_config = shared_save_cb
        _load_callback_config = load_cb
        _CALLBACK_SCHEMA = CALLBACK_SCHEMA
        _SEND_PROMPT_SCRIPT = SEND_PROMPT_SCRIPT
        _callbacks_imported = True
    except ImportError:
        # When used standalone without shared module on path
        _callbacks_imported = True  # Don't retry


def get_callback_schema() -> dict:
    """Get the CALLBACK_SCHEMA from shared callbacks."""
    _ensure_callbacks()
    return _CALLBACK_SCHEMA or {}


def get_send_prompt_script() -> Optional[Path]:
    """Get the SEND_PROMPT_SCRIPT path from shared callbacks."""
    _ensure_callbacks()
    return _SEND_PROMPT_SCRIPT


# === Helper Functions ===

def test_server() -> dict:
    """Test server connectivity and configuration."""
    _ensure_callbacks()

    platform_status = {}
    for plat in KNOWN_PLATFORMS:
        task_count = 0
        for stat in STATUSES:
            stat_dir = _task_path(stat, plat)
            if stat_dir.exists():
                task_count += sum(1 for item in stat_dir.iterdir()
                                 if item.is_dir() and any(item.glob("*.md")))
        platform_status[plat] = {"exists": task_count > 0, "task_count": task_count}

    send_prompt_script = get_send_prompt_script()

    return {
        "server": "task-coord",
        "version": SERVER_VERSION,
        "status": "ok",
        "config": {
            "ai_root": str(AI_ROOT),
            "ai_root_exists": AI_ROOT.exists(),
            "playbooks_dir": str(PLAYBOOKS_DIR),
            "playbooks_dir_exists": PLAYBOOKS_DIR.exists(),
            "templates_dir": str(TEMPLATES_DIR),
            "templates_dir_exists": TEMPLATES_DIR.exists(),
            "gen_task_script": str(GEN_TASK_SCRIPT),
            "gen_task_script_exists": GEN_TASK_SCRIPT.exists(),
            "watch_dir_script": str(WATCH_DIR_SCRIPT),
            "watch_dir_script_exists": WATCH_DIR_SCRIPT.exists(),
            "send_prompt_script": str(send_prompt_script) if send_prompt_script else "N/A",
            "send_prompt_script_exists": send_prompt_script.exists() if send_prompt_script else False
        },
        "platforms": platform_status,
        "available_playbooks": len(get_playbooks()),
        "available_templates": len(get_templates()),
        "active_watchers": len(WATCHERS)
    }


def load_yaml(path: Path) -> dict:
    """Load YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def get_playbooks() -> list[dict]:
    """List all playbooks with metadata."""
    playbooks = []
    manifest_path = PLAYBOOKS_DIR / "manifest.yml"

    if manifest_path.exists():
        manifest = load_yaml(manifest_path)
        pb_dict = manifest.get("playbooks", {})
        for name, info in pb_dict.items():
            playbooks.append({
                "name": name,
                "type": info.get("type", "unknown"),
                "description": info.get("description", ""),
                "file": info.get("file", f"{name}.yml"),
                "start_action": info.get("start_action", {})
            })
    else:
        for f in PLAYBOOKS_DIR.glob("*.yml"):
            if f.name != "manifest.yml":
                playbooks.append({
                    "name": f.stem,
                    "type": "unknown",
                    "description": "",
                    "file": f.name,
                    "start_action": {}
                })
    return playbooks


def get_templates() -> list[str]:
    """List available task templates."""
    templates = []
    for f in TEMPLATES_DIR.glob("*.template.md"):
        name = f.name.replace(".template.md", "")
        templates.append(name)
    return sorted(templates)


def find_tasks(platform: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    """Find tasks matching criteria."""
    tasks = []
    platforms_to_check = [platform] if platform else KNOWN_PLATFORMS
    statuses_to_check = [status] if status else STATUSES

    for stat in statuses_to_check:
        for plat in platforms_to_check:
            status_dir = _task_path(stat, plat)
            if not status_dir.exists():
                continue
            for item in status_dir.iterdir():
                if item.is_dir():
                    for tf in item.glob("*.md"):
                        if ".template" not in tf.name:
                            tasks.append({
                                "id": item.name,
                                "file": tf.name,
                                "platform": plat,
                                "status": stat,
                                "path": str(tf)
                            })
                            break
    return tasks


def get_next_task_number(platform: str) -> int:
    """Get next available task number for platform."""
    max_num = 0
    if platform not in KNOWN_PLATFORMS:
        return 1
    for stat in STATUSES:
        status_dir = _task_path(stat, platform)
        if not status_dir.exists():
            continue
        for item in status_dir.iterdir():
            if item.is_dir() and item.name.startswith("task_"):
                try:
                    num = int(item.name.split("_")[1])
                    max_num = max(max_num, num)
                except (IndexError, ValueError):
                    pass
    return max_num + 1


# === Callback Functions ===

def save_callback_config(task_dir: Path, callback: dict, task_id: str, platform: str) -> Path:
    """Save callback configuration alongside a task. Wraps shared library."""
    _ensure_callbacks()
    if _CallbackInfo and _shared_save_callback_config:
        cb_info = _CallbackInfo.from_dict(callback) if isinstance(callback, dict) else callback
        return _shared_save_callback_config(task_dir, cb_info, task_id=task_id, platform=platform)
    raise RuntimeError("Shared callbacks module not available")


def execute_callback(task_dir: Path, task_id: str, new_status: str, platform: str) -> Optional[str]:
    """Check for and execute callback if .callback.yml exists in task dir."""
    _ensure_callbacks()
    if not _load_callback_config or not _shared_execute_callback:
        return None

    cb_info = _load_callback_config(task_dir)
    if cb_info is None:
        return None

    result = _shared_execute_callback(
        cb_info, task_id=task_id, status=new_status,
    )

    # Mark callback as fired (preserve task-coord behavior)
    now = datetime.now()
    fired_file = task_dir / ".callback_fired"
    fired_file.write_text(f"fired_at: {now.isoformat()}\nstatus: {new_status}\nresult: {result.message}\n")

    return result.message


def parse_task_info_from_output(output: str) -> dict:
    """Extract task_id and path from gen-task script output.

    Expected output format:
        Created: /path/to/req_0042_name/req_0042_name.md
        Queue: claude_cli / staged
        Request ID: 0042
    """
    info = {}

    created_match = re.search(r"Created:\s+(.+)", output)
    if created_match:
        created_path = Path(created_match.group(1).strip())
        info["task_file"] = str(created_path)
        info["task_dir"] = str(created_path.parent)
        info["task_id"] = created_path.parent.name

    req_match = re.search(r"Request ID:\s+(\d+)", output)
    if req_match:
        info["req_id"] = req_match.group(1)

    queue_match = re.search(r"Queue:\s+(\S+)\s+/\s+(\S+)", output)
    if queue_match:
        info["platform"] = queue_match.group(1)
        info["status"] = queue_match.group(2)

    return info


def setup_completion_watcher(task_id: str, platform: str) -> list[dict]:
    """Set up watchers for task completion in terminal status directories.

    Returns list of watcher info dicts with watcher_id for each terminal status.
    Watchers monitor completed/, error/, and cancelled/ directories for the task.
    """
    fire_callback_script = AI_ROOT / "ai_general/scripts/orchestration/fire_callback.py"
    if not fire_callback_script.exists():
        return [{"error": f"fire_callback.py not found at {fire_callback_script}"}]

    watchers = []
    terminal_statuses = ["completed", "error", "cancelled"]

    for status in terminal_statuses:
        watch_dir = _task_path(status, platform)
        watch_dir.mkdir(parents=True, exist_ok=True)

        # Watch for task directory appearing in terminal status
        pattern = f"{task_id}/*"

        # Command template: {dir} is the task directory (e.g., completed/req_4016_task_foo)
        command = f"python3 {fire_callback_script} {{dir}} {task_id} {status} {platform}"
        label = f"callback_{task_id}_{status}"

        watcher = start_watcher(
            watch_path=str(watch_dir),
            pattern=pattern,
            command=command,
            one_shot=True,
            timeout=0,
            label=label
        )
        watchers.append(watcher)

    return watchers


# === Watcher Functions ===

def start_watcher(watch_path: str, pattern: str, command: str = "",
                  one_shot: bool = True, timeout: int = 0, label: str = "") -> dict:
    """Start an fswatch watcher using watch_dir.sh."""
    watcher_id = str(uuid.uuid4())[:8]
    if not label:
        label = f"watcher_{watcher_id}"

    cmd = [str(WATCH_DIR_SCRIPT)]
    if one_shot:
        cmd.append("--one-shot")
    if timeout > 0:
        cmd.extend(["--timeout", str(timeout)])
    cmd.extend(["--label", label])
    cmd.append(watch_path)
    cmd.append(pattern)
    cmd.append(command if command else "echo 'File matched: {filepath}'")

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True
    )

    WATCHERS[watcher_id] = {
        "id": watcher_id, "path": watch_path, "pattern": pattern,
        "command": command, "one_shot": one_shot, "timeout": timeout,
        "label": label, "pid": proc.pid, "status": "running",
        "started_at": datetime.now().isoformat()
    }
    return WATCHERS[watcher_id]


def stop_watcher(watcher_id: str) -> dict:
    """Stop a running watcher."""
    if watcher_id not in WATCHERS:
        return {"error": f"Watcher not found: {watcher_id}"}
    watcher = WATCHERS[watcher_id]
    try:
        os.killpg(os.getpgid(watcher["pid"]), signal.SIGTERM)
        watcher["status"] = "stopped"
    except ProcessLookupError:
        watcher["status"] = "already_completed"
    except Exception as e:
        watcher["status"] = f"error: {e}"
    return watcher


def list_watchers() -> list[dict]:
    """List all active watchers."""
    return list(WATCHERS.values())


def cleanup_completed_watchers() -> int:
    """Remove completed/stopped watchers from tracking. Returns count removed."""
    to_remove = []
    for watcher_id, watcher in WATCHERS.items():
        if watcher["status"] in ("stopped", "already_completed"):
            to_remove.append(watcher_id)
            continue
        # Check if process is still alive
        try:
            os.kill(watcher["pid"], 0)
        except ProcessLookupError:
            to_remove.append(watcher_id)
    for watcher_id in to_remove:
        del WATCHERS[watcher_id]
    return len(to_remove)


# === High-Level Task Operations (called by MCP server) ===

def get_playbook_content(name: str) -> Optional[str]:
    """Get full playbook definition as YAML string. Returns None if not found."""
    pb_file = PLAYBOOKS_DIR / f"{name}.yml"
    if not pb_file.exists():
        return None
    content = load_yaml(pb_file)
    return yaml.dump(content, default_flow_style=False)


def start_playbook(name: str, params: dict, callback: Optional[dict] = None) -> dict:
    """Start a playbook - creates initial task or runs start action.

    Returns dict with 'output' (success text) or 'error' key.
    """
    playbooks = get_playbooks()
    playbook = None
    for pb in playbooks:
        if pb["name"] == name:
            playbook = pb
            break

    if not playbook:
        return {"error": f"Playbook not found: {name}"}

    start_action = playbook.get("start_action", {})
    action_type = start_action.get("type", "create_task")

    if action_type == "create_task":
        template = start_action.get("template", "planning")
        platform = start_action.get("platform", "claude_cli")

        cmd = [str(GEN_TASK_SCRIPT), template, "--platform", platform]
        for k, v in params.items():
            cmd.append(f"{k.upper()}={v}")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return {"error": result.stderr}

        # Save callback config if provided
        output = result.stdout
        callback_info = ""
        if callback:
            task_info = parse_task_info_from_output(output)
            if task_info.get("task_dir"):
                task_dir = Path(task_info["task_dir"])
                task_id = task_info.get("task_id", "unknown")
                cb_path = save_callback_config(task_dir, callback, task_id, platform)
                callback_info = f"\nCallback configured: {cb_path}"

        return {"output": output + callback_info}

    elif action_type == "run_script":
        script = start_action.get("script")
        if not script:
            return {"error": "No script defined in playbook"}
        script_path = Path(os.path.expanduser(script))
        cmd = [str(script_path)] + [f"{k}={v}" for k, v in params.items()]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {"output": result.stdout or result.stderr}

    else:
        return {"error": f"Unknown action type: {action_type}"}


def stop_playbook(task_id: str) -> dict:
    """Stop/cancel a running playbook by task ID.

    Returns dict with 'output' or 'error' key.
    """
    found = None
    for plat in KNOWN_PLATFORMS:
        for status in ["staged", "to_execute", "in_progress"]:
            task_dir = _task_path(status, plat) / task_id
            if task_dir.exists():
                found = {"path": task_dir, "platform": plat, "status": status}
                break
        if found:
            break

    if not found:
        return {"error": f"Task not found: {task_id}"}

    cancelled_dir = _task_path("cancelled", found["platform"])
    cancelled_dir.mkdir(parents=True, exist_ok=True)
    dest = cancelled_dir / task_id
    shutil.move(str(found["path"]), str(dest))

    # Fire callback on cancellation (terminal status)
    cb_result = execute_callback(dest, task_id, "cancelled", found["platform"])
    cb_msg = f"\nCallback fired: {cb_result}" if cb_result else ""

    return {"output": f"Cancelled: {task_id}\nMoved to: {dest}{cb_msg}"}


def gen_task(template: str, platform: str, params: dict,
             execute: bool = False, callback: Optional[dict] = None) -> dict:
    """Generate a task from template.

    Returns dict with 'output' or 'error' key.
    """
    cmd = [str(GEN_TASK_SCRIPT), template, "--platform", platform]
    if execute:
        cmd.append("--execute")
    for k, v in params.items():
        cmd.append(f"{k.upper()}={v}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"error": result.stderr}

    # Save callback config and setup watchers if provided
    output = result.stdout
    callback_info = ""
    watcher_info = ""
    if callback:
        task_info = parse_task_info_from_output(output)
        if task_info.get("task_dir"):
            task_dir = Path(task_info["task_dir"])
            task_id = task_info.get("task_id", "unknown")
            cb_path = save_callback_config(task_dir, callback, task_id, platform)
            callback_info = f"\nCallback configured: {cb_path}"

            # Start watchers for terminal status monitoring
            watchers = setup_completion_watcher(task_id, platform)
            watcher_ids = [w.get("id", "unknown") for w in watchers if "error" not in w]
            if watcher_ids:
                watcher_info = f"\nWatchers started: {', '.join(watcher_ids)}"

    return {"output": output + callback_info + watcher_info}


def get_task_content(task_id: str) -> dict:
    """Get task content by ID or path.

    Returns dict with 'content' or 'error' key.
    """
    if "/" in task_id:
        task_path = Path(task_id)
        if task_path.exists():
            with open(task_path) as f:
                return {"content": f.read()}
        return {"error": f"Task file not found: {task_id}"}

    tasks = find_tasks()
    for t in tasks:
        if t["id"] == task_id:
            with open(t["path"]) as f:
                return {"content": f.read()}
    return {"error": f"Task not found: {task_id}"}


def move_task(task_id: str, new_status: str, platform: Optional[str] = None) -> dict:
    """Move task to new status.

    Returns dict with 'output' or 'error' key.
    """
    if new_status not in STATUSES:
        return {"error": f"Invalid status: {new_status}"}

    tasks = find_tasks(platform=platform)
    found = None
    for t in tasks:
        if t["id"] == task_id:
            found = t
            break

    if not found:
        return {"error": f"Task not found: {task_id}"}

    # Move directory
    src = Path(found["path"]).parent
    dest_dir = _task_path(new_status, found["platform"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / task_id
    shutil.move(str(src), str(dest))

    # Protocol v9.0: Create flag files for state tracking
    parts = task_id.split("_")
    if len(parts) >= 2 and parts[0] == "req":
        req_id = f"{parts[0]}_{parts[1]}"
    else:
        req_id = task_id

    dt_stamp = datetime.now().strftime("%Y%m%dT%H%M%S")

    if new_status == "in_progress":
        flag_file = dest / f"{req_id}_{dt_stamp}_started"
        flag_file.touch()
    elif new_status == "completed":
        flag_file = dest / f"{req_id}_{dt_stamp}_completed"
        flag_file.touch()
    elif new_status == "error":
        flag_file = dest / f"{req_id}_{dt_stamp}_error"
        flag_file.touch()
    elif new_status == "cancelled":
        flag_file = dest / f"{req_id}_{dt_stamp}_cancelled"
        flag_file.touch()

    # Handle callbacks: fire on terminal, setup watchers on non-terminal
    callback_msg = ""
    watcher_msg = ""
    callback_file = dest / ".callback.yml"

    if callback_file.exists():
        if new_status in ("completed", "error", "cancelled"):
            # Terminal status: fire callback immediately
            cb_result = execute_callback(dest, task_id, new_status, found["platform"])
            if cb_result:
                callback_msg = f"\nCallback fired: {cb_result}"
        else:
            # Non-terminal status: restart watchers for next completion
            watchers = setup_completion_watcher(task_id, found["platform"])
            watcher_ids = [w.get("id", "unknown") for w in watchers if "error" not in w]
            if watcher_ids:
                watcher_msg = f"\nWatchers restarted: {', '.join(watcher_ids)}"

    return {"output": f"Moved {task_id} to {new_status}\nPath: {dest}{callback_msg}{watcher_msg}"}


def list_platforms() -> list[dict]:
    """List available task platforms."""
    return [{"name": p, "path": str(TASK_ROOT / "*" / p)} for p in KNOWN_PLATFORMS]
