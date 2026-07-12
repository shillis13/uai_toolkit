"""
CLI agent operations library.

Provides the business logic behind agent launching, session management, task
factory creation, and terminal interaction.

Architecture:
- MCP tools do not import this module directly.
- `agent_ops_cli.py` imports this module and exposes a subprocess-safe JSON CLI.
- `sessions_cli_agent.py` shells out to `agent_ops_cli.py`.

All functions are synchronous and return plain dicts or strings.
"""

import os
import sys
import json
import yaml
import shutil
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Any


# === Configuration ===

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS

CLI_DIR = AI_SCRIPTS / "cli"
ROLES_DIR = AI_ROOT / "ai_general/prompts/roles"
ROLES_DIR_NEW = AI_ROOT / "ai_general/roles"  # new location (preferred)
COMMS_DIR = AI_ROOT / "ai_comms"
TASK_ROOT = Path(os.environ.get("TASK_ROOT", AI_ROOT / "ai_general" / "work" / "tasks"))

PLATFORMS = {
    "claude_cli": {
        "script": CLI_DIR / "claudeCli",
        "tasks_dir": TASK_ROOT / "claude_cli",
    },
    "codex_cli": {
        "script": CLI_DIR / "codexCli",
        "tasks_dir": TASK_ROOT / "codex_cli",
    },
    "gemini_cli": {
        "script": CLI_DIR / "geminiCli",
        "tasks_dir": TASK_ROOT / "gemini_cli",
    },
}

ROLES = ["librarian", "dev_lead", "custodian", "peer_review", "tester", "researcher", "validator"]

SERVER_VERSION = "1.0.0"


# === Helper Functions ===

def _ensure_session_mgmt_path():
    """Add session_mgmt scripts to sys.path if not already present."""
    session_mgmt_dir = str(AI_SCRIPTS / "session_mgmt")
    if session_mgmt_dir not in sys.path:
        sys.path.insert(0, session_mgmt_dir)


def _get_substrate():
    """Get the auto-detected session substrate instance."""
    _ensure_session_mgmt_path()
    from uai_toolkit.session_mgmt.lib_session_substrate import get_substrate
    return get_substrate()


def _get_session_store():
    """Lazy helper for session registry access."""
    _ensure_session_mgmt_path()
    from uai_toolkit.session_mgmt.session_store import SessionStore
    return SessionStore()


def _normalize_roles_arg(roles: Any) -> list[str]:
    """Normalize stored or CLI roles into a list of role strings."""
    if roles is None:
        return []
    if isinstance(roles, list):
        return [str(role).strip().replace("-", "_") for role in roles if str(role).strip()]
    if isinstance(roles, str):
        text = roles.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(role).strip().replace("-", "_") for role in parsed if str(role).strip()]
        return [part.strip().replace("-", "_") for part in text.split(",") if part.strip()]
    return []


def resolve_registry_entry(identifier: str) -> Optional[dict]:
    """Resolve any session identifier via SessionStore."""
    try:
        return _get_session_store().resolve(identifier)
    except Exception:
        return None


def _parse_launcher_result(output: str) -> dict:
    """Parse TRACKING_ID=... style launcher output into a dict."""
    result: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def test_server() -> dict:
    """Test server connectivity and configuration."""
    # Check which roles have config files (check both old and new locations)
    role_status = {}
    for role in ROLES:
        old_role_file = ROLES_DIR / role / "role.yml"
        new_role_file = ROLES_DIR_NEW / role / "role.yml"
        new_instructions = ROLES_DIR_NEW / role / "instructions.md"
        role_status[role] = old_role_file.exists() or new_role_file.exists() or new_instructions.exists()

    # Check platform scripts
    platform_status = {}
    for plat, config in PLATFORMS.items():
        platform_status[plat] = {
            "script_exists": config["script"].exists(),
            "tasks_dir_exists": config["tasks_dir"].exists()
        }

    # Check substrate availability
    try:
        sub = _get_substrate()
        substrate_info = {"name": sub.substrate_name, "available": True}
    except Exception as e:
        substrate_info = {"name": "unknown", "available": False, "error": str(e)}

    return {
        "server": "cli-agent",
        "version": SERVER_VERSION,
        "status": "ok",
        "config": {
            "ai_root": str(AI_ROOT),
            "ai_root_exists": AI_ROOT.exists(),
            "cli_dir": str(CLI_DIR),
            "cli_dir_exists": CLI_DIR.exists(),
            "roles_dir": str(ROLES_DIR),
            "roles_dir_exists": ROLES_DIR.exists()
        },
        "substrate": substrate_info,
        "roles": role_status,
        "platforms": platform_status
    }


