---
name: feedback_brief_note_session_work
description: When creating a handoff/self-compact brief, enumerate the concrete work
  done this session (features/fixes + commits/versions + todos touched)
status: active
---

When I create a handoff / self-compact brief, explicitly enumerate the concrete things worked during the session: each feature/fix, its commit(s)/deployed version, and which todos it touched (and whether fully or partially addressed).

**Why:** PianoMan wants session accomplishments traceable in the brief, not lost to compaction. A post-compaction me (or a reviewer) should see exactly what shipped and which tracked work advanced.

**How to apply:** Before running /compact, list session work grouped by project; cross-reference the todo tracker (`workflow_todo_list`) for matching todos and note partial vs full coverage; put that list in the brief. Related: [[feedback_commit_early_often]], [[feedback_close_review_loop]].
