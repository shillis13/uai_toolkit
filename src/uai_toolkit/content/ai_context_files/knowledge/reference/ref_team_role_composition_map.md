---
name: ref_team_role_composition_map
title: Team role-assignment → composition map
description: How a team's .team.yml role_assignment strings (builder/reviewer/lead) bind to role compositions (team_developer/team_reviewer/team_lead); the team_* roles compose the individual role + team_member, and the Team-Member instructions flow in transitively. todo_0665.
status: active
---

How a team's registry role-assignment strings (in `<name>.team.yml` → `role_assignments:`)
bind to **role compositions** in `ai_profiles/roles/`. Established by todo_0665
(child of todo_0654 Team readiness).

## The map

| `.team.yml` role string | composition target | composes |
|---|---|---|
| `builder` / `developer` | `role:team_developer` | assistant + worker + dev + team_member |
| `reviewer` | `role:team_reviewer` | assistant + worker + peer_reviewer + team_member |
| `lead` | `role:team_lead` | assistant + worker + dev + dev_lead + team_member |
| `architect` | `role:team_architect` *(archived; not loadable until restored from `ai_profiles/_archive/team_architect.yml`)* | assistant + architect + team_member |

## Naming convention (the rule that binds them)

The table above is the canonical map for the currently supported role strings. A new
team role string should target **`role:team_<canonical-role>`** only when that active
composition exists. Synonyms fold to the canonical composition (`builder` →
`team_developer`, since the individual role is `dev`/Developer). Existing registry
roles such as `coordinator` and `identity_infra` do not yet have a mapped composition;
do not invent one at load time.

## Why these compositions

Each `team_*` role = the **individual role** (dev / peer_reviewer / dev_lead) + the
**`team_member`** role. The Team-Member operating instructions
(`instr_team_membership`, todo_0664) are attached to `team_member`'s `context_files`, so they
flow into every `team_*` role **transitively** — verified: `context_mgr resolve role:team_developer`
(and team_reviewer / team_lead) includes `instruction:how_tos/instr_team_membership`. Attach once
to `team_member`, inherit everywhere.

## Current state / follow-up

- **Documentary today.** No code resolver yet turns a `role_assignments` string into a loaded
  `role:team_*` composition — `scripts/projects/projects_mgr.py` stores the assignment data
  (`role_assignments` {role: holders}, plus a `role_contexts` block) but does not resolve strings
  to role definitions.
- **Wiring point (follow-up):** a resolver — likely in `projects_mgr` and/or the SessionStart
  role-load path (`data/hooks/SessionStart/02_stage_session_context_sync.py` resolves a session's
  `roles` via guidance) — should use the explicit map above and add the result to the session's roles,
  so a teammate auto-loads its team composition. `role_contexts` in `.team.yml` may be the natural
  place to pin per-role composition overrides. Track under the todo_0654 Team-readiness umbrella.

Related individual roles: `role:dev`, `role:peer_reviewer`, `role:dev_lead`, and
`role:team_member`. Team operating instructions: `instruction:how_tos/instr_team_membership`.
