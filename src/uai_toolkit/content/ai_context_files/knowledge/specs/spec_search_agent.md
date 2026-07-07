---
id: spec_search_agent
name: Search Agent
status: active
version: 1.0.0
created: '2026-03-21'
updated: '2026-04-15'
---

# Search Agent Evolution: v1.0 → v2.5

**Document:** spec_search_agent.latest.md  
**Version:** 2.5.0  
**Date:** 2026-01-16  
**Status:** Active  
**Location:** ai_general/docs/40_specs/

---

## Executive Summary

The Gemini-based Search Agent provides intelligent search and question-answering over PianoMan's 3+ year AI conversation archive (~500 chats, ~4700 condensed chunks). Evolution from v1 to v2.5 transformed it from a basic grep wrapper into a dual-mode system capable of both curated search results and editorial synthesis with citations.

**Key Achievement:** v2.5 correctly answered "What problems have we had with Chatty?" with a 5-category synthesis citing 9 sources - vs v2's wrong inference that "Chatty" was a browser extension.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Search Agent v2.5                          │
├─────────────────────────────────────────────────────────────────┤
│  Mode Detection                                                 │
│  ├─ "Find X" / "Search for X" → SEARCH mode                    │
│  └─ "What is X?" / "Why did..." → ANSWER mode                  │
├─────────────────────────────────────────────────────────────────┤
│  4-Layer Search Cascade (case-insensitive)                      │
│  ├─ Layer 1: Topics index - original terms                      │
│  ├─ Layer 2: Topics index - with synonyms                       │
│  ├─ Layer 3: Content search - original terms                    │
│  └─ Layer 4: Content search - with synonyms                     │
├─────────────────────────────────────────────────────────────────┤
│  Index Sources                                                  │
│  ├─ all_topics.latest.csv (6600 rows - topic→chat mapping)     │
│  ├─ chat_index.latest.csv (500 chats - metadata)               │
│  └─ condensed_index.latest.csv (4700 chunks - file paths/sizes)│
├─────────────────────────────────────────────────────────────────┤
│  Output Options                                                 │
│  ├─ Display only (default)                                      │
│  ├─ Write results file                                          │
│  ├─ Retrieve artifacts (copy condensed files)                   │
│  └─ Full retrieval (both)                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Version Evolution

| Version | Date | Key Changes |
|---------|------|-------------|
| v1.0 | 2026-01-15 | Basic search, no curation, unlimited results |
| v2.0 | 2026-01-16 | Result limits (5-10), "Why relevant", synthesis |
| v2.1 | 2026-01-16 | Layered fallback (topics → titles → content) |
| v2.2 | 2026-01-16 | Case-insensitive mandatory, 4-layer cascade, synonyms |
| v2.3 | 2026-01-16 | Size/token reporting, chunk-level granularity |
| v2.4 | 2026-01-16 | File output, artifact retrieval, manifest generation |
| **v2.5** | **2026-01-16** | **Dual mode: SEARCH vs ANSWER** |

---

## Response Modes

### SEARCH Mode (Default for "find", "search", "list")

Returns curated list of matching documents with metadata.

```markdown
## Search: "{query}"

**Found:** {N} conversations | **Showing:** Top {M} by relevance
**Search path:** Layer {1-4} - {description}
**Total size:** ~{X}K tokens

### Most Relevant

1. **{title}** ({platform}, {date})
   - chat_id: `{id}` | {messages} messages | {chunks} chunks
   - **Size:** {bytes} bytes (~{tokens}K tokens)
   - **Why relevant:** {explanation}
   - Signals: {decisions ✓} {discoveries ✓}

### Patterns Noticed
{synthesis across results}

### To Go Deeper
- Specific chat: `cat {path}`
```

### ANSWER Mode (Default for questions)

Synthesizes editorial answer with inline citations.

