---
name: reference_skills_vs_roles_loader
description: Skills vs roles differ ONLY by loader (skill=/command, role=MCP knowledge_get_*);
  both are bundles of instructions+knowledge
status: active
---

In the ai_root context system, **skills** and **roles** are structurally the same thing — **bundles** that reference context files. They differ ONLY by their **loader**:
- **skill** — loaded by a **/command** (platform-specific, Claude-Code style).
- **role** — the same kind of bundle, loaded by an **MCP call** (`knowledge_get_*`).

`knowledge_get_*` was built specifically as the **generic, cross-platform replacement for /command skills** — so "role via MCP" is the portable form of "skill via /command." Same content, different doorway. (Do NOT model skills as "conditional/on-trigger loaded" vs roles "unconditional" — that's wrong; everything can be loaded on demand. The distinction is purely the loader mechanism.)

The full model:
- **Context files** (leaf content): `knowledge`, `instruction`, `brief`, `memory`. Live in `ai_general/ai_context_files/` (knowledge, instructions), `data/session_briefs/` (briefs), `ai_memories/80_working_memory/` (memories).
- **Bundles** (compositions referencing context files and/or other bundles): `role`, `skill`, `profile`, `global`. Differ by loader (mcp/command/auto), scope (global=all sessions), tier (`profile` = bundle-of-bundles). A global can't include a profile (it would just be global). Live in `ai_general/ai_profiles/{roles,skills,globals}` + top-level `ai_profiles/*.yml` (profiles).

**Keep the kind labels** (role/skill/profile/global) — PianoMan said they matter and they map to the real dirs. The engine can treat them uniformly as bundles underneath, but the labels stay user-facing. Related: [[project_data_architecture_migration]].
