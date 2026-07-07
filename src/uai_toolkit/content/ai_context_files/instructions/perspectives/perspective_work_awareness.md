# Principle: All Work Is Captured As a Todo

**Version:** 1.1
**Purpose:** A standing principle for every working session — *all meaningful work is represented by a todo.* This is the primary ingestion path for the work tracking system (todo_0307): work gets tracked because it is **done as a todo**, not filed separately afterward. (This is a principle, not a special mechanism — the filename is incidental.)

## The principle

All meaningful work should be captured as a todo. A todo is the unit of work; doing work means doing it under a todo.

## Timing — planned/assigned work links BEFORE it starts

**Planned or assigned work cannot start until it is linked to a todo.** When you take on a deliberate, scoped, or assigned piece of work:

1. Determine which todo it is — work you're already assigned, an existing todo it fits under, or a new todo you create.
2. Make that your **current work item** *before you begin*.
3. Then do the work.

The linkage is up front, **not** reconstructed after the fact. You're planning/assigning the work anyway, so finding or creating its todo is cheap at that moment — and the work is tracked from its very first action (which also makes tool-use attribution exact from the start).

## Emergent / ad-hoc work — capture as it surfaces, don't gate the flow

Not all work is pre-planned. Work that arises mid-flow (a fix you notice, a small thing that comes up in conversation) should still be captured — but **must not block the flow**. Capture it as a todo as it surfaces, or name it in your summary and let it be reconciled. The up-front gate is for *planned/assigned* work; emergent work is captured opportunistically so the conversation isn't slowed.

## Ownership and grouping

- **One owner per todo** (optional). `owner` = who executes; `project` = what scope it belongs to. They are independent — an unowned todo can still have a project.
- Multiple owners on one piece of work → **decompose into child todos** (physical directory nesting is the single source of truth).

## Recording

- Use `todos-mgr` (registry `ai_general/scripts/mgrs/todos-mgr`) or the `workflow_todo_*` MCP tools.
- Set `owner`/`project` when known. Fresh captures default to `Triaging`.
- Every status transition appends to `history.log` (the provenance record).

## Completion rigor

A transition toward done **requires a real completion check** — a verification artifact stating what was done, evidence it works (tests/output/walkthrough), and how to verify. Do not mark work done on a dry-run or assumption.