```markdown
## Question: "{query}"

### Answer

**Summary:** {1-2 sentence direct answer}

**Details:**
1. **{Point 1}** - {Explanation with context} [1][2]
2. **{Point 2}** - {Explanation} [3]
3. **{Point 3}** - {Explanation} [4][5]

**Caveats:** {If applicable}

### Sources
[1] `{chat_id}` - {title} ({platform}, {date}) | ~{tokens}K tokens | {why_cited}
[2] ...

### To Verify
- Primary: `cat {most_relevant_path}`
- Related: {other_paths}
```

---

## Test Results Comparison

### Test 7: "What problems have we had with Chatty?"

| Aspect | v2 Result | v2.5 Result |
|--------|-----------|-------------|
| Mode | SEARCH | ANSWER |
| Inference | ❌ Wrong ("Chatty" = browser extension) | ✓ Correct ("Chatty" = ChatGPT) |
| Format | 3 results listed | Editorial synthesis |
| Problems identified | 0 | **5 categories** |
| Citations | Results listed, not cited | **9 inline citations** |
| Token sizes | None | ✓ All sources sized |
| Actionable | "Here are chats" | "Here's what happened" |

**v2.5 Output Excerpt:**
```markdown
**Summary:** The primary issues with ChatGPT ("Chatty") revolve around 
fabricating information, leading to trust issues. Other problems include 
context limitations, instruction adherence, and automation challenges.

**Details:**
1. **Fabrication & Trust Issues:** ...multiple instances...led to 
   "damaged trust"...relationship now functional but cautious. [1][2][3][4]
2. **Context Limitations:** ...struggles in longer conversations... [5]
3. **Instruction Adherence:** ...custom instructions don't persist... [6]
4. **Integration Challenges:** ...Puppeteer workarounds required... [7]
5. **General Errors:** ...circular reference, output issues... [8][9]

### Sources
[1] `686f3b18` - personal.background_work_fabrication | ~6.5K tokens
[2] `685cc7f9` - ai.fabrication_detection | ~4.2K tokens
[3] `689b9c8e` - ai.trust_betrayal | ~11.9K tokens
...
```

### Other Test Results (v2)

| Test | Query | v2 Performance |
|------|-------|----------------|
| 1 | MCP timeout | ✓ 1 result, key finding extracted |
| 2 | Memory slots | ✓ 29 found → Top 4 with "Why relevant" |
| 3 | October | ✓ 78 found → Top 5 + thematic summary |
| 4 | YAML decision | ✓ 1 result + key finding date |
| 5 | CLI evolution | ✓ 22 found → Timeline narrative |
| 6 | Cryptocurrency | ❌ False negative (case-sensitive) |
| 7 | Chatty problems | ❌ Wrong inference |

Tests 6 & 7 fixed in v2.2+ (case-insensitive, synonyms, ANSWER mode).

---

## MCP Function Specification

```python
def search_knowledge_base(
    query: str,
    mode: Literal["search", "answer", "auto"] = "auto",
    use_synonyms: bool = True,
    max_results: int = 10,
    granularity: Literal["chat", "chunk"] = "chat",
    max_tokens: int | None = None,
    output_file: bool = False,
    retrieve_artifacts: bool = False,
    retrieval_dir: str | None = None
) -> SearchResults | AnswerWithSources:
    """
    Search the AI conversation knowledge base.
    
    Args:
        query: Search terms or question
        mode: "search" for results list, "answer" for editorial synthesis,
              "auto" detects from query format
        use_synonyms: Expand search with synonym table
        max_results: Maximum results to return (SEARCH mode)
        granularity: "chat" returns whole conversations, "chunk" returns 
                     specific chunks within conversations
        max_tokens: Optional budget constraint - stops when cumulative 
                    tokens would exceed
        output_file: Write results to timestamped .md file
        retrieve_artifacts: Copy matching condensed files to retrieval dir
        retrieval_dir: Custom retrieval directory (default: timestamped)
    
    Returns:
        SearchResults: List of matches with metadata (SEARCH mode)
        AnswerWithSources: Editorial synthesis with citations (ANSWER mode)
    """
```

