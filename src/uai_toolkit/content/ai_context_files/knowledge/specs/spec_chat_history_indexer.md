# Chat History Indexer Specification (v1.0)

**Purpose:**
Build and maintain a searchable metadata index of chunked chat histories, enabling efficient discovery and retrieval without parsing individual files.

**Script:** `ai_general/scripts/chat_pipeline/build_chat_index.py`
**Output:** `ai_memories/40_histories/indexes/chat_history_index.yml`

---

## 1. Design Goals

1. **Fast metadata extraction** - Index 4,110+ chunks in <5 minutes
2. **Idempotent** - Safe to re-run; same input produces same output
3. **Incremental updates** - Only process new/modified files
4. **Robust error handling** - Never crash on bad input; log and continue
5. **Schema-aware** - Understand v2.0 chunk format, handle variations gracefully

---

## 2. Input Specification

### 2.1 Source Location
```
ai_memories/40_histories/{platform}/{year}/{month}/{conversation_dir}/conversation.chunk_*.yml
```

### 2.2 Directory Structure
```
40_histories/
├── chatgpt/
│   └── 2025/
│       └── 01/
│           └── 2025-01-01_677587d9_stealth_bird_vs_mt1-pro/
│               ├── conversation.yml           # Full conversation (may not exist)
│               ├── conversation.chunk_001.yml # Chunk files
│               └── conversation.chunk_002.yml
└── claude/
    └── 2025/
        └── 11/
            └── 2025-11-01_bcb9b7f4_consolidating_and_organizing/
                ├── conversation.chunk_001.yml
                └── ...
```

### 2.3 Chunk File Schema (v2.0)
```yaml
schema_version: '2.0'
source:
  platform: claude       # or chatgpt
  conversation_id: bcb9b7f4-175d-4e13-9178-ab0f86262bfc
  parent_file: conversation.yml
  chunk_id: chunk_001
metadata:
  title: "Title (Chunk N/M)"
  created_at: '2025-11-01T18:40:09+00:00'
  updated_at: '2025-11-01T22:18:56+00:00'
  message_count: 3
  chunk_info:
    sequence: 1
    total: 15
    message_range: [0, 2]
    token_count: 993
messages:
  - role: user
    content: "..."
    timestamp: '...'
  - role: assistant
    content: "..."
    timestamp: '...'
```

---

## 3. Output Specification

### 3.1 Index Location
```
ai_memories/40_histories/indexes/chat_history_index.yml
```

### 3.2 Index Schema
```yaml
index_schema_version: "1.0"
generated: "2025-12-15T02:15:00Z"
generator: "build_chat_index.py v1.0"
stats:
  total_chunks: 4110
  total_conversations: 1267
  errors_skipped: 3
  platforms:
    claude: {conversations: 340, chunks: 2800, date_range: ["2025-06-01", "2025-12-15"]}
    chatgpt: {conversations: 927, chunks: 1310, date_range: ["2022-12-01", "2025-10-31"]}
  date_range: ["2022-12-01", "2025-12-15"]

entries:
  - path: "40_histories/claude/2025/11/2025-11-01_bcb9b7f4_consolidating/conversation.chunk_001.yml"
    platform: claude
    date: "2025-11-01"
    conversation_id: "bcb9b7f4"
    full_conversation_id: "bcb9b7f4-175d-4e13-9178-ab0f86262bfc"  # from YAML
    title: "Consolidating and organizing AI instructions"
    chunk_number: 1
    total_chunks: 15
    size_bytes: 4096
    message_count: 3
    token_count: 993
    created_at: "2025-11-01T18:40:09+00:00"
    updated_at: "2025-11-01T22:18:56+00:00"
    mtime: 1731456000.0  # for incremental update detection
```

### 3.3 Index Entry Fields

| Field | Source | Extraction Method | Priority |
|-------|--------|-------------------|----------|
| `path` | filesystem | Relative to `ai_memories/` | - |
| `platform` | YAML then path | `source.platform`, fallback to path parse | YAML first |
| `date` | YAML then path | `metadata.created_at`, fallback to dir name | YAML first |
| `conversation_id` | path | Parse: `{date}_{uuid8}_{title}` - extract uuid8 | path |
| `full_conversation_id` | YAML | `source.conversation_id` (full UUID) | YAML |
| `title` | YAML | `metadata.title` (strip chunk suffix) | YAML |
| `chunk_number` | filename | Parse: `.chunk_{N}.yml` → N | filename |
| `total_chunks` | YAML | `metadata.chunk_info.total` | YAML |
| `size_bytes` | stat | `os.path.getsize()` | filesystem |
| `message_count` | YAML | `metadata.message_count` | YAML |
| `token_count` | YAML | `metadata.chunk_info.token_count` (null if missing) | YAML |
| `created_at` | YAML | `metadata.created_at` | YAML |
| `updated_at` | YAML | `metadata.updated_at` | YAML |
| `mtime` | stat | `os.path.getmtime()` | filesystem |

