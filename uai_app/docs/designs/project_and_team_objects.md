# Project and Team Object Design

**Date:** 2026-05-13 (revised)
**Author:** Solstice (20260512_074733_864e2908_cla)
**Reviewer:** Codex (20260508_081557_2ec0d3ea_cod)
**Status:** Draft v2 — post-review revision
**Review:** See `project_and_team_review.md` for Codex's full critique of v1.

## Principle

Both are ecosystem-level entities. The filesystem is the source of truth
for **identity and configuration**. SQLite is the source of truth for
**runtime state and relationships**. YAML files are declarative; they
seed initial state but do not hold live occupancy or hot assignment data.

---

## Authority model

Every piece of data has exactly one authoritative source:

| Data | Authority | Other sources |
|------|-----------|---------------|
| Project identity (name, goal, tags) | `project.yml` | — |
| Project git state (branch, dirty) | Git at index time | — |
| Project session membership | `session.project_dir` (implicit) | — |
| Explicit project/team assignment | `entity_relationships` SQLite | YAML `assigned`/`projects` fields are seed-only |
| Team identity (name, slots, comms) | `teams/{id}.yml` | — |
| Team slot occupancy | `entity_relationships` SQLite | — |
| Session comms group membership | `session_store` `groups` field | Updated as side-effect of slot claim |
| Standing messages | Protocol comms directories | Not in team YAML |

YAML `assigned`, `projects`, and `related` fields are **bootstrap hints**.
On first index, they seed `entity_relationships` rows. After that, the
relationship table is authoritative and the YAML fields are informational.

---

## Project

### What it is

A Project is a body of work with a working directory, associated sessions,
and optional metadata. It corresponds to a physical location on disk — either
a devTree or a directory under `ai_general/projects/`.

### Ground truth: filesystem + `project.yml`

```
~/Documents/AI/devTrees/AI_ROOT_uai-resurrection/   <- devTree project
    project.yml                                      <- metadata (optional)
    ai_general/
        ...

~/Documents/AI/ai_root/ai_general/projects/          <- non-devTree projects
    unified_ai_interface/
        project.yml                                   <- metadata (optional)
        ...
```

### `project.yml` schema

```yaml
# project.yml -- optional; all fields optional.
# Absence of project.yml is fine -- the indexer derives what it can from
# the directory and git state alone.
schema_version: 1

name: UAI Resurrection                # Display name. Default: directory name, title-cased.
goal: >-                              # One-line purpose. Shown in project cards.
  Rebuild the Unified AI Interface as a modern Electron/React monorepo
  with typed tabs, AI comms, and Memorex.
lifecycle_status: active              # active | paused | complete | archived
owner: PianoMan                       # Project steward
tags: [uai, electron, react]

# Bootstrap hints -- seed entity_relationships on first index.
# After first index, relationships table is authoritative.
assigned:
  teams: [uai-core]                   # Seeds team -> assigned_to -> project
related:
  briefs: [Continuity_III, Pixel_v]   # Seeds brief -> relates_to -> project
```

### What is NOT in project.yml

- **Session list** — derived from `session.project_dir` matching
- **Git branch/status** — derived at index time
- **Build/test/start commands** — belong in the project's own tooling
  (`package.json`, `Makefile`, `scripts/`) not in identity metadata
- **`assigned.sessions`** — sessions bind via `project_dir`, not YAML lists
- **File counts, test results** — derived by tooling on demand

### Derived fields (populated at index time)

| Field | Source |
|-------|--------|
| `id` | Stable: hash of normalized `working_dir` path, prefixed `devtree_` or `project_` |
| `working_dir` | Absolute path to the project root |
| `branch` | `git branch --show-current` |
| `git_status` | `git status --porcelain` -> clean / dirty / ahead / behind / unknown |
| `session_count` | Count of sessions whose `project_dir` matches |
| `source_path` | Path to `project.yml` if it exists |
| `availability` | available / unavailable / parse_error |
| `parse_error` | Error message if YAML failed to parse |
| `indexed_at` | Timestamp of last index |

**Note:** `lifecycle_status` and `git_status` are separate fields.
The existing contract's `status` field maps to `git_status` (clean/dirty/etc).
`lifecycle_status` is new and comes from `project.yml` only.

### Contract changes required

Before implementation, update `entities.ts` and `cards.ts`:
- Add `lifecycle_status: 'active' | 'paused' | 'complete' | 'archived' | null`
- Add `goal: string | null`
- Add `owner: string | null`
- Rename existing `status` to `git_status` (or keep `status` for git and add `lifecycle_status` alongside)
- Deprecate `assigned_ais: string[]` in favor of relationship-based assignment

### Session <-> Project binding

| Binding type | Authority | How |
|-------------|-----------|-----|
| Implicit membership | `session.project_dir` | Set at launch, immutable |
| Explicit assignment | `entity_relationships` | `session -> assigned_to -> project` |

`project.yml` does NOT list sessions. Session count is derived.

