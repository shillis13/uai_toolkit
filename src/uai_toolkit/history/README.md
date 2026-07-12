# histories

Search library and CLI for the AI conversation knowledge base — the condensed history index stored in `ai_memories/40_histories/`.

## Scripts

### search_lib.py
Business logic for searching condensed chat histories. Implements a 4-layer cascade search: (1) topics index with original terms, (2) topics index with synonym expansion, (3) full chunk content grep, (4) chunk content grep with synonyms. Supports both `search` mode (returns ranked results) and `answer` mode (runs all layers and formats an editorial synthesis). Also handles artifact retrieval (copying condensed files to a retrieval directory) and writing results to timestamped markdown files.

Reads three CSV indexes from `ai_memories/40_histories/indexes/`: `all_topics.latest.csv`, `chat_index.latest.csv`, `condensed_index.latest.csv`.

No CLI entry point — imported by `search_cli.py` and the `knowledge-search` MCP server.

### search_cli.py
Thin CLI wrapper around `search_lib.py`. All subcommands emit JSON to stdout.

**Usage:**
```
search_cli.py search "query text" [--max-results N] [--mode search|answer|auto]
search_cli.py grep "pattern" [--max-results N] [--format condensed|full]
search_cli.py stats
search_cli.py test
```

## Dependencies

- `csv`, `re`, `shutil` — index loading and file operations (stdlib only; no external pip packages)
- `ai_memories/40_histories/indexes/` — CSV index files (must exist for search to return results)

## Notes

- The synonym table (`SYNONYMS`) and compound expansion table (`COMPOUND_EXPANSIONS`) in `search_lib.py` are hardcoded. Add entries there to improve recall for specific domains.
- `search` mode stops at the first layer with 3+ results (fast); `answer` mode runs all 4 layers (thorough). `auto` detects from query phrasing (question words → answer mode).
- `test` subcommand checks index file existence and returns counts — useful for verifying the pipeline has run recently.
