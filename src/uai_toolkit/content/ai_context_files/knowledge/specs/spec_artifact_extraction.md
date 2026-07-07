# Artifact Extraction Specification

**Version:** 1.0
**Status:** Draft - Pending Review
**Author:** CLI (req_2201)
**Date:** 2025-12-15

## Overview

Extract large code blocks, pasted files, and tables from chat history chunk files to separate artifact files, replacing them with minimal pointers.

**Primary Goal:** Reduce chunk file sizes while preserving all content and enabling byte-perfect restoration.

## Critical Constraint: Lessons from req_1032

The previous attempt FAILED because:
1. Verbose placeholders (60-80 chars each)
2. Added YAML metadata (extractions array, extraction_summary)
3. Files became LARGER, not smaller

**This implementation:**
- Uses 26-byte max placeholders: `[-> artifacts/code_001.py]`
- Adds ZERO new YAML metadata to chunks
- Verifies size REDUCTION before writing
- Enables byte-perfect restore via manifest

## Placeholder Format

```
[-> artifacts/code_001.py]
```

**26-28 bytes typical** (varies by extension). No byte counts, no descriptions, no metadata inline.

Using ASCII `->` (2 chars, 2 bytes) instead of Unicode `→` (1 char, 3 bytes) for simplicity.
Extensions: `.py`=26b, `.js`=26b, `.yml`=27b, `.json`=28b, `.md`=27b

## File Structure

```
{conversation_dir}/
├── artifacts/                    # NEW directory
│   ├── code_001.py              # Extracted code block
│   ├── code_002.js
│   ├── file_001.sh              # Extracted pasted file
│   ├── table_001.md             # Extracted table
│   └── manifest.yml             # Tracks all extractions
├── conversation.chunk_001.yml   # Modified: content → pointer
├── conversation.chunk_002.yml
└── ...
```

## Manifest Format

The manifest is the ONLY place metadata lives. Chunks remain clean.

```yaml
# artifacts/manifest.yml
version: "1.0"
created: "2025-12-15T05:00:00Z"
updated: "2025-12-15T05:00:00Z"
extractions:
  - id: code_001
    file: code_001.py
    source_chunk: conversation.chunk_002.yml
    original_position: 1523  # byte offset in original chunk content
    original_length: 4256    # bytes of original content
    placeholder: "[-> artifacts/code_001.py]"
    language: python
    lines: 87

  - id: table_001
    file: table_001.md
    source_chunk: conversation.chunk_003.yml
    original_position: 892
    original_length: 2100
    placeholder: "[-> artifacts/table_001.md]"
    rows: 45
```

## Extraction Rules

### What to Extract

| Type | Detection | Threshold | Output |
|------|-----------|-----------|--------|
| Code block | Triple backtick fenced | >20 lines OR >1KB | `code_NNN.{ext}` |
| Pasted file | Header pattern + content | >20 lines | `file_NNN.{ext}` |
| Large table | Markdown table syntax | >20 rows | `table_NNN.md` |

### Configurable Thresholds

```bash
--min-lines 20      # Minimum lines for extraction (default: 20)
--min-bytes 1024    # Minimum bytes for extraction (default: 1024)
--table-rows 20     # Minimum table rows (default: 20)
```

### Language Detection

```
python, py → .py
javascript, js → .js
typescript, ts → .ts
bash, sh, shell → .sh
yaml, yml → .yml
json → .json
sql → .sql
go → .go
rust → .rs
(none/unknown) → .txt
```

## CLI Interface

```bash
# Dry run - show what would be extracted (NO CHANGES)
python3 extract_artifacts.py --dry-run <chunk_file>
python3 extract_artifacts.py --dry-run --dir <conversation_dir>

# Single file extraction
python3 extract_artifacts.py <chunk_file>

# All chunks in conversation
python3 extract_artifacts.py --dir <conversation_dir>

# Batch with safety checks
python3 extract_artifacts.py --batch <directory> --min-reduction 10

# Validate existing extractions
python3 extract_artifacts.py --validate <conversation_dir>

# Restore from artifacts (reconstruct original)
python3 extract_artifacts.py --restore <conversation_dir>

# Configurable thresholds
python3 extract_artifacts.py --min-lines 15 --min-bytes 512 <chunk_file>
```

## Safety Requirements

