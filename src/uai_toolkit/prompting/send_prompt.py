#!/usr/bin/env python3
"""send_prompt.py — Send a message to various AI targets.

Ported from send_prompt.sh (behavior-preserving). Orchestrates: endpoint/target
normalization, sender-stamping, conversation-lock checks, busy detection, send
dispatch (Desktop / web UI / CLI / user), and queue/notify fallbacks.

Targets: claude-desktop · claude-web · claude-cli · codex-cli · gemini-cli ·
chatgpt-web · user.

Notes vs. the .sh:
- Imports callback_lib directly for endpoint parse/build (replaces inline
  `python3 -c` subprocesses).
- Calls ai_isBusy.py (already ported, substrate-agnostic) for CLI busy checks.
- Calls downstream Python helpers for CLI/Desktop/WebUI delivery; callers and
  behavior are unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS  # noqa: E402

# common_utils (shared logging core)
_PY_SRC = Path.home() / "bin" / "all_languages" / "python" / "src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import get_logger, configure_logging  # noqa: E402

log = get_logger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
CALLBACKS_DIR = AI_ROOT / "ai_general" / "scripts" / "callbacks"
SESSION_MGMT_DIR = AI_ROOT / "ai_general" / "scripts" / "session_mgmt"
MESSAGING = AI_SCRIPTS / "messages" / "messaging.py"

# callback_lib for endpoint parse/build
sys.path.insert(0, str(CALLBACKS_DIR))
try:
    from uai_toolkit.callbacks import callback_lib  # type: ignore
except Exception:  # pragma: no cover - callbacks optional for some paths
    callback_lib = None

# lib_identity_display for canonical "DisplayName (tracking_id)" sender stamping
sys.path.insert(0, str(SESSION_MGMT_DIR))
try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity  # type: ignore
except Exception:  # pragma: no cover - degrade to raw identity if unavailable
    format_identity = None

# ANSI — auto-disabled when the destination is NOT a real terminal, so captured
# output (e.g. a scheduled job's log) stays clean. `--color` forces it on; NO_COLOR
# / `--no-color` force it off. (scripts/DESIGN.md: color auto-disables when piped.)
def _isatty(stream):
    try:
        return stream.isatty()
    except Exception:
        return False


def _ansi(stream):
    if "--no-color" in sys.argv:
        on = False
    elif "--color" in sys.argv:
        on = True
    elif os.environ.get("NO_COLOR"):
        on = False
    else:
        on = _isatty(stream)
    if on:
        return ("\033[0m", "\033[1m", "\033[4m", "\033[36m", "\033[32m",
                "\033[33m", "\033[35m", "\033[2m", "\033[97m")
    return ("",) * 9


def show_usage(code: int = 1):
    R, B, U, C, G, Y, M, D, W = _ansi(sys.stderr)
    print(f"""{B}{U}send_prompt.py{R} — Send a message to any AI target

{B}USAGE{R}
  {C}send_prompt.py{R} {G}--target{R} <target> {G}--message{R} "text" [options]
  {C}send_prompt.py{R} {G}--endpoint{R} <uri> {G}--message{R} "text"

