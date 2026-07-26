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
GUIDANCE_CLI = AI_ROOT / "ai_general" / "scripts" / "context_files" / "guidance_cli.py"

DEFAULT_MAX_CHARS = 200_000
_RELOAD_PREFIX = "50_reload__"


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
        # Guidance emits a bracketed error marker when it can't resolve a name —
        # "[Not found: …]", "[Trait not found: …]", "[Brief not found]", etc. NEVER
        # inject that error string as content (that was the brief-load bug: the old
        # guard only checked "[Not found" and missed "[Trait not found …]"). Any
        # first-line bracketed "… not found …" ⇒ unresolved ⇒ fall back to raw path.
        lines = [line.strip().lower() for line in out.splitlines() if line.strip()]
        # guidance_cli may return either a direct bracketed error as the first line
        # or a markdown heading followed by the bracketed error, e.g.
        #   # Prism
        #   [Not found. Use get_knowledge_topics to browse.]
        # Treat either form as unresolved so .ref path fallback stays graceful.
        first_error_line = None
        for line in lines:
            if line.startswith("#"):
                continue
            first_error_line = line
            break
        looks_unresolved = bool(
            first_error_line
            and first_error_line.startswith("[")
            and "not found" in first_error_line
        )
        if out and not looks_unresolved:
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
        # A self-authored brief pins an EXACT file (register_self_brief.py sets
        # pin_path). That path is authoritative — read it directly. Resolving by
        # name through guidance can hit a DIFFERENT registered context of the same
        # name (a session named "Prism" collided with a guidance doc named "Prism"),
        # loading the wrong brief. Only fall back to name resolution if the pinned
        # file is gone.
        if ref.get("pin_path"):
            content, resolved = _read_file(ref.get("path", ""))
            if content is not None:
                return content, "{} (pinned path)".format(resolved)
        name = ref.get("name", "")
        content = _resolve_via_guidance(name, tracking_id)
        if content:
            return content, "{}/{} (via guidance)".format(ref.get("type", "ref"), name)
        return _read_file(ref.get("path", ""))
    return _read_file(entry)


def record_loaded_context(session_dir, tracking_id, name, ctype, source,
                          path=None, durable=True):
    """Record ONE loaded context item in the session's kv ``loaded_context`` list.

    The SINGLE capture path for every load channel — SessionStart globals/platform/
    roles, the context_to_load/ drain (.ref AND raw), and dynamic guidance callers
    that use this helper — so a session's state reflects everything captured through
    those paths (todo_0617 area C). Previously only raw drain entries were recorded,
    so most context was invisible to state.

    De-dups on ``(type, name)``: re-loading the same item REPLACES its entry (refreshed
    ``loaded_at``/``source``) instead of appending a duplicate — so post-compaction
    reload (area D) is idempotent. ``durable`` marks context that should be
    re-established after /compact; transient notices (inbox / catch-up-brief) pass
    ``durable=False`` so D can skip them. ``path`` is a re-stageable identity (a file
    path or a guidance name) for D. Best-effort; never raises (a state-write failure
    must never break a hook).
    """
    try:
        from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state
        loaded = read_union(session_dir, tracking_id).get("loaded_context", [])
        if not isinstance(loaded, list):
            loaded = []
        key = (ctype, name)
        loaded = [e for e in loaded
                  if not (isinstance(e, dict) and (e.get("type"), e.get("name")) == key)]
        loaded.append({
            "name": name, "type": ctype, "source": source, "path": path,
            "durable": bool(durable), "loaded_at": datetime.now().isoformat(),
        })
        write_session_state(session_dir, tracking_id, {
            "loaded_context": loaded,
            "updated_at": datetime.now().isoformat(),
        })
    except Exception:
        pass


def _classify_entry(entry):
    """Classify a context_to_load/ inbox entry for loaded_context recording.

    Returns ``(ctype, durable, ident)``:
    - persistent raw link -> ("raw", True, <resolved target path>)
    - copied raw file     -> ("raw", False, None)  # consumed from the inbox
    - transient notice    -> ("notice", False, None)  # inbox / catch-up-brief: do NOT reload
    - durable .ref doc    -> (<ref type>, True, <pin_path|name|path>)  # e.g. "brief","bundle"
    The ident is a re-stageable handle area D uses to reconstruct the load.
    """
    if entry.suffix != ".ref":
        # drain() unlinks the inbox entry after delivery. A symlink's resolved
        # target survives and can be re-staged after compaction; a copied raw file
        # does not, so it must not claim to be durable with a dead inbox path.
        if entry.is_symlink():
            try:
                resolved = entry.resolve(strict=True)
                if resolved.is_file():
                    return "raw", True, str(resolved)
            except OSError:
                pass
        return "raw", False, None
    try:
        ref = json.loads(entry.read_text())
    except (OSError, json.JSONDecodeError):
        return "ref", True, None
    rtype = ref.get("type", "ref")
    if rtype in ("inbox", "catchup_brief"):
        return "notice", False, None
    # Preserve the identity that resolve_entry() actually used: pinned refs are
    # path-authoritative; ordinary named refs resolve through guidance first and
    # use path only as fallback. Reversing that order would reload different
    # content after compaction.
    if ref.get("pin_path") and ref.get("path"):
        ident = ref.get("path")
    else:
        ident = ref.get("name") or ref.get("path")
    return rtype, True, ident


def _entry_record_name(entry):
    """Stable loaded_context name for an inbox entry.

    A .ref's semantic ``name`` must win over its queue filename. Area D prefixes
    reload filenames (``50_reload__...``); recording the stem would defeat
    de-duplication and append a new loaded_context entry on every compaction.
    """
    if entry.suffix == ".ref":
        try:
            ref = json.loads(entry.read_text())
            name = ref.get("name")
            if name:
                return str(name)
        except (OSError, json.JSONDecodeError):
            pass
    return entry.stem


def _record_loaded(session_dir, tracking_id, name, source):
    """Back-compat shim (raw-file load). Prefer record_loaded_context() directly."""
    record_loaded_context(session_dir, tracking_id, name, "raw", source, path=name)


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
    # PostCompact durable reloads must drain AFTER any already-staged brief or
    # catch-up instruction. Filename-only ordering cannot guarantee that (a brief
    # named ``Prism.ref`` sorts after ``50_reload__...``), so reload entries get an
    # explicit second priority bucket while preserving normal lexical order inside
    # each bucket.
    for entry in sorted(
        inbox.iterdir(),
        key=lambda p: (p.name.startswith(_RELOAD_PREFIX), p.name),
    ):
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
        # Capture EVERY delivered load in kv state — .ref and raw alike (area C).
        # Transient notices (inbox / catch-up-brief) are recorded durable=False so
        # post-compaction reload (area D) skips them.
        ctype, durable, ident = _classify_entry(entry)
        record_loaded_context(session_dir, tracking_id, _entry_record_name(entry), ctype, source,
                              path=ident, durable=durable)
        try:
            entry.unlink()
        except OSError:
            pass
    return delivered
