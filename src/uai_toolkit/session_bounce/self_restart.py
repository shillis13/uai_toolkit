#!/usr/bin/env python3
"""self_restart.py — a session restarts ITSELF (v0.4 self-Stop/Resume core).

The minimal mechanic, no kill / no bouncer process: the running session
schedules a one-shot launchd `--resume` of itself N minutes out, then cleanly
exits via `send_slash_command self /exit`. launchd brings the session back; the
SessionStart resumed-marker hook fires; the reloaded transcript continues.

This proves the CORE round-trip (exit → scheduled resume → back). Context-reclaim
(trim the JSONL before exit + stage a continuation in context_to_load/) layers on
top and is intentionally NOT in here yet.

Run BY the session that wants to restart — it reads its own $AI_TRACKING_ID.
ALWAYS --dry-run first on a real session; the live path WILL exit it. Intended
test target: a dedicated test session whose purpose IS this round-trip.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
MGR = AI_ROOT / "ai_general/scripts/scheduling/scheduled_task_mgr.py"
SEND_SLASH = AI_ROOT / "ai_general/scripts/session_mgmt/send_slash_command.py"
CLAUDECLI = Path.home() / "myenv/bin/claudeCli"          # managed launcher wrapper
PY = sys.executable


def main():
    ap = argparse.ArgumentParser(description="Schedule a launchd self-resume, then /exit.")
    ap.add_argument("--in-min", type=int, default=2, help="minutes until self-resume (default 2)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; do NOT schedule or exit")
    a = ap.parse_args()

    tid = os.environ.get("AI_TRACKING_ID", "")
    if not tid:
        print("ERROR: AI_TRACKING_ID not set — run inside the session that wants to restart",
              file=sys.stderr)
        return 1

    # Job id MUST be unique per session. Use the FULL tracking id, not a suffix:
    # tid.split("_")[-1] is the platform ("cla"/"cod"/"gem") — identical across all
    # sessions of a platform, so it collided (two Claude sessions clobbered each
    # other's resume job). The tracking id is already label-safe ([A-Za-z0-9_]).
    job_id = "self_restart_{}".format(tid)
    # The launchd one-shot runs via `bash -lc` with a minimal PATH (no ~/myenv/bin),
    # so use absolute paths and set AI_ROOT explicitly. tid / paths have no spaces.
    resume_cmd = "AI_ROOT={root} {cli} --resume {tid}".format(root=AI_ROOT, cli=CLAUDECLI, tid=tid)

    # 1) schedule the resume (a self-disabling one-shot launchd job)
    once = [PY, str(MGR), "once", "--in", "{}m".format(a.in_min),
            "--id", job_id, "--command", resume_cmd,
            "--log", str(AI_ROOT / "ai_general/logs/self_restart/{}.log".format(job_id))]
    if a.dry_run:
        once.append("--dry-run")
    print("[1] schedule self-resume (+{}m) — id={}".format(a.in_min, job_id))
    print("    resume cmd: {}".format(resume_cmd))
    if subprocess.run(once).returncode != 0:
        print("ERROR: failed to schedule the resume; NOT exiting.", file=sys.stderr)
        return 1

    # 2) exit cleanly — queues, fires when this turn ends
    if a.dry_run:
        print("[2] DRY-RUN — would exit via:  {} {} self /exit".format(PY, SEND_SLASH))
        print("    (skipped — session stays alive; the resume job was only previewed)")
        return 0
    print("[2] exiting via `send_slash_command self /exit` (fires at end of this turn)…")
    subprocess.run([PY, str(SEND_SLASH), "self", "/exit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
