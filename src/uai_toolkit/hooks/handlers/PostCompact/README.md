# PostCompact Handlers

Fired after context compaction completes.

| Handler | Type | Purpose |
|---|---|---|
| `01_compaction_sync.py` | sync | Symlink to `../PreCompact/01_compaction_sync.py`. Same handler — logs the PostCompact event and notifies. Infers event type from parent directory. |
| `02_auto_brief_postcompact_sync.py` | sync | Sets `compact.end` in session state. If `compact.brief_file` is set (auto-brief already finished), loads the brief into the session via `load_brief_into.py`. If brief is still pending, does nothing — `auto_brief.py` handles the load when it completes. |