### Response Schema

```python
@dataclass
class SearchResult:
    chat_id: str
    title: str
    platform: str  # claude, chatgpt, gemini
    date: str
    message_count: int
    chunk_count: int
    total_size_bytes: int
    estimated_tokens: int
    has_decisions: bool
    has_discoveries: bool
    has_procedures: bool
    has_artifacts: bool
    matching_chunks: list[int]  # Which chunks matched
    condensed_path: str
    match_layer: int  # 1-4
    relevance_score: float
    why_relevant: str

@dataclass
class AnswerWithSources:
    question: str
    summary: str
    details: list[AnswerPoint]
    caveats: str | None
    sources: list[Citation]
    verification_paths: list[str]
    total_source_tokens: int
```

---

## Synonym Table

| Original | Expands To |
|----------|------------|
| cryptocurrency | crypto, bitcoin, ethereum, blockchain, defi, web3 |
| ChatGPT | chatgpt, chatty, gpt |
| memory | mem, slot, persistence, context |
| problem | issue, error, bug, failure, trouble |
| decision | decided, chose, choice, selected, why |
| Claude | claude, anthropic |
| automation | automate, automated, auto, script |

---

## Key Design Decisions

### 1. Case-Insensitive by Default
**Problem:** v2 missed cryptocurrency results because `grep` was case-sensitive.  
**Solution:** All searches use `grep -i`. No exceptions.

### 2. 4-Layer Cascade
**Problem:** Single-layer search either returns too many irrelevant results or misses content.  
**Solution:** Start narrow (topics), expand progressively (synonyms, then content).

### 3. Dual Response Modes
**Problem:** Users sometimes want "find documents about X" and sometimes want "answer my question about X".  
**Solution:** Auto-detect from query format, allow override.

### 4. Mandatory Size Reporting
**Problem:** No way to budget context before loading files.  
**Solution:** Every result shows `bytes (~tokens)`. Running totals for retrieval.

### 5. Chunk-Level Granularity
**Problem:** A 58-chunk chat might have topic in only chunk 23.  
**Solution:** Optional chunk-level results for precision retrieval.

---

## File Locations

```
ai_comms/gemini_cli/prompts/
├── search_agent_v1.md       # Archived
├── search_agent_v2.md       # Archived  
├── search_agent_v2.2.md     # Archived
├── search_agent_v2.3.md     # Archived
├── search_agent_v2.4.md     # Archived
└── search_agent_v2.5.md     # ACTIVE

ai_comms/gemini_cli/tasks/outputs/
├── search_test_v2_results_20260116.md
└── answer_test_chatty_problems_20260116.md  # v2.5 ANSWER mode success

ai_memories/40_histories/indexes/
├── all_topics.latest.csv      # 6600 topic→chat mappings
├── chat_index.latest.csv      # 500 chat metadata records
└── condensed_index.latest.csv # 4700 chunk file records
```

---

## Future Enhancements

### v2.6 Candidates
- [ ] Search path indication in ANSWER mode ("Found via Layer 2 - synonyms")
- [ ] Running total for sources ("Total cited: ~67K tokens")
- [ ] Relevance filtering for ANSWER mode (exclude tangential sources)
- [ ] Confidence indicators for synthesized claims

### MCP Integration
- [ ] Implement as Desktop Commander MCP function
- [ ] Add to Claude Desktop tool palette
- [ ] Consider real-time index updates

### Cross-Platform
- [ ] Expose via public API for iOS/web access
- [ ] Integrate with CLI agents for autonomous research

---

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-15 | 1.0 | Initial search agent |
| 2026-01-16 | 2.0 | Curation rules, result limits |
| 2026-01-16 | 2.2 | Case-insensitive, synonyms |
| 2026-01-16 | 2.3 | Size/token reporting |
| 2026-01-16 | 2.4 | File output, retrieval |
| 2026-01-16 | 2.5 | Dual mode (SEARCH/ANSWER) |
