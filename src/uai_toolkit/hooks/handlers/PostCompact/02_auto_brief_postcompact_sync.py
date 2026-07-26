#!/usr/bin/env python3
"""PostCompact hook — record compact.end and stage brief for delivery.

Sets compact.end in session state. If compact.brief_file has a valid path,
stages it into context_to_load/ for delivery on next prompt.
"""

import json
import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state  # session-state bridge (todo_0495)

_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))


def _reload_durable_context(session_dir, state):
    """Re-stage the session's durable loaded_context so it re-establishes the base
    context it had before this compaction (todo_0617 area D).

    SessionStart/02 skips on source=compact, so globals/platform/roles are NOT
    re-injected after a /compact — only a brief comes back, and base context is lost.
    Here we read kv `loaded_context` (captured by area C), select the DURABLE entries
    (transient notices are durable=False and skipped), and drop a re-stage `.ref` for
    each into context_to_load/ — reusing the existing drain machinery, no new channel.

    Filenames are prefixed `50_reload__`; lib_context_load.drain() recognizes that
    prefix as a lower-priority bucket, so every already-staged brief/catch-up entry
    drains first regardless of its filename. When these drain next turn, area-C
    capture de-dups on (type, name), so reloading is idempotent (no duplicate
    loaded_context entries). Returns the count staged.

    Opt-out: `compact.reload_context=false` in session state suppresses this.
    Best-effort; never raises (a reload failure must not break the PostCompact hook).
    """
    inbox = Path(session_dir) / "context_to_load"

    # The current loaded_context state is authoritative. Remove stale reload refs
    # from a prior compact before applying opt-out/selection; otherwise an opt-out
    # or later unload could still be resurrected by an already-queued ref.
    if inbox.is_dir():
        for stale in inbox.glob("50_reload__*.ref"):
            try:
                if stale.is_file() or stale.is_symlink():
                    stale.unlink()
            except OSError:
                pass

    if not state.get("compact.reload_context", True):
        return 0
    loaded = state.get("loaded_context", [])
    if not isinstance(loaded, list) or not loaded:
        return 0
    try:
        inbox.mkdir(exist_ok=True)
    except OSError:
        return 0
    staged = 0
    seen = set()
    destinations = set()
    for entry in loaded:
        if not isinstance(entry, dict) or not entry.get("durable"):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        ctype = str(entry.get("type") or "ref").strip() or "ref"
        key = (ctype, name)
        if key in seen:
            continue
        seen.add(key)
        path = entry.get("path")
        # Mirror how briefs/refs already resolve: an existing file path is
        # authoritative (pin_path); otherwise resolve the name through guidance
        # (roles, bundles, …). Always carry `name` so area-C capture re-records the
        # ORIGINAL (type,name) — the 50_reload__ filename is only a priority marker.
        ref = {"type": ctype, "name": name}
        try:
            if isinstance(path, (str, os.PathLike)) and Path(path).is_file():
                ref["path"] = str(path)
                ref["pin_path"] = True
        except OSError:
            pass
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", "{}__{}".format(ctype, name))[:120]
        destination = "50_reload__{}.ref".format(safe)
        if destination in destinations:
            # Sanitization/truncation can collapse distinct identities (e.g.
            # role a/b vs a_b). Preserve the readable base and disambiguate only
            # collisions with a stable short digest.
            digest = hashlib.sha256(
                "{}\0{}".format(ctype, name).encode("utf-8")
            ).hexdigest()[:10]
            destination = "50_reload__{}__{}.ref".format(safe[:108], digest)
        destinations.add(destination)
        try:
            (inbox / destination).write_text(json.dumps(ref, indent=2))
            staged += 1
        except OSError:
            pass
    return staged


def handler(hook_input, context):
    tracking_id = context.tracking_id
    session_dir = context.session_dir

    if not tracking_id:
        return HookResult.skip("no tracking_id")
    if not session_dir or not Path(session_dir).is_dir():
        return HookResult.skip("no session_dir")

    state = read_union(session_dir, tracking_id)
    now = datetime.now().isoformat()

    # Record compact.end + reset the per-cycle compaction flags. These flags
    # (compact.self / compact.self_triggered) gate future compactions; if they
    # never clear, the auto-threshold path stops firing after the first cycle
    # and a stale compact.self could mislead the next run. Clear them now that
    # the cycle is ending — AFTER we read compact.brief_file. Targeted write
    # through the bridge (todo_0495).
    brief_file = state.get("compact.brief_file", "")
    write_session_state(session_dir, tracking_id, {
        "compact.end": now,
        "compact.self": False,
        "compact.self_triggered": False,
        "compact.brief_pending": False,
        "updated_at": now,
    })

    # Re-establish the durable base context this session had before compacting
    # (area D). Runs regardless of whether a brief exists; the brief still drains
    # first (the shared drain gives 50_reload__ entries lower priority). Uses the
    # state read above (pre-write).
    reloaded = _reload_durable_context(session_dir, state)

    # No brief was written for the conversation that just compacted (e.g. a forced
    # auto-compaction left no turn to write one). The transcript is still on disk,
    # so stage a one-shot instruction telling the session to write the brief from
    # the just-compacted messages on its next turn. A hook can't run an AI itself;
    # the session spawns the subagent when it reads this note. interval -2 is the
    # interval just before the current (post-compaction) live one — valid as long
    # as the catch-up runs before any further compaction, which it does (the
    # session is near-empty right after compacting, and the note drains next turn).
    if not brief_file or not Path(brief_file).exists():
        try:
            inbox = Path(session_dir) / "context_to_load"
            inbox.mkdir(exist_ok=True)
            ref = {
                "type": "catchup_brief",
                "interval": "-2",
                "brief_path": str(_AI_ROOT / "ai_general" / "data" / "session_briefs"
                                  / "auto_briefs" / f"{tracking_id}.yml"),
                "prompt_path": str(_AI_ROOT / "ai_general" / "ai_context_files"
                                   / "instructions" / "how_tos" / "instr_operational_handoff.md"),
            }
            (inbox / "00_catchup_brief.ref").write_text(json.dumps(ref, indent=2))
            return HookResult.allow(
                f"compact.end set, no brief — staged catch-up instruction + {reloaded} base-context reloads")
        except OSError as e:
            return HookResult.allow(f"compact.end set, no brief; catch-up staging failed: {e}")

    # A brief WAS registered pre-compaction. Its .ref is staged at registration
    # time by register_self_brief.py (the creator owns delivery staging), so there
    # is nothing to stage here — the .ref already survives the compaction and drains
    # on the next turn (UserPromptSubmit/06) or on resume (SessionStart/02).
    return HookResult.allow(
        f"compact.end set, brief registered; {reloaded} base-context reloads staged")


if __name__ == "__main__":
    sys.exit(run_hook("auto_brief_postcompact", "PostCompact", handler))
