# memories

CLI wrapper and business logic for the slot-based working memory system. Working memory is stored as timestamped YAML observation lists in `ai_memories/80_working_memory/` (slots `03.yml` through `30.yml`).

## Scripts

### memory_lib.py
Business logic for all slot operations. Reads and writes slot YAML files, handles both the current structured schema (`observations:` key) and the legacy pure-list format. Supports time filtering, ordered retrieval, and cross-slot search. Extracted from the `memory` MCP server.

No CLI entry point — imported by `memory_cli.py` and the MCP server.

Operations: `op_read`, `op_append`, `op_update`, `op_delete`, `op_search`, `op_set_slot_config`, `op_stats`, `op_get_manifest`.

### memory_cli.py
Thin subprocess-friendly CLI wrapper around `memory_lib.py`. All subcommands emit JSON to stdout; errors go to stderr with a non-zero exit code. Used by MCP tools and shell scripts that need to read or write working memory without importing Python directly.

**Usage:**
```
memory_cli.py get_manifest [--ai NAME]
memory_cli.py read SLOT [--since TS] [--limit N] [--oldest-first]
memory_cli.py append SLOT "observation text"
memory_cli.py update SLOT INDEX "new content"
memory_cli.py delete SLOT [--index N] [--before TS]
memory_cli.py search QUERY [--slot N ...] [--regex] [--since TS]
memory_cli.py set_config SLOT [--name N] [--purpose P] [--load AUTO|TOPIC|DEMAND]
memory_cli.py stats
```

## Dependencies

- `yaml` — slot file format
- `memory_lib.py` from `ai_general/scripts/memories/` — the actual implementation (this directory holds a thin copy/wrapper; `$AI_ROOT/ai_general/scripts/memories/` is the canonical location)

## Notes

- Slot files follow the format `{slot_num:02d}.yml` (e.g., `03.yml`).
- Key slots by convention: 03=user model, 04=communication, 05=tools, 06=current context, 07=limitations/workarounds, 08=learnings.
- The `--ai` flag allows targeting different AI instances' memory paths, though only `default` (pointing to `ai_memories/80_working_memory/`) is currently configured.
- `op_stats` shows per-slot entry counts and file sizes — useful for monitoring slot growth.