{B}REQUIRED{R}
  {G}--endpoint{R} <uri>      Callback endpoint URI (e.g. prompt://claude-cli/session)
  {G}--message{R} "text"      Message to send

{B}TARGETS{R}
  {W}claude-desktop{R}        Desktop Claude app (macOS, via AppleScript)
  {W}claude-web{R}            Claude web interface (via Chrome CDP on port 9222)
  {W}claude-cli{R}            Claude CLI in a terminal session (auto-discovered via session_ops)
  {W}codex-cli{R}             Codex CLI in a terminal session
  {W}gemini-cli{R}            Gemini CLI in a terminal session
  {W}chatgpt-web{R}           ChatGPT web interface (via Chrome CDP)
  {W}user{R}                  macOS user notification

{B}OPTIONS{R}
  {G}--convo_id{R} <id>       Conversation ID or URL
  {G}--force{R}               Bypass busy checks, send immediately
  {G}--fb_queue{R}            If target is busy, queue message to file
  {G}--fb_notification{R}     If target is busy, send macOS notification

{B}DEPRECATED{R} {D}(still work, will be removed){R}
  {G}--target{R} <target>     {Y}Deprecated{R} — use --endpoint URI instead
  {G}--session{R} <name>      {Y}Deprecated{R} — encode in endpoint URI instead
  {G}--submit{R}              {Y}Deprecated{R} — encode in endpoint URI (?submit=true)

Run {C}send_prompt.py --help-examples{R} for detailed examples.""", file=sys.stderr)
    sys.exit(code)


def show_examples():
    R, B, U, C, G, Y, M, D, W = _ansi(sys.stdout)
    print(f"""{B}EXAMPLES — send_prompt.py{R}

{B}CLI Agents (Claude, Codex, Gemini){R}
  {C}send_prompt.py --target gemini-cli --message "/chat save shard-01" --submit{R}
  {C}send_prompt.py --target claude-cli --message "check inbox" --session claude_cli_dev-lead_abc123 --submit{R}

{B}Fallback{R}
  {C}send_prompt.py --target claude-cli --message "Process queue" --submit --fb_queue{R}
  {C}send_prompt.py --target codex-cli --message "Stop" --force --submit{R}

{B}FOR AI AGENTS{R}
  {D}# Forgetting --submit types the message but never sends it.{R}
  {D}# CLI targets need a running terminal session (or --session <name>).{R}""")
    sys.exit(0)


def _run(cmd: list, **kw) -> int:
    """Subprocess returning exit code; stdout/stderr inherited."""
    return subprocess.run(cmd, **kw).returncode


def is_idle(target: str, session_name: str) -> bool:
    """True if target is available to send (idle). Mirrors check_if_busy()."""
    if target in ("claude-desktop", "desktop-claude", "claude-web", "chatgpt-web"):
        return True
    if target in ("claude-cli", "codex-cli", "gemini-cli", "grok-cli", "antigravity-cli"):
        cmd = [sys.executable, str(SCRIPT_DIR / "ai_isBusy.py"), target]
        if session_name:
            cmd += ["--session", session_name]
        return _run(cmd, capture_output=True) == 0  # rc 0=idle; busy/err => not idle
    return True


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    argv = list(sys.argv[1:] if argv is None else argv)

    target = ""
    message = ""
    fallback_queue = False
    fallback_notification = False
    convo_id = ""
    session_name = ""
    submit = False
    force = False
    endpoint_uri = ""
    tmux_alias_used = False

    # ── arg parse (manual, mirrors the .sh exactly) ──
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--endpoint":
            endpoint_uri = argv[i + 1]; i += 2
        elif a == "--target":
            target = argv[i + 1]; i += 2
        elif a == "--message":
            message = argv[i + 1]; i += 2
        elif a == "--fb_queue":
            fallback_queue = True; i += 1
        elif a == "--fb_notification":
            fallback_notification = True; i += 1
        elif a == "--convo_id":
            convo_id = argv[i + 1]; i += 2
        elif a == "--session":
            session_name = argv[i + 1]; i += 2
        elif a == "--tmux":
            session_name = argv[i + 1]; tmux_alias_used = True; i += 2
        elif a == "--submit":
            submit = True; i += 1
        elif a == "--force":
            force = True; i += 1
        elif a in ("--help", "-h"):
            show_usage()
        elif a == "--help-examples":
            show_examples()
        elif a in ("--color", "--no-color"):
            i += 1                      # handled by _ansi() via sys.argv; consume here
        else:
            log.error("Unknown argument: %s", a)
            log.error("Run 'send_prompt.py --help' for usage")
            return 1

    # ── deprecation warnings ──
    if tmux_alias_used:
        log.warning("--tmux is deprecated; use --endpoint URI instead.")
    if target and "://" not in target:
        log.warning("--target is deprecated; use --endpoint URI instead.")
    if session_name and not endpoint_uri:
        log.warning("--session is deprecated; encode in --endpoint URI instead.")

    # ── normalize: URI or target+session → both target and endpoint_uri ──
    if target and "://" in target:
        endpoint_uri = target
        target = ""

    endpoint_resolve_error = None
    if endpoint_uri and callback_lib is not None:
        try:
            ep = callback_lib.parse_endpoint(endpoint_uri)
            if not target:
                target = ep.path or ""
            if not session_name:
                session_name = ep.session or ""
            if ep.submit:
                submit = True
            if ep.force:
                force = True
        except Exception as e:
            # Do NOT swallow silently: a uai://session/<id> endpoint resolves the
            # LIVE session to a target, and a transient miss (session mid-compaction,
            # store/substrate hiccup) would otherwise surface downstream as the
            # misleading "--target or --endpoint is required" — an endpoint WAS given.
            # Keep the real reason so the validate step can report it truthfully.
            endpoint_resolve_error = e
            log.warning("could not resolve endpoint %s: %s: %s",
                        endpoint_uri, type(e).__name__, e)

    if target and not endpoint_uri and callback_lib is not None:
        try:
            endpoint_uri = callback_lib.make_endpoint_uri(
                "prompt", path=target, session=session_name, submit=submit, force=force
            )
        except Exception:
            endpoint_uri = ""

    # ── validate ──
    if not target:
        if endpoint_uri:
            # An endpoint was supplied but did not yield a deliverable target —
            # report THAT, not the false "nothing was given". Usually a
            # uai://session/<id> whose session isn't currently resolvable.
            if endpoint_resolve_error is not None:
                log.error("endpoint %s could not be resolved to a live target "
                          "(%s: %s)", endpoint_uri,
                          type(endpoint_resolve_error).__name__, endpoint_resolve_error)
            else:
                log.error("endpoint %s did not resolve to a deliverable target "
                          "(no live session matched, or the URI names no target)",
                          endpoint_uri)
            return 1
        log.error("--target or --endpoint is required")
        show_usage()
    if not message:
        log.error("--message is required")
        show_usage()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── sender stamp: "DisplayName (tracking_id)" — display name first ──
    sender_id = os.environ.get("AI_TRACKING_ID", "unknown")
    env_name = os.environ.get("AI_SESSION_NAME")
    if env_name and env_name != sender_id:
        # This process knows its own name (even if the store hasn't caught up).
        sender_stamp = f"{env_name} ({sender_id})"
    elif format_identity is not None:
        # Resolve the display name from the session store; falls back to the bare
        # id only when the store has no name for it.
        sender_stamp = format_identity(sender_id)
    else:
        sender_stamp = sender_id
    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = (
        f"From {sender_stamp} at {sent_at}:\n"
        "-----------------------------------\n"
        f"{message}\n"
        "-----------------------------------"
    )

    # ── conversation locks ──
    locks_dir = AI_ROOT / "ai_general" / "data" / "locks" / "conversations"
    if (locks_dir / "global.lock").is_file():
        log.error("BLOCKED: Global conversation lock is active")
        log.error("Lock file: %s", locks_dir / "global.lock")
        return 3
    if session_name and (locks_dir / f"{session_name}.lock").is_file():
        log.error("BLOCKED: Conversation lock active for session %s", session_name)
        log.error("Lock file: %s", locks_dir / f"{session_name}.lock")
        return 3

    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── busy / send-direct decision ──
    if force:
        print(f"[{_now()}] --force specified, bypassing busy check...")
        send_direct = True
    elif is_idle(target, session_name):
        print(f"[{_now()}] {target} is available, sending directly...")
        send_direct = True
    else:
        print(f"[{_now()}] {target} is busy")
        send_direct = False

    # ── submit args ──
    submit_args = ["--submit"] if submit else []
    cli_submit_args = ["--submit"] if submit else []
    if force:
        submit_args += ["--no-confirm"]

    if send_direct:
        if target in ("claude-desktop", "desktop-claude"):
            if _run(["pgrep", "-q", "Claude"], capture_output=True) != 0:
                print(f"[{_now()}] Desktop Claude not running, starting...")
                _run(["open", "-g", "-a", "Claude"])
                import time
                time.sleep(3)
            desktop_args = list(submit_args)
            if convo_id:
                desktop_args += ["--convo_id", convo_id]
            if _run([sys.executable, str(SCRIPT_DIR / "lib_send_prompt_desktop.py"), message, *desktop_args]) == 0:
                print(f"Message sent successfully to {target}")
                return 0
        elif target == "claude-web":
            url = convo_id or "new"
            if _run([sys.executable, str(SCRIPT_DIR / "lib_send_prompt_webui.py"),"claude", url, message, *submit_args]) == 0:
                print(f"Message sent successfully to {target}")
                return 0
        elif target == "chatgpt-web":
            url = convo_id or "new"
            if _run([sys.executable, str(SCRIPT_DIR / "lib_send_prompt_webui.py"),"chatgpt", url, message, *submit_args]) == 0:
                print(f"Message sent successfully to {target}")
                return 0
        elif target in ("claude-cli", "codex-cli", "gemini-cli", "grok-cli", "antigravity-cli"):
            if session_name:
                cmd = [sys.executable, str(SCRIPT_DIR / "lib_send_prompt.py"), "send",
                       target, message, "--session", session_name, *cli_submit_args]
                if _run(cmd) == 0:
                    print(f"Message sent successfully to {target}")
                    return 0
            else:
                print(f"[{_now()}] No session specified, running non-interactive...")
                oneshot, success_msg = {
                    "claude-cli": (["claude", "--print", message], "Message processed by claude --print"),
                    "codex-cli": (["codex", "--prompt", message], "Message processed by codex"),
                    "gemini-cli": (["gemini", "--prompt", message], "Message processed by gemini"),
                    "grok-cli": (["grok", "-p", message], "Message processed by grok"),
                    "antigravity-cli": (["agy", "--print", message], "Message processed by agy"),
                }[target]
                if _run(oneshot, stderr=subprocess.DEVNULL) == 0:
                    print(success_msg)
                    return 0
        elif target == "user":
            if _run([str(SCRIPT_DIR / ".." / "notifications" / "send_user_notification.py"), "info", message]) == 0:
                print("Notification sent to user")
                return 0
        else:
            log.error("Unknown target '%s'", target)
            log.error("Run 'send_prompt.py --help' for valid targets")
            return 1

    # ── fallbacks ──
    if fallback_notification:
        print("Sending notification as fallback...")
        if _run([str(SCRIPT_DIR / "send_notification.sh"), target, message]) == 0:
            print("Notification sent")
            return 0
        print("ERROR: Notification fallback failed")

    if fallback_queue:
        print("Queueing message as fallback...")
        home = Path.home()
        queue_dirs = {
            "claude-desktop": AI_ROOT / "ai_comms/claude/prompting/incoming/scheduled",
            "desktop-claude": AI_ROOT / "ai_comms/claude/prompting/incoming/scheduled",
            "claude-web": AI_ROOT / "ai_comms/claude/prompting/incoming/scheduled",
            "claude-cli": home / ".claude/coordination/to_execute",
            "codex-cli": AI_ROOT / "ai_comms/codex_cli/to_execute",
            "gemini-cli": AI_ROOT / "ai_comms/gemini_cli/to_execute",
            "chatgpt-app": AI_ROOT / "ai_comms/chatgpt/inbox",
            "chatgpt-web": AI_ROOT / "ai_comms/chatgpt/inbox",
            "user": AI_ROOT / "ai_comms/claude/notifications/pending",
        }
        queue_dir = queue_dirs.get(target)
        if queue_dir is None:
            log.error("Unknown target '%s'", target)
            return 1
        filepath = queue_dir / f"prompt_{target}_{timestamp}.txt"
        try:
            filepath.write_text(message + "\n")
        except OSError as e:
            # Matches the .sh: a missing queue dir fails the write (exit 1).
            log.error("could not queue to %s: %s", filepath, e)
            return 1
        print(f"[{_now()}] Queued prompt for {target}: {filepath.name}")
        print(f"Message: {message}")
        print(f"Location: {filepath}")
        return 0

    # ── no explicit fallback flags — auto-queue for later delivery ──
    print("Queueing for later delivery (no fallback flags specified)...")
    _run([sys.executable, str(MESSAGING), "queue-prompt",
          "--to", session_name, "--content", message,
          "--urgency", "prompt", "--delivery", "post-prompt",
          "--source", os.environ.get("AI_TRACKING_ID", "unknown")])
    print("Queued for later delivery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