---

## Team

### What it is

A Team is a named group of AI participants working together with defined
roles, a communication plan, and optionally a project assignment. Teams are
the coordination primitive for multi-agent work.

### Ground truth: two stores

1. **Team definition** (declarative): `ai_general/data/teams/{id}.yml`
2. **Slot occupancy** (runtime): `entity_relationships` SQLite table

The YAML defines what the team needs. SQLite tracks who fills it.

### `{team_id}.yml` schema

```yaml
# Team definition -- declarative configuration only.
# team_id is the filename stem (e.g., "uai-core" from uai-core.yml).
# Runtime state (who fills slots) lives in entity_relationships, not here.
schema_version: 1

name: UAI Core Team
description: >-
  Primary development team for the UAI resurrection project.
status: active                        # active | disbanded | paused
owner: PianoMan
tags: [uai, development]
created_at: "2026-05-13T08:00:00-04:00"

# -- Slots ------------------------------------------------
# Slots define what the team needs. Each slot is a role with a cardinality.
# Slot IDs are semantic (role name). If count > 1, multiple sessions
# share the same slot definition.
# Who fills each slot is tracked in entity_relationships, not here.

slots:
  - role: lead
    description: Coordinates work, reviews output, manages task flow
    platform: claude_cli              # Preferred platform (or "any")
    profile_ref: profiles/dev_lead    # Reference to a guidance profile
    count: 1

  - role: worker
    description: Implementation, handles delegated tasks
    platform: any
    profile_ref: profiles/dev
    count: 2                          # Two worker slots

  - role: reviewer
    description: Code review and quality assessment
    platform: codex_cli
    profile_ref: profiles/reviewer
    count: 1

# -- Communication Plan ------------------------------------
# How team members communicate. Integrates with protocol_comms_v1.0.

comms:
  escalation_chain: [lead, user]

  feedback_mechanism: prompt          # none | message | prompt
  feedback_timeout: 300               # seconds before escalation

  notification_routing:
    blocked: [lead, user]
    error: [lead, user]
    completion: [lead]
    review_needed: [reviewer]

  # Board references -- structured per protocol_comms_v1.0
  boards:
    - type: comms
      scope: team
      id: uai-core                    # Board ID matching team ID

# -- Bootstrap hints ---------------------------------------
# Seed entity_relationships on first index. After that, relationships
# table is authoritative.
projects: [devtree_uai-resurrection]  # Seeds team -> assigned_to -> project
```

### Slot occupancy: SQLite, not YAML

Slot assignment is a runtime operation stored in `entity_relationships`:

```
session:20260512_074733_864e2908_cla  --member_of-->  team:uai-core
  metadata: { slot: "lead", claimed_at: "2026-05-13T08:30:00-04:00" }
```

**Why not YAML:**
- Multiple sessions may claim/release slots concurrently
- Sessions crash without cleanup; YAML has no atomic CAS
- Config edits (adding slots) shouldn't risk wiping live occupancy
- SQLite gives transactional updates for free

### Slot claim/release flow

**Claiming a slot:**
1. Check slot availability: count relationships with matching `{team_id, slot_role}` vs slot `count`
2. If available, atomically insert `entity_relationship`:
   - `source: session:{tracking_id}`, `target: team:{team_id}`
   - `relation_type: member_of`
   - `metadata: { slot: "{role}", claimed_at: "...", claimed_by: "..." }`
3. Update session's comms `groups[]` to include the team ID (enables broadcast routing)
4. Deliver team standing messages to the session via protocol_comms_v1.0 standing-message scope

**Releasing a slot:**
1. Delete the `entity_relationship` row
2. Remove team ID from session's comms `groups[]`
3. Slot becomes available for reassignment

**Crash recovery (reconciler):**
A periodic reconciler (or on-index check) compares slot occupancy
relationships against live session status:
- If a session in `filled_by` has `process_status: stopped` for > N minutes, mark as stale
- Stale entries are cleaned up (relationship deleted, slot freed)
- Escalation fires per the team's comms plan (`blocked` routing)

### Escalation resolution

`escalation_chain: [lead, user]` resolves as:
- **Role -> sessions:** query relationships for `member_of` with `slot: "lead"`
- **Empty slot:** skip to next in chain
- **Multi-filled slot:** deliver to all active sessions filling that role
- **Stopped session:** treat as unavailable, skip
- **`user`:** always resolves to user notification (not a session)

### Comms integration binding

The key gap Codex identified: team membership must enter the comms
protocol's actual routing system.

| Protocol primitive | Team binding |
|-------------------|-------------|
| **Session `groups[]`** | Updated when slot is claimed/released. This is what enables `group: {team_id}` targeted broadcast. |
| **Board discovery** | Team boards are registered per `comms.boards[]` in team YAML. Sessions discover boards via their `groups[]` membership. |
| **Standing messages** | Stored in protocol's scoped directories (NOT in team YAML). Team-scoped standing messages apply to sessions with matching group membership. |
| **Escalation** | Resolved at delivery time by querying slot occupancy from relationships table + session liveness. |
| **Prompt delivery** | Routed to individual sessions. Team comms plan determines urgency mapping. |
| **Conversation locks** | Per-session, unaffected by team membership. |

