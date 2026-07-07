#!/usr/bin/env python3
"""Stop hook — capture session telemetry to session + platform state stores.

Reads from statusline JSON and read_jsonl --summary, writes to:
  - {session_dir}/{tracking_id}_state.json — per-session data
  - {platform_dir}/platform_state.json — cross-session, per-platform data (rate limits)

Async handler — fire-and-forget, never blocks.
Logs errors if session_dir or statusline data can't be found.
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))

# Shared writer for the app-facing session.activity_state field. This is the
# designated shared-{tid}_state.json writer for the Stop event (mark_idle keeps
# its dedicated activity_state.json to stay out of the concurrent-writer fray).
sys.path.insert(0, str(AI_ROOT / "ai_general" / "scripts" / "session_mgmt"))
try:
    from uai_toolkit.session_mgmt.lib_session_activity import set_activity_state
except Exception:  # pragma: no cover
    set_activity_state = None
PYTHON = "/opt/homebrew/bin/python3"
READ_JSONL = Path.home() / "bin" / "ai" / "jsonl" / "read_jsonl.py"

# ─── State file helpers ──────────────────────────────────────────────────

def read_state(path):
    """Read a JSON state file, return dict."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def write_state(path, state):
    """Write a JSON state file atomically."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(path)
    except OSError:
        pass


def update_state(path, updates):
    """Read-modify-write a state file with the given key-value updates."""
    state = read_state(path)
    state.update(updates)
    state["updated_at"] = datetime.now().isoformat()
    write_state(path, state)


# ─── Data sources ────────────────────────────────────────────────────────

def get_statusline_data(session_dir, tracking_id):
    """Read the latest statusline JSON from the session dir."""
    if not session_dir:
        return None

    uuid8 = ""
    if tracking_id and "_" in tracking_id:
        parts = tracking_id.split("_")
        if len(parts) >= 3:
            uuid8 = parts[2]

    if uuid8:
        path = Path(session_dir) / f"statusline.{uuid8}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    pattern = str(Path(session_dir) / "statusline.*.json")
    matches = glob.glob(pattern)
    if matches:
        try:
            return json.loads(Path(matches[0]).read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_jsonl_summary(cli_session_id):
    """Get transcript stats via read_jsonl --summary."""
    if not cli_session_id or not READ_JSONL.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(READ_JSONL), "--summary", cli_session_id],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def get_jsonl_role_counts(cli_session_id):
    """Count messages by role/type from the JSONL directly."""
    if not cli_session_id:
        return None
    jsonl_path = _find_jsonl_path(cli_session_id)
    if not jsonl_path:
        return None
    try:
        import json as _json
        counts = {"user": 0, "assistant": 0, "tool": 0, "thinking": 0, "all": 0}
        with open(jsonl_path) as f:
            for line in f:
                try:
                    d = _json.loads(line)
                    msg = d.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    role = msg.get("role", "")
                    if role == "user":
                        counts["user"] += 1
                        counts["all"] += 1
                    elif role == "assistant":
                        counts["assistant"] += 1
                        counts["all"] += 1
                        # Count thinking and tool_use blocks
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for b in content:
                                if isinstance(b, dict):
                                    if b.get("type") == "thinking":
                                        counts["thinking"] += 1
                                    if b.get("type") in ("tool_use", "tool_result"):
                                        counts["tool"] += 1
                except (ValueError, KeyError):
                    continue
        return counts
    except OSError:
        return None


def _find_jsonl_path(cli_session_id):
    """Find JSONL file path from CLI session ID."""
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        matches = glob.glob(str(claude_dir / "*" / f"{cli_session_id}.jsonl"))
        if matches:
            return Path(matches[0])
    # Codex fallback
    codex_dir = Path.home() / ".codex" / "sessions"
    if codex_dir.exists():
        for match in codex_dir.rglob(f"*{cli_session_id}*.jsonl"):
            return match
    return None


def get_codex_token_data(transcript_path):
    """Extract token/usage data from a Codex JSONL transcript.

    Codex stores token_count entries in the JSONL with total_token_usage,
    last_token_usage, model_context_window, and rate_limits.
    """
    if not transcript_path:
        return None
    tp = Path(transcript_path)
    if not tp.exists():
        return None
    try:
        # Read from end — token_count entries appear throughout
        with open(tp, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            content = f.read().decode('utf-8', errors='replace')

        for line in reversed(content.strip().split('\n')):
            try:
                d = json.loads(line)
                payload = d.get('payload', {})
                if isinstance(payload, dict) and payload.get('type') == 'token_count':
                    return payload
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        pass
    return None


def get_gemini_token_data(transcript_path):
    """Extract token data from a Gemini JSONL transcript.

    Gemini stores tokens as {input, output, cached, thoughts, tool, total}
    on message entries.
    """
    if not transcript_path:
        return None
    tp = Path(transcript_path)
    if not tp.exists():
        return None
    try:
        with open(tp, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 100_000))
            content = f.read().decode('utf-8', errors='replace')

        for line in reversed(content.strip().split('\n')):
            try:
                d = json.loads(line)
                tokens = d.get('tokens')
                if isinstance(tokens, dict) and 'total' in tokens:
                    return tokens
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:
        pass
    return None


def get_codex_footer_data(tracking_id):
    """Screen-scrape token/context data from a Codex session's terminal footer.

    Codex displays a footer line like:
      019e1241... · gpt-5.4 xhigh · Context 19% used · 950K window · 5h 99% · weekly 93% · 0.130.0 · ai_root · ~/... · Ready

    Returns dict with context_pct, window_size, rate_5h_pct, rate_7d_pct, model, or None.
    """
    import re
    session_ops = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_ops.py"
    if not session_ops.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(session_ops), "read-terminal", tracking_id],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        for line in reversed(result.stdout.strip().split('\n')):
            if 'Context' in line and 'used' in line and 'window' in line:
                data = {}

                # Context N% used
                ctx_match = re.search(r'Context\s+(\d+)%\s*used', line)
                if ctx_match:
                    data["context_pct"] = int(ctx_match.group(1))

                # NNK window
                win_match = re.search(r'([\d.]+)([KkMm])\s*window', line)
                if win_match:
                    val = float(win_match.group(1))
                    suffix = win_match.group(2).upper()
                    if suffix == 'K':
                        data["window_size"] = int(val * 1_000)
                    elif suffix == 'M':
                        data["window_size"] = int(val * 1_000_000)

                # 5h NN%
                h5_match = re.search(r'5h\s+(\d+)%', line)
                if h5_match:
                    data["rate_5h_pct"] = int(h5_match.group(1))

                # weekly NN%
                w_match = re.search(r'weekly\s+(\d+)%', line)
                if w_match:
                    data["rate_7d_pct"] = int(w_match.group(1))

                return data if data else None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_gemini_footer_data(tracking_id):
    """Screen-scrape token/context data from a Gemini session's terminal footer.

    Gemini displays a footer line like:
      ~/AI/ai_root  Auto (Gemini 3)  a623a00a  20% used  34.7m tokens  2% used  94.0 MB

    Returns dict with context_pct, tokens, quota_pct, memory_mb, model, or None.
    """
    import re
    session_ops = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_ops.py"
    if not session_ops.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(session_ops), "read-terminal", tracking_id],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None

        for line in reversed(result.stdout.strip().split('\n')):
            if 'used' in line and 'tokens' in line:
                data = {}

                # Context % — first "N% used"
                all_pcts = re.findall(r'(\d+)%\s*used', line)
                if all_pcts:
                    data["context_pct"] = int(all_pcts[0])

                # Tokens
                tok_match = re.search(r'([\d.]+)([kmb])\s*tokens', line, re.I)
                if tok_match:
                    val = float(tok_match.group(1))
                    suffix = tok_match.group(2).lower()
                    if suffix == 'm':
                        data["tokens"] = int(val * 1_000_000)
                    elif suffix == 'k':
                        data["tokens"] = int(val * 1_000)
                    else:
                        data["tokens"] = int(val)

                # Quota — second "N% used"
                if len(all_pcts) >= 2:
                    data["quota_pct"] = int(all_pcts[1])

                # Memory
                mem_match = re.search(r'([\d.]+)\s*MB', line)
                if mem_match:
                    data["memory_mb"] = float(mem_match.group(1))

                return data if data else None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_unread_counts(tracking_id):
    """Get unread message counts via messaging.py."""
    if not tracking_id:
        return None
    messaging_py = Path.home() / "bin" / "ai" / "messages" / "messaging.py"
    if not messaging_py.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(messaging_py), "check", "--session", tracking_id],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def get_jsonl_file_size(cli_session_id):
    """Get JSONL file size by finding the file."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return None
    pattern = str(claude_dir / "*" / f"{cli_session_id}.jsonl")
    matches = glob.glob(pattern)
    if matches:
        try:
            return Path(matches[0]).stat().st_size
        except OSError:
            pass
    return None


