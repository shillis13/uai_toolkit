#!/usr/bin/env python3
"""SessionStart hook — inject applicable standing messages as additionalContext."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

MESSAGING = Path.home() / "bin" / "ai" / "messages" / "messaging.py"


def get_platform():
    platform = os.environ.get("AI_SESSION_PLATFORM", "")
    if platform:
        return platform
    tracking_id = os.environ.get("AI_TRACKING_ID", "")
    if tracking_id and "_" in tracking_id:
        suffix = tracking_id.rsplit("_", 1)[-1]
        return {"cla": "claude_cli", "cod": "codex_cli", "gem": "gemini_cli"}.get(suffix, "")
    return ""


def get_groups():
    groups = os.environ.get("AI_GROUPS", "")
    return [g.strip() for g in groups.split(",") if g.strip()] if groups else []


def get_project():
    return os.environ.get("AI_PROJECT", "")


def query_standing(scopes, platform="", team="", project=""):
    cmd = [sys.executable, str(MESSAGING), "query-standing", "--scopes", scopes]
    if platform:
        cmd.extend(["--platform", platform])
    if team:
        cmd.extend(["--team", team])
    if project:
        cmd.extend(["--project", project])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return json.loads(result.stdout).get("messages", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return []


def format_messages(messages):
    parts = []
    for msg in messages:
        scope = msg.get("scope", "")
        scope_name = msg.get("scope_name", "")
        content = msg.get("content", "")
        from_sender = msg.get("from", "unknown")
        scope_label = f"{scope}/{scope_name}" if scope_name else scope
        parts.append(
            f"--- Standing Message [{scope_label}] from {from_sender} ---\n"
            f"{content}\n"
            f"--- End Standing Message ---"
        )
    return "\n\n".join(parts)


def handler(hook_input, context):
    source = hook_input.get("source", "")
    if source in ("clear", "compact"):
        return HookResult.skip("source is clear/compact")

    if not MESSAGING.exists():
        return HookResult.skip("messaging.py not found")

    scopes = ["global"]
    platform = get_platform()
    if platform:
        scopes.append("platform")

    messages = query_standing(scopes=",".join(scopes), platform=platform)

    for group in get_groups():
        messages.extend(query_standing(scopes="team", team=group))

    project = get_project()
    if project:
        messages.extend(query_standing(scopes="project", project=project))

    if not messages:
        return HookResult.allow("no standing messages")

    formatted = format_messages(messages)
    output = json.dumps({"hookSpecificOutput": {"additionalContext": formatted}})
    return HookResult.output(output, f"{len(messages)} standing messages injected")


if __name__ == "__main__":
    sys.exit(run_hook("inject_standing_messages", "SessionStart", handler))