1. **Backup before modify:** Create `.bak` file before ANY chunk modification
2. **Size verification:** ABORT if modified chunk ≥ original size
3. **YAML validity:** Parse output as YAML before writing
4. **Atomic writes:** Write to temp file, then rename
5. **Manifest integrity:** Update manifest atomically
6. **Restore verification:** `--validate` must pass after `--restore`

## Algorithm

### Extraction Process

```
1. Parse chunk YAML
2. For each message content:
   a. Find code blocks matching thresholds
   b. Find pasted files matching patterns
   c. Find tables matching thresholds
3. For each match:
   a. Generate artifact filename
   b. Calculate replacement savings (original_bytes - 26)
   c. If total savings > 0:
      - Write artifact file
      - Replace content with placeholder
      - Record in manifest
4. Calculate new chunk size
5. IF new_size >= original_size:
   - Log warning
   - Skip this chunk (don't write)
   - Continue to next chunk
6. ELSE:
   - Write backup
   - Write modified chunk atomically
   - Update manifest
```

### Restore Process

```
1. Read manifest.yml
2. For each extraction (in reverse order by position):
   a. Read artifact file content
   b. Read chunk file
   c. Find placeholder in chunk content
   d. Replace placeholder with original content
   e. Write restored chunk
3. Verify restored chunk matches backup (if available)
4. Delete artifacts/ directory (optional flag)
```

## Edge Cases

1. **Nested code blocks:** Content containing ``` inside code
   - Solution: Track fence depth, match opening/closing

2. **Code in YAML strings:** Content already escaped
   - Solution: Parse YAML properly, work on string values

3. **Empty code blocks:** ``` with no content
   - Solution: Skip, no savings possible

4. **Already extracted:** Placeholder already present
   - Solution: Detect `[-> artifacts/` pattern, skip

5. **Unicode content:** Non-ASCII in code
   - Solution: Use UTF-8 throughout, byte counts

6. **Very long single lines:** 10KB single line of code
   - Solution: Still extract if >min-bytes

7. **Multiple code blocks, one message:** Several small blocks
   - Solution: Only extract those meeting thresholds

8. **Manifest conflicts:** Multiple runs
   - Solution: Append to manifest with unique IDs

## Output Formats

### Dry Run Output

```
=== DRY RUN: conversation.chunk_002.yml ===
Current size: 34,789 bytes

Detected extractions:
  1. Code block (python): lines 45-132, 3,456 bytes → code_001.py
  2. Code block (bash): lines 200-245, 1,892 bytes → code_002.sh
  3. Table: 35 rows, 1,200 bytes → table_001.md

Total extractable: 6,548 bytes
Placeholder overhead: 78 bytes (3 × 26)
Net reduction: 6,470 bytes

Projected size: 28,322 bytes (-18.6%)

[Would create artifacts/code_001.py, code_002.sh, table_001.md]
[Would update artifacts/manifest.yml]
```

### Validation Output

```
=== VALIDATE: 2025-11-03_specifying_ai_story_teller ===
Checking artifacts/manifest.yml... OK (5 extractions)
Checking artifacts exist:
  - code_001.py: OK (3,456 bytes)
  - code_002.sh: OK (1,892 bytes)
  - table_001.md: OK (1,200 bytes)
Checking placeholders in chunks:
  - chunk_002.yml: 2 placeholders found, 2 expected ✓
  - chunk_003.yml: 1 placeholder found, 1 expected ✓
Restore test (memory only):
  - chunk_002.yml: matches backup ✓
  - chunk_003.yml: matches backup ✓

Validation: PASSED
```

## Success Criteria

- [ ] Dry-run accurately predicts changes
- [ ] All modified chunks are SMALLER than originals
- [ ] Placeholder format is exactly `[-> artifacts/filename]`
- [ ] Zero YAML metadata added to chunk files
- [ ] `--restore` reconstructs original EXACTLY
- [ ] `--validate` passes after any operation
- [ ] Thresholds configurable via CLI
- [ ] All edge cases handled
- [ ] Backup created before any modification
- [ ] Atomic writes prevent corruption

## Dependencies

- Python 3.8+
- PyYAML
- Standard library only (no external deps beyond PyYAML)

## Notes

- Directory is `artifacts/` not `_artifacts/` (application data, not system)
- Manifest tracks byte positions for restore accuracy
- Consider: conversation index (req_2200) can validate before/after
