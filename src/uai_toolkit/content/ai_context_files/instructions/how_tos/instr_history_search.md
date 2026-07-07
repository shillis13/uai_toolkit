---
id: history_search
name: History & JSONL Search
status: active
version: 1.0.0
created: 2026-04-19
updated: 2026-04-19
---

# History & JSONL Search — Lessons and Techniques

Methods for effectively searching CLI session histories (JSONL files) and the conversation archive.

## JSONL Session Files

### Structure
- Claude Code stores sessions as JSONL at `~/.claude/projects/{sanitized-cwd-path}/{uuid}.jsonl`
- Each line is a JSON object with: role (user/assistant), content, tool_use/tool_result pairs, thinking blocks
- JSONL is the sole source of truth — the API is stateless, full history reconstructed each call
- `compact_boundary` markers cause all pre-boundary messages to be dropped, replaced with a summary

### Searching JSONL Files

**Recommended workflow: jgrep → read_jsonl**

1. **`jgrep "pattern" <uuid>`** — Search for content and get turn numbers
   - Returns matching turns with turn numbers
   - Use to locate WHERE in a conversation something was discussed
   - Supports regex patterns

2. **`read_jsonl read <uuid>`** — Read specific turn ranges
   - Interactive REPL tool (type commands at the `jsonl>` prompt)
   - By default hides tool_use/tool_result messages (use `toggle` to show)
   - Use turn numbers from jgrep to read the relevant context

3. **`read_jsonl` other commands:**
   - `read_jsonl list` — list recent sessions across platforms
   - `read_jsonl summary <uuid>` — quick stats (message counts, timestamps)
   - `read_jsonl find <uuid>` — print the file path for a session

**Key: jgrep finds the turns, read_jsonl reads them in context.**

### Finding the Right Session

When asked to find a specific session:
1. Start with `read_jsonl list` for active sessions
2. For historical sessions, search the session registry database
3. Use content-based grep if UUID is unknown: `grep -rl "keyword" ~/.claude/projects/`

### Important: Transcripts ARE the Memory

A resumed session has no hidden state beyond its transcript. There is no "experiential memory" — the session reconstructs entirely from the JSONL. Reading the transcript gives you exactly the same information as resuming the session. Read the JSONL directly rather than resuming sessions to "get their experience."

## Lesson: Iterate Filters, Not Search Space

**When filtering narrows candidates to zero, fix the filter — don't abandon the candidate pool.**

Example failure: Asked to find a JSONL session file. Broad keyword grep found 64 candidates. Date-filtering by first-line timestamp silently dropped files whose first line lacked a timestamp (e.g., `file-history-snapshot` metadata). Result was zero matches, and instead of questioning the filter, searched unrelated directories. The answer was in the original pool all along.

### Rules:
- If a filter over known-good candidates returns nothing, **the filter is suspect** — try alternative methods (file mod time, deeper content grep, file size, different metadata fields)
- **Silent drops are dangerous**: when a pipeline step can't extract a value, surface it as "unknown" rather than discarding the entry
- 64 content-matched candidates → 0 after date filter = **the date filter is broken, not the data**
- Never abandon a working candidate pool to search elsewhere — fix the narrowing step first

## JSONL Technical Details

### Safe Edits
- Remove complete turns (user+assistant pairs)
- Strip all thinking blocks
- Remove content after a `compact_boundary`

### Unsafe Edits (will break the session)
- Modify thinking block signatures (encrypted content, required for multi-turn continuity)
- Orphan tool_results (every tool_result needs a paired tool_use)
- Break UUID chains
- Empty-string thinking without content causes 400 API errors

### Key Concepts
- `compact_boundary` — compaction marker; all pre-boundary messages replaced with summary
- Thinking block signatures — encrypted thinking content; tampering causes "Invalid signature" errors
- `--fork-session` — copies JSONL with new session ID
- Tool_use/tool_result must always be paired or the API rejects the request

## Conversation Archive Search

For searching the condensed conversation archive (not JSONL), use:
- `knowledge_search` — semantic search over chunked/condensed histories
- `knowledge_grep_search` — regex search over full content
- For complex research: use the `research_orchestration` skill (dispatch Gemini shards)

See: `knowledge_how_to('research_orchestration')` for the full multi-shard workflow.
