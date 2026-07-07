# Entity Model

**Status:** Active
**Updated:** 2026-06-04
**Author:** Wayfinder + PianoMan

---

## What Makes an Entity

An entity has:

1. **A need to be unique** — must be distinguishable from all other instances
2. **Conceptually continues to exist beyond lifecycle** — archived, stopped, or completed entities are still referenced
3. **Has state that needs to be maintained, persisted, tracked, and reasoned about**

Additional sufficient (but not required) conditions:

4. **Takes action** — if it acts, it's an entity
5. **Can be communicated with** — if it can be the target of comms and respond, it's an entity

---

## Entities

┌────────────┬────────────┬──────────────┬──────────────┬─────────────┬─────────────┬─────────────────────────────────────────────────────────────────┐
│ **Entity** │ **Unique** │ **Persists** │ **Stateful** │ **Takes**   │ **Comms**   │ **Notes**                                                       │
│            │            │              │              │ **action**  │ **target**  │                                                                 │
├────────────┼────────────┼──────────────┼──────────────┼─────────────┼─────────────┼─────────────────────────────────────────────────────────────────┤
│ Session    │ Yes        │ Yes          │ Yes          │ Yes         │ Yes         │ Primary actor. Identity in session_store (SQLite).              │
├────────────┼────────────┼──────────────┼──────────────┼─────────────┼─────────────┼─────────────────────────────────────────────────────────────────┤
│ Project    │ Yes        │ Yes          │ Yes          │ No          │ Yes (via    │ Unified entity — IS a team. Roles, sessions, optional           │
│            │            │              │              │             │ roles)      │ sub-teams.                                                      │
├────────────┼────────────┼──────────────┼──────────────┼─────────────┼─────────────┼─────────────────────────────────────────────────────────────────┤
│ Game       │ Yes        │ Yes          │ Yes          │ Yes         │ Yes         │ Extends Project. Game engine, board state, turns.               │
├────────────┼────────────┼──────────────┼──────────────┼─────────────┼─────────────┼─────────────────────────────────────────────────────────────────┤
│ Terminal   │ Yes        │ TBD          │ Yes          │ Maybe       │ Maybe       │ Addressable infrastructure. Entity status TBD — depends on      │
│            │            │              │              │             │             │ whether Terminals gain comms.                                   │
└────────────┴────────────┴──────────────┴──────────────┴─────────────┴─────────────┴─────────────────────────────────────────────────────────────────┘

### Session
- **ID:** Tracking ID (`YYYYMMDD_HHMMSS_uuid8_platform`)
- **URI:** `uai://session/<tracking_id>`
- **Storage:** `session_store.py` (SQLite), per-session state JSON, transcript JSONL
- **Lifecycle:** Created → Running → Stopped → Archived

### Project
- **ID:** uuid8
- **URI:** `uai://project/<id>`
- **Storage:** `project.proj.yml` (YAML on disk)
- **Lifecycle:** Sandbox → Registered → Active → Paused → Complete → Archived
- **Notes:** A Project IS a team. Roles and session assignments live directly on the project. Sub-teams are optional groupings. A project with just roles and no board/devtree/docs is effectively "just a team."

### Game
- **ID:** uuid8 (extends Project)
- **URI:** `uai://game/<id>` (TBD)
- **Storage:** Extends project with game-specific state
- **Notes:** Runtime instance of a project with game engine, board state, players, turns. Not yet designed in detail.

### Terminal
- **ID:** TBD
- **URI:** TBD
- **Storage:** TBD
- **Notes:** Infrastructure entity. Exists in the UAI app for "everything under one roof." Entity status depends on whether Terminals gain comms capability.

---

## Non-Entities

┌──────────────┬──────────────────────────────────────────────────────────────────────────────────────────┐
│ **Thing**    │ **Why not an entity**                                                                    │
├──────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤
│ Todo         │ No unique identity requirement. Filesystem artifact with naming convention. Done = done. │
├──────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤
│ Task         │ Structured work package. Tracked work, not persistent identity.                          │
├──────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤
│ Brief        │ Derived from session, immutable after condensation. No own identity.                     │
├──────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤
│ Folder       │ App-only presentation artifact. Organizes views, not relationships.                      │
├──────────────┼──────────────────────────────────────────────────────────────────────────────────────────┤
│ Context File │ Loaded into sessions, not independently addressable.                                     │
└──────────────┴──────────────────────────────────────────────────────────────────────────────────────────┘

---

## Work Artifacts (Non-Entities)

Work artifacts live under `ai_general/work/`:

```
ai_general/work/
  todos/          # Requirements, ideas, bugs. Lightweight backlog items.
  tasks/          # Work packages with implementation plans. Assigned to sessions/projects.
  projects/       # Project entities with roles, boards, lifecycle.
```

### Todo
- **Location:** `ai_general/work/todos/todo_NNNN_description/`
- **Metadata:** `.status`, `.tag`, `.flag` marker files, `notes.md`, `assigned.yml`
- **Not an entity:** No UUID, no URI, no persistence beyond completion

### Task
- **Location:** `ai_general/work/tasks/task_NNNN_description/`
- **Metadata:** `task.yml` (title, linked todos), `plan.md` (implementation plan), `.status`/`.tag`/`.flag` markers, `assigned.yml`
- **Not an entity:** Tracked work, not persistent identity. Once done, it's historical record.
- **Relationship to Todos:** Many-to-many. A Task can address multiple Todos. A Todo can spawn multiple Tasks.

---

## Relationship Summary

```
Session ──fills role──> Project
Session ──assigned to──> Task (via assigned.yml)
Project ──has──> Roles ──filled by──> Sessions
Project ──has──> Sub-teams ──have──> Roles
Task ──addresses──> Todo(s) (via task.yml linked todos)
Todo ──assigned to──> Project/Session (via assigned.yml)
Game ──extends──> Project
```

---

## URI Patterns

```
uai://session/<tracking_id>
uai://project/<id>
uai://project/<id>/<role>
uai://project/<id>/message
uai://project/<id>/prompt
uai://project/<id>/<role>/message
uai://project/<id>/<role>/prompt
uai://project/<id>/<team>/<role>/message
uai://project/<id>/<team>/<role>/prompt
uai://project/<id>/board
```

URI disambiguation is context-driven: the verb (message, prompt, read) determines whether a path segment is a role, team, or file.
