#!/usr/bin/env bash
# Canonical AI-workspace path env vars — the SHELL surface. Mirror of paths.py.
# Source from shells (.sh scripts, statusline); the installer stamps the RESOLVED
# values into launchd plists (launchd can't source this). Derive-by-default,
# override-when-needed: set only AI_ROOT (+ any genuinely-relocated var).
: "${AI_ROOT:=$HOME/AI/ai_root}"; export AI_ROOT
# Canonical MAIN root — = $AI_ROOT normally; stays the production main inside a
# devTree (devTree tooling sets $AI_ROOT_MAIN when they must differ).
export AI_ROOT_MAIN="${AI_ROOT_MAIN:-$AI_ROOT}"
# Derived (default $AI_ROOT/…, independently overridable):
export AI_DATA="${AI_DATA:-$AI_ROOT/ai_general/data}"
export AI_SCRIPTS="${AI_SCRIPTS:-$AI_ROOT/ai_general/scripts}"
export AI_BIN="${AI_BIN:-$AI_ROOT/ai_general/apps}"          # where apps live
export AI_LOGS="${AI_LOGS:-$AI_ROOT/ai_general/logs}"
export AI_HOOKS="${AI_HOOKS:-$AI_DATA/hooks}"
export AI_UAI_APP="${AI_UAI_APP:-$AI_BIN/uai}"
export AI_CONTEXT_FILES="${AI_CONTEXT_FILES:-$AI_ROOT/ai_general/ai_context_files}"   # TODO confirm dir
# Independent (NOT derivable from AI_ROOT):
export AI_JSONL="${AI_JSONL:-$HOME/.claude/projects}"        # CLI transcripts; caller appends the project slug
export AI_PYTHON="${AI_PYTHON:-$HOME/myenv/bin/python}"      # interpreter for the python MCP servers/jobs
