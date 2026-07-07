# Unified Worker Page + Session Work subtabs (Worker Mgr retirement)

**Owner:** Mullion · **Status:** design (confirmed direction, awaiting build go) · **Created:** 2026-06-30
**Spec authority:** PianoMan (2026-06-30 design discussion).

## The insight
A **Worker** is a Project, a Team, or a **Session**. The aspect-based page that the
Projects/Teams tabs already use (`ProjectEditor`: Navigator | Detail | Right-panel,
aspects Overview / Work / Team / Comms) IS the worker page. It just needs to adapt
its aspects to the worker. PianoMan: *"the Work section of a session Tab should look
more like Project/Team pages"* (NOT like Work Mgr).

So there is ONE worker page; Projects/Teams already have it; **Sessions are the gap.**

## Decisions
1. **Generalize `ProjectEditor` → a worker-scoped page.** It already handles project
   AND team (`isTeam` flag); extend it to accept a `worker` of type project | team |
   session. Per-worker-type adapters supply: id, display name, the **todo filter**,
   the **comms participant set**, and the **Overview fields**.
   - Work List filter: project → `project == X` (or assigned `uai://project/X`); team
     → union of member sessions; session → assigned `uai://session/<tracking_id>`.
   - Comms participants: project/team → roster tracking_ids; session → itself.
2. **Session aspects = Overview · Work · Comms.** Drop the **Team** aspect for a solo
   session (a session isn't a team). (Optional later: a "Peers" aspect = other
   sessions in the same project.)
   - Session Overview = session metadata (platform, status, roles, tracking_id,
     working_dir, last activity) — analogous to the project Overview block.
3. **Session entity gets `Chat | Work` subtabs.** Opening a session = a tab with a
   subtab switcher: **Chat** = the live terminal / transcript (current behavior);
   **Work** = the worker page scoped to this session. Lives in `SessionContent`
   (TabContentPane).
4. **The three "worker→work" items move to the WORK item (Work Mgr todo detail),** not
   the worker — they're context a *work item* accumulates (PianoMan):
   - Decisions & Pivots · Open Questions & Recommendations → a todo **"Activity"** area
     (structured entries appended to the todo dir, like `history.log` for status).
   - Chat-comments / Turn-Links → links from a todo to transcript turns / conversation
     message ids (now that conversations are real, these ids exist to link to).
   - NOTE: these were placeholders on the Worker view (no backing data yet) — this is
     new data-model work, not a UI move.
5. **Retire Worker Mgr.** Once 1–3 land, each worker type has its own page and the
   aggregator is redundant. Its only unique offering (cross-worker fleet load) is
   data-starved (~1/380 todos assigned). Remove the pane + routing; keep the
   `worker_mgr` viewport id reserved in case a thin fleet-load widget is wanted later.

## Build order (value-first)
1. **Session Chat | Work subtabs** — the keystone; what actually obsoletes Worker Mgr.
   Reuses the (generalized) worker page scoped to the session.
2. **Generalize ProjectEditor** to the worker descriptor (the refactor #1 depends on).
3. **Todo Activity area** in Work Mgr (design the data model first; Chat/Turn-Links is
   the most concrete now).
4. **Retire Worker Mgr.**

## Open (small) — non-blocking, building around defaults
- Generalize ProjectEditor in place vs. a thin `WorkerPage` wrapper? Default: generalize
  in place (project+team already share it).
- Solo-session "Peers" aspect — deferred unless PianoMan wants it.
