"""MCP tools wrapping scheduled_task_mgr.py — the launchd-backed scheduled task
system. Lets agents create/manage scheduled tasks the sanctioned way (YAML →
install) instead of hand-rolling launchd plists.

Pattern: thin subprocess wrappers around the CLI (the CLI is the single source
of truth). Tool names use the `sched_task_` prefix, consistent with the
`uai://sched_task/...` URI convention.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
TASK_MGR = AI_ROOT / "ai_general/scripts/scheduling/scheduled_task_mgr.py"
PREFIX = "sched_task_"


def _run(subcommand, args=None, timeout=120):
    """Run scheduled_task_mgr.py <subcommand> [args]. stdin is closed so the
    CLI runs non-interactively. Returns a result dict."""
    cmd = [sys.executable, str(TASK_MGR), subcommand] + (args or [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout running {subcommand}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return {"success": False, "error": (p.stderr or out or
                f"exit {p.returncode}").strip()}
    # status --json returns JSON; everything else returns text.
    try:
        return {"success": True, "data": json.loads(out)}
    except (json.JSONDecodeError, ValueError):
        return {"success": True, "output": out}


_GROUP = "Task group name = one YAML file in data/scheduled_tasks/. Holds related jobs (e.g. 'sysmon', 'news_scan')."
_ID = "Job id, unique within its group. A job is one scheduled task; it compiles to one launchd agent (com.shawnhillis.ai.<group>.<id>)."
_SCHED = ("Schedule: a 5-field cron expression, '@reboot', or a one-time absolute date "
          "'YYYY-MM-DD HH:MM' (fires once at that local time — pair with once=true so it runs "
          "exactly once). Cron supported subset: 'M H * * *' (daily), 'M H * * D' (weekly, D=0=Sun), "
          "'*/N * * * *' and 'M-59/N * * * *' (every N min), '* * * * *' (every min), '@reboot'. "
          "Unsupported CRON forms (hourly 'M * * * *', comma lists, hour ranges, cron day-of-month) "
          "are rejected — fail loud. (The one-time date form is the way to schedule a specific day.)")
_ONCE = ("If true, the job is run-once: after it fires, the tool automatically disables it (flips "
         "enabled:false, removes its agent) so it runs exactly once and then sits disabled until "
         "re-enabled/rescheduled. Use with a one-time date schedule for a fire-once-on-a-date task.")


def tools():
    return [
        Tool(name=f"{PREFIX}list",
             description="List all scheduled-task groups and the jobs in each. Read-only. "
                         "Use this to discover what scheduled tasks exist before editing or running one.",
             inputSchema={"type": "object", "properties": {
                 "all": {"type": "boolean", "default": False,
                         "description": "If true, include disabled groups (default: only enabled)."}}}),
        Tool(name=f"{PREFIX}status",
             description="Structured JSON status of every scheduled task: per-job install state, "
                         "last run (exit code + time), next fire time, and overall sync/drift "
                         "(whether installed launchd agents match the YAML definitions). Read-only. "
                         "The primary tool for 'are my scheduled tasks healthy / in sync?'.",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name=f"{PREFIX}view",
             description="Show one group's jobs in detail (ids, schedules, commands, log paths, env). Read-only.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP}},
                 "required": ["group"]}),
        Tool(name=f"{PREFIX}create",
             description="Create a new, empty task group (a YAML file). Add jobs to it with "
                         "sched_task_add. Use this when starting a new category of scheduled work. "
                         "No launchd change until a job is added and installed.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string",
                           "description": "New group name. Lowercase letters, digits, '_' and '-' only. Becomes <group>.yml and the launchd label segment."},
                 "description": {"type": "string", "description": "Human-readable description of what this group of tasks is for (optional)."}},
                 "required": ["group"]}),
        Tool(name=f"{PREFIX}add",
             description="Add a scheduled task (job) to an existing group and install it as a launchd "
                         "agent immediately. SIDE EFFECT: auto-installs — the new agent is bootstrapped "
                         "and will start firing on its schedule. This is the sanctioned way to create a "
                         "scheduled task; do NOT hand-write launchd plists.\n"
                         "Examples (all also need group + id):\n"
                         "  • daily at 05:30  -> schedule='30 5 * * *',  command='$AI_ROOT/ai_general/scripts/x.py'\n"
                         "  • every 10 min    -> schedule='*/10 * * * *', command='...'\n"
                         "  • weekly Sun 06:30-> schedule='30 6 * * 0',  command='...'\n"
                         "  • FIRE ONCE on a date then auto-disable -> schedule='2026-07-01 08:53', once=true, command='...'\n"
                         "  • boot-persistent watcher (stays running) -> schedule='@reboot', command='...'\n"
                         "Tip: set log to capture output; check results later with sched_task_logs / sched_task_status.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP + " Must already exist (use sched_task_create first if not)."},
                 "id": {"type": "string", "description": _ID},
                 "schedule": {"type": "string", "description": _SCHED},
                 "command": {"type": "string",
                             "description": "Shell command to run on schedule. Runs via /bin/bash -lc, so $AI_ROOT and other env vars expand. For a long-running watcher use schedule '@reboot' (it becomes RunAtLoad+KeepAlive)."},
                 "log": {"type": "string", "description": "Absolute path for the task's stdout+stderr log. Convention: $AI_ROOT/ai_general/logs/<group>/<id>.log. Optional but recommended."},
                 "once": {"type": "boolean", "default": False, "description": _ONCE},
                 "description": {"type": "string", "description": "Human-readable description of what this task does (optional)."}},
                 "required": ["group", "id", "schedule", "command"]}),
        Tool(name=f"{PREFIX}edit",
             description="Edit fields of an existing job, then auto-reinstall it. SIDE EFFECT: the "
                         "job's launchd agent is re-bootstrapped (a ~1s restart). Only the fields you "
                         "pass are changed; omitted fields are left as-is.\n"
                         "Common uses:\n"
                         "  • RESCHEDULE a job -> pass schedule (cron, '@reboot', or one-time 'YYYY-MM-DD HH:MM')\n"
                         "  • make a job run-once -> once=true  (or once=false to clear it)\n"
                         "  • repoint its command/log -> pass command / log\n"
                         "Example: group='news_scan', id='news_daily', schedule='45 6 * * *'.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": _ID},
                 "schedule": {"type": "string", "description": "New schedule (same format as add). Omit to leave unchanged."},
                 "command": {"type": "string", "description": "New shell command. Omit to leave unchanged."},
                 "log": {"type": "string", "description": "New log path. Omit to leave unchanged."},
                 "once": {"type": "boolean", "description": "Set/clear run-once on this job. " + _ONCE + " Omit to leave unchanged."},
                 "description": {"type": "string", "description": "New description. Omit to leave unchanged."}},
                 "required": ["group", "id"]}),
        Tool(name=f"{PREFIX}delete",
             description="DESTRUCTIVE: delete a job (or the whole group if id is omitted) and bootout "
                         "its launchd agent(s). Removes the YAML entry and unloads the running agent. "
                         "Not reversible except by re-creating the task.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": "Job id to delete. OMIT to delete the ENTIRE group and all its jobs."}},
                 "required": ["group"]}),
        Tool(name=f"{PREFIX}enable",
             description="Enable a task group, OR a single job within it (pass id), and reinstall the "
                         "affected agent(s) (they start firing again). SIDE EFFECT: bootstraps agents. "
                         "Example: enable group='news_scan' id='news_daily' re-arms just that job; omit "
                         "id to enable the whole group. (Re-enabling a fired run-once job re-arms it.)",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": "OPTIONAL job id. Provide to enable just this one job; omit to enable the whole group. " + _ID}},
                 "required": ["group"]}),
        Tool(name=f"{PREFIX}disable",
             description="Disable a task group, OR a single job within it (pass id), and bootout the "
                         "affected agent(s) (they stop firing) without deleting the definitions. "
                         "SIDE EFFECT: unloads launchd agent(s); re-enable with sched_task_enable. "
                         "Example: disable group='news_scan' id='news_daily' stops just that job; omit "
                         "id to disable the whole group. Definitions are kept, so you can re-enable later.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": "OPTIONAL job id. Provide to disable just this one job; omit to disable the whole group. " + _ID}},
                 "required": ["group"]}),
        Tool(name=f"{PREFIX}install",
             description="Sync all launchd agents to the current YAML definitions. Idempotent and "
                         "content-aware: only NEW or CHANGED agents are re-bootstrapped; unchanged "
                         "(incl. running KeepAlive) agents are left untouched. Removes managed agents "
                         "whose YAML was deleted. Normally not needed (add/edit/etc auto-install) — use "
                         "it to reconcile drift or after editing YAML files directly.",
             inputSchema={"type": "object", "properties": {
                 "dry_run": {"type": "boolean", "default": False,
                             "description": "If true, report what would be added/removed without changing anything."}}}),
        Tool(name=f"{PREFIX}import",
             description="Adopt a hand-installed launchd agent into a managed YAML task by "
                         "reverse-engineering the YAML from its installed plist (label→group/job, "
                         "schedule keys→cron, ProgramArguments→command, env/log). Writes/merges the "
                         "YAML but does NOT install — review the result, then call sched_task_install "
                         "to make it managed. Use this to fix 'drift' from an agent created outside this system.",
             inputSchema={"type": "object", "properties": {
                 "label": {"type": "string",
                           "description": "Full launchd label of the installed agent, e.g. 'com.shawnhillis.ai.uai.build_watcher'. Get candidates from sched_task_status (sync.extra) or 'launchctl list'."},
                 "dry_run": {"type": "boolean", "default": False,
                             "description": "If true, print the YAML it would write without writing it."}},
                 "required": ["label"]}),
        Tool(name=f"{PREFIX}run",
             description="Run a job's command immediately, once, in the foreground and wait for it "
                         "(synchronous). Does NOT affect the schedule. Use to test a task or trigger an "
                         "ad-hoc run. Output/exit status are returned.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": _ID}},
                 "required": ["group", "id"]}),
        Tool(name=f"{PREFIX}logs",
             description="Return the tail of a job's log file (the path set in its YAML). Read-only.",
             inputSchema={"type": "object", "properties": {
                 "group": {"type": "string", "description": _GROUP},
                 "id": {"type": "string", "description": _ID},
                 "lines": {"type": "integer", "default": 30,
                           "description": "Number of trailing log lines to return (default 30)."}},
                 "required": ["group", "id"]}),
    ]


async def call_tool(name, arguments):
    short = name[len(PREFIX):] if name.startswith(PREFIX) else name
    a = arguments or {}

    if short == "list":
        res = _run("list", ["--all"] if a.get("all") else [])
    elif short == "status":
        res = _run("status", ["--json"])
    elif short == "view":
        res = _run("view", [a["group"]])
    elif short == "create":
        args = [a["group"]]
        if a.get("description"):
            args += ["--desc", a["description"]]
        res = _run("create", args)
    elif short == "add":
        args = [a["group"], "--id", a["id"], "--schedule", a["schedule"],
                "--command", a["command"]]
        if a.get("log"):
            args += ["--log", a["log"]]
        if a.get("description"):
            args += ["--desc", a["description"]]
        if a.get("once"):
            args.append("--once")
        res = _run("add", args)
    elif short == "edit":
        args = [a["group"], a["id"]]
        for k in ("schedule", "command", "log", "description"):
            if a.get(k):
                args += [f"--{'desc' if k == 'description' else k}", a[k]]
        if "once" in a:                      # boolean: set or clear run-once
            args += ["--once", "true" if a["once"] else "false"]
        res = _run("edit", args)
    elif short == "delete":
        args = [a["group"]]
        if a.get("id"):
            args.append(a["id"])
        args.append("--yes")
        res = _run("delete", args)
    elif short == "enable":
        res = _run("enable", [a["group"]] + ([a["id"]] if a.get("id") else []))
    elif short == "disable":
        res = _run("disable", [a["group"]] + ([a["id"]] if a.get("id") else []))
    elif short == "install":
        res = _run("install", ["--dry-run"] if a.get("dry_run") else [])
    elif short == "import":
        args = [a["label"]]
        if a.get("dry_run"):
            args.append("--dry-run")
        res = _run("import", args)
    elif short == "run":
        res = _run("run", [a["group"], a["id"]], timeout=120)
    elif short == "logs":
        res = _run("logs", [a["group"], a["id"], "--lines", str(a.get("lines", 30))])
    else:
        return None

    return [TextContent(type="text", text=json.dumps(res, indent=2))]
