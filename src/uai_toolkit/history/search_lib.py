#!/usr/bin/env python3
"""
Search library for AI conversation knowledge base.

Extracted from knowledge-search MCP server.py to follow
"thin wrapper around scripts" pattern.

Provides:
- CSV index loading (topics, chat, condensed)
- Chat ID extraction with regex
- 4-layer search cascade
- Synonym expansion
- Compound query matching
- Grep-based content search
- Result building and formatting
"""

import os
import re
import csv
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal, Any
from dataclasses import dataclass, asdict


# === Configuration ===
_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT
MEMORIES_ROOT = AI_ROOT / "ai_memories"
INDEXES_DIR = MEMORIES_ROOT / "40_histories/indexes"
HISTORIES_DIR = MEMORIES_ROOT / "40_histories"
OUTPUTS_DIR = AI_ROOT / "ai_comms/gemini_cli/tasks/outputs"

# Index files
TOPICS_INDEX = INDEXES_DIR / "all_topics.latest.csv"
CHAT_INDEX = INDEXES_DIR / "chat_index.latest.csv"
CONDENSED_INDEX = INDEXES_DIR / "condensed_index.latest.csv"

# Synonym expansions - bidirectional semantic mappings
SYNONYMS = {
    "cryptocurrency": ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "web3"],
    "chatgpt": ["chatgpt", "chatty", "gpt", "openai"],
    "memory": ["mem", "slot", "persistence", "context"],
    "problem": ["issue", "error", "bug", "failure", "trouble", "trust", "fabricat"],
    "decision": ["decided", "chose", "choice", "selected", "why"],
    "claude": ["claude", "anthropic"],
    "automation": ["automate", "automated", "auto", "script"],
    "trust": ["trust", "fabricat", "hallucin", "lie", "honest", "betray", "breakdown"],
    "fabrication": ["fabricat", "hallucin", "lie", "made_up", "invented", "fake"],
    "chatty": ["chatty", "chatgpt", "gpt", "openai"],
}

# Compound query expansions - when these terms appear together, add these search terms
COMPOUND_EXPANSIONS = {
    frozenset(["chatty", "problem"]): ["trust", "fabricat", "error", "issue", "breakdown"],
    frozenset(["chatgpt", "problem"]): ["trust", "fabricat", "error", "issue", "breakdown"],
    frozenset(["chatty", "issue"]): ["trust", "fabricat", "error", "breakdown"],
    frozenset(["ai", "problem"]): ["trust", "fabricat", "error", "limitation"],
    frozenset(["ai", "trust"]): ["fabricat", "betray", "breakdown", "honest"],
}


# === Data Classes ===

@dataclass
class SearchResult:
    chat_id: str
    title: str
    platform: str
    date: str
    message_count: int
    chunk_count: int
    total_size_bytes: int
    estimated_tokens: int
    has_decisions: bool
    has_discoveries: bool
    has_procedures: bool
    has_artifacts: bool
    condensed_path: str
    match_layer: int
    why_relevant: str


@dataclass
class Citation:
    index: int
    chat_id: str
    title: str
    platform: str
    date: str
    tokens: int
    why_cited: str


# === Index Loading ===

