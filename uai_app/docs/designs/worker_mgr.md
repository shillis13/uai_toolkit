# Worker Mgr — reshape design

**Owner:** Mullion · **Status:** design (awaiting build) · **Created:** 2026-06-27
**Spec authority:** PianoMan. Origin: housekeeping #4 ("Worker Mgr looks like a Session Folder — should be something different") + the architecture framing ("Worker Mgr answers *who is doing work and how loaded are they*").

## The problem (verified)
`WorkerMgrPane` renders its roster of Sessions through the **same `CardListView`** the Navigator and Folders use (`WorkerMgrPane.tsx:269`). So visually it *is* the session list with a different label — exactly the "Session Folder clone" smell. A Worker = Session | Project | Team, but the cards express **identity**, not **work**.

## The reshape — foreground work-load
The differentiator (and the thing a Folder can't do): show, per worker, **how much work they hold and its state** — answering "who's loaded, who's idle, who's blocked." This is now computable because todos carry `assigned` URIs:
- `uai://session/<tracking_id>` · `uai://project/<project_id>` · (team via its sessions)

### Work-load join (direction-independent, build first)
A `useWorkerLoad()` hook: load `window.uai.todos.list()`, bucket every todo by each `assigned` URI → per-worker:
- `total` active work-items (excluding Done/Cancelled), `byStatus` mix (in-progress / blocked / reviewing / …), `blocked` count, `lastActivity` (max todo.updated).
- A session worker's URI = `uai://session/<tracking_id>`; project = `uai://project/<project_id>`; team = union of its member sessions.

### Roster card (visual — confirm with PianoMan)
Each worker card foregrounds load instead of identity:
- name + type glyph (session/project/team) + platform tint (kept).
- **load bar / counts:** `N active` with a small status-mix strip (colored segments per status), `blocked` flagged red, `idle` (0 active) dimmed/flagged.
- last-activity recency.
- Grouped by worker-type (Sessions / Projects / Teams) — kept.
- Default sort: **most-loaded first**; idle workers sink. (Sort dropdown: Load / Name / Recent.)

### Filters — pills stay (they're fixed enums)
worker-type, platform, activity are all fixed-membership enums → pills are correct per `ux_standards.md`. No change. (Contrast Work Mgr, where project/assignee were changing sets → dropdowns.) Search stays.

### Detail — keep + enrich
`WorkerSessionDetail` / `WorkerProjectDetail` already exist (todo-centric). Keep; surface the same load summary at the top. Team detail still a later slice.

## Describable + drivable retrofit (same pattern as Work Mgr)
- `useViewport('worker_mgr')` (id already reserved in `TabContentPane` `APP_VIEWPORT_IDS`). `state`: filters, counts, totalWorkers, most-loaded, selected worker. `actions`: open a worker's detail; (mutations are few — Worker Mgr is mostly read/nav, so it's primarily *describable*; any future "assign work to worker" action maps to `todo.assign`).

## Build order
1. `useWorkerLoad()` hook + the per-worker load model (no visual risk).
2. Roster card reshape (load-forward) — the piece needing PianoMan's eye.
3. Viewport reporter (`worker_mgr`).
4. Detail load-summary header.

## Open question for PianoMan
- Card visual: a **status-mix strip + counts** (compact, scannable) vs a **single load number + sparkline** vs a **mini work-list preview** on the card? Default plan: status-mix strip + counts + idle/blocked flags. Overshoot-then-converge per your visual-tweak preference.
