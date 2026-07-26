---
name: reference_sessionstore_list_filters_are_substring
description: 'SessionStore.list(filters={field: val}) is SUBSTRING match (UI search),
  not exact — routing code must post-filter to exact equality'
status: active
---

`SessionStore.list(filters={"display_name": x})` (and other field filters) does **substring** matching, because it backs UI search/listing. It is NOT exact like `store.resolve()`.

Consequence for op-routing: a fallback that resolves a session by feeding a name into `store.list(filters=...)` will let a short prefix reach the wrong record — e.g. `"Noct"` matches `"Noctis"`, routing an op (get-status, write-to, kill) to a session the caller didn't name.

**How to apply:** any code that uses `store.list` field filters to RESOLVE/ROUTE (not just display) must post-filter results back to exact equality: `[m for m in matches if m.get(field) == ident]`. `store.resolve()` (tracking_id/terminal_session/cli_uuid) is already exact — use it first; only the display-name fallback needs the guard.

Found by Codex/Git-Guardian review of todo_0278 (commit 7369db4e0) — the fix + regression `test_display_name_fallback_does_not_substring_match` live in `scripts/session_mgmt/tests/test_name_collision.py`. The resolver is `session_ops._resolve_session`. Related: [[feedback_verify_with_real_execution]], [[feedback_no_manufactured_rereview]].
