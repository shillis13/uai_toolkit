# ai_profiles/ — Composition Layer

Named assemblies of traits at different granularities. Every item carries its own content (description, responsibilities, rationale) plus references to traits in `ai_traits/`.

## Structure

| Directory | What it contains |
|-----------|-----------------|
| `globals/` | Universal trait bundles included for every agent (by launcher convention) |
| `platforms/` | Platform-specific trait bundles (claude_code, gemini, codex, etc.) |
| `roles/` | Atomic identity fragments — duties, ownership, role-specific trait references |
| `skills/` | Executable compositions with trigger conditions and flow logic |
| Top-level `*.yml` | Pre-composed profiles — named sets of roles representing full agent identities |

## How It Works

- **Roles** are atomic — they carry only what's uniquely role-shaped (duties, ownership, role-specific traits)
- **Profiles** are pre-composed bundles of roles (e.g., `developer_teammate.yml` = [assistant, worker, dev, team_member])
- **Globals and platforms** are not bundled into roles or profiles — the launcher includes them based on convention and target platform
- Roles can be added at launch or during a session
- Traits can also be applied individually, outside any role

## Design Spec

Full architecture: `todos/todo_0267_ai_data_architecture_redesign_traits_and_profiles/2026-04-13-ai-data-architecture-design.md`
