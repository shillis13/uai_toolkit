#!/usr/bin/env python3
"""Unified AI CLI launcher entrypoint.

Canonical public entrypoint for launching Claude, Codex, Antigravity, and Grok
CLI sessions.
Busybox symlinks:
  claudeCli      -> ai_launch.py
  codexCli       -> ai_launch.py
  antigravityCli -> ai_launch.py   (Antigravity CLI `agy`)
  grokCli        -> ai_launch.py   (Grok Build `grok`)
(gemini_cli retired 2026-07-12 — discontinued upstream; Antigravity CLI is its
successor.)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_COMMON_UTILS_SRC = Path.home() / "bin/all_languages/python/src"
if str(_COMMON_UTILS_SRC) not in sys.path:
    sys.path.insert(0, str(_COMMON_UTILS_SRC))

from uai_toolkit.common_utils.lib_logging import configure_logging
from uai_toolkit.cli.lib_orchestrator import main as orchestrator_main


_PLATFORMS = {'claude_cli', 'codex_cli', 'antigravity_cli', 'grok_cli'}


def detect_platform(argv0: str, argv: list[str]) -> tuple[str, list[str]]:
    name = Path(argv0).stem.lower()
    if 'claude' in name:
        return 'claude_cli', argv
    if 'codex' in name:
        return 'codex_cli', argv
    if 'antigravity' in name or name == 'agy':
        return 'antigravity_cli', argv
    if 'grok' in name:
        return 'grok_cli', argv

    env_platform = os.environ.get('AI_LAUNCH_PLATFORM')
    if env_platform in _PLATFORMS:
        return env_platform, argv

    if len(argv) >= 2 and argv[0] == '--platform' and argv[1] in _PLATFORMS:
        return argv[1], argv[2:]

    return 'claude_cli', argv


if __name__ == '__main__':
    # Single logging configuration point for the whole launcher. Picks up env
    # defaults (AI_LOG_LEVEL default INFO, console on -> stderr). Libraries like
    # lib_orchestrator only get_logger()+log; the entrypoint configures.
    configure_logging()
    platform, remaining_argv = detect_platform(sys.argv[0], sys.argv[1:])
    sys.exit(orchestrator_main(platform, remaining_argv))
