---
id: arch_traits_profiles_registry
name: Traits, Profiles, and Registry Architecture
status: active
version: 1.0.0
created: 2026-05-07
updated: 2026-05-08
description: Canonical architecture for AI content ontology — traits, profiles, roles, skills, frontmatter, registry database, and guidance delivery.
supersedes:
  - arch_data_architecture_traits_and_profiles.md
  - arch_traits_registry.md
  - taxonomy_document_types_v1.0.md
last_reconciled_against:
  - ai_general/ai_traits/ (directory structure)
  - ai_general/ai_profiles/ (directory structure)
  - ai_general/scripts/traits/scan_traits_registry.py
  - ai_general/data/traits/traits_registry.db
  - ai_general/apps/mcps/knowledge/tools/knowledge_guidance.py
---

# Traits, Profiles, and Registry Architecture

**Version:** 1.0.0
**Status:** Active — canonical architecture for the AI content system
**Companion docs:**
- Doc 1: `ai_root_architecture_overview.latest.md` — ecosystem overview
- Doc 3: `arch_memory_context_library.latest.md` — memory, context, and library architecture (planned — todo_0288)

---

## 1. Executive Summary

The trait system is the source-of-truth content layer for the AI CLI ecosystem. Human/AI-authored files define knowledge, processes, procedures, methods, and templates. These are composed into roles and profiles that give sessions their identity and capabilities. A SQLite registry indexes all content for programmatic lookup via the guidance MCP server.

**Core principle:** Files own authored content; the database owns computed metadata. The registry is always regenerable from source files.

---

## 2. Three Conceptual Layers

### Ontology Layer — What content exists

Six categories of authored content, each with a distinguishing test:

┌─────────────────┬─────────────────────────────────────────────────────────────────────────────────────┬──────────────────────────┐
│ **Category**    │ **Distinguishing Test**                                                             │ **Location**             │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Perspective** │ Does it shape *how* the AI sees the world? (identity, values, user model)           │ `ai_traits/perspective/` │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Knowledge**   │ Does it teach *what* the AI should know? (architecture, specs, schemas, registries) │ `ai_traits/knowledge/`   │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Processes**   │ Does it define *how things work together*? (protocols, playbooks, coordination)     │ `ai_traits/processes/`   │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Procedures**  │ Does it prescribe *step-by-step what to do*? (operational rules, checklists)        │ `ai_traits/procedures/`  │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Methods**     │ Does it teach *how to think about problems*? (problem-solving approaches)           │ `ai_traits/methods/`     │
├─────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼──────────────────────────┤
│ **Templates**   │ Does it provide *reusable structure*? (task templates, review scaffolds)            │ `ai_traits/templates/`   │
└─────────────────┴─────────────────────────────────────────────────────────────────────────────────────┴──────────────────────────┘

Additional directories: `ai_traits/reminders/` (standing reminders), `ai_traits/_drafts/` (work in progress).

**Historical note:** An earlier taxonomy (2025) used a hierarchical document-type system (Architecture → Registry → Protocol → Spec → etc.). Superseded by this six-category ontology, but numbered prefixes (10_architecture, 30_protocols, 50_schemas) are preserved as granularity markers within Knowledge and Processes categories.

### Composition Layer — How content assembles into identities

┌─────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Term**    │ **Definition**                                                                                                              │
├─────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ **Trait**   │ A single authored file: one piece of knowledge, one protocol, one procedure. Atomic unit of content.                        │
├─────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ **Role**    │ An identity fragment that bundles traits for a specific function (assistant, worker, dev, peer_reviewer). Defined in        │
│             │ `ai_profiles/roles/*.yml` .                                                                                                 │
├─────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ **Profile** │ A complete composed identity: globals + platform + role(s) + project. Defined as top-level `ai_profiles/*.yml` files.       │
├─────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ **Skill**   │ An executable composition with trigger conditions, delivered via guidance MCP. Defined in `ai_profiles/skills/` .           │
└─────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