**Field Priority Rule:** When a field can come from multiple sources, YAML takes precedence over path-derived values. This handles edge cases like renamed directories or non-standard naming.

---

## 4. CLI Interface

```bash
# Full rebuild (default)
python3 build_chat_index.py --rebuild

# Incremental update (only new/modified files)
python3 build_chat_index.py --update

# Output format
python3 build_chat_index.py --format json
python3 build_chat_index.py --format yaml  # default

# Dry run (show what would be indexed)
python3 build_chat_index.py --dry-run

# Validate existing index against filesystem
python3 build_chat_index.py --validate

# Verbose output
python3 build_chat_index.py -v

# Custom paths
python3 build_chat_index.py --source-dir /path/to/40_histories --output /path/to/index.yml
```

### 4.1 Exit Codes
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Source directory not found |
| 3 | Permission error |
| 4 | Validation failed (with --validate) |

### 4.2 Validation Mode Details (--validate)

When run with `--validate`, the script checks:

1. **Orphaned index entries:** Index references files that don't exist on disk
2. **Missing from index:** Files on disk not in index (suggests rebuild needed)
3. **Mtime mismatch:** Indexed mtime differs from current (file changed since indexing)
4. **Chunk sequence gaps:** Missing chunks (e.g., chunk_001, chunk_003 but no chunk_002)
5. **Total chunks mismatch:** `total_chunks` doesn't match actual file count for conversation
6. **Schema version:** Index schema version compatibility

Output includes counts and first N examples of each issue type.

---

## 5. Implementation Notes

### 5.1 Discovery Method
Shell glob works where `find` may fail due to extended attributes:
```python
# Use glob pattern matching
from pathlib import Path
for chunk in Path(source_dir).glob("*/*/*/*/conversation.chunk_*.yml"):
    process_chunk(chunk)
```

### 5.2 YAML Parsing Strategy
1. **Fast path:** Extract key fields without full parse where possible
2. **Fallback:** Full YAML load for complex cases
3. **Error handling:** Log and skip malformed files

```python
import yaml

def extract_metadata(filepath: Path) -> dict:
    try:
        with open(filepath) as f:
            data = yaml.safe_load(f)
        return {
            'platform': data.get('source', {}).get('platform'),
            'title': data.get('metadata', {}).get('title', ''),
            'message_count': data.get('metadata', {}).get('message_count', 0),
            'chunk_info': data.get('metadata', {}).get('chunk_info', {}),
        }
    except yaml.YAMLError as e:
        logging.warning(f"YAML parse error in {filepath}: {e}")
        return {}
```

### 5.3 Incremental Update Strategy
1. Load existing index and build path→entry lookup
2. Discover all current chunk files via glob
3. Compare current files against indexed entries:
   - **New files:** Add to index
   - **Modified files:** Re-process (compare stored mtime vs current)
   - **Deleted files:** Remove from index (prune orphans)
4. Write updated index atomically

```python
def incremental_update(source_dir: Path, existing_index: dict) -> dict:
    # Build lookup of existing entries by path
    indexed_paths = {e['path']: e for e in existing_index.get('entries', [])}

    # Discover current files
    current_paths = set()
    for chunk in source_dir.glob("*/*/*/*/conversation.chunk_*.yml"):
        rel_path = str(chunk.relative_to(source_dir.parent))
        current_paths.add(rel_path)

        if rel_path not in indexed_paths:
            # New file - add to index
            yield ('add', chunk)
        elif chunk.stat().st_mtime > indexed_paths[rel_path].get('mtime', 0):
            # Modified file - re-index
            yield ('update', chunk)

    # Find deleted files (in index but not on disk)
    for path in indexed_paths:
        if path not in current_paths:
            yield ('delete', path)
```

### 5.4 Atomic Write
Prevent corruption from interrupted writes:
```python
def atomic_write(filepath: Path, content: str):
    temp_path = filepath.with_suffix('.tmp')
    temp_path.write_text(content)
    temp_path.replace(filepath)  # Atomic on POSIX
```

### 5.5 Title Extraction
Remove chunk suffix from title:
```python
import re

def clean_title(raw_title: str) -> str:
    # "Title (Chunk 1/15)" -> "Title"
    return re.sub(r'\s*\(Chunk \d+/\d+\)$', '', raw_title)
```

