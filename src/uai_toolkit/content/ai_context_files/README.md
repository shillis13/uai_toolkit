# ai_context_files/ — Leaf Context

The **leaf content** an AI session loads: **knowledge** (what *is*) and **instructions**
(how to *operate*). These are the atomic, reusable building blocks. The **composition layer**
lives separately in `ai_profiles/` (bundles, roles, skills, globals), which pull these leaves
in by reference.

Indexed by the Context Mgr (`scripts/context_files/context_mgr.py`) into a rebuildable SQLite
index, and delivered to sessions via the guidance/knowledge MCP (`get_context`, `get_role`, …).
References from `ai_profiles/` are **extension-less, `ai_general`-relative paths**.

> Terminology note: this used to be `ai_traits/` under a "traits / profiles / methods / processes /
> procedures" ontology. That model is retired. Content is now just **knowledge** + **instructions**;
> compositions are **bundles / roles / skills / globals** (the `profile` kind is retired). The old
> `.latest.*` / `*_latest.*` version symlinks are no longer created for active content.
> The resolver and move tooling still recognize them for backward compatibility; see
> Extensions in `DESIGN.md`.

## Two families

### `instructions/` — how to operate

┌───────────────┬──────────────────┬──────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
│ **Category**  │ **Dir**          │ **Prefix**                               │ **What**                                                   │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Collaboration │ `collaboration/` │ `feedback_`                              │ How PianoMan works: preferences, working norms, standing   │
│               │                  │                                          │ feedback                                                   │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Rules         │ `rules/`         │ `rules_`                                 │ Normative conventions (naming, versioning, formatting,     │
│               │                  │                                          │ multi-session safety)                                      │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ How-tos       │ `how_tos/`       │ `instr_`                                 │ Procedures for a specific system or task                   │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Perspectives  │ `perspectives/`  │ `perspective_`                           │ Mindsets / operating principles / verification & quality   │
│               │                  │                                          │ discipline                                                 │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Reminders     │ `reminders/`     │ `reminder_`                              │ Short recurring nudges                                     │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ UX            │ `ux/`            │ `ux_`                                    │ Visual / UI standards                                      │
├───────────────┼──────────────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Templates     │ `templates/`     │ *(none; descriptive names, usually       │ Document scaffolding that generates dynamic instances      │
│               │                  │ `*_template` )*                          │                                                            │
└───────────────┴──────────────────┴──────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

### `knowledge/` — what is

┌──────────────┬─────────────────┬────────────┬────────────────────────────────────────────┐
│ **Category** │ **Dir**         │ **Prefix** │ **What**                                   │
├──────────────┼─────────────────┼────────────┼────────────────────────────────────────────┤
│ Reference    │ `reference/`    │ `ref_`     │ Facts about tools, systems, and mechanisms │
├──────────────┼─────────────────┼────────────┼────────────────────────────────────────────┤
│ Architecture │ `architecture/` │ `arch_`    │ Structural / system understanding          │
├──────────────┼─────────────────┼────────────┼────────────────────────────────────────────┤
│ Schemas      │ `schemas/`      │ `schema_`  │ Data schemas (`.json`)                     │
├──────────────┼─────────────────┼────────────┼────────────────────────────────────────────┤
│ Specs        │ `specs/`        │ `spec_`    │ Specifications                             │
└──────────────┴─────────────────┴────────────┴────────────────────────────────────────────┘

## Also here

- `globals/` and `platforms/<platform>/` — the default startup context loaded by the SessionStart
  hook (`data/hooks/SessionStart/02`). Wiring the default set is tracked under todo_0617.
- `_archive/` — soft-deleted leaves. The indexer skips any dir starting with `_` or `.`, so archived
  items drop out of the active catalog automatically.

## Conventions & tooling

- **Naming / creation / archiving rules:** see `DESIGN.md` in this directory (category→prefix table,
  extensions, suffixes, per-instance discriminators).
- **Never hand-edit references** in `ai_profiles/` compositions. Use the Context Mgr:
  - `context_mgr.py link` / `unlink` — add / remove a reference (edits the YAML where `reindex` reads).
  - `context_mgr.py move` — rename/relocate a leaf and repoint every inbound reference.
  - `context_mgr.py validate` — report dangling edges + orphans.
- **Create a leaf:** `context_mgr.py create --kind {knowledge|instruction} --category <cat> --title …`
  (`--new-category` to deliberately create a new category dir).
- **Resolution / load order** for a leaf: `.condensed.yml` → `.yml` → `.md`.

## Composition layer (`ai_profiles/`)

Leaves are composed into:

┌────────────┬────────────────────────┬───────────────────────────────────────────────────────────┐
│ **Kind**   │ **Dir**                │ **Is**                                                    │
├────────────┼────────────────────────┼───────────────────────────────────────────────────────────┤
│ **bundle** │ `ai_profiles/bundles/` │ A curated content-set (references leaves + other bundles) │
├────────────┼────────────────────────┼───────────────────────────────────────────────────────────┤
│ **role**   │ `ai_profiles/roles/`   │ Bundle + responsibilities; composes sub-roles             │
├────────────┼────────────────────────┼───────────────────────────────────────────────────────────┤
│ **skill**  │ `ai_profiles/skills/`  │ A capability                                              │
├────────────┼────────────────────────┼───────────────────────────────────────────────────────────┤
│ **global** │ `ai_profiles/globals/` │ Loaded for every agent                                    │
└────────────┴────────────────────────┴───────────────────────────────────────────────────────────┘

The `profile` kind is **retired** — a session carries roles and bundles directly. See
`ai_profiles/DESIGN.md`.