Composition at launch: `ai_launcher.py` assembles globals → platform traits → profile/role traits → project-specific traits into a bootstrap prompt. The result is a coherent identity, not a bag of instructions.

### Delivery Layer — How content reaches sessions

- **Guidance MCP** (primary): `get_role`, `get_skill`, `get_trait`, `how_to`, `search`, `get_knowledge` — on-demand trait retrieval from the registry database.
- **Bootstrap prompt** (launch): `ai_launcher.py` assembles composed profiles into the system prompt.
- **CLAUDE.md / system prompt** (supporting): Static instructions loaded by the platform itself.

---

## 3. Physical Structure

```
ai_general/ai_traits/                        authored content (source of truth)
├─ perspective/                              identity, values, user model
├─ knowledge/
│  ├─ 10_architecture/                       architecture docs (this doc)
│  ├─ 20_registries/                         glossary, indexes
│  ├─ 40_specs/                              specifications
│  ├─ 50_schemas/                            YAML/data schemas
│  └─ mcp_usage/                             MCP tool usage guides
├─ processes/
│  └─ 30_protocols/                          coordination protocols
├─ procedures/                               operational rules
├─ methods/                                  problem-solving approaches
├─ templates/                                reusable scaffolds
├─ reminders/                                standing reminders
└─ _drafts/                                  work in progress

ai_general/ai_profiles/                      composition layer
├─ globals/                                  universal bundles (loaded by all)
├─ platforms/                                Claude/Codex/Gemini platform traits
├─ roles/                                    identity fragments (13 roles)
├─ skills/                                   executable compositions
└─ *.yml                                     top-level profile files (composed identities)

ai_general/docs/                             compatibility symlink layer → ai_traits/
```

Many historical tier paths under `ai_general/docs/` (10_architecture, 20_registries, 40_specs, 50_schemas, etc.) are now compatibility symlinks pointing into `ai_traits/knowledge/`. The source of truth for authored content is `ai_traits/`. However, `docs/` also contains real directories and files (e.g., `commands/`, `ideas/`, `news/`, `70_instructions/`) that have not been migrated.

---

## 4. Frontmatter Schema

Every trait file carries YAML frontmatter for registry indexing.

### Required Fields

┌───────────┬──────────┬──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Field** │ **Type** │ **Purpose**                                                                                                              │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `id`      │ string   │ Unique identifier (snake_case, no version suffix)                                                                        │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `name`    │ string   │ Human-readable display name                                                                                              │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `status`  │ string   │ Target: `draft` , `active` , `superseded` , `retired` . Note: status normalization is incomplete; the live registry      │
│           │          │ currently contains legacy/non-normalized values (e.g., `production` , `validated` , `complete` , `DRAFT` ).              │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `version` │ semver   │ Document version                                                                                                         │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `created` │ date     │ Creation date                                                                                                            │
├───────────┼──────────┼──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ `updated` │ date     │ Last modification date                                                                                                   │
└───────────┴──────────┴──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

### Optional Authored Fields

┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ **Field**       │ **Purpose**                                                     │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `description`   │ One-line summary (used in search results)                       │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `nature`        │ Content classification tags (e.g., `composite` , `foundational` │
│                 │ )                                                               │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `supersedes`    │ List of doc IDs this replaces                                   │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `superseded_by` │ Doc ID that replaces this one                                   │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `aliases`       │ Alternative lookup names                                        │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `requires`      │ Dependencies on other traits                                    │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ `mcp_tools`     │ MCP tools this trait documents                                  │
└─────────────────┴─────────────────────────────────────────────────────────────────┘

### Format-Specific Rules

- **Markdown files:** Standard YAML frontmatter between `---` delimiters.
- **YAML files:** Use a `_registry:` top-level key to separate metadata from operational content. This prevents the registry scanner from treating operational YAML keys as metadata.

---

## 5. Registry Database

