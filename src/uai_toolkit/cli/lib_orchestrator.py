#!/usr/bin/env python3
"""Layer 2: orchestrator for ai_launch.

Owns argument parsing and high-level session lifecycle control flow.
Delegates platform command construction to lib_cli_wrapper and registry/identity
operations to lib_session_mgr.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import uuid as _uuid
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SESSION_MGMT_DIR = _SCRIPT_DIR.parent / 'session_mgmt'
_COMMON_UTILS_SRC = Path.home() / 'bin/all_languages/python/src'
for _d in (_SCRIPT_DIR, _SESSION_MGMT_DIR, _COMMON_UTILS_SRC):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.common_utils.lib_logging import get_logger

log = get_logger(__name__)  # "ai.lib_orchestrator"

from uai_toolkit.cli.lib_paths import AI_ROOT
from uai_toolkit.session_mgmt.lib_session_substrate import get_substrate, SubstrateError
from uai_toolkit.cli.lib_cli_common import build_bootstrap_prompt, build_system_instructions, build_file_list, get_ai_root
from uai_toolkit.cli.lib_cli_wrapper import build_cmd
from uai_toolkit.cli.lib_session_mgr import (
    apply_launch_env,
    allocate_tracking_identity,
    build_identity_block,
    build_launch_env,
    build_registry_entry,
    compute_session_dir,
    compute_transcript_path,
    create_session,
    current_substrate_context,
    determine_resume_action,
    discover_cli_uuid,
    generate_tracking_id,
    get_store,
    normalize_roles_arg,
    pre_assign_uuid,
    reserve_draft,
    resolve_session,
    shell_env_prefix,
    try_screen_uuid,
    update_registry,
)

PROMPTS_DIR = AI_ROOT / 'ai_general' / 'prompts'
from uai_toolkit.cli.lib_session_mgr import UUID_RE, platform_short
_store = get_store()


def build_resume_prompt(tracking_id, cli_uuid, platform, extra_prompt=None):
    """The first-turn prompt delivered on EVERY resume.

    A `--resume`d session lands idle and gets no bootstrap/identity prompt (those
    are new/fork-only). This delivers a terse, timestamped `<<<SESSION RESUMED>>>`
    marker as the resumed session's first turn — which (1) re-activates the idle
    session, (2) lands a restart marker in the JSONL, and (3) tells the agent it
    was resumed. Supersedes the SessionStart additionalContext approach, which on
    resume neither persisted to the transcript nor triggered a turn. `extra_prompt`
    (the launcher's positional prompt arg) is appended for callers that want the
    resumed session to continue with something specific (e.g. self_restart).
    """
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ident = "tracking_id={}".format(tracking_id)
    if platform:
        ident += " · platform={}".format(platform)
    if cli_uuid:
        ident += " · cli_session={}".format(cli_uuid)
    marker = ("<<<SESSION RESUMED>>>{ts} and context continues from a reloaded transcript. "
              "Identity: {ident} <<<END SESSION RESUMED>>>").format(ts=ts, ident=ident)
    return marker + "\n\n" + extra_prompt if extra_prompt else marker


def deliver_resume_marker(terminal_name, marker, platform, *, timeout=30.0):
    """Wake an autonomously-resumed session by RAW-injecting the resume marker once
    it's ready — the Axis-1 raw lane (see instr_session_messaging), replacing the old
    launch-positional-prompt delivery. Route-independent (any platform/substrate) and
    correctly typed as a raw system kick (session_ops.send_raw refuses commands and
    is infra-only).

    Best-effort: we wait for the session to report ready, then send; if it never
    reports ready we send anyway at the timeout. A missed marker is HARMLESS — the
    session simply sits idle until any prompt arrives, and the staged context_to_load
    continuation rides whatever turn eventually triggers. Nothing runs until then.
    """
    import time
    from uai_toolkit.session_mgmt import session_ops
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            state = session_ops.get_ai_status(terminal_name, platform).get("state")
        except Exception:
            state = None
        if state in ("idle", "prompt_occupied"):
            break
        time.sleep(1.0)
    try:
        session_ops.send_raw(terminal_name, marker)
    except Exception as e:
        log.warning("resume marker send_raw failed (benign — session idle until prompted): %s", e)


def _mark_resumed_awaiting_prompt(session_dir, tracking_id):
    """Set the human-visible 'resumed, no prompt yet' indication in session state.

    A Bounce resumes IDLE (see the passive-marker block in the resume flow); this flag
    lets the statusline/footer show which sessions are resumed-but-unprompted. Cleared by
    the UserPromptSubmit hook on the first real prompt.
    """
    if not session_dir or not tracking_id:
        return
    import json
    from datetime import datetime
    sp = Path(session_dir) / f"{tracking_id}_state.json"
    try:
        state = json.loads(sp.read_text()) if sp.exists() else {}
    except (json.JSONDecodeError, OSError):
        state = {}
    state["bounce.resumed_awaiting_prompt"] = True
    state["bounce.resumed_at"] = datetime.now().isoformat()
    try:
        sp.write_text(json.dumps(state, indent=2))
    except OSError as e:
        log.warning("could not set resumed_awaiting_prompt flag: %s", e)


def print_dry_run(
    platform: str,
    tracking_id: str,
    terminal_session: str | None,
    cli_uuid: str | None,
    cli_cmd: list[str],
    registry_entry: dict,
    substrate_name: str | None = None,
    substrate_context: str | None = None,
    system_instructions: str | None = None,
    bootstrap_prompt: str | None = None,
    registry_action: str = 'will write',
) -> None:
    """Print dry-run output with large prompt pieces written to temp files."""
    # Temp-file disambiguator only. Never parse the (opaque) tracking ID for this
    # — fall back to a fresh random token when the CLI UUID isn't known yet
    # (session_mgmt/DESIGN.md: nothing parses tracking-ID format).
    uuid8 = (cli_uuid or str(_uuid.uuid4())).replace('-', '')[:8]
    sys_prompt_file = None
    if system_instructions:
        sys_prompt_path = Path(f'/tmp/system_prompt_{uuid8}.txt')
        sys_prompt_path.write_text(system_instructions)
        sys_prompt_file = str(sys_prompt_path)
    prompt_file = None
    if bootstrap_prompt:
        prompt_path = Path(f'/tmp/prompt_{uuid8}.txt')
        prompt_path.write_text(bootstrap_prompt)
        prompt_file = str(prompt_path)

    if terminal_session and substrate_name and substrate_name != 'none':
        terminal_cmd = f'{substrate_name}:{terminal_session}'
        if substrate_context:
            terminal_cmd += f' (context={substrate_context})'
    else:
        terminal_cmd = '(direct foreground — no managed terminal session)'

    cli_cmd_display: list[str] = []
    skip_next = False
    for i, arg in enumerate(cli_cmd):
        if skip_next:
            skip_next = False
            continue
        if arg == '--append-system-prompt' and i + 1 < len(cli_cmd):
            cli_cmd_display.append(f'--append-system-prompt @{sys_prompt_file or "<system_prompt>"}')
            skip_next = True
        elif arg == '-c' and i + 1 < len(cli_cmd) and 'model_instructions_file=' in cli_cmd[i + 1]:
            cli_cmd_display.append(f'-c model_instructions_file={sys_prompt_file or "<instructions>"}')
            skip_next = True
        elif arg == '--' and i + 1 < len(cli_cmd) and len(cli_cmd[i + 1]) > 200:
            cli_cmd_display.append(f'-- @{prompt_file or "<prompt>"}')
            skip_next = True
        elif arg == '-i' and i + 1 < len(cli_cmd) and len(cli_cmd[i + 1]) > 200:
            cli_cmd_display.append(f'-i @{prompt_file or "<prompt>"}')
            skip_next = True
        elif len(arg) > 200:
            cli_cmd_display.append(f'@{prompt_file or "<long_arg>"}')
        else:
            cli_cmd_display.append(shlex.quote(arg) if (' ' in arg or "'" in arg) else arg)

    print(f'system prompt: {sys_prompt_file or "(none — resume mode)"}')
    print(f'prompt: {prompt_file or "(none)"}')
    print(f'terminal cmd: {terminal_cmd}')
    print(f'CLI cmd: {" ".join(cli_cmd_display)}')
    print(f'session registry ({registry_action}): {json.dumps(registry_entry, indent=2)}')



def parse_args(platform: str, argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse launcher arguments for a specific platform."""
    prog_name = {
        'claude_cli': 'claudeCli',
        'codex_cli': 'codexCli',
        'gemini_cli': 'geminiCli',
    }.get(platform, 'ai_launch')

    parser = argparse.ArgumentParser(
        prog=prog_name,
        description=f"Launch a {platform_short(platform)} CLI session.",
    )

    parser.add_argument('--display-name', help='Human-readable label for the session (default: tracking ID)')
    parser.add_argument('--session-id', help='Explicit CLI UUID (Claude only; auto-generated if omitted)')
    parser.add_argument('--tracking-id', help='Pre-generated tracking ID (from app draft session). Skips ID generation.')
    parser.add_argument('--reserve', action='store_true', help='Reserve a draft session (mint identity, persist draft row) and print TRACKING_ID/CLI_UUID without launching. App-facing reservation entrypoint.')
    parser.add_argument('-r', '--resume', help='Resume existing session (Tracking ID, CLI UUID, or terminal name)')
    parser.add_argument('--fork-from', help='Fork new session from existing conversation')
    parser.add_argument('--parent', help='Parent tracking ID (for worker sessions, without forking)')
    parser.add_argument('-m', '--model', help='Model override')
    parser.add_argument('--auto-approve', action='store_true', default=True, help='Skip permission prompts (default: enabled)')
    parser.add_argument('--ask-permissions', dest='no_auto_approve', action='store_true', help='Require permission prompts (overrides default auto-approve)')
    parser.add_argument('-i', '--direct', action='store_true', help='Direct foreground (no managed terminal session)')
    parser.add_argument('-w', '--workdir', help='Working directory')
    parser.add_argument('-A', '--roles', '--agent', help="Roles (comma-separated, e.g., 'assistant,worker,dev'). Default: assistant")
    parser.add_argument('-T', '--task', help='Task instructions file')
    parser.add_argument('--notes', '--description', dest='notes', help="Free-text notes/description for the session; populates the session's Notes state field")
    parser.add_argument('--pre-prompt', help='Prepend to bootstrap prompt')
    parser.add_argument('--post-prompt', help='Append to bootstrap prompt')
    parser.add_argument('--start-clean', action='store_true', help='Skip all bootstrap')
    parser.add_argument('--oneshot', action='store_true', help='Non-interactive: run, print, exit')
    parser.add_argument('--no-mcp', action='store_true', help='Claude only: skip MCP config')
    parser.add_argument('--dry-run', action='store_true', help='Print commands and registry entry, then exit')
    parser.add_argument('prompt', nargs='?', default=None, help='Initial prompt text')

    return parser.parse_known_args(argv)


def main(platform: str, argv: list[str]) -> int:
    args, passthrough = parse_args(platform, argv)

    is_resume = args.resume is not None
    is_fork = args.fork_from is not None

    if args.no_auto_approve:
        args.auto_approve = False

    workdir = str(Path(args.workdir).expanduser()) if args.workdir else str(AI_ROOT)
    ai_root = get_ai_root()

    if args.reserve:
        tracking_id, cli_uuid = reserve_draft(
            platform,
            display_name=args.display_name,
            project_dir=(str(Path(args.workdir).expanduser()) if args.workdir else None),
            roles=normalize_roles_arg(args.roles) if args.roles else None,
            parent_tracking_id=args.parent,
            seed_uuid=args.session_id,
            notes=args.notes,
        )
        print(f'TRACKING_ID={tracking_id}')
        print(f'CLI_UUID={cli_uuid or "pending"}')
        return 0

    if is_resume:
        _caller_uuid = args.resume if UUID_RE.match(args.resume or '') else None
        entry = resolve_session(args.resume, caller_uuid=_caller_uuid)
        if entry is None:
            cli_uuid = _caller_uuid or args.resume
            resume_prompt = build_resume_prompt(args.resume, cli_uuid, platform, extra_prompt=args.prompt)
            cli_cmd = build_cmd(platform, args=args, cli_uuid=cli_uuid, is_resume=True, bootstrap_prompt=resume_prompt, session_name=None, passthrough=passthrough, workdir=workdir)
            if args.dry_run:
                print(f"Session '{args.resume}' not in registry — falling through to native resume")
                print(f"Command: {' '.join(cli_cmd)}")
                return 0
            log.info("Session '%s' not in registry — trying native resume", args.resume)
            os.execvp(cli_cmd[0], cli_cmd)
            return 1

        tracking_id = entry.get('tracking_id', args.resume)
        terminal_name = entry.get('terminal_session') or entry.get('tracking_id')
        cli_uuid = entry.get('cli_session_id')
        cli_pid = entry.get('cli_pid')
        if terminal_name is None:
            log.error('Cannot determine terminal session name for resume')
            return 1

        if not cli_uuid and platform in ('codex_cli', 'gemini_cli'):
            screen_uuid = try_screen_uuid(terminal_name, platform)
            if screen_uuid and len(screen_uuid) >= 8:
                cli_uuid = screen_uuid
                update_registry(tracking_id, cli_session_id=cli_uuid)
                log.info('UUID discovered from screen: %s', cli_uuid)

        workdir = entry.get('project_dir') or str(AI_ROOT)
        project_dir = workdir
        session_dir = entry.get('session_dir') or compute_session_dir(tracking_id, platform)
        substrate_context = entry.get('substrate_context')
        launch_env = build_launch_env(tracking_id, cli_uuid, platform, session_dir, project_dir, substrate_context=substrate_context)
        apply_launch_env(launch_env)

        resume_prompt = build_resume_prompt(tracking_id, cli_uuid, platform, extra_prompt=args.prompt)
        # --direct execs (replaces this process), so its marker must ride the launch
        # positional. The managed path delivers the marker post-launch via send_raw
        # (route-independent raw injection — see deliver_resume_marker), so it does
        # NOT bake the marker into the launch command (avoids a double-marker).
        launch_marker = resume_prompt if args.direct else None
        cli_cmd = build_cmd(platform, args=args, cli_uuid=cli_uuid, is_resume=True, bootstrap_prompt=launch_marker, session_name=terminal_name, passthrough=passthrough, workdir=workdir)

        if args.dry_run:
            print_dry_run(platform, tracking_id, terminal_name, cli_uuid, cli_cmd, entry, substrate_name=get_substrate(runtime_context=substrate_context).substrate_name if not args.direct else 'none', substrate_context=substrate_context, bootstrap_prompt=resume_prompt, registry_action='existing — will update status+pid on relaunch')
            return 0

        if args.direct:
            os.chdir(workdir)
            os.execvpe(cli_cmd[0], cli_cmd, os.environ.copy())
            return 0

        substrate = get_substrate(runtime_context=substrate_context)
        action = determine_resume_action(entry, substrate, platform)
        app_invocation = not sys.stdout.isatty()

        # Bounce = resume IDLE with a PASSIVE marker (no re-activation). Before the new
        # CLI loads the transcript, append an inert isMeta <<<SESSION RESUMED>>> record:
        # it persists (the model sees "I was resumed" on its first real prompt, tooling
        # can grep the boundary) but, being isMeta, it does NOT wake the session or read
        # as an instruction — so it can't make the session run off and continue work.
        # Re-activation was only ever for an instant token/context readout, which now
        # waits for the first real prompt (PianoMan, 2026-07-04). Only for autonomous
        # (app) relaunches, where the prior process has EXITED (safe to append). Worst
        # case (if isMeta doesn't suppress the turn) it degrades to the old wake marker —
        # visible instantly, harmless.
        if app_invocation and action in ('relaunch_cli', 'recreate_terminal'):
            _tp = entry.get('transcript_path')
            if not _tp or _tp == '[]':
                _tp = compute_transcript_path(platform, cli_uuid, workdir)
            # normalize: transcript_path may be a plain str, a JSON list-string '["…"]',
            # or a Python list — write_passive_resume_marker → Path() needs a plain path str.
            # (This was the "not 'list'" crash that made the passive marker fail and a bounce
            # resume come back silent/unmarked.)
            if isinstance(_tp, (list, tuple)):
                _tp = _tp[0] if _tp else None
            elif isinstance(_tp, str) and _tp.strip().startswith('['):
                try:
                    _parsed = json.loads(_tp)
                    _tp = _parsed[0] if _parsed else None
                except Exception:
                    pass
            if _tp:
                try:
                    _sb_dir = str(AI_ROOT / 'ai_general' / 'scripts' / 'session_bounce')
                    if _sb_dir not in sys.path:
                        sys.path.insert(0, _sb_dir)
                    import resume_marker as _rm
                    _muid = _rm.write_passive_resume_marker(
                        _tp, cli_uuid=cli_uuid, tracking_id=tracking_id,
                        platform=platform, cwd=workdir)
                    log.info('passive resume marker appended (%s) — session resumes idle', _muid)
                    _mark_resumed_awaiting_prompt(session_dir, tracking_id)
                except Exception as e:
                    log.warning('passive resume marker failed (benign — resumes with no marker): %s', e)

        if action == 'attach':
            if not app_invocation:
                substrate.attach(terminal_name)
        elif action == 'relaunch_cli':
            resume_str = shell_env_prefix(launch_env) + ' ' + ' '.join(shlex.quote(c) for c in cli_cmd)
            substrate.send_keys(terminal_name, resume_str)
            if not app_invocation:
                substrate.attach(terminal_name)
        elif action == 'recreate_terminal':
            launch = substrate.create_session(terminal_name, cli_cmd, workdir)
            new_pid = launch.pid
            if not app_invocation:
                substrate.attach(terminal_name)
        elif action == 'error':
            log.error("CLI process (PID %s) is alive but terminal '%s' does not exist. This is an anomaly — check if the process is still the expected CLI binary.", cli_pid, terminal_name)
            return 1
        else:
            log.error("Unknown resume action '%s'", action)
            return 1

        if action in ('relaunch_cli', 'recreate_terminal'):
            update_fields = {'status': 'running'}
            if action == 'recreate_terminal':
                if new_pid:
                    update_fields['cli_pid'] = new_pid
                update_fields['substrate'] = substrate.substrate_name
                update_fields['substrate_context'] = substrate_context
            existing_tp = entry.get('transcript_path')
            if not existing_tp or existing_tp == '[]':
                tp = compute_transcript_path(platform, cli_uuid, workdir)
                if tp:
                    update_fields['transcript_path'] = tp
            update_registry(tracking_id, **update_fields)

            # (Autonomous resume no longer WAKES the session — the passive isMeta marker
            # was appended to the transcript BEFORE launch, above, so the session resumes
            # idle and waits for the first real prompt. The old send_raw wake is retired.)

        print(f'TRACKING_ID={tracking_id}')
        print(f'TERMINAL={terminal_name}')
        print(f'CLI_UUID={cli_uuid or "pending"}')
        return 0

    if is_fork:
        parent_entry = resolve_session(args.fork_from)
        if parent_entry is None:
            log.error("Parent session not found for '%s'", args.fork_from)
            return 1

        parent_tracking_id = parent_entry.get('tracking_id', args.fork_from)
        parent_cli_uuid = parent_entry.get('cli_session_id')
        if platform == 'gemini_cli':
            log.error('Gemini does not support fork')
            return 1

        if args.tracking_id:
            tracking_id = args.tracking_id
            draft_entry = _store.get(tracking_id)
            seed_uuid = (
                args.session_id
                or (draft_entry.get('cli_session_id') if (draft_entry and platform == 'claude_cli') else None)
                or str(_uuid.uuid4())
            )
            cli_uuid = pre_assign_uuid(platform, seed_uuid)
        else:
            # allocate_tracking_identity keeps cli_uuid and the tracking uuid8 in
            # lockstep even when a store collision forces a fresh UUID; an
            # explicit --session-id collides loudly rather than being swapped.
            tracking_id, chosen_uuid = allocate_tracking_identity(
                platform, args.session_id, strict_seed=bool(args.session_id))
            cli_uuid = pre_assign_uuid(platform, chosen_uuid)
        session_name = tracking_id
        project_dir = workdir
        session_dir = compute_session_dir(tracking_id, platform)
        substrate_context = current_substrate_context()
        launch_env = build_launch_env(tracking_id, cli_uuid, platform, session_dir, project_dir, substrate_context=substrate_context)

        if not args.direct:
            substrate = get_substrate(runtime_context=substrate_context)
            if substrate.session_exists(session_name) and substrate.session_is_running(session_name):
                log.error("Session '%s' already running. Choose a different name or resume the existing session.", session_name)
                return 1

        identity_block = build_identity_block(tracking_id, session_name, cli_uuid, parent_tracking_id=parent_tracking_id)
        system_instructions = None
        bootstrap_prompt = None
        if not args.start_clean:
            system_instructions = build_system_instructions(args.roles, PROMPTS_DIR, ai_root, platform=platform_short(platform))
            if system_instructions:
                system_instructions = identity_block + '\n\n' + system_instructions
            file_list = build_file_list(args.roles, has_task=bool(args.task), platform=platform_short(platform), prompts_dir=PROMPTS_DIR)
            bootstrap_prompt = build_bootstrap_prompt(files=file_list, task_file=args.task, any_task_dir=None, pre_prompt=args.pre_prompt, post_prompt=args.post_prompt, user_prompt=args.prompt, ai_root=str(ai_root), identity_block=identity_block)

        if platform == 'claude_cli' and parent_cli_uuid:
            parent_project_dir = parent_entry.get('project_dir') or parent_entry.get('working_dir')
            if parent_project_dir and os.path.realpath(workdir) != os.path.realpath(parent_project_dir):
                src_tp = compute_transcript_path(platform, parent_cli_uuid, parent_project_dir)
                if src_tp:
                    src_path = Path(json.loads(src_tp)[0])
                    if src_path.exists():
                        dst_tp = compute_transcript_path(platform, parent_cli_uuid, workdir)
                        if dst_tp:
                            dst_path = Path(json.loads(dst_tp)[0])
                            dst_path.parent.mkdir(parents=True, exist_ok=True)
                            if not dst_path.exists():
                                import shutil
                                shutil.copy2(str(src_path), str(dst_path))
                                log.info('Copied parent JSONL to new project dir: %s/', dst_path.parent.name)

        cli_cmd = build_cmd(platform, args=args, cli_uuid=cli_uuid, is_fork=True, parent_cli_uuid=parent_cli_uuid, bootstrap_prompt=bootstrap_prompt, system_instructions=system_instructions, session_name=session_name, passthrough=passthrough, workdir=workdir)
        registry_entry = build_registry_entry(tracking_id, session_name, cli_uuid, platform, display_name=args.display_name, parent_tracking_id=parent_tracking_id, project_dir=project_dir, session_dir=session_dir, substrate_context=substrate_context)
        if args.dry_run:
            sub_name = get_substrate(runtime_context=substrate_context).substrate_name if not args.direct else 'none'
            print_dry_run(platform, tracking_id, session_name, cli_uuid, cli_cmd, registry_entry, substrate_name=sub_name, substrate_context=substrate_context, system_instructions=system_instructions, bootstrap_prompt=bootstrap_prompt, registry_action='will write — new fork')
            return 0

        if args.direct:
            create_session(tracking_id=tracking_id, terminal_session=session_name, platform=platform, cli_session_id=cli_uuid, parent_tracking_id=parent_tracking_id, display_name=args.display_name, working_dir=workdir, project_dir=project_dir, session_dir=session_dir, model=args.model, substrate='none', substrate_context=None, roles=normalize_roles_arg(args.roles), transcript_path=compute_transcript_path(platform, cli_uuid, workdir), notes=args.notes)
            apply_launch_env(launch_env)
            os.chdir(workdir)
            os.execvpe(cli_cmd[0], cli_cmd, os.environ.copy())
            return 0

        substrate = get_substrate(runtime_context=substrate_context)
        apply_launch_env(launch_env)
        substrate.create_session(session_name, cli_cmd, workdir)
        create_session(tracking_id=tracking_id, terminal_session=session_name, platform=platform, cli_session_id=cli_uuid, parent_tracking_id=parent_tracking_id, display_name=args.display_name, working_dir=workdir, project_dir=project_dir, session_dir=session_dir, model=args.model, substrate=substrate.substrate_name, substrate_context=substrate_context, roles=normalize_roles_arg(args.roles), transcript_path=compute_transcript_path(platform, cli_uuid, workdir), notes=args.notes)
        print(f'TRACKING_ID={tracking_id}')
        print(f'TERMINAL={session_name}')
        print(f'CLI_UUID={cli_uuid or "pending"}')
        sys.stdout.flush()
        if not sys.stdout.isatty():
            return 0
        substrate.attach(session_name)
        return 0

    if args.tracking_id:
        tracking_id = args.tracking_id
        draft_entry = _store.get(tracking_id)
        # Reuse the UUID the draft was reserved with so the eventual Claude
        # --session-id matches the tracking ID's uuid8 (set at reserve time).
        # Codex/Gemini discover their UUID post-launch, so only Claude carries a
        # meaningful reserved cli_session_id here.
        seed_uuid = (
            args.session_id
            or (draft_entry.get('cli_session_id') if (draft_entry and platform == 'claude_cli') else None)
            or str(_uuid.uuid4())
        )
        cli_uuid = pre_assign_uuid(platform, seed_uuid)
        if draft_entry:
            if not args.display_name and draft_entry.get('display_name'):
                args.display_name = draft_entry['display_name']
            if not args.workdir and draft_entry.get('project_dir'):
                workdir = draft_entry['project_dir']
            if args.roles == 'assistant' and draft_entry.get('roles'):
                roles_raw = draft_entry['roles']
                if isinstance(roles_raw, list) and roles_raw:
                    args.roles = ','.join(roles_raw)
                elif isinstance(roles_raw, str) and roles_raw not in ('[]', ''):
                    try:
                        parsed = json.loads(roles_raw)
                        if isinstance(parsed, list) and parsed:
                            args.roles = ','.join(parsed)
                    except (json.JSONDecodeError, TypeError):
                        pass
            if not getattr(args, 'parent', None) and draft_entry.get('parent_tracking_id'):
                args.parent = draft_entry['parent_tracking_id']
    else:
        # allocate_tracking_identity keeps cli_uuid and the tracking uuid8 in
        # lockstep even when a store collision forces a fresh UUID; an explicit
        # --session-id collides loudly rather than being silently swapped.
        tracking_id, chosen_uuid = allocate_tracking_identity(
            platform, args.session_id, strict_seed=bool(args.session_id))
        cli_uuid = pre_assign_uuid(platform, chosen_uuid)
    session_name = tracking_id
    project_dir = workdir
    session_dir = compute_session_dir(tracking_id, platform)
    substrate_context = current_substrate_context()
    launch_env = build_launch_env(tracking_id, cli_uuid, platform, session_dir, project_dir, substrate_context=substrate_context)

    if not args.direct and session_name:
        substrate = get_substrate(runtime_context=substrate_context)
        if substrate.session_exists(session_name) and substrate.session_is_running(session_name):
            log.error("Session '%s' already running. Choose a different name or use --resume.", session_name)
            return 1

    identity_block = build_identity_block(tracking_id, session_name, cli_uuid, parent_tracking_id=getattr(args, 'parent', None))
    system_instructions = None
    bootstrap_prompt = None
    if not args.start_clean:
        system_instructions = build_system_instructions(args.roles, PROMPTS_DIR, ai_root, platform=platform_short(platform))
        if system_instructions:
            system_instructions = identity_block + '\n\n' + system_instructions
        file_list = build_file_list(args.roles, has_task=bool(args.task), platform=platform_short(platform), prompts_dir=PROMPTS_DIR)
        bootstrap_prompt = build_bootstrap_prompt(files=file_list, task_file=args.task, any_task_dir=None, pre_prompt=args.pre_prompt, post_prompt=args.post_prompt, user_prompt=args.prompt, ai_root=str(ai_root), identity_block=identity_block)

    cli_cmd = build_cmd(platform, args=args, cli_uuid=cli_uuid, bootstrap_prompt=bootstrap_prompt, system_instructions=system_instructions, session_name=session_name, passthrough=passthrough, workdir=workdir)
    registry_entry = build_registry_entry(tracking_id, session_name or f'direct_{tracking_id}', cli_uuid, platform, display_name=args.display_name, project_dir=project_dir, session_dir=session_dir, substrate_context=substrate_context)

    if args.dry_run:
        sub_name = 'none'
        if not args.direct:
            try:
                sub_name = get_substrate(runtime_context=substrate_context).substrate_name
            except (SubstrateError, FileNotFoundError):
                sub_name = 'unknown'
        print_dry_run(platform, tracking_id, session_name, cli_uuid, cli_cmd, registry_entry, substrate_name=sub_name, substrate_context=substrate_context, system_instructions=system_instructions, bootstrap_prompt=bootstrap_prompt, registry_action='will write — new session')
        return 0

    if args.direct:
        create_session(tracking_id=tracking_id, terminal_session=session_name or f'direct_{tracking_id}', platform=platform, cli_session_id=cli_uuid, display_name=args.display_name, working_dir=workdir, project_dir=project_dir, session_dir=session_dir, model=args.model, substrate='none', substrate_context=None, roles=normalize_roles_arg(args.roles), notes=args.notes)
        apply_launch_env(launch_env)
        os.chdir(workdir)
        os.execvpe(cli_cmd[0], cli_cmd, os.environ.copy())
        return 0

    substrate = get_substrate(runtime_context=substrate_context)
    apply_launch_env(launch_env)
    launch = substrate.create_session(session_name, cli_cmd, workdir)
    cli_pid = launch.pid
    transcript_path = compute_transcript_path(platform, cli_uuid, workdir)
    create_session(tracking_id=tracking_id, terminal_session=session_name, platform=platform, cli_session_id=cli_uuid, cli_pid=cli_pid, display_name=args.display_name, working_dir=workdir, project_dir=project_dir, session_dir=session_dir, model=args.model, substrate=substrate.substrate_name, substrate_context=substrate_context, roles=normalize_roles_arg(args.roles), transcript_path=transcript_path, parent_tracking_id=getattr(args, 'parent', None), notes=args.notes)
    if cli_uuid is None and platform in ('codex_cli', 'gemini_cli'):
        result = discover_cli_uuid(platform, cli_pid, tracking_id=tracking_id, timeout=15.0, session_name=session_name)
        if result:
            cli_uuid, actual_pid = result
            update_fields: dict[str, object] = {'cli_session_id': cli_uuid}
            if actual_pid and actual_pid != cli_pid:
                update_fields['cli_pid'] = actual_pid
            update_registry(tracking_id, **update_fields)

    print(f'TRACKING_ID={tracking_id}')
    print(f'TERMINAL={session_name}')
    print(f'CLI_UUID={cli_uuid or "pending"}')
    sys.stdout.flush()
    if not sys.stdout.isatty():
        return 0

    substrate.attach(session_name)
    return 0
