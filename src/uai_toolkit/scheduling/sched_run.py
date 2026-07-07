#!/usr/bin/env python3
"""sched_run.py — logging wrapper for scheduled-task jobs.

Runs a job's real command and captures its output as the EVIDENCE half of the
two-channel failure-signaling contract (see ai_general/scripts/DESIGN.md §
Failure Signaling). It:

  - reads the child's stdout and stderr separately, prefixes every line with a
    local `[YYYY-MM-DD HH:MM:SS] [OUT|ERR]` stamp (so a UI/SwiftBar can flag and
    colour ERR lines), and appends each to BOTH a per-job log and a per-group log;
  - passes the same lines through to its own stdout/stderr (nothing is swallowed);
  - writes a START header and EXIT footer (with duration + exit code) to both logs;
  - exits with the CHILD's exit code — so the scheduler's state-capture wrapper
    still records real pass/fail (the INDICATOR channel; this wrapper never masks
    a nonzero exit).

Installed automatically around every job by launchd_backend (via
sched_task_mgr.py) — not normally run by hand. The real command is unchanged in
the task YAML; only how its output is logged changes.

The job command is run via `bash -lc <cmd>` (same as the un-wrapped scheduler),
so `$VARS`, `cd &&`, pipes, etc. keep working. The installer passes it
base64-encoded (`--cmd-b64`) so arbitrary shell text survives the nested bash -lc
context with no quoting/escaping hazards; `--cmd` takes a plain string for manual
runs.

Python 3.9 compatible (launchd runs it with a minimal environment).
"""
from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Sink:
    """Append-writes prefixed lines to the job log + group log, thread-safe."""

    def __init__(self, job_log: Path, group_log: Path):
        self._paths = [p for p in (job_log, group_log) if p]
        self._lock = threading.Lock()
        for p in self._paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    def write(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            for p in self._paths:
                try:
                    with open(p, "a", encoding="utf-8") as f:
                        f.write(text)
                except OSError:
                    pass  # a log write must never break the job


def _pump(stream, tag: str, sink: _Sink, passthrough) -> None:
    """Read `stream` line by line; stamp+tag each line to the sink and pass through."""
    for raw in iter(stream.readline, ""):
        line = raw.rstrip("\n")
        sink.write("[{}] [{}] {}\n".format(_stamp(), tag, line))
        try:
            passthrough.write(raw)
            passthrough.flush()
        except (OSError, ValueError):
            pass
    try:
        stream.close()
    except OSError:
        pass


def run(group: str, job: str, job_log: Path, group_log: Path, cmd_str: str) -> int:
    sink = _Sink(job_log, group_log)
    start = datetime.now()
    sink.write("=== {}/{} START {} :: {} ===\n".format(
        group, job, _stamp(), cmd_str))
    try:
        # Run via a login shell so $VARS / cd && / pipes behave exactly as the
        # un-wrapped scheduler (which also uses bash -lc).
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", cmd_str],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
    except OSError as e:
        sink.write("[{}] [ERR] sched_run: failed to launch: {}\n".format(_stamp(), e))
        sink.write("=== {}/{} EXIT 127 (0s) {} ===\n".format(group, job, _stamp()))
        print("sched_run: failed to launch {!r}: {}".format(cmd_str, e), file=sys.stderr)
        return 127

    t_out = threading.Thread(target=_pump, args=(proc.stdout, "OUT", sink, sys.stdout))
    t_err = threading.Thread(target=_pump, args=(proc.stderr, "ERR", sink, sys.stderr))
    t_out.start(); t_err.start()
    rc = proc.wait()
    t_out.join(); t_err.join()

    dur = int((datetime.now() - start).total_seconds())
    sink.write("=== {}/{} EXIT {} ({}s) {} ===\n".format(group, job, rc, dur, _stamp()))
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="sched_run.py",
        description="Logging wrapper for scheduled-task jobs: timestamped, "
                    "stderr-tagged tee of a job's output to per-job + per-group "
                    "logs, passed through, exiting with the child's code.")
    p.add_argument("--group", required=True, help="scheduler group name")
    p.add_argument("--job", required=True, help="job id within the group")
    p.add_argument("--job-log", required=True, help="per-job log path (absolute)")
    p.add_argument("--group-log", default="", help="per-group log path (absolute)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--cmd", help="shell command string to run (bash -lc)")
    g.add_argument("--cmd-b64", help="base64-encoded shell command string "
                                     "(quoting-safe; used by the installer)")
    args = p.parse_args(argv)

    if args.cmd_b64:
        try:
            cmd_str = base64.b64decode(args.cmd_b64).decode("utf-8")
        except Exception as e:
            p.error("--cmd-b64 is not valid base64/utf-8: {}".format(e))
    else:
        cmd_str = args.cmd
    if not cmd_str.strip():
        p.error("empty command")

    return run(args.group, args.job, Path(args.job_log),
               Path(args.group_log) if args.group_log else None, cmd_str)


if __name__ == "__main__":
    sys.exit(main())