def get_terminal_sessions() -> list[dict]:
    """Get all terminal sessions with metadata via substrate."""
    try:
        _ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        sessions = list_sessions()
        return [
            {"session_id": s["name"], "attached": s.get("attached", False)}
            for s in sessions
        ]
    except Exception:
        return []


def get_session_info(session_id: str) -> Optional[dict]:
    """Get detailed info for a specific terminal session via substrate."""
    registry_entry = resolve_registry_entry(session_id)
    registry_roles = _normalize_roles_arg(registry_entry.get("roles")) if registry_entry else []
    registry_platform = registry_entry.get("platform") if registry_entry else None
    registry_display_name = registry_entry.get("display_name") if registry_entry else None

    try:
        _ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        all_sessions = list_sessions()
        for s in all_sessions:
            name = s["name"]
            if name != session_id:
                continue

            attached = s.get("attached", False)
            exited = not s.get("running", True)
            platform, role = parse_session_name(name)

            # Compute created-ago from timestamp if available
            created_ago = ""
            created_ts = s.get("created")
            if created_ts:
                try:
                    from datetime import timezone
                    created_dt = datetime.fromisoformat(created_ts)
                    delta = datetime.now(timezone.utc) - created_dt
                    created_ago = format_runtime(delta.total_seconds())
                except (ValueError, TypeError):
                    pass

            if exited:
                status = "exited"
            elif attached:
                status = "attached"
            else:
                status = "running"

            role = registry_roles[0] if registry_roles else role
            platform = registry_platform or platform
            if role and role not in ROLES:
                return None

            return {
                "session_id": name,
                "tracking_id": registry_entry.get("tracking_id") if registry_entry else name,
                "platform": platform,
                "role": role,
                "display_name": registry_display_name or role or name,
                "created_ago": created_ago,
                "attached": attached,
                "status": status
            }
    except Exception:
        pass

    if registry_entry:
        role = registry_roles[0] if registry_roles else None
        if role and role not in ROLES:
            return None
        return {
            "session_id": registry_entry.get("terminal_session") or session_id,
            "tracking_id": registry_entry.get("tracking_id", session_id),
            "platform": registry_entry.get("platform"),
            "role": role,
            "display_name": registry_display_name or role or session_id,
            "created_ago": "",
            "attached": False,
            "status": registry_entry.get("status", "unknown"),
        }
    return None


def parse_session_name(name: str) -> tuple[Optional[str], Optional[str]]:
    """Parse session name to extract platform and role."""
    platform = None
    role = None

    for plat in PLATFORMS.keys():
        if name.startswith(plat):
            platform = plat
            break

    for r in ROLES:
        if f"_{r}_" in name or name.endswith(f"_{r}"):
            role = r
            break

    return platform, role


def format_runtime(seconds: float) -> str:
    """Format runtime as human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def capture_pane_output(session_id: str, lines: int = 50) -> str:
    """Capture recent output from terminal session via substrate."""
    try:
        _ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import read_terminal
        output = read_terminal(session_id)
        if not output:
            return ""
        all_lines = output.strip().split("\n")
        if lines and len(all_lines) > lines:
            all_lines = all_lines[-lines:]
        return "\n".join(all_lines)
    except Exception:
        return ""


def session_exists(session_id: str) -> bool:
    """Check if terminal session exists via substrate."""
    try:
        _ensure_session_mgmt_path()
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        sessions = list_sessions()
        return any(s["name"] == session_id for s in sessions)
    except Exception:
        return False


def attach(session_id: str) -> None:
    """Attach to a terminal session via substrate (session-aware server resolution)."""
    _ensure_session_mgmt_path()
    from uai_toolkit.session_mgmt.session_ops import _resolve_substrate_for_session
    sub = _resolve_substrate_for_session(session_id)
    sub.attach(session_id)


def generate_session_name(platform: str, role: str) -> str:
    """Generate unique session name."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{platform}_{role}_{timestamp}"


# === Task Factory Helpers ===

