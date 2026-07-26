# DESIGN — ai_profiles/

Rules for **creating and naming** files under `ai_profiles/`. Read this before
adding, renaming, or moving anything here.

## Golden rule: list the directory first

**NEVER create a file in a directory without first listing that directory.** One
`ls` prevents naming-convention violations, duplicates, and wrong locations.

## What lives here

`ai_profiles/` holds the **composition layer** — the bundles that pull in leaf
context from `ai_context_files/`:

| Directory | Kind | File | References |
|---|---|---|---|
| `bundles/` | bundle | `<name>.yml` | context files (a curated content-set) |
| `roles/` | role | `<name>.yml` | context files, bundles (+ sub-roles) |
| `skills/` | skill | `<name>.yml` | context files, bundles |
| `globals/` | global | `<name>.yml` | context files, bundles (loaded for everyone) |

The `profile` kind is **retired** — a session carries roles and bundles directly, so a
profile added nothing. The old root-level `ai_profiles/*.yml` profiles are archived under
`ai_profiles/_archive/`.

## Naming

- Bundles use a **bare, descriptive name — no type prefix**: `architect.yml`,
  `condenser.yml`, `devtree_workflow.yml`, `base.yml`. The directory already
  encodes the kind (`role:architect`, `skill:devtree_workflow`).
- Lowercase, `[a-z0-9_]`, words joined by `_`.
- **Extension is `.yml`** for every bundle (they're structured composition
  documents). A rename must never change the extension.

## References are extension-less and must stay valid

A bundle references leaves/roles by an **extension-less, ai_general-relative
path** (e.g. `ai_context_files/instructions/rules/rules_file_conventions`), under
`context_files:` (a dict of category buckets OR a flat list) and `roles:` /
`skills:`.

- **Add/remove a reference with `context_mgr.py link` / `unlink`** — they edit
  the YAML in the exact place `reindex` reads and keep the index in sync.
- **Rename/relocate the TARGET of a reference with `context_mgr.py move`** — it
  repoints every inbound reference. Never hand-`mv` a referenced file; you'll
  dangle its referrers (surfaced by `context_mgr.py validate`).

## `context_files:` shape

Both forms are valid and parsed:

```yaml
context_files:            # (a) dict of category buckets
  rules:
  - path: ai_context_files/instructions/rules/rules_development
    purpose: Coding standards
```
```yaml
context_files:            # (b) flat list
- ai_context_files/instructions/rules/rules_development
```

When adding an entry, match the shape and bucket the file's siblings already use.

## Archiving

Archived bundles move under `_archive/` (a `_`-prefixed dir); `context_mgr.py`
skips any dir starting with `_` or `.`, so they drop out of the active catalog.

## Reminders

- Don't use `mkdir -p`; a failed `mkdir` means your model is wrong — stop and look.
- `globals/` bundles load for **every** agent — change them with care.
