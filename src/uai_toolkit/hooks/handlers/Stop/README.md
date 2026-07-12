# Stop Handlers

Fired when the AI finishes responding. Can **block** (exit 2) to force a retry turn, or allow (exit 0).

┌──────────────────────────────────────────┬──────────┬──────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Handler**                              │ **Type** │ **Purpose**                                                                                  │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `00_dump_stdin_async.py`                 │ async    │ **Temporary debug** — dumps raw hook stdin JSON for platform inspection. Remove after use.   │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `01_deliver_postresponse_sync.py`        │ sync     │ Delivers postResponse queued prompts via send_prompt. Respects conversation locks.           │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `02_block_permission_seeking_sync.py`    │ sync     │ **Blocks** responses ending with permission-seeking phrases ("Want me to...", "Should I...", │
│                                          │          │ etc.). Returns handler name and matched phrase. Instructs AI to self-assess whether it has   │
│                                          │          │ authority, plan, and information to act.                                                     │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `03_quality_gate_sync.py`                │ sync     │ Evaluates response against a quality checklist (request mismatch, intent without action,     │
│                                          │          │ claims without evidence). **Observe mode only** — logs findings but never blocks. Uses LLLM  │
│                                          │          │ as evaluator backend if running.                                                             │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `04_store_session_data_async.py`         │ async    │ Captures session telemetry: context%, tokens, cache usage, working dir, per-role message     │
│                                          │          │ counts (u/r/t/h/a), JSONL file size, turns, unread prompts/messages, rate limits, last       │
│                                          │          │ activity. **Also:** offload archive metrics                                                  │
│                                          │          │ (`archive.file_size_bytes`/`blocks`/`orig_bytes`), backfills the `metrics.snapshot` token    │
│                                          │          │ baseline on first Stop, and computes the stop/resume savings estimate (`metrics.resume` —    │
│                                          │          │ sheddable tokens + payback-tiered indicator) via `common/lib_offload_metrics.py` . Writes to │
│                                          │          │ session state file and platform state file.                                                  │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `05_intent_without_action_async.py`      │ async    │ Detects a response that states intent to act but stops without acting, then EVALUATES (does  │
│                                          │          │ not block — it is async/fire-and-forget). A regex pre-filter (config intent_patterns, minus  │
│                                          │          │ action_evidence) gates candidates to the evaluator (LLLM) which decides act-now vs wait,     │
│                                          │          │ few-shot-calibrated by positive/negative examples in intent_without_action.config.yml. Logs  │
│                                          │          │ every candidate as JSONL {ts,result,reason,message} to                                       │
│                                          │          │ logs/hooks/intent_without_action.jsonl. EVALUATION MODE: push_back:false = log only; flip to │
│                                          │          │ true to deliver an async self-prompt nudge (never a block). `--selftest` grades the regex    │
│                                          │          │ against the examples. One config, two consumers.                                             │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `06_todo_audit_sync.py`                  │ sync     │ Todo enforcement (todo_0333), phased by **mode** (`todo_audit.config.json`, default          │
│                                          │          │ **observe**; per-session override `todo_audit.mode` in session state). Always logs per turn  │
│                                          │          │ to `data/work/todo_audit.jsonl` : whether file-mutating work happened (deterministic, via    │
│                                          │          │ `file_access_tracker` Edit/Write scoped to the turn), whether a todo was referenced          │
│                                          │          │ (`todo_NNNN`), the verdict, the mode, and the last assistant message. **observe** = log      │
│                                          │          │ only; **warn** = + non-blocking systemMessage nudge on work-without-todo; **block** = stop   │
│                                          │          │ the turn on work-without-todo (exit 2). Sync so the block is honored; loop-protected via     │
│                                          │          │ `stop_hook_active` ; fails open on its own errors. Flip the mode to advance the ramp — no    │
│                                          │          │ code change.                                                                                 │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `07_remind_owed_replies_sync.py`         │ sync     │ Checks pending_replies directory for reply obligations. If this session owes replies,        │
│                                          │          │ injects a systemMessage reminder with message IDs and senders.                               │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `08_auto_self_compact_sync.py`           │ sync     │ Triggers `/self-compact` when context usage ≥ threshold (`compact.auto_self_pct`, default    │
│                                          │          │ 89%); warns approaching it. Issues a one-time auth token; sets `compact.self_triggered` to   │
│                                          │          │ fire once per cycle. Never blocks.                                                           │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `09_decrement_prompt_block_sync.py`      │ sync     │ Counts down a `--turns N` prompt block by one per **completed** turn (numbered 09 so it runs │
│                                          │          │ after the blocking handlers — a blocked/retried turn short-circuits before reaching it, so   │
│                                          │          │ only real completed turns count). Auto-lifts and releases held prompts at 0. No-op           │
│                                          │          │ otherwise. See `scripts/messages/prompt_blocks.py` .                                         │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `11_turn_digest_async.py`                │ async    │ Writes a per-turn DIGEST of the just-closed turn (`turn_digest.py --turns last`) into        │
│                                          │          │ `<uuid>/int##_br##.yml` — the turn-grained searchable library. **CANARY**: gated by          │
│                                          │          │ `turn_digest_allowlist.yml` (fail-CLOSED — only listed tracking_ids run; `*` = all). Endpoint│
│                                          │          │ chain `llm,claude,extractive` (local LLM → cheap headless Claude → deterministic floor).     │
│                                          │          │ #11 so it runs before `99_offload` pages tool content out. Idempotent, best-effort.          │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────┤
│ `99_offload_tool_results_sync.py`        │ sync     │ **Always last.** If reached (no earlier sync handler blocked the Stop ⇒ turn truly ended)    │
│                                          │          │ and opt-in `offload.on_stop` is set, launches `scripts/jsonl/offload_tool_results.py`        │
│                                          │          │ **detached** to page aged tool content out of the transcript for a leaner next `--resume` .  │
│                                          │          │ Non-blocking (exit 0); throttled by `offload.on_stop_min_growth` (default 8192B); no         │
│                                          │          │ coupling to other handlers.                                                                  │
└──────────────────────────────────────────┴──────────┴──────────────────────────────────────────────────────────────────────────────────────────────┘
