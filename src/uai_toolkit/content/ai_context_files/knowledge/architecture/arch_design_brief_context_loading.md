# Brief & Context Loading Lifecycle — Design Draft

**Date:** 2026-06-14 · **Author:** Claude (session Broken-Clock) with Shawn
**Status:** DRAFT — design agreed, not yet implemented
**Related:** [usage_efficiency](../usage_efficiency/design_usage_efficiency_actions.20260614.md) (§6b JSONL safe-edit), team_topology.

---

## 1. Core principle (the inversion that fixes the current tangle)

`loaded_briefs` and `loaded_context_files` are **session state variables** that *record what is currently loaded into the session's context* — they are the **OUTPUT of loading**, and they are what the **UAI Session Details → right panel** shows. They are **NOT** a replay-driver.

The current `SessionStart/02_stage_session_context_sync.py` treats `loaded_briefs` as an *input to re-inject* — that is backwards (and on resume it would duplicate content already in the replayed transcript). Storage location of the variable is not the point; the semantic is: **state reflects what's loaded; references drive loading.**

The single queue is **`<session_dir>/context_to_load/`** — an inbox of **references** (not raw files) to load at the next opportunity.

## 2. Rules

1. **Producers stage typed REFERENCES**, never raw files/symlinks, into `context_to_load/`, **via an MCP tool or script** (so an intelligent, typed reference is used — brief, context-file, trait, role, …). Raw symlink/file drops are a no-no.
2. **On compaction: reset** the session's `loaded_briefs` and `loaded_context_files` state — compaction drops that content from context, so the record must no longer claim it's loaded.
3. **Consumers** read references, recognize their type, and call the proper loader (`knowledge_get_context` / `session_load`) which **returns content AND does the bookkeeping** (sets `loaded_briefs` / `loaded_context_files`). Content is injected as `additionalContext`; consumed references are removed from the inbox.
   - **`SessionStart/02`** — on `source=compact` (and `clear`): do the §2 **reset first**, then consume the inbox. On `startup`: consume (fresh session). On `resume` (incl. fork): do **not** re-inject (the transcript replay already contains prior content) and do **not** reset; only consume any *new* references staged since.
   - **`UserPromptSubmit/06`** — mid-session catch-all consumer; reads existing `loaded_briefs`/`loaded_context_files` first and **skips already-loaded** items (no redundant re-load).

## 3. Capability facts (verified via Claude Code hooks docs, 2026-06-14)

- **SessionStart `source` ∈ {`startup`, `resume`, `clear`, `compact`}.** new=`startup`, resume=`resume` (reliably distinguishable).
- **Compaction (auto and `/compact`) fires `SessionStart` with `source: "compact"`** — this is Anthropic's *documented, intended* pattern for re-injecting context after compaction. So the compaction reset + reload belongs in SessionStart(compact).
- **SessionStart supports context injection** via `hookSpecificOutput.additionalContext`.
- **PostCompact CANNOT inject** (no documented output schema; docs steer to SessionStart-compact). PostCompact = side effects only (logging/optional staging).
- **fork** (`--resume --fork-session --session-id`) is undocumented as a `source`; assumed to report `resume`. Verify only if it misbehaves.

## 4. Per-event flow (compaction)

- **PreCompact** — generate the handover brief (content still present to summarize) and stage its **reference** into `context_to_load/` via the tool/script.
- **PostCompact** — side effects only (e.g., logging). NOT the loader.
- **SessionStart(source=compact)** — reset `loaded_briefs`/`loaded_context_files`, then consume `context_to_load/` (resolve refs via loader → content injected + loaded-state set).

## 5. Deltas from current code (the build)

- `PostCompact/02_auto_brief_postcompact_sync.py` — stage a **typed reference** via tool/script, not a raw symlink. (Brief generation itself belongs in PreCompact.)
- `SessionStart/02_stage_session_context_sync.py` — stop using `loaded_briefs` as a replay-driver; add `source` branching: reset on compact/clear, consume `context_to_load/`, skip re-injection on resume. (Factor the inbox-consumer into a shared `common/` helper.)
- `UserPromptSubmit/06_deliver_pending_context_sync.py` — already consumes-and-deletes the inbox (good); change: route references through the proper loader so it sets `loaded_briefs`/`loaded_context_files`, and add the redundancy check against loaded-state. Share the consumer helper with SessionStart/02.
- **Briefs as a first-class loadable type** — `06`'s `GUIDANCE_TYPES = {traits, roles, profiles, skills}` excludes briefs; briefs currently take a read-from-path fallback with partial `session_traits` bookkeeping. To load briefs "properly" (via `knowledge_get_context`, full bookkeeping incl. setting `loaded_briefs`), either add `brief`/`session_brief` to the guidance/knowledge resolution or give the consumer an explicit brief-load path that writes `loaded_briefs`.

## 6. Open decisions

- **Reload-after-compaction policy:** (A) handover brief only — reset, load just the brief; prior context files not reloaded (brief summarizes them). *(lean A)* vs (B) restore prior loads — re-stage references for everything previously loaded (faithful but re-bloats, partly defeating compaction). Could be per-item.
- **`loaded_briefs` storage** — must be the session-state variable that the UAI right panel reads/writes; today there are two unconnected `loaded_briefs` (per-session `*_state.json` read by SessionStart/02 vs `app_state.json` sessionPrefs written by UAI `setBriefs`), and no writer feeds the one SessionStart/02 reads. Unify on one source of truth (the one UAI shows).
- Whether briefs become a first-class guidance/knowledge type (§5 last bullet).
