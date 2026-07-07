# Project & Team Registry — Design

**Date:** 2026-06-22
**Author:** Mullion (session 20260621_031933_50aaa957_cla) with PianoMan
**Status:** Decided — proceeding to implementation
**Companion:** `2026-06-21-project-editor-design.md`; supersedes the SQLite-indexed project model in `architecture/uai_architecture_v1.1.md section 2.3`

## Terms
- **Registry** — a plain directory of YAML files that *is* the source of truth for projects and teams. Not a database.
- **Project** — a conceptual unit of work with optional working dir. **Team** — a composition of AIs/roles; a *project with a switch flipped* (no working dir, member-focused). Team ⊂ Project.

## Decisions (locked)

1. **Filesystem is the source of truth — no SQLite.** The registry is a directory of YAML files; reading it = listing the dir + parsing. At project/team scale (dozens), no index is needed. A SQLite/JSON index would be a *derived, rebuildable cache* only — deferred until query perf actually hurts. (This deliberately supersedes arch v1.1's SQLite-indexed projects, consistent with the todos "filesystem is the database" decision.)

2. **Registry location:** `ai_general/data/projects/`

3. **Filename encodes id AND type:** `<id>.proj.yml` and `<id>.team.yml`.
   ```
   ai_general/data/projects/
     uai_app.proj.yml
     axis_allies.proj.yml
     uai_core.team.yml
   ```

4. **One unified schema; the extension is the type discriminator** (no redundant `kind:` field to drift). Team-side fields are simply populated in `.team.yml` and empty/absent in `.proj.yml`.

5. **Resolve by id, glob the type:** to load entity `X`, glob `<registry>/X.*.yml` and read whichever exists. The extension tells you the type. This is what keeps conversion safe (see 6).

6. **Conversion = atomic rename.** Team→project: `mv X.team.yml X.proj.yml` and set `working_dir`. Project→team: reverse. Because every reference is by **id** and lookup is `id.*.yml`, **no reference breaks across the rename.**

7. **Lifecycle vocabulary (shared):** `active | paused | complete | archived` for both projects and teams. **Sandbox** (a dir with no registry entry) and **Orphaned devTree** remain *derived* states — never stored.

8. **Team membership is explicit** in the team file (`members`, `role_assignments`), NOT derived from session `project_dir` matching (which is unreliable — sessions run from the root). Projects may still associate sessions by working dir for display, but teams own their roster.

## Structural states (derived, not stored)

Two independent axes — (has registry entry?) × (has working dir?):

| | has `<id>.proj.yml` | no registry entry |
|---|---|---|
| **has dir** | **Active** (instantiated) | **Sandbox / unregistered** |
| **no dir** | **Uninstantiated** (registered, not yet created) | — (n/a) |

**Teams don't have a working dir by design**, so the dir-based states don't map. A team's instantiation axis is *membership*, not *workspace*:
- **A project instantiates via its dir; a team instantiates via its members.**
- **Forming** = `.team.yml` with empty `members` (registered, unstaffed) — the team analog of *Uninstantiated*.
- **Staffed** = has `members` — the team analog of *Active*.
- **Sandbox does not apply to teams** (no dir ⇒ no "dir without a file").

`lifecycle_status` (active/paused/complete/archived) is orthogonal *stored intent*, layered over these *derived* structural states.

## Navigation — teams live in the Projects tab

Teams surface in the **Projects tab** (one registry = one surface), in a **Teams section** alongside `Active · Uninstantiated · Sandbox · Done · Orphaned DevTrees`. Opening a team opens the **team-flavored `ProjectEditor`** (Team Details = the subset). The legacy separate team path (`TabContentPane case 'team'` → `TeamDetailView`, and any standalone Teams nav surface) is **retired/redirected** so there is exactly one way to view a team. `ProjectsTab` sections updated to the real taxonomy above.

## Schema

```yaml
# <id>.proj.yml  /  <id>.team.yml   (unified; extension = type)
id: uai_app                     # immutable; matches filename stem
name: Unified AI Interface
goal: Desktop workspace for managing AI CLI agent sessions
lifecycle_status: active        # active | paused | complete | archived
owner: PianoMan
tags: [electron, typescript, react]
working_dir: /Users/.../uai_app/unified_ai_interface   # null for teams / registered-no-dir
devtree: uai-resurrection       # optional
created: 2026-03-15

# ── team-side (populated in .team.yml; absent in .proj.yml) ──
members: [Mullion, Plumbline, Hamilton]          # display names or tracking ids
role_assignments:
  lead: Hamilton
  builder: Mullion
comms_plan:
  escalation_chain: [lead, user]
```

## Resolution & API (filesystem, no DB)

A small `projects-mgr` (CLI + the app's indexer) operating purely on the dir:
- `list()` → read every `*.proj.yml` / `*.team.yml`, parse, return.
- `get(id)` → glob `<id>.*.yml`.
- `create(id, type, fields)` → write `<id>.<type>.yml`.
- `convert(id, toType)` → rename + adjust `working_dir`.
- `set(id, field, value)` → rewrite the YAML.
- Derived (not stored): sandbox = working dirs with no registry entry; orphaned devTree = devTree with no registry reference.

## App integration

The Electron `project-indexer` switches from "scan the filesystem for in-dir `project.yml`" to **"read the registry dir."** Registered projects/teams come from `ai_general/data/projects/`; sandbox dirs remain a secondary derived listing. `window.uai.projects.list()` then returns real registered entities, and the Project Editor (and Team Details = ProjectEditor over a `.team.yml`) finally has data.

## Build order
1. Create the registry dir + register the real projects/teams that exist (uai_app first, the actual teams).
2. Point the app's project-indexer at the registry (read `*.proj.yml`/`*.team.yml`).
3. `projects-mgr` CLI (create/convert/set) — filesystem only.
4. Team Details specialization in ProjectEditor (default aspect = Team; hide Docs when no working_dir).
