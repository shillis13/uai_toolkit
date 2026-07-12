# DESIGN — Work Landscape & Session Assessment

**Status:** v1 (active)
**Author:** Anvil (session 20260610_003447_a91cb496_cla) + PianoMan
**Date:** 2026-06-21
**Scope:** `scripts/work/` — `work_landscape.py`, `work_assess_sessions.py`, `work_summarize_sessions.py`
**Tracks:** `todo_0322_hamilton_coordinator_infrastructure`
**Companion:** Unified Work Tracking spec (`work/todos/todo_0307_.../2026-06-11-unified-work-tracking-design.md`); Coordinator architecture (`work/todos/todo_0307_.../2026-06-19-coordinator-session-architecture.md`)

## Terms

- **LLLM** — *local LLM*. A locally-run `llama-server` model with **no tools**: text in, structured text out. Orchestrated by a script; it cannot act, only assess. Reached via `scripts/lllm/lllm_prompt.py`.
- **Coordinator / Hamilton** — the standing session that watches the whole work landscape and curates what needs PianoMan. `Coordinator` is the reusable role; `hamilton` is the profile that wears it. These scripts are its data backbone.
- **Landscape** — the joined, cross-session view of who is doing what, what's blocked, what's pending.
- **Assignee** — the session(s) working a todo, as `uai://session/<tracking_id>` URIs in the todo's `assigned.yml` (resolved here to `display_name`). The single assignment representation — the old `origin.yml owner` field is retired. **Project** — the scope a todo belongs to (in `origin.yml`). Independent axes.
- **Structural vs interpretive** — *structural* facts are recorded in data (a todo's assignee/status). *Interpretive* facts must be inferred from prose (a session is "stuck"). The components below split exactly on this line.

## Purpose

Give the coordinator (and, later, the UAI cockpit) one answer to *"who is doing what, what's stale, what needs me?"* — without the coordinator burning its own context reading everyone's logs. Read-only, composable, each script useful alone.

## Architecture — a two-layer split (+ a standalone summarizer)

```
  sess-mgr ──┐
  todos-mgr ─┼──►  work_landscape.py       ──►  structural table       ──┐
             │     (fast, deterministic,                                  │
             │      always correct)                                       ├──► work_landscape.py --enrich
  transcripts ──►  work_assess_sessions.py ──►  data/work/                ┘     (full picture:
                   (slow, probabilistic,         assessments.json               states + NEEDS PIANOMAN)
                    LLLM, scheduled)

  transcripts ──►  work_summarize_sessions.py ──► {session_dir}/{id}_lllmSummary.log
                   (standalone free-text per-session summaries; not part of the join)
```

The two landscape layers are deliberately decoupled: if the LLLM is down, the structural landscape is unaffected — it simply shows no interpretive tags. The enrich step is a cheap file read that joins them by session name. `work_summarize_sessions.py` is a related but separate tool (see Component 3).

---

## Component 1 — `work_landscape.py` (structural skeleton)

Read-only. Joins existing sources into one table. Never mutates.

### Sources
Shells out to the managers with `--json` rather than touching their stores (keeps this script ignorant of storage internals):
- `sess-mgr list --json` → sessions (`display_name`, `platform`, `status`, `activity_state`, `activity_state_at`, `last_activity`, `roles`, ...).
- `todos-mgr list --json` → todos (`id`, `status`, `assigned` (URI list), `project`, `flags`, `summary`, ...).

`_run_json(mgr, args)` wraps this: 30 s timeout; returns `[]` on any failure (non-zero exit, JSON error, OS error); unwraps a bare list or a `{sessions|todos|items: [...]}` envelope. A broken manager degrades the view to empty, never a crash.

### The join — `load_landscape(include_stopped, enrich)`
1. `assigned = {assignee_name → [todos]}`. **The link comes from each todo's `assigned` URIs** (`uai://session/<tracking_id>`), resolved to the session `display_name` (e.g. `"Mullion"`).
2. For each session (skip non-`active` unless `--all`), emit a row: `name, platform, status, ago, roles, todos, assessment`.
3. `ago` ← `_ago(last_activity)`: relative time (`now`/`Nm`/`Nh`/`Nd`) from the ISO timestamp — the freshness signal.
3b. **STATE** ← Relay's reconciled `activity_state` (`responding`/`idle`/`blocked`/`permission_prompt`/`prompt_occupied`/`exited`), preferred over raw `status` (active/stopped), which is unreliable (sessions read "active" days after going quiet). Falls back to `status` when `activity_state` is `unknown` (Relay's recommendation). `blocked`/`permission_prompt` are real-time "needs the user" signals folded into NEEDS PIANOMAN alongside the assessor's `needs_pianoman`.
4. Rows sorted active-first, then by name.
5. `totals`: gap tallies — active sessions with no assigned todo; todos with no assignee/project. The honest "premise not yet met" numbers.

### Enrichment — opt-in `--enrich`
`_load_assessments()` reads `data/work/assessments.json` (empty dict if absent → always safe) and attaches each session's verdict to its row by name. Gated behind the flag so the **default view is fast and has zero LLLM dependency**.

### Render — `render(model)`
Fixed-width table. Enrichment adds: (a) a non-`productive` state appended to the work cell as `[waiting_on_user ⚑]`; (b) a **NEEDS PIANOMAN** section listing every session with `needs_pianoman: true` and its `open_question` — the `curate_for_pianoman` payoff. `--json` emits the raw model instead (for the eventual UAI cockpit).

