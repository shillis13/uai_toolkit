---
name: feedback_reference_todos_by_id
description: Reference todos by persistent todo_# (e.g. todo_0315), never the transient
  TR# handle
status: active
---

Always reference todo items by their **persistent `todo_#`** id (e.g. `todo_0315_offloader_should_be_compaction_aware`), NOT by the `TR#` handle the todo tools display.

**Why:** `TR#` is **transient/positional** — the "TR" reflects status (Triaging) and the number is just a position in the current list. It renumbers whenever a todo changes state, or the list is filtered/sorted. Example: deleting `todo_0171` (then `TR13`) made `TR75` become `TR74`. So a `TR#` written down today points at a different todo tomorrow.

**How to apply:** When creating, citing, or recording a todo (in chat, memories, commit messages, design docs, briefs), use the `todo_####_slug` id returned by `workflow_todo_create` as `todo.id`. Treat `ref`/`TR#` as a throwaway display label only. If a prior note used `TR#`, resolve it to its `todo_#` before relying on it.
