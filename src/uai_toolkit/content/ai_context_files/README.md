# ai_traits/ — The Corpus

Source of truth for all AI content elements, organized by ontology categories.

Each element in this directory is a **trait** — an atomic, reusable building block that gets composed into roles, profiles, and skills via `ai_profiles/`.

## Ontology Categories

| Category | Directory | Core Question | Distinguishing Test |
|----------|-----------|--------------|-------------------|
| **Perspective** | `perspective/` | How do you think? | Shapes judgment, tone, orientation — not specific actions |
| **Knowledge** | `knowledge/` | What is? | Facts, reference, structural understanding |
| **Processes** | `processes/` | What do you do and when? | Workflows, lifecycles, coordination sequences |
| **Procedures** | `procedures/` | How do you do it? | Specific rules, conventions, standards |
| **Methods** | `methods/` | How do you solve this class of problem? | Self-contained methodologies for specific problem types |
| **Templates** | `templates/` | What's the structure for this work product? | Scaffolding that generates dynamic instances |

## Versioning

Files use the `.latest.*` symlink convention. Each trait may have versioned files with a `.latest.*` symlink pointing to the current version.

## Design Spec

Full architecture: `todos/todo_0267_ai_data_architecture_redesign_traits_and_profiles/2026-04-13-ai-data-architecture-design.md`
