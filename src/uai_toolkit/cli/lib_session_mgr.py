#!/usr/bin/env python3
"""Layer 3: session bookkeeping helpers for ai_launch.

Owns tracking IDs, registry access, transcript discovery, environment
construction, and runtime discovery helpers. This module does not build vendor
CLI commands.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_SESSION_MGMT_DIR = _SCRIPT_DIR.parent / 'session_mgmt'
for _d in (_SCRIPT_DIR, _SESSION_MGMT_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.cli.lib_paths import AI_ROOT, get_ai_root
from uai_toolkit.session_mgmt.session_store import PLATFORM_CODES, SessionStore, compute_session_dir_path
from uai_toolkit.session_mgmt import lib_session_substrate as substrate_runtime

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

_store = SessionStore()
CODEX_SESSIONS_DIR = Path.home() / '.codex' / 'sessions'
GEMINI_TMP_DIR = Path.home() / '.gemini' / 'tmp'


def get_store() -> SessionStore:
    return _store


def platform_short(platform: str) -> str:
    return platform.replace('_cli', '')


def allocate_tracking_identity(
    platform: str,
    seed_uuid: str | None = None,
    *,
    strict_seed: bool = False,
) -> tuple[str, str]:
    """Mint a tracking ID together with the full UUID whose 8-char prefix it embeds.

    Returns ``(tracking_id, chosen_uuid)``. The tracking ID's uuid8 component is
    always ``chosen_uuid[:8]``, so a launcher that hands ``chosen_uuid`` to the
    vendor CLI (Claude ``--session-id``) guarantees, *by construction*, that
    ``uuid8 == cli_session_id[:8]``. This is the single point where that
    correspondence is established — nothing downstream parses it back out
    (session_mgmt/DESIGN.md: tracking IDs are opaque strings).

    seed_uuid: preferred UUID — an explicit ``--session-id`` or a reserved
        draft's ``cli_session_id``. When omitted, a fresh uuid4 is minted.
    strict_seed: when True (an explicit, user-supplied seed), a tracking-ID
        collision raises rather than silently substituting a different UUID, so
        an explicit ``--session-id`` is never quietly replaced.
    """
    now = datetime.now()
    code = PLATFORM_CODES.get(platform)
    if not code:
        raise ValueError(f'Unknown platform for tracking ID: {platform}')
    for attempt in range(100):
        if attempt == 0:
            chosen_uuid = seed_uuid or str(_uuid.uuid4())
        elif strict_seed and seed_uuid:
            raise RuntimeError(
                f'Tracking ID collision for explicit seed {seed_uuid} at '
                f'{now.isoformat()}; refusing to substitute a different UUID.'
            )
        else:
            chosen_uuid = str(_uuid.uuid4())
        uuid8 = chosen_uuid.replace('-', '')[:8].lower()
        candidate = f"{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}_{uuid8}_{code}"
        if _store.get(candidate) is None:
            return candidate, chosen_uuid
    raise RuntimeError(f'Cannot generate unique tracking ID for {platform} at {now.isoformat()}')


def generate_tracking_id(platform: str, seed_uuid: str | None = None) -> str:
    """Back-compat wrapper. New code should use allocate_tracking_identity so the
    chosen UUID can be reused as the vendor CLI session id (keeping the uuid8
    correspondence intact through the collision-fallback path)."""
    tracking_id, _ = allocate_tracking_identity(platform, seed_uuid)
    return tracking_id


def reserve_draft(
    platform: str,
    *,
    display_name: str | None = None,
    project_dir: str | None = None,
    roles: list[str] | None = None,
    parent_tracking_id: str | None = None,
    seed_uuid: str | None = None,
    notes: str | None = None,
) -> tuple[str, str | None]:
    """Reserve a draft session: mint launcher-owned identity and persist the draft
    row. Returns ``(tracking_id, cli_uuid)``.

    For Claude the reserved full UUID is stored as ``cli_session_id`` so the
    eventual launch (via ``--tracking-id``) reuses it as ``--session-id``,
    keeping ``uuid8 == cli_session_id[:8]``. For Codex/Gemini the real UUID is
    discovered only after launch, so ``cli_session_id`` is left null here and the
    tracking uuid8 stays a launch-time label.

    This is the app-facing reservation entrypoint: the app must not mint identity
    itself (session_mgmt/DESIGN.md: ai_launcher.py owns identity creation).
    """
    tracking_id, chosen_uuid = allocate_tracking_identity(platform, seed_uuid)
    cli_uuid = pre_assign_uuid(platform, chosen_uuid)  # claude only; None otherwise
    session_dir = compute_session_dir(tracking_id, platform)
    create_session(
        tracking_id=tracking_id,
        terminal_session=tracking_id,
        platform=platform,
        cli_session_id=cli_uuid,
        parent_tracking_id=parent_tracking_id,
        display_name=display_name,
        project_dir=project_dir,
        session_dir=session_dir,
        roles=roles or ['assistant'],
        identity_status='draft',
        notes=notes,
    )
    return tracking_id, cli_uuid


def pre_assign_uuid(platform: str, seed_uuid: str) -> str | None:
    """Return a launch-time UUID when the platform supports pre-assignment."""
    return seed_uuid if platform == 'claude_cli' else None


def build_launch_env(
    tracking_id: str,
    cli_uuid: str | None,
    platform: str,
    session_dir: str,
    project_dir: str,
    substrate_context: str | None = None,
) -> dict[str, str]:
    # Ensure myenv/bin is on PATH so scripts find pip-installed packages (keyring, etc.)
    myenv_bin = str(Path.home() / 'myenv' / 'bin')
    bin_bin = str(Path.home() / 'bin' / 'bin')
    current_path = os.environ.get('PATH', '')
    if myenv_bin not in current_path:
        current_path = f"{myenv_bin}:{bin_bin}:{current_path}"

    # AI_ROOT: respect an explicitly-provided root (devTrees pass their own via
    # the inherited env), but normalize the legacy ~/Documents/AI -> ~/AI
    # backwards-compat symlink so a child session never inherits the stale
    # Documents-form path. Falls back to the canonical default when unset.
    # os.path.realpath collapses the symlink while preserving devTree subpaths.
    _root = os.environ.get('AI_ROOT') or str(get_ai_root())
    ai_root = os.path.realpath(_root)
    # Normalize the legacy ~/Documents/AI -> ~/AI compat symlink on every path
    # var the session (and its statusline, which reads AI_SESSION_DIR) will
    # display or inherit — so none of them carry the stale Documents prefix,
    # regardless of what the registry/caller passed in. realpath only collapses
    # symlinks; devTree subpaths are preserved.
    session_dir = os.path.realpath(session_dir) if session_dir else session_dir
    project_dir = os.path.realpath(project_dir) if project_dir else project_dir

    env = {
        'AI_ROOT': ai_root,
        'AI_TRACKING_ID': tracking_id,
        'AI_CLI_SESSION_ID': cli_uuid or '',
        'AI_SESSION_DIR': session_dir,
        'AI_SESSION_PLATFORM': platform,
        'AI_PROJECT_DIR': project_dir,
        'PATH': current_path,
    }
    if substrate_context:
        env['AI_SUBSTRATE_CONTEXT'] = substrate_context
    return env


def current_substrate_context() -> str:
    return substrate_runtime.derive_substrate_context_name(AI_ROOT)


def apply_launch_env(env_vars: dict[str, str]) -> None:
    for key, value in env_vars.items():
        os.environ[key] = value


def shell_env_prefix(env_vars: dict[str, str]) -> str:
    return ' '.join(f"{key}={shlex.quote(value)}" for key, value in env_vars.items())


def normalize_roles_arg(roles: str | None) -> list[str]:
    if not roles:
        return ['assistant']
    parsed = [part.strip().replace('-', '_') for part in roles.split(',') if part.strip()]
    return parsed or ['assistant']


def build_identity_block(
    tracking_id: str,
    terminal_session: str | None,
    cli_uuid: str | None,
    parent_tracking_id: str | None = None,
) -> str:
    parts = [
        f'Tracking ID: {tracking_id}',
        f'Terminal session: {terminal_session or "none"}',
        f'CLI session ID: {cli_uuid or "pending"}',
        f'Parent: {parent_tracking_id or "none"}',
    ]
    return '<<<SESSION_IDENTITY>>> ' + ' | '.join(parts) + ' <<<END SESSION_IDENTITY>>>'


def resolve_session(identifier: str, caller_uuid: str | None = None) -> dict | None:
    entry = _store.resolve(identifier)
    if entry and caller_uuid:
        entry['cli_session_id'] = caller_uuid
    return entry


def build_registry_entry(
    tracking_id: str,
    terminal_session: str,
    cli_uuid: str | None,
    platform: str,
    display_name: str | None = None,
    parent_tracking_id: str | None = None,
    cli_pid: int | None = None,
    project_dir: str | None = None,
    session_dir: str | None = None,
    history_file: str | None = None,
    substrate_context: str | None = None,
) -> dict[str, Any]:
    entry = {
        'schema_version': 3,
        'tracking_id': tracking_id,
        'terminal_session': terminal_session,
        'cli_session_id': cli_uuid,
        'cli_pid': cli_pid,
        'platform': platform,
        'session_dir': session_dir,
        'project_dir': project_dir,
        'history_file': history_file,
        'display_name': display_name or terminal_session,
        'parent_tracking_id': parent_tracking_id,
        'created_at': datetime.now().astimezone().isoformat(),
        'status': 'running',
    }
    if substrate_context:
        entry['substrate_context'] = substrate_context
    return entry


def create_session(**kwargs) -> dict[str, Any]:
    if 'runtime_context' in kwargs and 'substrate_context' not in kwargs:
        kwargs['substrate_context'] = kwargs.pop('runtime_context')
    return _store.create(**kwargs)


def update_registry(tracking_id: str, **fields) -> dict[str, Any] | None:
    if 'runtime_context' in fields and 'substrate_context' not in fields:
        fields['substrate_context'] = fields.pop('runtime_context')
    return _store.update(tracking_id, **fields)


def compute_session_dir(tracking_id: str, platform: str) -> str:
    return str(compute_session_dir_path(tracking_id, platform))


def compute_transcript_path(platform: str, cli_uuid: str | None, workdir: str) -> str | None:
    if platform == 'claude_cli' and cli_uuid:
        if workdir:
            path_hash = '-' + re.sub(r'[^a-zA-Z0-9]', '-', workdir.strip('/'))
            candidate = Path.home() / '.claude' / 'projects' / path_hash / f'{cli_uuid}.jsonl'
            return json.dumps([str(candidate)])
        projects = Path.home() / '.claude' / 'projects'
        if projects.exists():
            for d in projects.iterdir():
                if d.is_dir():
                    f = d / f'{cli_uuid}.jsonl'
                    if f.exists():
                        return json.dumps([str(f)])

    if platform == 'gemini_cli' and cli_uuid:
        uuid8 = cli_uuid[:8]
        if GEMINI_TMP_DIR.exists():
            for f in GEMINI_TMP_DIR.rglob(f'session-*-{uuid8}.jsonl'):
                return json.dumps([str(f)])
            for f in GEMINI_TMP_DIR.rglob(f'session-*-{uuid8}.json'):
                return json.dumps([str(f)])

    if platform == 'codex_cli' and cli_uuid:
        if CODEX_SESSIONS_DIR.exists():
            for f in CODEX_SESSIONS_DIR.rglob(f'rollout-*-{cli_uuid}.jsonl'):
                return json.dumps([str(f)])
            for f in sorted(CODEX_SESSIONS_DIR.rglob('rollout-*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    with open(f) as fh:
                        first_line = fh.readline()
                    data = json.loads(first_line)
                    if data.get('sessionId') == cli_uuid or data.get('id') == cli_uuid:
                        return json.dumps([str(f)])
                except (json.JSONDecodeError, OSError, KeyError):
                    continue
    return None


def try_screen_uuid(session_name: str, platform: str) -> str | None:
    try:
        from uai_toolkit.session_mgmt.session_ops import get_ai_status
        status = get_ai_status(session_name, platform=platform)
        uuid = status.get('uuid')
        if uuid and len(uuid) >= 8:
            return uuid
    except Exception:
        pass
    return None


def _schedule_retry_discovery(platform: str, tracking_id: str, session_name: str) -> None:
    try:
        ai_root = os.environ.get('AI_ROOT') or str(get_ai_root())
        store_script = f'{ai_root}/ai_general/scripts/session_mgmt/session_store.py'
        retry_cmd = (
            f'UUID=$(cd {ai_root}/ai_general/scripts/session_mgmt && '
            f'python3 -c "from uai_toolkit.session_mgmt.session_ops import get_ai_status; '
            f's = get_ai_status(\\\"{session_name}\\\", platform=\\\"{platform}\\\"); '
            f'u = s.get(\\\"uuid\\\", \\\"\\\"); '
            f'print(u if u and len(u) >= 8 else \\\"\\\")") && '
            f'[ -n "$UUID" ] && python3 {store_script} update {tracking_id} --set cli_session_id="$UUID"'
        )
        subprocess.run(['at', 'now', '+', '1', 'minute'], input=retry_cmd, text=True, capture_output=True, timeout=5)
    except Exception:
        pass


def discover_cli_uuid(platform: str, pid: int | None, tracking_id: str = '', timeout: float = 15.0, session_name: str = '') -> tuple[str, int | None] | None:
    uuid_re = re.compile(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')

    if session_name:
        screen_uuid = try_screen_uuid(session_name, platform)
        if screen_uuid and len(screen_uuid) == 36:
            return (screen_uuid, None)

    deadline = time.monotonic() + timeout

    if platform == 'codex_cli' and pid:
        while time.monotonic() < deadline:
            try:
                ps_result = subprocess.run(['ps', '-eo', 'pid,ppid'], capture_output=True, text=True, timeout=5)
                children: dict[int, list[int]] = {}
                for ps_line in ps_result.stdout.strip().splitlines()[1:]:
                    parts = ps_line.split()
                    if len(parts) >= 2:
                        try:
                            children.setdefault(int(parts[1]), []).append(int(parts[0]))
                        except ValueError:
                            pass
                pids_to_check = []
                queue = [pid]
                while queue:
                    p = queue.pop()
                    pids_to_check.append(p)
                    queue.extend(children.get(p, []))
                pid_args = ','.join(str(p) for p in pids_to_check)
                result = subprocess.run(['lsof', '-p', pid_args], capture_output=True, text=True, timeout=5)
                for line in result.stdout.splitlines():
                    if '.codex/sessions' in line and '.jsonl' in line:
                        m = uuid_re.search(line)
                        if m:
                            lsof_parts = line.split()
                            actual_pid = None
                            if len(lsof_parts) >= 2:
                                try:
                                    actual_pid = int(lsof_parts[1])
                                except ValueError:
                                    pass
                            return (m.group(1), actual_pid)
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(2)
    elif platform == 'gemini_cli':
        while time.monotonic() < deadline:
            if GEMINI_TMP_DIR.exists():
                for logs_path in GEMINI_TMP_DIR.glob('*/logs.json'):
                    try:
                        entries = json.loads(logs_path.read_text())
                        if isinstance(entries, list):
                            for entry in reversed(entries):
                                msg = entry.get('message', '')
                                if tracking_id and tracking_id in msg:
                                    session_id = entry.get('sessionId')
                                    if session_id and uuid_re.match(session_id):
                                        return (session_id, None)
                    except (json.JSONDecodeError, OSError):
                        pass
            time.sleep(2)

    if session_name:
        screen_uuid = try_screen_uuid(session_name, platform)
        if screen_uuid and len(screen_uuid) == 36:
            return (screen_uuid, None)
        if screen_uuid and len(screen_uuid) == 8:
            return (screen_uuid, None)
    if session_name and tracking_id:
        _schedule_retry_discovery(platform, tracking_id, session_name)
    return None


def _pid_alive(pid: int, platform: str) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    binary_name = {
        'claude_cli': 'claude',
        'codex_cli': 'codex',
        'gemini_cli': 'gemini',
    }.get(platform, 'claude')

    try:
        result = subprocess.run(['ps', '-eo', 'pid=,ppid=,comm='], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            children: dict[int, list[int]] = {}
            comm_by_pid: dict[int, str] = {}
            for line in result.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) < 3:
                    continue
                try:
                    child_pid = int(parts[0]); parent_pid = int(parts[1])
                except ValueError:
                    continue
                comm = parts[2].strip().lower()
                comm_by_pid[child_pid] = comm
                children.setdefault(parent_pid, []).append(child_pid)
            queue = [pid]
            seen: set[int] = set()
            while queue:
                current = queue.pop()
                if current in seen:
                    continue
                seen.add(current)
                comm = comm_by_pid.get(current, '')
                if binary_name in comm:
                    return True
                queue.extend(children.get(current, []))
            return False
    except (subprocess.TimeoutExpired, OSError):
        pass
    return True


def determine_resume_action(registry_entry: dict, substrate, platform: str) -> str:
    pid = registry_entry.get('cli_pid')
    terminal_name = registry_entry.get('terminal_session')
    pid_is_alive = _pid_alive(pid, platform) if pid else False
    try:
        terminal_exists = substrate.session_exists(terminal_name)
    except substrate_runtime.SubstrateError:
        terminal_exists = False
    try:
        terminal_running = substrate.session_is_running(terminal_name) if terminal_exists else False
    except substrate_runtime.SubstrateError:
        terminal_running = False
    if pid_is_alive and terminal_exists:
        return 'attach'
    if pid_is_alive and not terminal_exists:
        return 'error'
    if not pid_is_alive and terminal_exists and terminal_running:
        return 'relaunch_cli'
    if not pid_is_alive and terminal_exists and not terminal_running:
        return 'recreate_terminal'
    return 'recreate_terminal'
