# PreCompact Handlers

Fired before context compaction begins.

┌──────────────────────────┬──────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Handler**              │ **Type** │ **Purpose**                                                                                                        │
├──────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `01_compaction_sync.py`  │ sync     │ Logs the compaction event to session dir (`compaction_events.jsonl`), central audit log, and sends a user          │
│                          │          │ notification. Infers hook type (PreCompact/PostCompact) from parent directory name.                                │
├──────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `02_auto_brief_async.py` │ async    │ Sets `compact.start` in session state, snapshots pre-compaction metrics (ctx%, tokens, turns, msgs), clears        │
│                          │          │ `compact.brief_file` , then launches `auto_brief.py` to create a session brief via an idle condenser. Sends user   │
│                          │          │ notification on failure.                                                                                           │
└──────────────────────────┴──────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
