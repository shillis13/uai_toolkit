# context_files

Tools for building and querying the **context-files index** — the SQLite database
(`ai_general/data/context.db`) that indexes all content in `ai_general/ai_context_files/`
and `ai_general/ai_profiles/`. It powers the `knowledge` MCP server's guidance search
and retrieval (`get_context` / `get_role` / `how_to`).

**Authoritative tool: `context_mgr.py`** (index + edits) and **`guidance_cli.py`** (delivery).

> **Retired (todo_0319):** `scan_traits_registry.py` (the old "traits registry" scanner,
> `data/context_files/context_files_registry.db`) and its `schema.sql`/`test_registry.py`
> are **archived** under `scripts/_archive/context_files_registry_retired/`. `context_mgr.py`
> is now the sole builder of `context.db`; the post-commit hook runs `context_mgr.py reindex`.
> Delivery (`guidance_lib`) and discovery (`session_context_registry`) read `context.db`.

## Scripts

### ~~scan_traits_registry.py~~ (RETIRED — see banner above)
Historical: scanned `ai_traits/`/`ai_profiles/` into the legacy traits-registry SQLite DB.

**Usage:**
```
scan_traits_registry.py --full          # rebuild from scratch
scan_traits_registry.py --incremental   # (currently same as --full; hash-based optimization pending)
scan_traits_registry.py --check         # report issues, no writes
scan_traits_registry.py --stats         # print registry statistics
scan_traits_registry.py --inventory     # file/variant group inventory
scan_traits_registry.py --inventory --json
```

### guidance_cli.py
CLI wrapper exposing all `guidance_lib` operations as subcommands. Used by MCP tools and shell scripts to query roles, skills, traits, profiles, and knowledge without importing Python directly. All output goes to stdout as formatted text (same format as MCP tool responses).

**Usage:**
```
guidance_cli.py get_role dev
guidance_cli.py get_skill ai-comms
guidance_cli.py get_trait instr_commit_conventions
guidance_cli.py get_profile individual_developer
guidance_cli.py get_knowledge_topics [--category knowledge]
guidance_cli.py get_knowledge "commit conventions"
guidance_cli.py how_to "write a commit message"
guidance_cli.py remind_me
guidance_cli.py search "query" [--category ...] [--item-type trait|role|skill|profile]
guidance_cli.py list_roles
guidance_cli.py list_skills
guidance_cli.py list_profiles
guidance_cli.py get_stale [--days 90]
```

### generate_frontmatter.py
Adds or merges `---` frontmatter (Markdown) or `_registry:` blocks (YAML) into trait files that are missing them. Infers `id`, `name`, `status`, `version`, `created`, and `updated` fields from filename, path, and git history. Only processes canonical source files — skips symlinks and files in `versions/` or `generated/` directories.

**Usage:**
```
generate_frontmatter.py --all              # process all files missing frontmatter
generate_frontmatter.py --file <path>      # process one file
generate_frontmatter.py --dry-run          # show what would be generated
generate_frontmatter.py --check            # report files missing frontmatter
```

### post-commit-hook.sh
Shell script intended to be installed as a git post-commit hook in `ai_general/`. Triggers an incremental registry scan after each commit that touches trait or profile files.

### test_registry.py
Test suite for registry scanning logic. Run with pytest.

### guidance_lib.py
Business logic for the guidance MCP server — imported by `guidance_cli.py` and the MCP server. Not a CLI script.

### schema.sql
SQLite schema for the traits registry database. Tables: `content_items`, `content_files`, `item_natures`, `item_aliases`, `content_references`, `content_fts`, `mcps`, `mcp_tools`, `scan_log`, `scan_errors`, `registry_meta`.

## Dependencies

- `sqlite3` — registry database (stdlib)
- `yaml` — frontmatter and YAML file parsing
- `guidance_lib.py` from `ai_general/scripts/traits/` — the actual guidance query implementation
- `git` — used by `generate_frontmatter.py` to extract creation/modification dates

## Notes

- The registry database path (`ai_general/data/traits/traits_registry.db`) and schema path (`ai_general/scripts/traits/schema.sql`) are hardcoded relative to `$AI_ROOT`.
- `scan_traits_registry.py` acquires a lock file (`data/traits/.scan.lock`) and treats locks older than 5 minutes as stale.
- The `E2E_TEST_PLAN.md` in this directory outlines the end-to-end test plan for the registry pipeline.