def get_next_req_id(platform: str) -> int:
    """Scan tasks directory and return next available req_id."""
    tasks_dir = PLATFORMS[platform]["tasks_dir"]
    max_id = 0

    # Check all status directories
    for status in ["staged", "to_execute", "in_progress", "completed", "error", "cancelled"]:
        status_dir = tasks_dir / status
        if not status_dir.exists():
            continue
        for item in status_dir.iterdir():
            if item.is_dir():
                match = re.match(r"req_(\d+)_", item.name)
                if match:
                    req_num = int(match.group(1))
                    max_id = max(max_id, req_num)

    return max_id + 1


def slugify(text: str, max_length: int = 40) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s-]+', '_', slug)
    slug = slug.strip('_')

    if len(slug) > max_length:
        slug = slug[:max_length].rstrip('_')

    return slug or "task"


def get_role_instructions_path(role: str) -> Optional[Path]:
    """Find instructions file for a role, checking new and old locations."""
    # Check new location first (ai_general/roles/) - try both naming conventions
    for filename in ["instructions.md", "prompt.md"]:
        new_path = ROLES_DIR_NEW / role / filename
        if new_path.exists():
            return new_path

    # Fall back to old location (ai_general/prompts/roles/)
    old_path = ROLES_DIR / role / "prompt.md"
    if old_path.exists():
        return old_path

    # Check for role.yml to find custom instructions_file
    role_yml = ROLES_DIR / role / "role.yml"
    if role_yml.exists():
        try:
            with open(role_yml) as f:
                role_meta = yaml.safe_load(f)
            instr_file = role_meta.get("instructions_file", "prompt.md")
            custom_path = ROLES_DIR / role / instr_file
            if custom_path.exists():
                return custom_path
        except:
            pass

    return None


def create_task_for_launch(
    platform: str,
    role: str,
    query: str
) -> dict:
    """
    Create a task directory with instructions and task file.
    Returns dict with task_id and task_path on success.
    """
    import hashlib

    # Get next req_id
    req_id = get_next_req_id(platform)
    req_str = f"req_{req_id:04d}"

    # Generate slug from query
    slug = slugify(query)
    task_name = f"{req_str}_{slug}"

    # Create task directory in to_execute/
    tasks_dir = PLATFORMS[platform]["tasks_dir"]
    to_execute = tasks_dir / "to_execute"
    to_execute.mkdir(parents=True, exist_ok=True)

    task_dir = to_execute / task_name
    task_dir.mkdir(exist_ok=True)

    # Copy role instructions
    instructions_src = get_role_instructions_path(role)
    if instructions_src:
        instructions_dst = task_dir / "instructions.md"
        shutil.copy(instructions_src, instructions_dst)
        template_source = str(instructions_src.relative_to(AI_ROOT))

        # Compute hash for audit trail
        with open(instructions_src, 'rb') as f:
            template_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    else:
        template_source = None
        template_hash = None

    # Write task file
    task_file = task_dir / f"{task_name}.md"
    now = datetime.now().isoformat()

    task_content = f"""---
metadata:
  id: {req_str}
  slug: {slug}
  created: {now}
  role: {role}
  platform: {platform}
  template_source: {template_source or "none"}
  template_hash: {template_hash or "none"}
---

# Query

{query}

# Instructions

See `instructions.md` in this directory for role-specific instructions.

# Response

Write your response to `{req_str}_{slug}.response.md` in this directory.
"""

    with open(task_file, 'w') as f:
        f.write(task_content)

    return {
        "success": True,
        "task_id": task_name,
        "task_path": str(task_dir),
        "task_file": str(task_file),
        "req_id": req_id,
        "instructions_copied": instructions_src is not None
    }