### What a team is NOT

- Not a container for cards (use groups/folders for that)
- Not a project (a team can work on multiple projects; a project can have multiple teams)
- Not a profile/role (those are per-session identity; teams coordinate across sessions)

### Contract changes required

Before implementation, update contracts:
- Add `TeamCard` to `cards.ts` with fields: name, description, status, slot_count, filled_count, project_ids, tags
- Add `TeamCard` to `AnyCard` union
- Update `Team` in `entities.ts` to use slot-based model (replace `profiles[]` + `role_assignments`)
- Add `'team'` to container type considerations if teams should participate in card hierarchy

---

## How they relate to each other

```
Project <--assigned_to---- Session ----member_of--> Team
   |                          |                       |
   |                          | project_dir            | entity_relationships
   |                          | (implicit)             | (slot occupancy)
   |                          |                        |
   +-- project.yml            +-- sessions.db          +-- teams/{id}.yml
       (identity)                 (state + rels)           (definition)
```

### Relationship types used

| Relationship | Authority | Meaning |
|-------------|-----------|---------|
| `session -> member_of -> team` | `entity_relationships` | Session fills a team slot |
| `session -> assigned_to -> project` | `entity_relationships` | Explicit assignment beyond path match |
| `team -> assigned_to -> project` | `entity_relationships` | Team works on a project |
| `project -> relates_to -> project` | `entity_relationships` | Cross-project dependency |

YAML `assigned`/`projects`/`related` fields bootstrap these rows on first
index but are NOT authoritative after that.

### Indexing pattern

Both follow the same pattern as briefs:

1. **Filesystem scan** at startup and on signal file change
2. **YAML parse** with fallback for missing/malformed files
3. **Bootstrap seed** — on first index, create `entity_relationships` from YAML hints
4. **Card creation** for renderer consumption
5. **Reconciliation** — check slot occupancy against session liveness
6. **Change signal** — `projects.changed` / `teams.changed` signal files

### Storage summary

| Entity | Identity (declarative) | Runtime state | Derived |
|--------|----------------------|---------------|---------|
| Project | `project.yml` + filesystem | `entity_relationships` (assignment) | branch, git_status, session_count |
| Team | `teams/{id}.yml` | `entity_relationships` (slot occupancy) | filled_count, active members |
| Session | `sessions.db` | roles, display_name, tags, groups | runtime_state, activity_state |
| Brief | `session_briefs/*.yml` | (immutable after condensation) | file_size, mtime |

---

## Migration plan

### Current state
- No `project.yml` files exist anywhere
- No `ai_general/data/teams/` directory exists
- Existing contracts define a different Team model (`profiles[]` + `role_assignments`)
- `ProjectCard.status` means git status, not lifecycle status
- No `TeamCard` in `cards.ts`
- `assigned_ais` field exists but is always empty

### Implementation order

1. **Contract updates** — Update `entities.ts` and `cards.ts` first:
   - Split project status fields
   - Add `TeamCard`
   - Update `Team` interface to slot model
   - Update `AnyCard` union

2. **Team indexer** — Create `team-indexer.ts` following brief-indexer pattern:
   - Scan `ai_general/data/teams/*.yml`
   - Parse team definition
   - Query `entity_relationships` for slot occupancy
   - Return `TeamCard[]`

3. **Project indexer update** — Add `project.yml` parsing to existing indexer:
   - Read optional `project.yml` for identity metadata
   - Bootstrap seed relationships on first index
   - Add `lifecycle_status` and `goal` to ProjectCard

4. **Slot claim/release commands** — Add to command-handlers.ts:
   - `team.slot.claim` — atomic relationship insert + groups update
   - `team.slot.release` — relationship delete + groups update
   - `team.create` / `team.disband` — YAML file operations

5. **Reconciler** — Periodic check for stale slot occupancy

6. **UI** — TeamCard rendering, team navigator tab, slot assignment UI

### Backwards compatibility
- `assigned_ais` remains on ProjectCard but is deprecated (always empty)
- Existing project indexing works unchanged when no `project.yml` exists
- Teams are entirely new — no legacy data to migrate

---

## UAI's role

UAI is a consumer, not the owner. It:

- **Reads** project.yml and team YAML files via indexers
- **Reads** slot occupancy from `entity_relationships`
- **Displays** ProjectCards and TeamCards in the navigator
- **Renders** team slot assignments and project session counts
- **Writes** slot claims/releases via command bus (which updates SQLite atomically)
- **Watches** signal files for external changes (other tools editing YAML)

Other ecosystem participants (Hamilton, session launchers, comms protocol,
CLI tools) can read team YAML and query/update `entity_relationships`
independently.
