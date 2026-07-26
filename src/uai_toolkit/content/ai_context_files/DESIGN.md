# DESIGN — ai_context_files/

Rules for **creating and naming** files under `ai_context_files/`. Read this
before adding, renaming, or moving anything here.

## Golden rule: list the directory first

**NEVER create a file in a directory without first listing that directory.** One
`ls` prevents naming-convention violations, duplicates, wrong locations, and
missing an existing resource you should have reused.

## What lives here

`ai_context_files/` holds the **leaf context** an agent loads: knowledge and
instructions (plus `globals/`, `_archive/`). It is indexed by `context_mgr.py`
and referenced (extension-less) from composition files in `ai_profiles/`.

## Directory → filename prefix (match the folder you're in)

New leaf files use the prefix for their subdirectory. A small number of active files
still carry pre-standardization names (for example `reference_*` under `reference/`);
the table is the authoring rule, not a claim that migration debt is already zero.

| Directory | Prefix | Example |
|---|---|---|
| `instructions/perspectives/` | `perspective_` | `perspective_operating_principles.md` |
| `instructions/how_tos/` | `instr_` | `instr_activity_logging.md` |
| `instructions/rules/` | `rules_` | `rules_file_conventions.yml` |
| `instructions/reminders/` | `reminder_` | `reminder_response_format.md` |
| `instructions/collaboration/` | `feedback_` | `feedback_plain_terminology.md` |
| `instructions/ux/` | `ux_` | `ux_more_colors_means_bold_backgrounds.md` |
| `instructions/templates/` | *(none; descriptive names, usually `*_template`)* | `design_template.md` |
| `knowledge/reference/` | `ref_` | `ref_tools_manifest.yml` |
| `knowledge/architecture/` | `arch_` | `arch_entity_model.md` |
| `knowledge/schemas/` | `schema_` | `schema_base.json` |
| `knowledge/specs/` | `spec_` | `spec_session_identity.yml` |

The first path segment of a context id **is** the category (`instruction:rules/rules_x`),
so the prefix and the folder must agree.

## Extensions & format

- `.md` — canonical, human-written/reviewed prose.
- `.yml` — structured / machine-parseable (often a condensed form of a `.md`).
- `.json` — data schemas only (`knowledge/schemas/`).
- **A rename must never change the extension/format.** Use `context_mgr.py move`
  (it preserves the source extension and repoints every inbound reference) — do
  NOT hand-`mv` a referenced file, or you'll dangle its referrers.

## Suffixes (before the extension, never after)

Tags/markers/versions go **before** the extension: `doc.NEEDS_PROCESSING.md`,
not `doc.md.NEEDS_PROCESSING`.

- `_vX.Y` — explicit version (`doc_v3.0.md`).
- `.condensed.yml` — token-optimized form (loaded first).
- `*.latest.*` / `*_latest.*` — legacy compatibility symlinks. The resolver still
  accepts them and `context_mgr.py move` preserves a sibling `_latest` symlink, but
  do not create them for new active leaves.
- Resolution/loading order: `.condensed.yml` → `.yml` → `.md`.

## Per-instance files carry a discriminator

A file that exists per-instance embeds its discriminator in the slug, before the
extension: `sessionInfo.f3c818cf.json`, `response.req_2115.md`. Generic names
across many dirs cause ambiguous tabs, grep noise, and clobbering.

## Archiving

Archived leaves move under `_archive/` (a `_`-prefixed dir). `context_mgr.py`
does NOT index anything under a dir starting with `_` or `.` — so `_archive/`
items drop out of the active catalog automatically. Use `context_mgr.py archive`.

## Reminders

- Filenames: lowercase, `[a-z0-9_]`, words joined by `_`.
- Timestamps/dates in filenames: local time, not UTC.
- Don't use `mkdir -p`; a failed `mkdir` means your mental model is wrong — stop
  and look.
