# Chat History Pipeline Protocol

**Version:** 1.0
**Source:** chat_pipeline/PIPELINE.md (condensed)

## Purpose

Convert raw WebUI or Desktop Claude chat exports to normalized, chunked format for search/analysis/context loading.

## Directory Structure

| Directory | Description |
|-----------|-------------|
| `10_exported/` | Stage 0 - Raw exports by platform (chatgpt/, claude/) |
| `20_preprocessed/` | Optional multi-chat splits (pending/, converted/) |
| `30_converted/` | Stage 2 output - v2.0 schema JSON (chatgpt/, claude/) |
| `40_histories/` | Stage 4 output - Final chunked histories |

### Final Structure
```
40_histories/{platform}/{platform}_{YYYYMMDD}_{uuid8}_{title_slug}/
  {dirname}.001.yml
  _intermediate/  (converted YAML provenance)
  _source/        (symlink to original in 10_exported)
```

## Pipeline Stages

### Stage 0: Export
- **CLI sessions (current):** session transcript JSONL, one per conversation, copied from the session data directory
- **Legacy bulk archives:** historical single-JSON exports already captured under `10_exported/{platform}/` (chatgpt/, claude/)
- **Output:** `10_exported/{platform}/`

### Stage 1: Split
- **Script:** `chat_export_splitter.py`
- **Location:** `ai_general/scripts/chat_processing/`
- **Input:** Single JSON with all conversations
- **Output:** Individual JSON files per conversation
- **Command:** `python -m chat_processing.chat_export_splitter /path/to/export.json -o .../10_exported/chatgpt/archive/bulk_export_YYYYMMDD/`

### Stage 2: Convert
- **Script:** `chat_converter.py`
- **Location:** `ai_general/scripts/chat_processing/`
- **Input:** Platform-native JSON/Markdown
- **Output:** v2.0 schema JSON or YAML
- **Formats Supported:** ChatGPT JSON, Claude JSON, Markdown, HTML share pages
- **Command:** `python -m chat_processing.chat_converter input.json -o output_v2.json -f json`

### Stage 3: Chunk
- **Script:** `chat_chunker.py`
- **Location:** `ai_general/scripts/chat_processing/`
- **Input:** v2.0 schema YAML
- **Output:** Multiple chunk files (.001.yml, .002.yml, etc.)
- **Target Size:** ~4000 tokens
- **Preserves:** Q&A coherence
- **Command:** `python -m chat_processing.chat_chunker input_v2.yaml -o chunks/ --target-size 4000`

### Stage 4: Organize
- **Script:** `process_stage4.py`
- **Location:** `ai_general/scripts/chat_pipeline/` (symlinked from ai_memories/scripts/)
- **Input:** Files in `30_converted/{platform}/`
- **Output:** Organized directories in `40_histories/{platform}/`
- **Command:** `python scripts/process_stage4.py --platform chatgpt`

## Naming Conventions

| Element | Pattern |
|---------|---------|
| Directory | `{platform}_{YYYYMMDD}_{uuid8}_{title_slug}/` |
| Chunk File | `{dirname}.{NNN}.{ext}` |
| Extension | yml for ChatGPT, yaml for Claude |
| Title Slug | max 50 chars, lowercase, underscores |

## Supporting Scripts

| Script | Purpose |
|--------|---------|
| `chatgpt_tree_converter.py` | Convert ChatGPT tree exports to v2 YAML |
| `process_to_histories.py` | Chunk and organize into year/month structure |
| `rename_histories.py` | Bulk rename dirs/chunks to new naming convention |
| `validate_v2_json.py` | Validate v2.0 schema compliance |
| `count_chunks.py` | Count chunks across directories |
| `archive_chatgpt_bulk.sh` | Archive bulk export to dated directory |
| `reset_pipeline_test.sh` | Reset pipeline for testing |

## Schema Reference

- **Location:** `ai_general/scripts/chat_processing/schemas/chat_history_v2.0.schema.yaml`
- **Versions:** 2.0, 2.1 (with thinking field)
- **Key Fields:**
  - `schema_version`: "2.0" or "2.1"
  - `chat_id`: unique conversation ID
  - `platform`: source platform
  - `title`: conversation title
  - `created_at`, `updated_at`: ISO timestamps
  - `messages[]`: role (user/assistant/system), content, thinking (v2.1), timestamp

## Quick Reference

### Full Pipeline (ChatGPT)
```bash
# 1. Split
python -m chat_processing.chat_export_splitter ~/Downloads/export.json -o .../bulk_export_$(date +%Y%m%d)/

# 2. Convert
for f in .../*.json; do python -m chat_processing.chat_converter "$f" -o "${f%.json}_v2.json"; done

# 3. Move
mv ...*_v2.json .../30_converted/chatgpt/

# 4. Process
python scripts/process_stage4.py --platform chatgpt
```

### Single Conversation
```bash
python -m chat_processing.chat_converter input.json -o output_v2.yaml -f yaml
python -m chat_processing.chat_chunker output_v2.yaml -o chunks/
```

## Related Documents

- Schema: `ai_general/scripts/chat_processing/schemas/chat_history_v2.0.schema.yaml`
- Architecture: `ai_general/docs/10_architecture/`
- Scripts: `ai_general/scripts/chat_pipeline/`
