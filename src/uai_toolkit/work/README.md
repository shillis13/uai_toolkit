# scripts/work

Work/session-analysis tooling for the coordinator (Hamilton). All read-only.
Architecture, data contracts, and rationale: see **`DESIGN.md`** in this directory.

## Scripts

| Script | What it does |
|---|---|
| `work_landscape.py` | Cross-session work view — joins `sess-mgr` + `todos-mgr` into one "who is doing what / what's stale / what's unassigned" table. The structural skeleton. |
| `work_assess_sessions.py` | LLLM interpretive layer — reads transcripts, infers per-session `{state, project_guess, open_question, needs_pianoman}` → `data/work/assessments.json`. Built to run scheduled. |
| `work_summarize_sessions.py` | Standalone — free-text per-session summaries appended to `{session_dir}/{id}_lllmSummary.log`. Related but separate from the landscape join. |

## Common usage

```bash
# Structural landscape (fast, no LLLM dependency)
work_landscape.py                 # active sessions × assigned todos + gaps
work_landscape.py --all           # include stopped sessions
work_landscape.py --owners-only   # only sessions that own a todo
work_landscape.py --json          # raw model (for the UAI cockpit)

# Add the LLLM interpretive layer (states + NEEDS PIANOMAN)
work_assess_sessions.py                 # assess fresh active sessions → data/work/assessments.json
work_assess_sessions.py --session NAME  # assess one (ignores freshness gate)
work_assess_sessions.py --stdout        # print, don't write
work_landscape.py --enrich              # render landscape joined with assessments

# Free-text per-session summaries
work_summarize_sessions.py              # all running, last 3 JSONL turns
work_summarize_sessions.py --jsonl 5    # last 5 turns
```

## Scheduling

`data/scheduled_tasks/work.yml` defines a 30-min `assess_sessions` job, **disabled by
default** (enabling keeps a local model warm ~continuously — a GPU/RAM commitment):

```bash
sched-task-mgr enable work && sched-task-mgr install
```

## Dependencies

- `scripts/mgrs/sess-mgr`, `scripts/mgrs/todos-mgr` — data sources (`--json`).
- `scripts/lllm/lllm_prompt.py` — the local-LLM interface (its venv has `httpx`).
- `scripts/session_mgmt`, `scripts/jsonl` — used by `work_summarize_sessions.py`.
- `data/work/assessments.json` — written by the assessor, read by the landscape.