### Architecture

```
Authored files (ai_traits/, ai_profiles/)
        │
        ▼
scan_traits_registry.py ──▶ traits_registry.db (SQLite)
        │                        │
        │                        ├─ content_items (logical entries)
        │                        ├─ content_files (physical files)
        │                        ├─ content_references (cross-references)
        │                        ├─ item_natures (classification tags)
        │                        └─ item_aliases (alternative names)
        │
        ▼
guidance MCP server ──▶ get_role / get_trait / search / ...
```

**Clean split principle:** Files own authored content (text, instructions, code). The database owns computed metadata (path, category, references, file hashes). The database is always regenerable from source — deleting `traits_registry.db` and re-running the scanner rebuilds it completely.

### Database Model

Two-level design separating logical identity from physical files:

- **`content_items`** — One row per logical trait (id, name, status, version, category, description). The `id` is unique and version-independent.
- **`content_files`** — One row per physical file (path, variant, is_preferred, content_hash, token_estimate, file_size, symlink_target). Multiple files can map to one logical item (e.g., versioned files + latest symlink).
- **`content_references`** — Cross-references extracted from content (source_id → target_id, ref_type).
- **`item_natures`** — Classification tags per item (item_id, nature).
- **`item_aliases`** — Alternative lookup names per item (item_id, alias).

Full schema: `ai_general/scripts/traits/schema.sql`

### Scanner

`scan_traits_registry.py` scans `ai_traits/` and `ai_profiles/`, extracts frontmatter, and populates the database.

- **Full scan** (`--full`): Clears and rebuilds the entire database.
- **Incremental scan** (`--incremental`): Only processes files modified since last scan.
- **Check mode** (`--check`): Reports what would change without modifying the database.
- **Reference extraction:** Four-layer approach — YAML `requires`/`supersedes` parsing → regex content scanning → MCP tool name matching → unresolved reference logging.

### Git Hook Integration

A post-commit hook can trigger incremental scanning so the registry stays current with every commit. The scanner uses a lockfile to prevent concurrent runs.

---

## 6. Guidance MCP Server

The guidance MCP server (`ai_general/apps/mcps/knowledge/tools/knowledge_guidance.py`) provides on-demand trait retrieval backed by the registry database. Direct `guidance_cli.py` is operational; the knowledge/guidance MCP wrapper currently has an AI_ROOT path-resolution bug (doubled `ai_general/ai_general` path) in some environments and needs fixing.

### Tools

┌─────────────────┬─────────────────────────────────────────────┐
│ **Tool**        │ **Purpose**                                 │
├─────────────────┼─────────────────────────────────────────────┤
│ `get_role`      │ Load a role definition by name              │
├─────────────────┼─────────────────────────────────────────────┤
│ `get_skill`     │ Load a skill definition                     │
├─────────────────┼─────────────────────────────────────────────┤
│ `get_trait`     │ Load any trait by ID or name                │
├─────────────────┼─────────────────────────────────────────────┤
│ `get_knowledge` │ Load a knowledge document                   │
├─────────────────┼─────────────────────────────────────────────┤
│ `how_to`        │ Find procedural guidance for a task         │
├─────────────────┼─────────────────────────────────────────────┤
│ `search`        │ Full-text search across all indexed content │
├─────────────────┼─────────────────────────────────────────────┤
│ `remind_me`     │ Retrieve a specific reminder                │
└─────────────────┴─────────────────────────────────────────────┘

### Lookup Resolution

1. Exact `id` match in `content_items`
2. Exact `alias` match in `aliases`
3. Fuzzy/prefix match on `name`
4. If not found: report missing, do not guess

### Database Connection Strategy

Fresh SQLite connection per request — no long-lived handles. This ensures the MCP server always reads the latest state after scanner updates, without restart.

---

## 7. Design Principles

