---
name: feedback_todo_trailer_and_status_notes
description: 'Every commit needs a Todo: trailer in the body; every status change
  needs a note'
status: active
---

A todo moved to a new status (esp. → Reviewing/Done) with no comment AND no linked changed files reads as unjustified — PianoMan flagged todo_0540 for exactly this. Two fixes, both required:

1. **Put `Todo: todo_XXXX` in the commit BODY yourself.** Passing `--todo` to Git Guardian did NOT produce a `Todo:` trailer on my commits (checked: d15ff9f5e, 931257efd, 6ad8f94cf all missing it). Without the trailer the UAI Files/git view can't link a todo to its changed files, so the todo looks empty even though work shipped. Don't trust the flag — write the trailer line.

2. **Leave a real note on every status change** — what shipped + the commit hash + files. An empty status transition is unreadable.

**Why:** the todo is the unit PianoMan reviews; if the work isn't visible FROM the todo (files + a comment), it looks like status was changed for nothing.

**How to apply:** commit body includes `Todo: todo_XXXX`; and `todos-mgr comment <id>` (or the set-status note) states what was done + commit + files before/at the status change. Relates to [[feedback_brief_note_session_work]] and [[feedback_explain_root_cause]].