### 5.6 Path Parsing
```python
def parse_path(path: Path) -> dict:
    # path: 40_histories/claude/2025/11/2025-11-01_bcb9b7f4_title/conversation.chunk_001.yml
    parts = path.parts

    # Platform from path
    platform_idx = parts.index('40_histories') + 1
    platform = parts[platform_idx]

    # Conversation dir name: 2025-11-01_bcb9b7f4_title
    conv_dir = parts[-2]
    date, conv_id, *title_parts = conv_dir.split('_')

    # Chunk number from filename
    chunk_match = re.search(r'\.chunk_(\d+)\.yml$', path.name)
    chunk_num = int(chunk_match.group(1)) if chunk_match else 0

    return {
        'platform': platform,
        'date': date,
        'conversation_id': conv_id,
        'title_slug': '_'.join(title_parts),
        'chunk_number': chunk_num
    }
```

---

## 6. Edge Cases

### 6.1 File System Issues
| Scenario | Handling |
|----------|----------|
| Empty directory | Skip, no error |
| Permission denied | Log warning, continue |
| Symlinks | Follow symlinks with cycle detection (track visited inodes) |
| Symlink loops | Detect via inode tracking, skip duplicates |
| Unicode in paths | Handle as UTF-8 |
| Very long paths | Handle up to OS limit |
| Clock skew/future mtime | Accept and process (log warning if >1 day in future) |
| Deleted files during run | Skip gracefully (ENOENT) |

### 6.2 Content Issues
| Scenario | Handling |
|----------|----------|
| Malformed YAML | Log warning, skip file |
| Missing required fields | Use defaults/null |
| Empty messages array | Index with message_count=0 |
| Non-standard naming | Best-effort parsing |
| Backup files (`_backup/`) | Skip |
| Non-chunk `.yml` files | Skip |

### 6.3 Large Files
| Scenario | Handling |
|----------|----------|
| Chunk >100KB | Process normally, log info |
| Index >10MB | Consider compression in v2 |

---

## 7. Performance Requirements

| Metric | Target |
|--------|--------|
| Full rebuild (4,110 files) | <5 minutes |
| Incremental update (100 files) | <30 seconds |
| Memory usage | <500MB |
| Index file size | <5MB YAML, <3MB JSON |

### 7.1 Optimization Strategies
1. Use `glob()` not `os.walk()` for targeted discovery
2. Stream YAML parsing (avoid loading full content)
3. Batch write to index file
4. Use `multiprocessing` if single-threaded exceeds target

---

## 8. Testing Strategy

### 8.1 Unit Tests
```python
def test_parse_path():
    """Test path parsing for various formats"""

def test_clean_title():
    """Test title extraction and chunk suffix removal"""

def test_extract_metadata():
    """Test YAML field extraction"""

def test_incremental_detection():
    """Test mtime comparison logic"""
```

### 8.2 Edge Case Tests
- Empty directories
- Files with missing fields
- Malformed YAML
- Unicode in titles
- Very large chunks
- Backup files (should skip)
- Symlinks and symlink loops
- Deleted files during incremental update (pruning)
- Path/YAML precedence (path says claude, YAML says chatgpt)
- Chunk sequence gaps (missing chunk_002 of 5)
- total_chunks mismatch (says 5 but only 3 files exist)

### 8.3 Integration Tests
```python
def test_rebuild_creates_valid_index():
    """Full rebuild produces schema-compliant index"""

def test_update_only_processes_new():
    """Incremental update skips unchanged files"""

def test_validate_catches_orphans():
    """--validate detects missing files and orphaned entries"""

def test_incremental_prunes_deleted():
    """--update removes index entries for deleted files"""

def test_validation_chunk_gaps():
    """--validate detects missing chunks in sequence"""

def test_dry_run_no_side_effects():
    """--dry-run doesn't modify filesystem"""
```

### 8.4 Performance Tests
- Benchmark full corpus (4,110 files)
- Memory profiling
- Incremental update timing

---

## 9. Future Enhancements (v2)

**NOT in v1 scope:**
- Topic extraction (requires LLM)
- Summary generation
- Semantic search embedding
- Conversation-level rollup
- Index compression
- Distributed processing

---

## 10. Dependencies

```
python >= 3.9
pyyaml >= 6.0
```

No additional dependencies for v1 core functionality.

---

## 11. Files

| File | Purpose |
|------|---------|
| `ai_general/scripts/chat_pipeline/build_chat_index.py` | Main script |
| `ai_general/docs/40_specs/spec_chat_history_indexer.md` | This spec |
| `ai_memories/40_histories/indexes/chat_history_index.yml` | Output index |

---

*Version: 1.0*
*Author: CLI (PID 57066)*
*Created: 2025-12-15*
*Reviewed: Codex CLI (2025-12-15) - addressed schema completeness, edge cases, deletion handling*
