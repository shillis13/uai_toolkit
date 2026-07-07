# Instruction: TODO System

**Version:** 2.0.1
**Last Updated:** 2026-07-03
**Maintainer:** PianoMan
**Status:** active
**Load Priority:** topic

## Purpose

The procedure for putting work under a todo. This is the *how*; the *why* is the
principle in `perspective/instr_work_awareness` — **all meaningful work is captured
as a todo.** A todo is the unit of work; doing work means doing it under a todo.

> **Supersedes v1.0**, which framed todos as out-of-scope backlog capture ("work
> within your current scope — just do it"). That is no longer correct: your current
> work belongs under a todo too. The whole work-tracking system — cross-session
> landscape, attribution, coordination — depends on it.

## The principle (short form)

- **Planned / assigned work links to a todo BEFORE it starts.** Find the todo it
  belongs to (your assignment, an existing one it fits, or a new one you create),
  make it your current work item, *then* begin. The linkage is up front, not
  reconstructed later — which also makes tool-use attribution exact from the first
  action.
- **Emergent / ad-hoc work is captured as it surfaces** — but must not block the
  flow. Create the todo as it comes up, or name it in your summary for reconciliation.

## Where todos live

`ai_general/work/todos/todo_NNNN_slug/` — one directory per todo. Parent/child
grouping is **physical directory nesting** (a child todo's directory lives inside
its parent's directory); that nesting is the single source of truth for hierarchy.

## How to create and manage

Use **`todos-mgr`** (registry: `ai_general/scripts/mgrs/todos-mgr`) or the
**`workflow_todo_*` MCP tools** (`workflow_todo_create`, `workflow_todo_set_status`,
`workflow_todo_get`, `workflow_todo_list`, `workflow_todo_find`). The manager handles
numbering, directory creation, and provenance — never hand-`mkdir` a todo directory.

```bash
todos-mgr create "verb noun summary" --project <scope>
todos-mgr create-light "quick capture"      # lightweight floor (see below)
todos-mgr assign <ref> uai://session/<tracking_id>   # assign a session, team, or project (all assignee URIs)
todos-mgr kanban                            # what's on your plate
todos-mgr view <ref>                        # ref = IP1 / 0045 / todo_0045_* / substring
todos-mgr status <ref> <status>             # e.g. todos-mgr status IP1 reviewing
todos-mgr complete <ref>                    # mark Done + archive
```

## Assignees (sessions, teams, projects)

A todo is associated with whatever works it via **`assigned.yml`** — a list of
`uai://…` URIs, set with `todos-mgr assign`. There is **one** association
representation (the `owner` field is retired), and an **assignee can be any entity
type**:

- **Session** — `uai://session/<tracking_id>` (an individual worker).
- **Team** — `uai://team/<id>` (a group of workers).
- **Project** — `uai://project/<id>` (the project the work belongs to).

**Project and Team are assignee *types*, not a separate relationship.** Associating a
todo with a project = assigning the project's URI, exactly like assigning a session or
team — multiple assignees of mixed types are fine (e.g. a session *and* a project).

> **Supersedes the older model** where `project` was an independent scope field in
> `origin.yml`, separate from assignment. Project membership is now expressed through
> assignment. (`origin.yml` still records provenance — `created_by`, `created_at`,
> `source`.)

## Status lifecycle

```
Triaging (TR) → Needs_Research (NR) / Needs_Derivation (ND) → Ready (RD)
   → In_Progress (IP) → Reviewing (RV) → Accepting (AC) → Done (DN)
   (Blocked (BL) at any point; Cancelled (CN) to abandon)
```

Fresh captures default to **Triaging**. Every status transition appends to
**`history.log`** — the provenance record. Use `--note` on a transition to record why.

## Lightweight floor

A todo needs very little to exist: a **summary**, a **status**, and **`origin.yml`**.
No `notes.md` is required. Capture cheaply; enrich only if the work warrants it.
Don't let ceremony block capture.

## Completion rigor

A transition toward **Done** requires a real completion check — a verification
artifact stating what was done, evidence it works (tests / output / walkthrough),
and how to verify. **Do not mark work done on a dry-run or assumption.**

## Quick agent loop

1. About to do planned/assigned work? **Find or create its todo first**, set it
   In_Progress, make it your current item.
2. Work surfaced mid-flow? Capture it (`create-light`) without derailing, or note it
   in your summary for reconciliation.
3. On a status change, let `history.log` record it (the manager does this) — add a
   `--note` for context.
4. Toward Done → run the completion check; only then `complete`.
