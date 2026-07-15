#!/usr/bin/env python3
"""Layer 1: CLI wrapper.

Owns platform-specific command construction and binary resolution.
This layer knows how Claude, Codex, Antigravity (`agy`), and Grok Build
(`grok`) expect their command line arguments, but it does not decide
*when* or *why* to launch them.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
from pathlib import Path

from uai_toolkit.cli.lib_paths import AI_ROOT
from uai_toolkit.cli.lib_cli_common import write_system_instructions_file

_CLAUDE_SETTINGS = Path.home() / '.claude' / 'settings.json'

# Sane current default when nothing else specifies a model. Bump per Claude Code
# release. Overridable without editing code via the AI_DEFAULT_MODEL env var or a
# "model" key in ~/.claude/settings.json — so this constant is only the last resort.
_FALLBACK_CLAUDE_MODEL = 'claude-opus-4-8[1m]'


def _default_claude_model() -> str | None:
    """Resolve the model to pin when the caller didn't pass -m.

    Why this exists: Claude Code applies its default model only to brand-NEW
    sessions; on --resume (and fork) it restores the conversation's *saved*
    model instead — silently dropping a session back onto a stale/unavailable
    spec (e.g. an opus-4.6[1m] session resuming onto plain 4.6 / 200K and
    force-compacting). Passing a model explicitly makes resume behave like new.

    Resolution order (first wins), so the user controls it in one place:
      1. AI_DEFAULT_MODEL env var  (per-shell / per-launch override)
      2. "model" in ~/.claude/settings.json  (if the user pins one there)
      3. _FALLBACK_CLAUDE_MODEL constant  (last resort)
    Note: Claude Code's own /model default is NOT reliably file-readable in
    2.1.x (it resolves a built-in version default), which is why we keep our
    own explicit source rather than trying to read theirs.
    """
    env = os.environ.get('AI_DEFAULT_MODEL')
    if env:
        return env
    try:
        pinned = json.loads(_CLAUDE_SETTINGS.read_text()).get('model')
        if pinned:
            return pinned
    except (OSError, ValueError):
        pass
    return _FALLBACK_CLAUDE_MODEL

MCP_CONFIG_PATH = Path.home() / '.claude' / 'mcp_cli_config.json'


def find_binary(platform: str) -> str:
    """Find the vendor CLI binary for the platform."""
    name_map = {
        'claude_cli': 'claude',
        'codex_cli': 'codex',
        'antigravity_cli': 'agy',
        'grok_cli': 'grok',
    }
    binary_name = name_map.get(platform, 'claude')

    result = shutil.which(binary_name)
    if result:
        return result

    fallback_dirs = [
        '/opt/homebrew/bin',
        '/usr/local/bin',
        str(Path.home() / '.local/bin'),
        str(Path.home() / '.npm-global/bin'),
    ]
    for directory in fallback_dirs:
        candidate = Path(directory) / binary_name
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        f"Binary '{binary_name}' not found in PATH or common locations ({', '.join(fallback_dirs)})."
    )


def build_cmd(
    platform: str,
    *,
    args: argparse.Namespace,
    cli_uuid: str | None,
    is_resume: bool = False,
    is_fork: bool = False,
    parent_cli_uuid: str | None = None,
    bootstrap_prompt: str | None = None,
    system_instructions: str | None = None,
    session_name: str | None = None,
    passthrough: list[str] | None = None,
    workdir: str | None = None,
) -> list[str]:
    """Build the vendor CLI command for a platform."""
    binary = find_binary(platform)
    auto_approve = args.auto_approve and not args.no_auto_approve

    if platform == 'claude_cli':
        return _build_claude_cmd(
            binary, args, cli_uuid,
            is_resume=is_resume,
            is_fork=is_fork,
            parent_cli_uuid=parent_cli_uuid,
            bootstrap_prompt=bootstrap_prompt,
            system_instructions=system_instructions,
            session_name=session_name,
            auto_approve=auto_approve,
            passthrough=passthrough or [],
        )
    if platform == 'codex_cli':
        return _build_codex_cmd(
            binary, args, cli_uuid,
            is_resume=is_resume,
            is_fork=is_fork,
            parent_cli_uuid=parent_cli_uuid,
            system_instructions=system_instructions,
            session_name=session_name,
            auto_approve=auto_approve,
            passthrough=passthrough or [],
            workdir=workdir,
        )
    if platform == 'antigravity_cli':
        return _build_antigravity_cmd(
            binary, args, cli_uuid,
            is_resume=is_resume,
            is_fork=is_fork,
            bootstrap_prompt=bootstrap_prompt,
            auto_approve=auto_approve,
            passthrough=passthrough or [],
            workdir=workdir,
        )
    if platform == 'grok_cli':
        return _build_grok_cmd(
            binary, args, cli_uuid,
            is_resume=is_resume,
            is_fork=is_fork,
            parent_cli_uuid=parent_cli_uuid,
            bootstrap_prompt=bootstrap_prompt,
            system_instructions=system_instructions,
            auto_approve=auto_approve,
            passthrough=passthrough or [],
            workdir=workdir,
        )
    raise ValueError(f'Unknown platform: {platform}')


def _build_claude_cmd(
    binary: str,
    args: argparse.Namespace,
    cli_uuid: str | None,
    *,
    is_resume: bool,
    is_fork: bool,
    parent_cli_uuid: str | None,
    bootstrap_prompt: str | None,
    system_instructions: str | None,
    session_name: str | None,
    auto_approve: bool,
    passthrough: list[str],
) -> list[str]:
    cmd = [binary]

    if is_resume:
        cmd.extend(['-r', cli_uuid or ''])
    elif is_fork:
        cmd.extend(['--resume', parent_cli_uuid or ''])
        cmd.append('--fork-session')
        cmd.extend(['--session-id', cli_uuid or ''])
    else:
        if cli_uuid:
            cmd.extend(['--session-id', cli_uuid])
        display = args.display_name or session_name
        if display:
            cmd.extend(['-n', display])

    if not args.no_mcp and MCP_CONFIG_PATH.exists():
        cmd.extend(['--mcp-config', str(MCP_CONFIG_PATH)])

    if auto_approve:
        cmd.append('--dangerously-skip-permissions')

    # Model: explicit -m wins. Otherwise fall back to the settings.json default
    # so resume/fork don't restore a stale saved model. Exceptions specify -m.
    model = args.model or _default_claude_model()
    if model:
        cmd.extend(['--model', model])

    if not is_resume and not args.start_clean and system_instructions:
        cmd.extend(['--append-system-prompt', system_instructions])

    if args.oneshot:
        cmd.append('--print')

    cmd.extend(passthrough)

    if bootstrap_prompt:
        cmd.extend(['--', bootstrap_prompt])

    return cmd


def _build_codex_cmd(
    binary: str,
    args: argparse.Namespace,
    cli_uuid: str | None,
    *,
    is_resume: bool,
    is_fork: bool,
    parent_cli_uuid: str | None,
    system_instructions: str | None,
    session_name: str | None,
    auto_approve: bool,
    passthrough: list[str],
    workdir: str | None = None,
) -> list[str]:
    cmd = [binary]

    if args.oneshot and not is_resume and not is_fork:
        cmd.append('exec')
    elif is_resume:
        cmd.extend(['resume', cli_uuid or ''])
    elif is_fork:
        cmd.extend(['fork', parent_cli_uuid or ''])

    cmd.append('--no-alt-screen')

    if auto_approve:
        cmd.append('--dangerously-bypass-approvals-and-sandbox')

    if args.model:
        cmd.extend(['--model', args.model])

    cmd.extend(['-C', workdir or args.workdir or str(AI_ROOT)])

    if not is_resume and not args.start_clean and system_instructions:
        instructions_file = write_system_instructions_file(system_instructions, session_name or 'codex_session')
        cmd.extend(['-c', f'model_instructions_file={instructions_file}'])

    cmd.extend(passthrough)

    prompt = args.prompt
    if prompt:
        cmd.append(prompt)

    return cmd


def _build_antigravity_cmd(
    binary: str,
    args: argparse.Namespace,
    cli_uuid: str | None,
    *,
    is_resume: bool,
    is_fork: bool,
    bootstrap_prompt: str | None,
    auto_approve: bool,
    passthrough: list[str],
    workdir: str | None = None,
) -> list[str]:
    """Build the Antigravity CLI (`agy`) command.

    agy is Claude-Code-lineage: `--print/-p <prompt>` for headless single-shot,
    `--prompt-interactive/-i <prompt>` to seed an interactive session, `-c` /
    `--conversation <ID>` to resume, `--add-dir` for the workspace, and
    `--dangerously-skip-permissions` for auto-approve. It generates its own
    conversation IDs (no `--session-id` on new sessions), so — like Codex/Gemini —
    it does not take a pre-assigned UUID; transcript/UUID discovery is a follow-on.
    """
    if is_fork:
        raise ValueError('antigravity_cli does not support forking yet')

    cmd = [binary]

    if is_resume:
        if cli_uuid:
            cmd.extend(['--conversation', cli_uuid])
        else:
            cmd.append('--continue')

    wd = workdir or args.workdir
    if wd:
        cmd.extend(['--add-dir', wd])

    if auto_approve:
        cmd.append('--dangerously-skip-permissions')

    if args.model:
        cmd.extend(['--model', args.model])

    cmd.extend(passthrough)

    # Prompt delivery: managed launches embed a bootstrap/marker; direct/oneshot
    # launches carry the user's text in args.prompt. Prefer the marker, fall back
    # to the positional prompt. Headless single-shot uses --print; a managed
    # interactive session seeds with --prompt-interactive.
    prompt_text = bootstrap_prompt or args.prompt
    if prompt_text:
        flag = '--print' if args.oneshot else '--prompt-interactive'
        cmd.extend([flag, prompt_text])
    elif args.oneshot:
        cmd.append('--print')

    return cmd


def _build_grok_cmd(
    binary: str,
    args: argparse.Namespace,
    cli_uuid: str | None,
    *,
    is_resume: bool,
    is_fork: bool,
    parent_cli_uuid: str | None,
    bootstrap_prompt: str | None,
    system_instructions: str | None,
    auto_approve: bool,
    passthrough: list[str],
    workdir: str | None = None,
) -> list[str]:
    """Build the Grok Build (`grok`) command.

    Grok Build is Claude-Code-lineage and — unlike agy — accepts `--session-id`
    for a *new* conversation, so it gets the same pre-assigned-UUID treatment as
    Claude (tracking uuid8 == cli_session_id[:8]). `-r/--resume [<ID>]` resumes,
    `--fork-session` + `--session-id` forks, `--always-approve` auto-approves,
    `--cwd` sets the workspace, `--rules` appends to the system prompt, `-p
    <prompt>` is headless single-turn, and a positional prompt seeds interactive.
    """
    cmd = [binary]

    if is_resume:
        cmd.append('--resume')
        if cli_uuid:
            cmd.append(cli_uuid)
    elif is_fork:
        cmd.extend(['--resume', parent_cli_uuid or ''])
        cmd.append('--fork-session')
        if cli_uuid:
            cmd.extend(['--session-id', cli_uuid])
    else:
        if cli_uuid:
            cmd.extend(['--session-id', cli_uuid])

    cmd.append('--no-alt-screen')

    if auto_approve:
        cmd.append('--always-approve')

    if args.model:
        cmd.extend(['--model', args.model])

    cmd.extend(['--cwd', workdir or args.workdir or str(AI_ROOT)])

    if not is_resume and not args.start_clean and system_instructions:
        cmd.extend(['--rules', system_instructions])

    cmd.extend(passthrough)

    # Prompt delivery: managed launches embed a bootstrap/marker; direct/oneshot
    # launches carry the user's text in args.prompt. Prefer the marker, fall back
    # to the positional prompt. Headless single-turn uses -p; interactive takes
    # the prompt as the positional PROMPT (must come last).
    prompt_text = bootstrap_prompt or args.prompt
    if prompt_text:
        if args.oneshot:
            cmd.extend(['-p', prompt_text])
        else:
            cmd.append(prompt_text)

    return cmd
