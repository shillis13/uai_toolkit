# SessionStart Handlers

Fired when a session starts or resumes.

┌────────────────────────────────────────┬──────────┬────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Handler**                            │ **Type** │ **Purpose**                                                                                    │
├────────────────────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `01_inject_standing_messages_sync.py`  │ sync     │ Queries standing messages (global, platform, team, project) and injects them as                │
│                                        │          │ additionalContext so the AI sees them without asking                                           │
├────────────────────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `02_stage_session_context_sync.py`     │ sync     │ Consumes the `context_to_load/` inbox (skips on clear/compact); resolves staged references via │
│                                        │          │ the loader and injects them.                                                                   │
├────────────────────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `03_snapshot_offload_metrics_async.py` │ async    │ Snapshots the offload-metrics baseline (`metrics.snapshot`): lean resumed jsonl size +         │
│                                        │          │ cumulative archive size/blocks. Token baseline marked pending — first Stop backfills it        │
│                                        │          │ (resumed token count isn't knowable at start). Fires on every source. Feeds the stop/resume    │
│                                        │          │ savings estimate (`common/lib_offload_metrics.py`).                                            │
└────────────────────────────────────────┴──────────┴────────────────────────────────────────────────────────────────────────────────────────────────┘