1. **Traits are source of truth.** All AI knowledge, rules, and composition live in authored files under `ai_traits/` and `ai_profiles/`. Everything else is derived.
2. **Flat composability.** Roles and profiles compose traits by reference. No deep inheritance hierarchies.
3. **Delivery is implementation.** How a trait reaches a session (MCP, bootstrap, CLAUDE.md) is separate from its content.
4. **Registry is regenerable.** The SQLite database is a cache. Delete and rebuild from source at any time.
5. **Files over configuration.** Adding a new trait = creating a file with frontmatter. No config changes needed.
6. **Versioning via symlinks.** `*.latest.md` symlinks point to the current version in `versions/`. History is preserved; latest is always the symlink target.

---

## 8. Status and Known Issues

**Implemented:**
- Six-category ontology in `ai_traits/` — populated and in use
- 13 roles in `ai_profiles/roles/`
- `scan_traits_registry.py` — operational, indexes ~270 items / ~335 files
- `traits_registry.db` — active with WAL, current
- Guidance MCP server — operational, serves all listed tools
- `ai_launcher.py` bootstrap composition — operational

**Outstanding:**
- Ontology glossary — authored terms exist at `ai_traits/knowledge/20_registries/ontology_glossary.latest.md` (v1.0, active). Generated file index portion not yet implemented.
- Platform `.md` generation from profiles — designed, not implemented
- Project scaffolding (auto-create trait structure for new projects) — designed, not implemented
- Git hook for automatic incremental scanning — designed, installation pending
- `hooks.yml` + `install_hooks.py` for cross-platform hook management — schema exists, implementation pending

**Migration complete:** The April 2026 data architecture migration moved content from the old `ai_general/docs/` flat structure to the six-category `ai_traits/` + `ai_profiles/` structure. The `docs/` directory is now a compatibility symlink layer. Migration mapping details archived in source docs.

---

## 9. Consolidated Decision Log

Key architectural decisions (condensed from source docs):

┌───────┬──────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────┐
│ **#** │ **Decision**                             │ **Rationale**                                                                         │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D1    │ Six categories, not more                 │ Each category has a clear distinguishing test. Finer splits create classification     │
│       │                                          │ ambiguity.                                                                            │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D2    │ `ai_traits/` and `ai_profiles/` as       │ Traits are content; profiles are composition. Mixing them creates circular            │
│       │ separate trees                           │ dependencies.                                                                         │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D3    │ `docs/` becomes symlink layer            │ Backwards compatibility without duplication. New content goes to `ai_traits/` ; old   │
│       │                                          │ paths still resolve.                                                                  │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D4    │ SQLite over JSON/YAML for registry       │ Queryable, atomic updates, scales to thousands of entries. JSON catalog was fragile.  │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D5    │ `_registry:` block for YAML metadata     │ Prevents operational YAML keys from being parsed as frontmatter. Safe for schemas and │
│       │                                          │ configs.                                                                              │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D6    │ Files own content, DB owns metadata      │ Registry is always regenerable. No data loss if DB is deleted.                        │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D7    │ Fresh DB connection per MCP request      │ Avoids stale reads after scanner updates. No server restart needed.                   │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D8    │ Roles are atomic, profiles compose       │ Roles can be mixed freely. A session can be `assistant + dev + peer_reviewer` .       │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D9    │ Skills have trigger conditions           │ Skills are not just bundles — they declare when they should be activated.             │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D10   │ Versioned files + latest symlinks        │ History preserved. `*.latest.md` always points to current. No file deletion needed    │
│       │                                          │ for updates.                                                                          │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D11   │ Nature tags over type hierarchies        │ Tags are additive and non-exclusive. A trait can be both `foundational` and           │
│       │                                          │ `composite` .                                                                         │
├───────┼──────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ D12   │ Numbered prefixes as granularity markers │ `10_architecture/` , `30_protocols/` — filesystem ordering within categories. Not a   │
│       │                                          │ type hierarchy.                                                                       │
└───────┴──────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────┘