def load_topics_index() -> list[dict]:
    """Load all_topics.latest.csv into memory."""
    if not TOPICS_INDEX.exists():
        return []

    topics = []
    with open(TOPICS_INDEX, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            topics.append(row)
    return topics


def load_chat_index() -> dict[str, dict]:
    """Load chat_index.latest.csv keyed by 8-char hex chat_id."""
    if not CHAT_INDEX.exists():
        return {}

    chats = {}
    with open(CHAT_INDEX, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Extract 8-char hex from chat_name
            chat_name = row.get('chat_name', '')
            chat_id = extract_chat_id(chat_name)
            if chat_id:
                # Also store useful fields
                row['title'] = chat_name.split('.')[-1] if '.' in chat_name else chat_name
                row['message_count'] = row.get('total_tokens', 0)  # Approximate
                chats[chat_id] = row
    return chats


def load_condensed_index() -> dict[str, list[dict]]:
    """Load condensed_index.latest.csv grouped by 8-char hex chat_id."""
    if not CONDENSED_INDEX.exists():
        return {}

    condensed = {}
    with open(CONDENSED_INDEX, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Extract 8-char hex from chat_id field or filename
            chat_id_field = row.get('chat_id', '')
            filename = row.get('filename', '')

            chat_id = extract_chat_id(chat_id_field) or extract_chat_id(filename)
            if chat_id:
                if chat_id not in condensed:
                    condensed[chat_id] = []
                condensed[chat_id].append(row)
    return condensed


def extract_chat_id(text: str) -> str:
    """Extract 8-char hex chat_id from various formats.

    The chat_id is always an 8-char hex that contains at least one letter (a-f).
    This distinguishes it from dates like 20221221 which are all digits.

    Handles:
    - chatgpt.20250710.686f3b18.title -> 686f3b18
    - 20251123.32843ee2.title -> 32843ee2
    - claude.20251123.32843ee2.title.001.condensed.yml -> 32843ee2
    - 686f3b18 (already 8-char hex) -> 686f3b18
    """
    # Direct 8-char hex with at least one letter
    if re.match(r'^[a-f0-9]{8}$', text) and re.search(r'[a-f]', text):
        return text

    # Find all 8-char hex sequences between dots (use lookahead to not consume trailing dot)
    matches = re.findall(r'\.([a-f0-9]{8})(?=\.)', text)
    for m in matches:
        if re.search(r'[a-f]', m):  # Must contain at least one letter
            return m

    # Pattern at start: date.hex.title (no leading dot)
    match = re.search(r'^(\d{8})\.([a-f0-9]{8})(?=\.)', text)
    if match and re.search(r'[a-f]', match.group(2)):
        return match.group(2)

    return ""


# === Search Functions ===

def expand_with_synonyms(terms: list[str]) -> list[str]:
    """Expand search terms with synonyms and compound expansions."""
    expanded = set(terms)
    terms_lower = set(t.lower() for t in terms)

    # Normalize plurals for compound matching (simple stemming)
    normalized_terms = set()
    for t in terms_lower:
        normalized_terms.add(t)
        if t.endswith('s') and len(t) > 3:
            normalized_terms.add(t[:-1])  # problems -> problem
        if t.endswith('ing') and len(t) > 5:
            normalized_terms.add(t[:-3])  # having -> hav (rough but works)

    # Individual term synonyms
    for term in terms:
        term_lower = term.lower()
        for key, syns in SYNONYMS.items():
            if term_lower == key or term_lower in syns:
                expanded.update(syns)
            # Also check without trailing 's'
            if term_lower.endswith('s') and (term_lower[:-1] == key or term_lower[:-1] in syns):
                expanded.update(syns)

    # Compound query expansions - check if term pairs match (using normalized terms)
    for compound_key, compound_terms in COMPOUND_EXPANSIONS.items():
        if compound_key.issubset(normalized_terms):
            expanded.update(compound_terms)

    return list(expanded)


def search_topics(terms: list[str], topics: list[dict]) -> list[dict]:
    """Search topics index for matching terms (case-insensitive).

    Returns matches with 'match_score' = number of terms matched.
    """
    # Create pattern for matching
    pattern = '|'.join(re.escape(t) for t in terms)
    regex = re.compile(pattern, re.IGNORECASE)

    # Create individual term patterns for scoring
    term_patterns = [(t, re.compile(re.escape(t), re.IGNORECASE)) for t in terms]

    matches = []
    seen_chats = set()

    for row in topics:
        topic = row.get('topic', '')
        chat_id = row.get('chat_id', '')

        if regex.search(topic) and chat_id not in seen_chats:
            # Count how many terms match this topic
            match_score = 0
            matched_terms = []
            for term, term_re in term_patterns:
                if term_re.search(topic):
                    match_score += 1
                    matched_terms.append(term)

            row_copy = dict(row)
            row_copy['match_score'] = match_score
            row_copy['matched_terms'] = matched_terms
            matches.append(row_copy)
            seen_chats.add(chat_id)

    # Sort by match_score descending
    matches.sort(key=lambda x: -x.get('match_score', 0))
    return matches


def grep_chunk_files(terms: list[str], max_results: int = 50) -> list[dict]:
    """Grep full chunk files for terms (case-insensitive).

    Searches actual chunk content (more text = more keyword hits).
    Returns paths to both chunk and corresponding condensed file.
    """
    pattern = '|'.join(re.escape(t) for t in terms)
    regex = re.compile(pattern, re.IGNORECASE)

    matches = []
    seen_chats = set()

    # Walk through chunk files (*.yml but NOT *.condensed.yml)
    for chunk_file in HISTORIES_DIR.rglob("*.yml"):
        if len(matches) >= max_results:
            break

        # Skip condensed files and index files
        if '.condensed.' in chunk_file.name:
            continue
        if chunk_file.parent.name == 'indexes':
            continue

        chat_id = extract_chat_id(chunk_file.name)
        if not chat_id or chat_id in seen_chats:
            continue

        try:
            content = chunk_file.read_text(encoding='utf-8')
            if regex.search(content):
                # Derive condensed path from chunk path
                condensed_name = chunk_file.name.replace('.yml', '.condensed.yml')
                condensed_path = chunk_file.parent / condensed_name

                matches.append({
                    'chat_id': chat_id,
                    'chunk_path': str(chunk_file),
                    'condensed_path': str(condensed_path) if condensed_path.exists() else None,
                    'match_context': extract_match_context(content, regex)
                })
                seen_chats.add(chat_id)
        except Exception:
            continue

    return matches


def extract_match_context(content: str, regex: re.Pattern, context_chars: int = 100) -> str:
    """Extract context around first match."""
    match = regex.search(content)
    if not match:
        return ""

    start = max(0, match.start() - context_chars)
    end = min(len(content), match.end() + context_chars)

    context = content[start:end]
    # Clean up YAML artifacts
    context = re.sub(r'\s+', ' ', context).strip()
    return f"...{context}..."


def grep_search_core(
    query: str,
    use_synonyms: bool = True,
    max_results: int = 50
) -> tuple[list[dict], bool]:
    """
    Grep full chunk files for query terms.

    Returns (matches, used_synonyms) where used_synonyms indicates
    if synonym expansion was needed to find results.
    """
    query_clean = re.sub(r'[^\w\s]', ' ', query.lower())
    terms = [t.strip() for t in query_clean.split() if len(t.strip()) > 2]
    if not terms:
        terms = [query.lower()]

    all_matches = {}
    used_synonyms = False

    # First pass: original terms
    matches = grep_chunk_files(terms, max_results)
    for m in matches:
        cid = m.get('chat_id')
        if cid:
            all_matches[cid] = {**m, 'score': 1}

    # Second pass: with synonyms (if enabled and need more results)
    if use_synonyms:
        expanded_terms = expand_with_synonyms(terms)
        if set(expanded_terms) != set(terms):  # Only if synonyms added something
            matches = grep_chunk_files(expanded_terms, max_results)
            for m in matches:
                cid = m.get('chat_id')
                if cid:
                    if cid in all_matches:
                        all_matches[cid]['score'] += 1
                    else:
                        all_matches[cid] = {**m, 'score': 1}
                        used_synonyms = True

    sorted_matches = sorted(all_matches.values(), key=lambda x: -x['score'])
    return sorted_matches[:max_results], used_synonyms


def four_layer_search(
    query: str,
    use_synonyms: bool = True,
    max_results: int = 50,
    thorough: bool = False
) -> tuple[list[dict], int]:
    """
    Execute 4-layer search cascade.
    Returns (matches, layer_found).

    If thorough=True, runs ALL layers and combines results (for ANSWER mode).
    If thorough=False, stops at first layer with 3+ results (for SEARCH mode).
    """
    # Parse query into terms - remove punctuation
    query_clean = re.sub(r'[^\w\s]', ' ', query.lower())
    terms = [t.strip() for t in query_clean.split() if len(t.strip()) > 2]
    if not terms:
        terms = [query.lower()]

    topics = load_topics_index()
    all_matches = {}  # chat_id -> match dict with score
    best_layer = 0

    # Layer 1: Topics - original terms
    matches = search_topics(terms, topics)
    for m in matches:
        cid = m.get('chat_id')
        if cid:
            all_matches[cid] = {**m, 'score': m.get('match_score', 1), 'layer': 1}
    if matches and not thorough:
        if len(matches) >= 3:
            return matches[:max_results], 1
    best_layer = 1 if matches else 0

    # Layer 2: Topics - with synonyms (ALWAYS run if use_synonyms)
    if use_synonyms:
        expanded_terms = expand_with_synonyms(terms)
        matches = search_topics(expanded_terms, topics)
        for m in matches:
            cid = m.get('chat_id')
            if cid:
                new_score = m.get('match_score', 1)
                if cid in all_matches:
                    # Take better score
                    all_matches[cid]['score'] = max(all_matches[cid]['score'], new_score)
                else:
                    all_matches[cid] = {**m, 'score': new_score, 'layer': 2}
        if matches and not thorough:
            if len(matches) >= 3:
                # Return combined results sorted by score
                sorted_matches = sorted(all_matches.values(), key=lambda x: -x['score'])
                return sorted_matches[:max_results], 2
        best_layer = max(best_layer, 2 if matches else 0)

    # Layer 3: Content - original terms
    content_matches = grep_chunk_files(terms, max_results)
    for m in content_matches:
        cid = m.get('chat_id')
        if cid:
            if cid in all_matches:
                all_matches[cid]['score'] += 1
                all_matches[cid]['match_context'] = m.get('match_context', '')
            else:
                all_matches[cid] = {**m, 'score': 1, 'layer': 3}
    if content_matches and not thorough:
        if len(all_matches) >= 3:
            sorted_matches = sorted(all_matches.values(), key=lambda x: -x['score'])
            return sorted_matches[:max_results], 3
    best_layer = max(best_layer, 3 if content_matches else best_layer)

    # Layer 4: Content - with synonyms
    if use_synonyms:
        expanded_terms = expand_with_synonyms(terms)
        content_matches = grep_chunk_files(expanded_terms, max_results)
        for m in content_matches:
            cid = m.get('chat_id')
            if cid:
                if cid in all_matches:
                    all_matches[cid]['score'] += 1
                    if not all_matches[cid].get('match_context'):
                        all_matches[cid]['match_context'] = m.get('match_context', '')
                else:
                    all_matches[cid] = {**m, 'score': 1, 'layer': 4}
        best_layer = max(best_layer, 4 if content_matches else best_layer)

    # Return combined results sorted by score
    sorted_matches = sorted(all_matches.values(), key=lambda x: -x['score'])
    return sorted_matches[:max_results], best_layer if sorted_matches else 0


# === Result Building ===

def build_search_results(
    matches: list[dict],
    layer: int,
    chat_index: dict,
    condensed_index: dict
) -> list[SearchResult]:
    """Convert raw matches to SearchResult objects with metadata."""
    results = []

    for match in matches:
        chat_id = match.get('chat_id', '')
        if not chat_id:
            continue

        # Get chat metadata
        chat_meta = chat_index.get(chat_id, {})

        # Get condensed files for this chat
        chunks = condensed_index.get(chat_id, [])
        total_bytes = sum(int(c.get('size_bytes', 0)) for c in chunks)

        # Find first condensed path
        condensed_path = ""
        if chunks:
            condensed_path = chunks[0].get('path', '')

        result = SearchResult(
            chat_id=chat_id,
            title=chat_meta.get('title', match.get('topic', 'Unknown')),
            platform=chat_meta.get('platform', 'unknown'),
            date=chat_meta.get('start_date', chat_meta.get('date', '')),
            message_count=int(chat_meta.get('message_count', 0)),
            chunk_count=len(chunks),
            total_size_bytes=total_bytes,
            estimated_tokens=total_bytes // 4,
            has_decisions=str(chat_meta.get('has_decisions', False)).lower() == 'true',
            has_discoveries=str(chat_meta.get('has_discoveries', False)).lower() == 'true',
            has_procedures=str(chat_meta.get('has_procedures', False)).lower() == 'true',
            has_artifacts=str(chat_meta.get('has_artifacts', False)).lower() == 'true',
            condensed_path=condensed_path,
            match_layer=layer,
            why_relevant=match.get('topic', match.get('match_context', ''))
        )
        results.append(result)

    return results


# === Mode Detection ===

def detect_mode(query: str) -> Literal["search", "answer"]:
    """Detect whether query is a search or question."""
    query_lower = query.lower().strip()

    # Question patterns -> ANSWER mode
    question_patterns = [
        r'^what\s',
        r'^why\s',
        r'^how\s',
        r'^when\s',
        r'^who\s',
        r'^explain\s',
        r'^describe\s',
        r'\?$',
    ]

    for pattern in question_patterns:
        if re.search(pattern, query_lower):
            return "answer"

    # Search patterns -> SEARCH mode
    search_patterns = [
        r'^find\s',
        r'^search\s',
        r'^list\s',
        r'^show\s',
        r'^locate\s',
    ]

    for pattern in search_patterns:
        if re.search(pattern, query_lower):
            return "search"

    # Default to search
    return "search"


# === Output Formatting ===

def format_search_output(
    query: str,
    results: list[SearchResult],
    layer: int,
    max_results: int = 10
) -> str:
    """Format results for SEARCH mode."""
    total_found = len(results)
    shown = results[:max_results]
    total_tokens = sum(r.estimated_tokens for r in shown)

    layer_desc = {
        1: "Topics - original terms",
        2: "Topics - with synonyms",
        3: "Content - original terms",
        4: "Content - with synonyms",
        0: "No matches found"
    }

    output = [
        f'## Search: "{query}"',
        f'',
        f'**Found:** {total_found} conversations | **Showing:** Top {len(shown)} by relevance',
        f'**Search path:** Layer {layer} - {layer_desc.get(layer, "Unknown")}',
        f'**Total size:** ~{total_tokens // 1000}K tokens',
        f'',
        f'### Most Relevant',
        f''
    ]

    for i, r in enumerate(shown, 1):
        signals = []
        if r.has_decisions: signals.append("decisions ✓")
        if r.has_discoveries: signals.append("discoveries ✓")
        if r.has_procedures: signals.append("procedures ✓")
        if r.has_artifacts: signals.append("artifacts ✓")
        signals_str = " | ".join(signals) if signals else "none"

        output.extend([
            f'{i}. **{r.title}** ({r.platform}, {r.date})',
            f'   - chat_id: `{r.chat_id}` | {r.message_count} messages | {r.chunk_count} chunks',
            f'   - **Size:** {r.total_size_bytes:,} bytes (~{r.estimated_tokens // 1000}K tokens)',
            f'   - **Why relevant:** {r.why_relevant[:200]}',
            f'   - Signals: {{{signals_str}}}',
            f''
        ])

    # Patterns noticed
    platforms = {}
    for r in shown:
        platforms[r.platform] = platforms.get(r.platform, 0) + 1

    output.extend([
        f'### Patterns Noticed',
        f'- Platform distribution: {", ".join(f"{p}: {c}" for p, c in platforms.items())}',
        f'- Total searchable tokens in shown results: ~{total_tokens:,}',
        f'',
        f'### To Go Deeper',
        f'- Specific chat: `cat {shown[0].condensed_path}`' if shown else '- No results to explore'
    ])

    return '\n'.join(output)


def format_answer_output(
    query: str,
    results: list[SearchResult],
    layer: int
) -> str:
    """Format results for ANSWER mode - editorial synthesis."""
    if not results:
        return f'## Question: "{query}"\n\n### Answer\n\nNo relevant information found in the knowledge base.'

    # Group results by theme for synthesis
    total_tokens = sum(r.estimated_tokens for r in results[:10])

    output = [
        f'## Question: "{query}"',
        f'',
        f'### Answer',
        f'',
        f'**Summary:** Based on {len(results)} relevant conversations found via Layer {layer} search.',
        f'',
        f'**Details:**',
        f''
    ]

    # Create numbered points from top results
    for i, r in enumerate(results[:5], 1):
        output.append(f'{i}. **{r.title}** - {r.why_relevant[:150]}... [{i}]')
        output.append('')

    # Sources section
    output.extend([
        f'### Sources'
    ])

    for i, r in enumerate(results[:10], 1):
        output.append(
            f'[{i}] `{r.chat_id}` - {r.title} ({r.platform}, {r.date}) | '
            f'~{r.estimated_tokens // 1000}K tokens | {r.why_relevant[:50]}'
        )

    # Verification
    output.extend([
        f'',
        f'### To Verify',
        f'- Primary source: `cat {results[0].condensed_path}`' if results else ''
    ])

    return '\n'.join(output)


def format_grep_output(
    query: str,
    results: list[SearchResult],
    used_synonyms: bool,
    return_format: str,
    max_results: int
) -> str:
    """Format grep search results."""
    total_found = len(results)
    shown = results[:max_results]
    total_tokens = sum(r.estimated_tokens for r in shown)

    synonym_note = " (with synonyms)" if used_synonyms else ""

    output = [
        f'## Grep Search: "{query}"',
        f'',
        f'**Method:** Regex over full chunk content{synonym_note}',
        f'**Return format:** {return_format}',
        f'**Found:** {total_found} conversations | **Showing:** {len(shown)}',
        f'**Total size:** ~{total_tokens // 1000}K tokens',
        f'',
        f'### Results',
        f''
    ]

    for i, r in enumerate(shown, 1):
        output.extend([
            f'{i}. **{r.title}** ({r.platform}, {r.date})',
            f'   - chat_id: `{r.chat_id}`',
            f'   - **Match:** {r.why_relevant[:200]}',
            f'   - Path: `{r.condensed_path}`',
            f''
        ])

    return '\n'.join(output)


# === File Output ===

def write_results_file(content: str, prefix: str = "search_results") -> str:
    """Write results to timestamped markdown file."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{timestamp}.md"
    filepath = OUTPUTS_DIR / filename
    filepath.write_text(content, encoding='utf-8')
    return str(filepath)


def retrieve_artifacts(
    results: list[SearchResult],
    retrieval_dir: Optional[str] = None
) -> str:
    """Copy condensed files to retrieval directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if retrieval_dir:
        dest_dir = Path(retrieval_dir)
    else:
        dest_dir = OUTPUTS_DIR / f"retrieval_{timestamp}"

    dest_dir.mkdir(parents=True, exist_ok=True)

    # Create manifest
    manifest = {
        "timestamp": timestamp,
        "total_files": 0,
        "total_bytes": 0,
        "files": []
    }

    for r in results:
        if r.condensed_path:
            src = Path(r.condensed_path)
            if not src.is_absolute():
                src = HISTORIES_DIR / r.condensed_path.lstrip('./')

            if src.exists():
                dest = dest_dir / src.name
                shutil.copy2(src, dest)
                manifest["files"].append({
                    "chat_id": r.chat_id,
                    "title": r.title,
                    "filename": src.name,
                    "size_bytes": r.total_size_bytes,
                    "why_relevant": r.why_relevant[:100]
                })
                manifest["total_files"] += 1
                manifest["total_bytes"] += r.total_size_bytes

    # Write manifest
    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    return str(dest_dir)


# === High-Level API Functions (called by MCP server) ===

def search_knowledge_base(
    query: str,
    mode: str = "auto",
    use_synonyms: bool = True,
    max_results: int = 10,
    granularity: str = "chat",
    max_tokens: Optional[int] = None,
    output_file: bool = False,
    retrieve_artifacts_flag: bool = False,
    retrieval_dir: Optional[str] = None
) -> dict:
    """
    Main search function.

    Args:
        query: Search terms or question
        mode: "search", "answer", or "auto" (detect from query)
        use_synonyms: Expand search with synonym table
        max_results: Maximum results to return
        granularity: "chat" or "chunk" level results
        max_tokens: Optional budget constraint
        output_file: Write results to .md file
        retrieve_artifacts_flag: Copy condensed files to retrieval dir
        retrieval_dir: Custom retrieval directory

    Returns:
        Dict with results, metadata, and optional file paths
    """
    # Detect mode if auto
    if mode == "auto":
        mode = detect_mode(query)

    # Execute search (thorough mode for ANSWER to get best results)
    thorough = (mode == "answer")
    matches, layer = four_layer_search(query, use_synonyms, max_results * 2, thorough=thorough)

    # Load indexes for metadata
    chat_index = load_chat_index()
    condensed_index = load_condensed_index()

    # Build results
    results = build_search_results(matches, layer, chat_index, condensed_index)

    # Apply token budget if specified
    if max_tokens:
        filtered = []
        running_total = 0
        for r in results:
            if running_total + r.estimated_tokens <= max_tokens:
                filtered.append(r)
                running_total += r.estimated_tokens
            else:
                break
        results = filtered

    # Format output based on mode
    if mode == "answer":
        formatted = format_answer_output(query, results, layer)
    else:
        formatted = format_search_output(query, results, layer, max_results)

    # Build response
    response = {
        "query": query,
        "mode": mode,
        "layer_used": layer,
        "total_found": len(matches),
        "results_returned": len(results),
        "total_tokens": sum(r.estimated_tokens for r in results),
        "formatted_output": formatted,
        "results": [asdict(r) for r in results[:max_results]]
    }

    # Optional outputs
    if output_file:
        prefix = "answer" if mode == "answer" else "search"
        filepath = write_results_file(formatted, prefix)
        response["output_file"] = filepath

    if retrieve_artifacts_flag:
        retrieval_path = retrieve_artifacts(results, retrieval_dir)
        response["retrieval_dir"] = retrieval_path

    return response


def grep_search(
    query: str,
    use_synonyms: bool = True,
    max_results: int = 10,
    return_format: str = "condensed",
    output_file: bool = False
) -> dict:
    """
    Grep search - regex search over full chunk file contents.

    Args:
        query: Search terms
        use_synonyms: Expand with synonym table
        max_results: Maximum results
        return_format: "condensed" (token-efficient) or "full" (complete content)
        output_file: Write to .md file
    """
    matches, used_synonyms = grep_search_core(query, use_synonyms, max_results * 2)

    chat_index = load_chat_index()
    condensed_index = load_condensed_index()

    # Build results with appropriate paths based on return_format
    results = []
    for match in matches[:max_results]:
        chat_id = match.get('chat_id', '')
        if not chat_id:
            continue

        chat_meta = chat_index.get(chat_id, {})
        chunks = condensed_index.get(chat_id, [])
        total_bytes = sum(int(c.get('size_bytes', 0)) for c in chunks)

        # Select path based on return_format
        if return_format == "full":
            result_path = match.get('chunk_path', '')
        else:
            result_path = match.get('condensed_path') or match.get('chunk_path', '')

        result = SearchResult(
            chat_id=chat_id,
            title=chat_meta.get('title', match.get('match_context', 'Unknown')[:50]),
            platform=chat_meta.get('platform', 'unknown'),
            date=chat_meta.get('start_date', chat_meta.get('date', '')),
            message_count=int(chat_meta.get('message_count', 0)),
            chunk_count=len(chunks),
            total_size_bytes=total_bytes,
            estimated_tokens=total_bytes // 4,
            has_decisions=str(chat_meta.get('has_decisions', False)).lower() == 'true',
            has_discoveries=str(chat_meta.get('has_discoveries', False)).lower() == 'true',
            has_procedures=str(chat_meta.get('has_procedures', False)).lower() == 'true',
            has_artifacts=str(chat_meta.get('has_artifacts', False)).lower() == 'true',
            condensed_path=result_path,
            match_layer=2 if used_synonyms else 1,  # grep layers
            why_relevant=match.get('match_context', '')
        )
        results.append(result)

    # Format output
    formatted = format_grep_output(query, results, used_synonyms, return_format, max_results)

    response = {
        "query": query,
        "mode": "grep_search",
        "return_format": return_format,
        "used_synonyms": used_synonyms,
        "total_found": len(matches),
        "results_returned": len(results),
        "total_tokens": sum(r.estimated_tokens for r in results),
        "formatted_output": formatted,
        "results": [asdict(r) for r in results]
    }

    if output_file:
        filepath = write_results_file(formatted, "grep_search")
        response["output_file"] = filepath

    return response


def get_search_stats() -> dict:
    """Get index statistics."""
    topics = load_topics_index()
    chat_index = load_chat_index()
    condensed_index = load_condensed_index()

    total_chunks = sum(len(chunks) for chunks in condensed_index.values())
    total_bytes = 0
    for chunks in condensed_index.values():
        for c in chunks:
            total_bytes += int(c.get('size_bytes', 0))

    return {
        "topics_count": len(topics),
        "chats_count": len(chat_index),
        "chunks_count": total_chunks,
        "total_bytes": total_bytes,
        "estimated_tokens": total_bytes // 4,
        "indexes": {
            "topics": str(TOPICS_INDEX),
            "topics_exists": TOPICS_INDEX.exists(),
            "chat": str(CHAT_INDEX),
            "chat_exists": CHAT_INDEX.exists(),
            "condensed": str(CONDENSED_INDEX),
            "condensed_exists": CONDENSED_INDEX.exists()
        }
    }


def test_server() -> dict:
    """Test server connectivity."""
    stats = get_search_stats()
    return {
        "server": "knowledge-search",
        "version": "2.5.0",
        "status": "ok",
        "ai_root": str(AI_ROOT),
        "ai_root_exists": AI_ROOT.exists(),
        "indexes": stats["indexes"],
        "stats": {
            "topics": stats["topics_count"],
            "chats": stats["chats_count"],
            "chunks": stats["chunks_count"]
        }
    }
