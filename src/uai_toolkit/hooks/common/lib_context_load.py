"""
lib_context_load.py — the one driver for a session's context_to_load/ inbox.

Any process stages context for a session by dropping files into
<session_dir>/context_to_load/. This module reads them, resolves each entry to
text, and removes it after delivery. Every hook that delivers pending context
(UserPromptSubmit, SessionStart, …) calls drain() — none of them has
type-specific logic. The rule is simply: if it's in the directory, it loads; if
it's not, it doesn't.

Entry resolution (generic — no per-type routing table):
  .ref files      JSON {type, name, path}. Always resolved through the knowledge
                  loader (guidance_cli get_context <name>), which assembles the
                  content AND records the load. Falls back to reading `path` only
                  if the loader returns nothing.
  everything else raw text files / symlinks, read directly from disk.

AI_ROOT note: resolved once here from the environment, canonical default
~/AI/ai_root. No legacy-path handling — a session's env is the source of truth.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT") or (Path.home() / "AI" / "ai_root"))
GUIDANCE_CLI = AI_ROOT / "ai_general" / "scripts" / "traits" / "guidance_cli.py"

DEFAULT_MAX_CHARS = 200_000


def _resolve_via_guidance(name, tracking_id):
    """Resolve a reference name through guidance_cli get_context. Returns the
    content string, or None if the loader can't resolve it."""
    if not name:
        return None
    env = os.environ.copy()
    if tracking_id:
        env["AI_TRACKING_ID"] = tracking_id
    try:
        result = subprocess.run(
            [sys.executable, str(GUIDANCE_CLI), "get_context", name],
            capture_output=True, text=True, timeout=30, env=env,
        )
        out = result.stdout.strip()
        if out and "[Not found" not in out:
            return out
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _read_file(path):
    """Read a file (following symlinks). Returns (content, resolved_path) or (None, None)."""
    try:
        resolved = Path(path).resolve()
        if resolved.exists():
            return resolved.read_text(encoding="utf-8", errors="replace"), str(resolved)
    except (OSError, UnicodeDecodeError):
        pass
    return None, None


def resolve_entry(entry, tracking_id):
    """Resolve one inbox entry to (content, source_description).

    Generic: a .ref is always handed to the knowledge loader first (which knows
    how to find any registered type, briefs included) and falls back to its
    `path`; anything else is read raw.
    """
    if entry.suffix == ".ref":
        try:
            ref = json.loads(entry.read_text())
        except (OSError, json.JSONDecodeError):
            return None, None
        # Inbox notice: a proactive "you've got mail" surface for a recipient that
        # was busy when mail arrived. Direct it to its WHOLE inbox (not one
        # message — that would make it read only that one and miss the rest). Do
        # NOT mark read_by; that happens only on explicit comms_read_message.
        # drain() consumes this .ref after injecting once, so a busy recipient
        # gets exactly one surface; the canonical inbox pull still works.
        if ref.get("type") == "inbox":
            notice = ("\U0001F4EC You have unread mail. Check your inbox with "
                      "comms_check_messages and read with comms_read_message.")
            return notice, "inbox notice"
        # Catch-up brief: a compaction finished WITHOUT a handoff brief (e.g. a
        # forced auto-compaction left no turn to write one). The compacted
        # conversation is still on disk, so instruct the session to write the brief
        # now from the just-compacted messages via a subagent. drain() consumes
        # this after injecting once.
        if ref.get("type") == "catchup_brief":
            iv = ref.get("interval", "-2")
            brief = ref.get("brief_path", "")
            prompt = ref.get("prompt_path", "")
            notice = (
                "⚠️ You just compacted WITHOUT writing a handoff brief, but the "
                "compacted conversation is still saved on disk. Before doing other work, "
                "write that brief now using a subagent:\n"
                "  1. Spawn a Task subagent and have it run:\n"
                "       python3 ~/AI/ai_root/ai_general/scripts/jsonl/condense.py "
                "--src-uuid \"$AI_CLI_SESSION_ID\" --interval {iv} --prepare-only "
                "--output /tmp/catchup_brief_src.json\n"
                "     (interval {iv} is the conversation that was just compacted away.)\n"
                "  2. Have the subagent read /tmp/catchup_brief_src.json and the handoff "
                "instructions at {prompt}, then write a YAML handoff brief to {brief} "
                "(confirm it parses with yaml.safe_load before finishing).\n"
                "  3. After the subagent returns, run: python3 ~/AI/ai_root/ai_general/"
                "scripts/session_mgmt/register_self_brief.py {brief}\n"
                "  The brief will then load on your next turn."
            ).format(iv=iv, prompt=prompt, brief=brief)
            return notice, "catch-up brief instruction"
        name = ref.get("name", "")
        content = _resolve_via_guidance(name, tracking_id)
        if content:
            return content, "{}/{} (via guidance)".format(ref.get("type", "ref"), name)
        return _read_file(ref.get("path", ""))
    return _read_file(entry)


def _record_loaded(session_dir, tracking_id, name, source):
    """Record a raw-file load in session state. (.ref loads are recorded by
    guidance itself, so this only covers raw files.)"""
    state_path = Path(session_dir) / "{}_state.json".format(tracking_id)
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        loaded = state.get("loaded_context", [])
        if not isinstance(loaded, list):
            loaded = []
        loaded.append({"name": name, "source": source, "loaded_at": datetime.now().isoformat()})
        state["loaded_context"] = loaded
        state["updated_at"] = datetime.now().isoformat()
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except (OSError, json.JSONDecodeError):
        pass


def drain(session_dir, tracking_id, max_chars=DEFAULT_MAX_CHARS):
    """Resolve and remove every entry in <session_dir>/context_to_load/.

    Returns a list of (stem, content, source) tuples for delivered entries.
    Unreadable/unresolvable entries are removed and skipped. When the running
    total would exceed max_chars, the remaining entries are left in place for the
    next delivery.
    """
    if not session_dir or not tracking_id:
        return []
    inbox = Path(session_dir) / "context_to_load"
    if not inbox.is_dir():
        return []

    delivered = []
    total = 0
    for entry in sorted(inbox.iterdir()):
        if not (entry.is_file() or entry.is_symlink()):
            continue
        content, source = resolve_entry(entry, tracking_id)
        if content is None:
            try:
                entry.unlink()
            except OSError:
                pass
            continue
        if total + len(content) > max_chars:
            break  # leave the rest for the next delivery
        delivered.append((entry.stem, content, source))
        total += len(content)
        if entry.suffix != ".ref":
            _record_loaded(session_dir, tracking_id, entry.name, source)
        try:
            entry.unlink()
        except OSError:
            pass
    return delivered