def launch_cli_agent(
    platform: str,
    role: str,
    task_id: Optional[str] = None,
    prompt: Optional[str] = None,
    context_files: Optional[list[str]] = None,
    use_devtree: bool = False
) -> dict:
    """Launch a CLI agent with given parameters.

    This is a higher-level agent workflow wrapper over the canonical platform
    launcher entrypoints (claudeCli/codexCli/geminiCli). Terminal session
    creation and CLI execution are owned by the launcher, not by this module.
    """

    if platform not in PLATFORMS:
        return {"success": False, "error": f"Unknown platform: {platform}. Valid: {list(PLATFORMS.keys())}"}

    # Normalize role name (support both hyphen and underscore)
    role_normalized = role.replace("-", "_")
    if role_normalized not in ROLES:
        return {"success": False, "error": f"Unknown role: {role}. Valid: {ROLES}"}

    script = PLATFORMS[platform]["script"]
    if not script.exists():
        return {"success": False, "error": f"CLI script not found: {script}"}

    display_name = generate_session_name(platform, role_normalized)

    # Build command
    cmd = ["python3", str(script)]
    # NOTE: do NOT pass "-a" here. The launcher already auto-approves by default, and
    # "-a" is not one of its options — it falls through parse_known_args and is appended
    # verbatim to the vendor CLI. Codex's strict parser maps "-a" to "--ask-for-approval"
    # (which needs a value) and exits 2, so the session dies with no UUID/transcript.
    # (Claude tolerates the stray flag; codex does not.)
    cmd.extend(["-A", role_normalized])  # agent/role
    cmd.extend(["--display-name", display_name])

    # Task XOR prompt
    if task_id and prompt:
        return {"success": False, "error": "Provide task_id OR prompt, not both"}

    task_factory_result = None  # Track if we created a task

    if task_id:
        task_path = PLATFORMS[platform]["tasks_dir"] / "to_execute" / task_id
        if task_path.is_dir():
            md_files = list(task_path.glob("*.md"))
            if md_files:
                cmd.extend(["-T", str(md_files[0])])
            else:
                return {"success": False, "error": f"No .md file in task directory: {task_path}"}
        elif task_path.with_suffix(".md").exists():
            cmd.extend(["-T", str(task_path.with_suffix(".md"))])
        else:
            return {"success": False, "error": f"Task not found: {task_id}"}
    elif prompt:
        # Create task via task-factory, then launch with task
        task_factory_result = create_task_for_launch(platform, role_normalized, prompt)
        if not task_factory_result.get("success"):
            return {"success": False, "error": f"Task creation failed: {task_factory_result}"}

        created_task_file = task_factory_result["task_file"]
        cmd.extend(["-T", created_task_file])
    else:
        # No task or prompt — launch an interactive agent session (idle at its prompt).
        # NOTE: previously appended "--any-task", but the launcher doesn't define that
        # flag, so it fell through to the vendor CLI and broke codex (exit 2). The
        # "grab next from to_execute" intent was already dead on this path anyway.
        pass

    # DevTree isolation
    if use_devtree:
        cmd.append("--use-devtree")

    # Additional context files via --pre-prompt
    if context_files:
        file_refs = ", ".join(f"'{f}'" for f in context_files)
        pre = f"Also read: {file_refs}."
        cmd.extend(["--pre-prompt", pre])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(AI_ROOT),
            timeout=90,
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

    if result.returncode != 0:
        return {
            "success": False,
            "error": (result.stderr or result.stdout or f"Launch failed (exit {result.returncode})").strip(),
            "debug": {
                "cmd": cmd,
                "cwd": str(AI_ROOT),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            },
        }

    launch_info = _parse_launcher_result(result.stdout)
    session_name = launch_info.get("TERMINAL", "")
    tracking_id = launch_info.get("TRACKING_ID", "")
    cli_uuid = launch_info.get("CLI_UUID", "")
    if not session_name or not tracking_id:
        return {
            "success": False,
            "error": f"Unexpected launcher output: {result.stdout.strip()}",
            "debug": {
                "cmd": cmd,
                "cwd": str(AI_ROOT),
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            },
        }

    registry_entry = resolve_registry_entry(tracking_id)
    if registry_entry and registry_entry.get("roles") in (None, [], "[]", ""):
        try:
            _get_session_store().update(tracking_id, roles=[role_normalized])
        except Exception:
            pass

    substrate_name = registry_entry.get("substrate") if registry_entry else ""
    return {
        "success": True,
        "session_id": session_name,
        "tracking_id": tracking_id,
        "platform": platform,
        "role": role_normalized,
        "cli_uuid": cli_uuid,
        "status": "launched",
        "message": f"Agent launched via {script.name}: {session_name}",
        "task": task_factory_result if task_factory_result else None,
        "debug": {
            "cmd": cmd,
            "cwd": str(AI_ROOT),
            "substrate": substrate_name,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    }