# ─── Handler ─────────────────────────────────────────────────────────────

def handler(hook_input, context):
    session_dir = context.session_dir
    tracking_id = context.tracking_id

    if not session_dir or not Path(session_dir).is_dir():
        return HookResult.error(f"session_dir not found: {session_dir or 'not set'}")

    if not tracking_id:
        return HookResult.error("no tracking_id")

    # Publish the app-facing idle state up front (change-guarded, signals the app),
    # independent of whether token telemetry is available below. Sequential with the
    # update_state() RMW later in this handler, so it isn't clobbered within-process.
    if set_activity_state:
        set_activity_state(session_dir, tracking_id, "idle")

    platform = os.environ.get("AI_SESSION_PLATFORM", "")
    transcript_path = hook_input.get("transcript_path", "")
    session_updates = {}
    captured = []
    rate_limits = {}

    # ── Read platform-specific context/token data ────────────────────
    statusline = get_statusline_data(session_dir, tracking_id)

    if statusline:
        # Claude Code — full statusline JSON
        ctx_window = statusline.get("context_window", {})

        ctx_pct = ctx_window.get("used_percentage")
        if ctx_pct is not None:
            session_updates["context.used_pct"] = int(ctx_pct)
            captured.append(f"ctx:{int(ctx_pct)}%")

        total_input = ctx_window.get("total_input_tokens")
        total_output = ctx_window.get("total_output_tokens")
        if total_input is not None and total_output is not None:
            session_updates["context.tokens"] = int(total_input) + int(total_output)
            session_updates["context.input_tokens"] = int(total_input)
            session_updates["context.output_tokens"] = int(total_output)
            captured.append(f"tok:{session_updates['context.tokens']}")

        ctx_size = ctx_window.get("context_window_size")
        if ctx_size is not None:
            session_updates["context.window_size"] = int(ctx_size)

        usage = ctx_window.get("current_usage", {})
        cache_creation = usage.get("cache_creation_input_tokens")
        cache_read = usage.get("cache_read_input_tokens")
        if cache_creation is not None:
            session_updates["context.cache_creation_tokens"] = int(cache_creation)
        if cache_read is not None:
            session_updates["context.cache_read_tokens"] = int(cache_read)

        rate_limits = statusline.get("rate_limits", {})

        workspace = statusline.get("workspace", {})
        working_dir = workspace.get("current_dir") or workspace.get("project_dir") or statusline.get("cwd", "")
        if working_dir:
            session_updates["session.working_dir"] = working_dir

    elif platform == "codex_cli":
        # Codex — extract from JSONL token_count entries
        codex_data = get_codex_token_data(transcript_path)
        if codex_data:
            info = codex_data.get("info", {})
            total_usage = info.get("total_token_usage", {})
            ctx_size = info.get("model_context_window")

            total_in = total_usage.get("input_tokens", 0)
            total_out = total_usage.get("output_tokens", 0)
            total_tok = total_usage.get("total_tokens", total_in + total_out)
            cached = total_usage.get("cached_input_tokens", 0)

            session_updates["context.tokens"] = int(total_tok)
            session_updates["context.input_tokens"] = int(total_in)
            session_updates["context.output_tokens"] = int(total_out)
            session_updates["context.cache_read_tokens"] = int(cached)
            captured.append(f"tok:{total_tok}")

            if ctx_size:
                session_updates["context.window_size"] = int(ctx_size)
                # Estimate ctx% from last request tokens vs window
                last_usage = info.get("last_token_usage", {})
                last_total = last_usage.get("total_tokens", 0)
                if last_total and ctx_size:
                    ctx_pct = int(100 * last_total / ctx_size)
                    session_updates["context.used_pct"] = ctx_pct
                    captured.append(f"ctx:{ctx_pct}%")

            # Codex rate limits from JSONL
            codex_rl = codex_data.get("rate_limits", {})
            if codex_rl:
                primary = codex_rl.get("primary", {})
                secondary = codex_rl.get("secondary", {})
                rate_limits = {
                    "five_hour": {
                        "used_percentage": primary.get("used_percent", 0),
                        "resets_at": primary.get("resets_at"),
                    },
                    "seven_day": {
                        "used_percentage": secondary.get("used_percent", 0),
                        "resets_at": secondary.get("resets_at"),
                    },
                }

        # Codex footer fallback — fills gaps JSONL didn't cover
        codex_footer = get_codex_footer_data(tracking_id)
        if codex_footer:
            if "context_pct" in codex_footer and "context.used_pct" not in session_updates:
                session_updates["context.used_pct"] = codex_footer["context_pct"]
                captured.append(f"ctx:{codex_footer['context_pct']}%")
            if "window_size" in codex_footer and "context.window_size" not in session_updates:
                session_updates["context.window_size"] = codex_footer["window_size"]
            if not rate_limits:
                if "rate_5h_pct" in codex_footer or "rate_7d_pct" in codex_footer:
                    rate_limits = {
                        "five_hour": {"used_percentage": codex_footer.get("rate_5h_pct", 0)},
                        "seven_day": {"used_percentage": codex_footer.get("rate_7d_pct", 0)},
                    }
                    if "rate_5h_pct" in codex_footer:
                        captured.append(f"5h:{codex_footer['rate_5h_pct']}%")
                    if "rate_7d_pct" in codex_footer:
                        captured.append(f"7d:{codex_footer['rate_7d_pct']}%")

    elif platform == "gemini_cli":
        # Gemini — try JSONL tokens field first, then screen-scrape footer
        gemini_data = get_gemini_token_data(transcript_path)
        if gemini_data:
            total_in = gemini_data.get("input", 0)
            total_out = gemini_data.get("output", 0)
            total_tok = gemini_data.get("total", total_in + total_out)
            cached = gemini_data.get("cached", 0)

            session_updates["context.tokens"] = int(total_tok)
            session_updates["context.input_tokens"] = int(total_in)
            session_updates["context.output_tokens"] = int(total_out)
            if cached:
                session_updates["context.cache_read_tokens"] = int(cached)
            captured.append(f"tok:{total_tok}")

        # Screen-scrape footer for context %, quota %, memory (not in JSONL)
        footer = get_gemini_footer_data(tracking_id)
        if footer:
            if "context_pct" in footer:
                session_updates["context.used_pct"] = footer["context_pct"]
                captured.append(f"ctx:{footer['context_pct']}%")
            if "tokens" in footer and "context.tokens" not in session_updates:
                session_updates["context.tokens"] = footer["tokens"]
                captured.append(f"tok:{footer['tokens']}")
            if "quota_pct" in footer:
                rate_limits = {
                    "five_hour": {"used_percentage": footer["quota_pct"]},
                }
                captured.append(f"quota:{footer['quota_pct']}%")
            if "memory_mb" in footer:
                session_updates["context.memory_mb"] = footer["memory_mb"]

    if not session_updates:
        return HookResult.error(f"no token/context data found for {platform or 'unknown'} in {session_dir}")

    session_updates["context.updated_at"] = datetime.now().isoformat()

    # ── Working dir fallback ─────────────────────────────────────────
    if "session.working_dir" not in session_updates:
        cwd = hook_input.get("cwd", "")
        if cwd:
            session_updates["session.working_dir"] = cwd

    # ── Read JSONL summary + per-role counts ─────────────────────────
    cli_session_id = os.environ.get("AI_CLI_SESSION_ID", "")
    summary = get_jsonl_summary(cli_session_id)
    if summary:
        user_msgs = summary.get("user_messages", 0)
        session_updates["transcript.turns"] = user_msgs  # turns ≈ user messages
        session_updates["transcript.messages"] = summary.get("message_count", 0)
        session_updates["transcript.assistant_messages"] = summary.get("assistant_messages", 0)
        session_updates["transcript.tool_calls"] = summary.get("tool_calls", 0)
        captured.append(f"turns:{user_msgs}")
        captured.append(f"msgs:{summary.get('message_count', 0)}")

    # Per-role message counts (u/r/t/h/a)
    role_counts = get_jsonl_role_counts(cli_session_id)
    if role_counts:
        session_updates["transcript.msgs_user"] = role_counts.get("user", 0)
        session_updates["transcript.msgs_response"] = role_counts.get("assistant", 0)
        session_updates["transcript.msgs_tool"] = role_counts.get("tool", 0)
        session_updates["transcript.msgs_thinking"] = role_counts.get("thinking", 0)
        session_updates["transcript.msgs_all"] = role_counts.get("all", 0)
        u = role_counts.get("user", 0)
        r = role_counts.get("assistant", 0)
        t = role_counts.get("tool", 0)
        h = role_counts.get("thinking", 0)
        a = role_counts.get("all", 0)
        captured.append(f"msgs:u{u}/r{r}/t{t}/h{h}/a{a}")

    file_size = summary.get("file_size_bytes") if summary else get_jsonl_file_size(cli_session_id)
    if file_size is not None:
        session_updates["transcript.file_size_bytes"] = int(file_size)
        size_mb = file_size / (1024 * 1024)
        captured.append(f"jsonl:{size_mb:.1f}MB")

    # ── Unread prompts/messages ──────────────────────────────────────
    unread = get_unread_counts(context.tracking_id)
    if unread:
        session_updates["comms.prompts_unread"] = unread.get("inbox_unread", 0)
        session_updates["comms.broadcasts_unread"] = unread.get("broadcast_unread", 0)
        total_unread = unread.get("total_unread", 0)
        if total_unread > 0:
            captured.append(f"unread:{total_unread}")

    # ── Last activity timestamp ──────────────────────────────────────
    session_updates["session.last_activity"] = datetime.now().isoformat()

    state_path = Path(session_dir) / f"{tracking_id}_state.json"

    # ── Offload archive metrics + stop/resume savings estimate ───────
    # Best-effort; metrics must never break core telemetry.
    try:
        from uai_toolkit.hooks.common import lib_offload_metrics as lom
        if transcript_path:
            a = lom.archive_stats(transcript_path)
            session_updates["archive.file_size_bytes"] = a["file_bytes"]
            session_updates["archive.blocks"] = a["blocks"]
            session_updates["archive.orig_bytes"] = a["orig_bytes"]
            if a["blocks"]:
                captured.append(f"arch:{a['blocks']}blk")

        existing = read_state(state_path)
        snapshot = existing.get("metrics.snapshot")
        # First Stop after a SessionStart snapshot backfills the token baseline
        # (the resumed token count isn't knowable at SessionStart).
        if isinstance(snapshot, dict) and snapshot.get("tokens_pending"):
            snapshot = dict(snapshot)
            snapshot["tokens"] = session_updates.get("context.tokens")
            snapshot["ctx_pct"] = session_updates.get("context.used_pct")
            snapshot["tokens_pending"] = False
            session_updates["metrics.snapshot"] = snapshot

        current = {
            "jsonl_bytes": session_updates.get("transcript.file_size_bytes", 0) or 0,
            "jsonl_msgs": session_updates.get("transcript.messages", 0) or 0,
            "tokens": session_updates.get("context.tokens", 0) or 0,
            "ctx_pct": session_updates.get("context.used_pct", 0) or 0,
            "archive_orig_bytes": session_updates.get("archive.orig_bytes", 0) or 0,
            "archive_bytes": session_updates.get("archive.file_size_bytes", 0) or 0,
        }
        # Capacity-based recommendation; used_pct comes from current['ctx_pct'].
        est = lom.estimate(snapshot, current)
        if est:
            est["ts"] = datetime.now().isoformat()
            session_updates["metrics.resume"] = est
            captured.append(f"resume:{est['recommend']}(~{est['sheddable_tokens']}tok@{est['used_pct']}%)")
    except Exception:
        pass

    # ── Write session state ──────────────────────────────────────────
    update_state(state_path, session_updates)

    # ── Update last_activity in session store ────────────────────────
    store_script = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"
    if store_script.exists():
        now_iso = datetime.now().astimezone().isoformat()
        try:
            subprocess.run(
                [PYTHON, str(store_script), "edit", tracking_id,
                 "--set", f"last_activity={now_iso}"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    # ── Extract and write rate limits (cross-session, per-platform) ──
    # rate_limits was populated earlier from statusline (Claude) or JSONL (Codex)
    if rate_limits and platform:
        platform_dir = AI_ROOT / "ai_general" / "data" / "sessions" / platform
        if platform_dir.is_dir():
            platform_state_path = platform_dir / "platform_state.json"
            platform_updates = {}

            five_hour = rate_limits.get("five_hour", {})
            if five_hour:
                platform_updates["usage.5h.used_pct"] = round(five_hour.get("used_percentage", 0), 1)
                platform_updates["usage.5h.resets_at"] = five_hour.get("resets_at")
                captured.append(f"5h:{round(five_hour.get('used_percentage', 0))}%")

            seven_day = rate_limits.get("seven_day", {})
            if seven_day:
                platform_updates["usage.7d.used_pct"] = round(seven_day.get("used_percentage", 0), 1)
                platform_updates["usage.7d.resets_at"] = seven_day.get("resets_at")
                captured.append(f"7d:{round(seven_day.get('used_percentage', 0))}%")

            platform_updates["usage.last_reporter"] = tracking_id

            update_state(platform_state_path, platform_updates)

            # Also store in session state for per-session visibility
            session_rate_updates = {}
            if five_hour:
                session_rate_updates["usage.5h.used_pct"] = platform_updates.get("usage.5h.used_pct")
                session_rate_updates["usage.5h.resets_at"] = platform_updates.get("usage.5h.resets_at")
            if seven_day:
                session_rate_updates["usage.7d.used_pct"] = platform_updates.get("usage.7d.used_pct")
                session_rate_updates["usage.7d.resets_at"] = platform_updates.get("usage.7d.resets_at")
            if session_rate_updates:
                update_state(state_path, session_rate_updates)

    return HookResult.allow(", ".join(captured) if captured else "no data captured")


if __name__ == "__main__":
    sys.exit(run_hook("store_session_data", "Stop", handler))
