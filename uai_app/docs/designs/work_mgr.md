# Work Mgr — design & build plan

**Owner:** Mullion · **Status:** building (IPC foundation first) · **Created:** 2026-06-26
**Spec authority:** PianoMan (13-point spec, 2026-06-26). When his guidance is specific, follow exactly.

## DECISION — Git View (detail Files, external changes) — DEFERRED (2026-06-29)
The Files section's second part ("changes to files outside the todo dir") needs a way
to attribute git changes to a todo. The three candidate models — (a) per-todo commit
range/branch, (b) todo-owned path list, (c) time window since In-Progress — all fail
because **there is no commit→todo attribution today** (Git Guardian commits centrally;
commits don't say which todo/session). PianoMan's call: defer the Git View until
**commits carry their todo_id**. Enabler (Git Guardian's lane, not Work Mgr): the GG
commit request takes an optional `todo_id`, stamped into the commit as a trailer
(`Todo: todo_0320_...`). Then the Work Mgr Git View = `git log --grep "Todo: <id>"`
(or git-notes) → that todo's commits + diffs, accurately. Build the UI side once the
trailer exists. Until then the Files section shows Artifacts only (a placeholder stub
hints at the planned Git View).

## Terms
- **Work item / todo** — a directory under `ai_general/work/todos/`. Used interchangeably; "work" is the UI vocabulary, "todo" is the on-disk/engine vocabulary.
- **Engine** — `~/bin/all_languages/python/src/todo_mgr/todo_mgr.py`, the authoritative reader+writer. Needs `PYTHONPATH=~/bin/all_languages/python/src` and `TODO_ROOT=<todos dir>`.
- **Ref** — kanban handle (e.g. `TR1`, `IP3`); transient, renumbers. NEVER used as an id.
- **id** — `todo_####_slug` directory name; stable identifier.

## Key architecture decision
The current `uai:todos:list` IPC is a **hand-rolled flat TS scan** that only reads `*.status/*.tag/*.flag` markers — it ignores nesting, `assigned.yml`, `origin.yml`, `history.log`. **Replace it** with `todo_mgr.py json` (now crash-free; was a datetime-serialization bug, fixed 2026-06-26). The engine's serializer is the single source of truth — no TS reimplementation to drift. Aligns with DESIGN principle #1 (External Ground Truth) and #2 (Component API Layer).

### On-disk model (verified)
A todo dir contains:
- `<Status>.status` — empty marker (e.g. `In_Progress.status`). Exactly one.
- `<tag>.tag`, `<flag>.flag` — empty markers.
- `notes.md` — structured `##` sections (Description, What Success Looks Like, Approach, Why It Matters, Requirements, Dependencies, Notes). **These sections are the "fields."**
- `assigned.yml` — list of `uai://<type>/<id>` URIs. **This is `assigned_to`.**
- `origin.yml` — `created_by, created_at, source, owner, project`.
- `history.log` — pipe-delimited `ts | status | session | note` lines.
- `data/` — arbitrary attached files.
- **Children = subdirectories** that are themselves todos. Parent is DERIVED from nesting (not an editable field).

### `todo_mgr.py json` item contract (verified)
`id, ref, path, rel_path, status, tags[], flags[], assigned[], owner, project, parent, children[], title, summary, created, updated, origin, created_by, source`

## 13 points -> concrete changes

| # | Ask | Change |
|---|-----|--------|
| 1 | Too many pills; tags shouldn't be pills (too dynamic) | Filter pills only for STABLE axes: **status, project, assigned_to**. Tags render **inline** on the row/detail, not as filter pills. |
| 2 | todo identifiers printed & used as ids | Surface `id` (todo_####); show the `####` prominently on each row + detail; key all selection/IPC by `id`, never `ref`. |
| 3 | Tree + flat view (currently flat only); status indicators on nodes | View toggle (Tree \| Flat). Tree from `parent/children`; each node shows a status dot. |
| 4 | Parent-child invisible even in detail; expand/collapse; jump from detail & left panel | Tree expand/collapse. Detail shows Parent (clickable up) + Children (clickable down). Left rows with children get a disclosure caret. |
| 5 | "Open" button -> external app | `uai:todos:open` -> reveal todo dir / open `notes.md` in OS default (or configured editor). [UI target choice — see Open Questions] |
| 6 | notes.md contents as fields with data | Parse `##` sections -> labeled editable fields. Save writes back to `notes.md`. |
| 7 | `<id>/data/` as attached files | List `data/` dir; each file = attachment chip with open/reveal. |
| 8 | `origin.yml` + `history.log` as merged data | Combined "Provenance & History" panel: origin fields + chronological history.log entries, one timeline. |
| 9 | enforce todo_#### uniqueness | Create via engine `create` (allocates next unique id). Surface `validate` warnings (dupes) in UI. |
| 10 | move into new parent / set parent-less | Row/detail action -> engine `move <target|root> <id>`. (Drag-to-reparent later.) |
| 11 | all changes reflected on-disk | Every mutation goes through engine write verbs via new IPC — no optimistic-only state. Removes the current STUBBED local-only status cycle. |
| 12 | assigned_to defined? | YES — `assigned.yml` + engine `assign`/`unassign`/`assigned`. Already defined. |
| 13 | reflect assigned_to; group & filter by it | Show assignees on rows/detail; add assigned_to to group-by + filter-pill axes. |

## Build sequence
1. **IPC foundation** (this slice): rewrite `uai:todos:list` -> `todo_mgr.py json`; add verbs `status, move, assign, unassign, tag, create, open, data(list), provenance(origin+history), writeNotesSection`. Wire `preload.ts` + `global.d.ts`. All via `execFile python3 … --json` (mirrors `uai:tasks:list`), with `PYTHONPATH` + `TODO_ROOT` env.
2. **WorkMgrPane rebuild**: tree/flat toggle, id display, inline tags, real on-disk status cycle, assigned_to group/filter, parent-child nav.
3. **Detail rebuild**: notes-as-fields, data/ attachments, provenance+history timeline, Open button, move/reparent action.
4. Absorb `TodoManagerPane` shared viewer, then delete legacy panes (Task/Assigned) + their IPC.

## Open questions (non-blocking; building around them)
- **#5 Open target:** reveal-in-Finder of the todo dir, vs open `notes.md` in default editor, vs configured IDE? Default: reveal dir + secondary "edit notes" opening notes.md.
- **#6 notes editing:** structured per-section fields (parse `##`) vs one markdown editor with section affordances? Default: per-section fields, raw fallback for unrecognized content.