---

## Component 2 — `work_assess_sessions.py` (interpretive layer)

Adds what structure can't see — *stuck? waiting on PianoMan? what's the open question?* — by reading transcripts with the LLLM. Designed to run **headless on a schedule**.

### Pipeline — `gather(only_session)`
1. `sess-mgr list --json`; apply a **freshness gate** (`_fresh`, `FRESH_HOURS=12`) to skip stale "active" ghosts. `--session X` bypasses the gate (assess one on demand).
2. `_transcript_tail(path, TAIL_CHARS=6000)` — `transcript_path` is a **list** (one entry per resume); take the last. Read the final ~60 jsonl lines, extract human-readable text from `user`/`assistant` turns (handles string and structured-`content` array forms), keep the last 6000 chars. Bounded, recent context only.
3. `assess_one(name, excerpt)` — runs `lllm_prompt.py <ASSESS_PROMPT> --text <excerpt>`. The prompt demands a single JSON object: `{state, project_guess, open_question, needs_pianoman}`. **Invoked via its own shebang** (the MCP venv python, which has `httpx`) — *not* the caller's interpreter.
4. `_parse_assessment(raw)` — regex-extracts the first `{...}` block and parses it (`None` on failure). Local models wrap JSON in prose/fences; this is defensive.
5. Stamp each verdict with `assessed_at`; collect `{name → verdict}`.

### Write — `main()` (merge, not overwrite)
Loads the existing `assessments.json` and `.update()`s it with new verdicts. A run producing nothing (LLLM busy/down, no fresh sessions) is a **no-op merge, never a clobber** of last-good data; un-reassessed sessions keep their prior verdict (older `assessed_at` shows the staleness). `--stdout` prints instead of writing.

`AI_ROOT` resolution ignores a non-existent env value and falls back to the absolute default — robust under shell, scheduler, or launchd.

---

## Component 3 — `work_summarize_sessions.py` (standalone summarizer)

Pre-existing tool, relocated here from `scripts/lllm/` so all work/session-analysis lives together. **Distinct from Component 2:** it produces a free-text, human-readable summary of a session's recent activity and appends it to `{session_dir}/{tracking_id}_lllmSummary.log` — it does **not** feed the landscape join and emits no structured verdict.

- Reads recent turns from JSONL transcripts (`--jsonl N`) or terminal scrollback (`--terminal N`) for running sessions.
- Imports `session_ops`/`session_store`/`read_jsonl` (from `scripts/session_mgmt` + `scripts/jsonl`) and `lllm_prompt.prompt_text` (from `scripts/lllm`). On the move it kept those imports working by adding `scripts/lllm/` to `sys.path` explicitly (not its own dir).
- Use Component 2 (`work_assess_sessions.py`) for the structured landscape signal; use this when you want a readable narrative summary per session.

---

## Data contract — `data/work/assessments.json`

```json
{
  "<session display_name>": {
    "state": "productive | blocked | waiting_on_user | idle",
    "project_guess": "<string or null>",
    "open_question": "<string or null>",
    "needs_pianoman": true,
    "assessed_at": "2026-06-21T05:46:00"
  }
}
```

Keyed by session `display_name` — the same key `work_landscape.py` joins on.

## Scheduling

`data/scheduled_tasks/work.yml` defines an `assess_sessions` job at `*/30 * * * *`, **`enabled: false`**. Enabling installs a launchd agent that runs the LLLM every 30 min, keeping a model warm ~continuously — a GPU/RAM commitment that is PianoMan's call. To activate:
```
sched-task-mgr enable work && sched-task-mgr install
```

## Design decisions & rationale

| Decision | Why |
|---|---|
| Two decoupled layers (structural vs interpretive) | Structure is fast/exact and must never depend on a probabilistic model being up. Interpretation is best-effort, cached to a file. |
| Shell out to managers (`--json`), not read stores | Keeps these scripts ignorant of storage internals; the managers own their schema. |
| `last_activity` freshness over raw `status` | Observed: `status=active` lies (days-old sessions still "active"). Freshness is computed and honest. |
| Merge, not overwrite, in the assessor | An empty/failed run must not destroy last-good interpretation. |
| Invoke `lllm_prompt.py` by shebang | Its venv has `httpx`; the caller's `python3` may not. Using the caller's interpreter silently zeroed every assessment under the scheduler. |
| `enabled: false` by default | Continual LLLM use is an ongoing machine-resource commitment — operator's decision, not the script's. |
| Enrichment opt-in (`--enrich`) | Default view stays instant and dependency-free. |

## Known gaps / future work

- **Assignee/project are sparse** — most todos have neither yet, so the structural join is thin. The assessor's `project_guess` is a stepping stone toward LLLM-inferred backfill that *populates* assignment/`project`, closing the gap it currently only surfaces.
- ~~Point `work_landscape.py` at Relay's reconciled activity-state to retire raw `status`.~~ **Done (2026-06-21)** — STATE column uses `activity_state`, falls back to `status` when `unknown`; `blocked`/`permission_prompt` feed NEEDS PIANOMAN.
- **UAI cockpit** consumes `work_landscape.py --json` as a coordinator view.
- **Latency** — assessment is sequential per session; fine for a 30-min cadence, would need batching/parallelism for near-real-time.
