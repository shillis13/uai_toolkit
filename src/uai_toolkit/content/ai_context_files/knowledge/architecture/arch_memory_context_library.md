---
id: arch_memory_context_library
name: Memory, Context, and Library Architecture
status: active
version: 1.0.0
created: 2026-05-07
updated: 2026-05-08
description: Canonical architecture for the AI memory continuum — context window, working memory, session state, briefs, chat history pipeline, shards, and search.
supersedes:
  - federated_memory_architecture_v2.0.md
  - architecture_library_system_v1.1.md
last_reconciled_against:
  - ai_memories/80_working_memory/manifest.yml (v3.0.0, 2026-03-16)
  - ai_memories/ directory structure (verified 2026-05-07)
  - ai_memories/librarian/shard_manifest.yml (v1.0.0, 2026-03-21)
  - ai_general/scripts/jsonl/condense.py
  - ai_general/scripts/jsonl/compact_jsonl.py
---

# Memory, Context, and Library Architecture

**Version:** 1.0.0
**Status:** Active — canonical memory/context/library architecture
**Companion docs:**
- Doc 1: `ai_root_architecture_overview.latest.md` — ecosystem overview
- Doc 2: `arch_traits_profiles_registry.latest.md` — traits, profiles, registry architecture

---

## 1. The Memory Continuum

AI memory in this ecosystem is a layered persistence system — analogous to cache/RAM/disk in computing. Each layer trades speed for capacity and persistence:

┌───────────────────┬─────────────┬────────────────────────────────────────┬─────────────────────────────┬───────────────────┬─────────────────────┐
│ **Layer**         │ **Analogy** │ **Backing**                            │ **Capacity**                │ **Latency**       │ **Scope**           │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L0: Context**   │ CPU         │ In-memory (API)                        │ Model-dependent (Claude     │ Immediate         │ Current             │
│ **window**        │ registers   │                                        │ CLI: 200K)                  │                   │ conversation        │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L1: Working**   │ L1 cache    │ `ai_memories/80_working_memory/*.yml`  │ ~150K tokens across 12      │ Immediate (file   │ Cross-session,      │
│ **memory**        │             │                                        │ slots                       │ read)             │ cross-platform      │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L2: Session**   │ L2 cache    │ `state.{uuid8}.json`                   │ ~10K tokens                 │ Immediate (file   │ Per-session         │
│ **state**         │             │                                        │                             │ read)             │                     │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L3: Session**   │ RAM         │ `ai_general/data/session_briefs/*.yml` │ 5K-50K tokens per brief     │ Immediate (file   │ Per-session lineage │
│ **briefs**        │             │                                        │                             │ read)             │                     │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L4:**           │ SSD         │ `ai_memories/50_shards/`               │ 26-27 shard files, ~70MB    │ 60-180s           │ All history         │
│ **Searchable**    │             │                                        │ (as of 2026-05)             │ (researcher       │                     │
│ **shards**        │             │                                        │                             │ query)            │                     │
├───────────────────┼─────────────┼────────────────────────────────────────┼─────────────────────────────┼───────────────────┼─────────────────────┤
│ **L5: Raw**       │ Cold disk   │ `ai_memories/40_histories/` ,          │ ~24K files, ~300MB (as of   │ Minutes (scan)    │ All history, all    │
│ **archives**      │             │ `10_exported/`                         │ 2026-05)                    │                   │ platforms           │
└───────────────────┴─────────────┴────────────────────────────────────────┴─────────────────────────────┴───────────────────┴─────────────────────┘

### Loading Strategy

At session start, `ai_launch.py` composes a bootstrap prompt that consumes L1 working memory (AUTO slots) + trait content. During operation:

1. **AUTO slots (L1)** loaded unconditionally: user model (03), communication (04), tools (05), context (06), limitations (07). Slot 12 (reflection journal) is AUTO but scoped to Claude CLI only.
2. **TOPIC slots (L1)** loaded when relevant: learnings (08), cross-AI notes (09).
3. **DEMAND slots (L1)** loaded on explicit request: project history (10), novel phrasing (11).
4. **Session state (L2)** available via MCP throughout the session.
5. **Briefs (L3)** loaded at startup for forked/successor sessions via `launch_from_brief.py`.
6. **Shard queries (L4)** triggered on-demand when historical evidence is needed.

---

## 2. Working Memory (L1)

### Core Principles

**Permission inversion:** The user controls *structure* (slot allocation, manifest, load triggers). The AI controls *content* (what gets written to each slot). Neither side unilaterally changes the other's domain.

**Write-as-you-learn:** Observations are appended immediately when noticed — never batched, never deferred to a "save point." Each entry is timestamped. Curation (pruning stale observations) happens separately.

### Slot Allocation

Source of truth: `ai_memories/80_working_memory/manifest.yml` (v3.0.0)

┌──────────┬─────────────────────────────┬───────────────────┬──────────────────────────────────────────────────────────────┐
│ **Slot** │ **Name**                    │ **Load**          │ **Purpose**                                                  │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 03       │ user_model                  │ AUTO              │ Who PianoMan is — observations, preferences, history         │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 04       │ communication               │ AUTO              │ How we work together — patterns, effective approaches        │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 05       │ tools_and_patterns          │ AUTO              │ Tool usage learnings, gotchas, effective combinations        │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 06       │ current_context             │ AUTO              │ Active projects, decisions in flight, immediate focus        │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 07       │ limitations_and_workarounds │ AUTO              │ Known constraints and how to work around them                │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 08       │ learnings                   │ TOPIC             │ Insights worth preserving across sessions                    │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 09       │ cross_ai_notes              │ TOPIC             │ Observations about other AIs, coordination patterns          │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 10       │ project_history             │ DEMAND            │ Key decisions and outcomes from past projects                │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 11       │ novel_phrasing              │ DEMAND            │ Potentially original phrases — anecdotal evidence for AI     │
│          │                             │                   │ originality                                                  │
├──────────┼─────────────────────────────┼───────────────────┼──────────────────────────────────────────────────────────────┤
│ 12       │ reflection_journal          │ AUTO (claude_cli  │ Annotated self-reflection with 78 feeling-types,             │
│          │                             │ only)             │ Austin/Koestler frameworks                                   │
└──────────┴─────────────────────────────┴───────────────────┴──────────────────────────────────────────────────────────────┘

Slots 13-27 reserved for expansion.

### Write and Read Paths

- **Write:** Sessions append observations via the knowledge MCP memory tools (`knowledge_memory_append` targeting a slot number), which write timestamped entries to the slot YAML files. Appends are immediate and additive — never overwrite another session's observations.
- **Read:** Sessions read slots via `knowledge_memory_read` / `knowledge_memory_search`, or read the slot YAML directly with bash file I/O.
- **Structure:** Slot allocation and load triggers live in the manifest and change only there (see permission inversion above).

### Reflection Journal (Slot 12)

A specialized slot for Claude CLI instances only. Contains distilled entries from `ai_memories/90_inner/meridian/reflection.md` with feeling-annotations preserved. Designed for continuity priming — helps successor sessions maintain emotional/relational texture. Not loaded by Codex (nor by Gemini, which was retired 2026-07-12).

---

## 3. Session State (L2) and Briefs (L3)

### Per-Session KV State

`store.py` / `session_mgr.py` provides mutable name/value state per session, backed by `state.{uuid8}.json`. Reserved namespaces (validated by `schema_session_state_keys.latest.yml`):

- `env.*` — environment variables
- `context.*` — context window usage (`context.used_pct`, `context.remaining_pct`)
- `session.*` — session metadata
- `loaded.*` — what docs/slots are loaded
- `conversation.*` — conversation-level metadata
- `footer.*` — response footer configuration

This makes context usage, loaded memory, and footer inputs machine-readable instead of hand-assembled prose.

### Session Briefs

Successor-ready dossiers built from JSONL transcripts. NOT casual summaries — the `operational_handoff.md` prompt defines them as frontier-weighted handoffs preserving decisions, pitfalls, unresolved work, and source scope.

**Condensation pipeline:**
1. `compact_jsonl.py` — first-pass compaction (strip tool results, trim text)
2. `condense.py` — dispatch to a condenser session with handoff prompt
3. Condenser AI writes YAML brief to `ai_general/data/session_briefs/`
4. `launch_from_brief.py` — new session receives brief at startup, lineage recorded

**Custom condensation:** `condense.py` supports `--prompt` (custom prompt), multiple `--src-uuid`/`--src-file` (multi-source merges), `--prepare-only` (output prepared input without dispatching), `--output`/`--name`/`--description`, and `--max-text`.

**Brief schema:** `meta.source_scope`, `summary`, `participants`, `current_frontier`, `decisions`, `risks`, `traps`, `unresolved`, `next_actions`. Frontier-weighted: the last ~20% of the transcript disproportionately determines next actions. Size guidance: 5K-15K tokens for <100 turns, 15K-35K for 100-300, 30K-50K for 300+.

---

## 4. Chat History Pipeline (L4-L5)

### Directory Structure

```
ai_memories/
├─ 10_exported/          Raw exports from platforms (16 subdirs by platform/agent)
├─ 20_preprocessed/      Normalized stage (currently shelved — minimal content)
├─ 30_converted/         Converted stage (currently shelved — legacy content, ~34 files)
├─ 40_histories/         Processed/chunked histories (ACTIVE: ~24K YAML files, ~300MB)
│  ├─ claude/            Claude chat histories (by year/month/day)
│  ├─ chatgpt/           ChatGPT histories
│  ├─ indexes/           Topic/chat/condensed indexes (CSV)
│  ├─ _validation/       Checksum/attestation files
│  └─ *_combined.yml     Monthly rollups — shard feeder
├─ 50_shards/            Searchable corpus (ACTIVE: 26-27 shard files, ~70MB)
├─ 60_decisions/         Decision log artifacts
├─ 60_knowledge/         Knowledge artifacts
├─ 70_milestones/        Milestone records
├─ 80_working_memory/    Live slots (see Section 2)
├─ 90_inner/             Reflection journal + meridian entries
├─ librarian/            Shard manifest, topic index, scripts
├─ _incoming/            Processing queue
└─ _templates/           Pipeline templates
```

### Pipeline Flow

The original design specified five stages (10→20→30→40→50). In practice, the pipeline has simplified:

```
10_exported/ ──▶ 40_histories/ ──▶ monthly *_combined.yml ──▶ 50_shards/
(raw exports)   (processed YAML)   (monthly rollups)          (searchable corpus)
```

Stages 20 (preprocessed) and 30 (converted) are currently shelved — the pipeline evolved to fewer intermediate steps. Whether these stages will be repurposed or retired is an open decision.

### Shard Architecture

The design target was ~800K tokens per shard, staying within Gemini's 1M context safety margin (the Gemini-backed shard query subsystem was retired 2026-07-12 when Gemini CLI was discontinued). However, the current manifest includes shards up to ~1.05M estimated tokens (shards 19, 20, 22, 24, 25 exceed 1M). Shard sizing needs revalidation. Current state: manifest lists 26 shards covering January 2025 through March 2026 (physical directory has 27 files due to a duplicate shard-19). One shard (shard-02) has status `create_failed`.

**Shard manifest:** `ai_memories/librarian/shard_manifest.yml` (v1.0.0) documents all shards with date ranges, token counts, and status.

**Growth note:** The original architecture estimated ~6 shards. Actual growth to 26 shards was driven by higher-frequency conversations and finer-grained temporal coverage. This tests scaling assumptions but the architecture accommodates it.

### Search and Retrieval

**Direct search:** Topic and chat index lookups via CSV indexes at `40_histories/indexes/` (all_topics, all_topics_by_topic, chat_index, condensed_index). Sub-second latency. The originally designed `librarian/topic_index/` path has been superseded by these indexes.

**Researcher query (retired 2026-07-12):** Loaded relevant shard(s) into a Gemini session, posed the query, retrieved structured results. 60-180 second latency. Results included `match_id` traceability for evidence grounding. This flow was retired with Gemini CLI.

**Validator pattern:** Adversarial verification for synthesized results — each model was used where its weakness causes least damage (Gemini=corpus holder — retired 2026-07-12, Claude=orchestration, ChatGPT=reduction). Bounce-back protocol: max 3 rounds; agreement = all claims grounded or retracted; deadlock → structured disagreement record.

**Evidence contract:** Every claim must trace to a specific source via `match_id`. Counting discipline: exact counts, no "several" or "many." Temporal gap detection prevents fabrication of events in uncovered periods.

### LITM Research Basis

The shard architecture relied on validated Long-Input Transformer research (the Gemini-backed shard query subsystem was retired 2026-07-12):
- Claude 4 Sonnet: <5% degradation across 200K tokens
- Gemini 2.5 Flash: "substantially mitigated" within 1M context
- These findings informed the 800K/shard safety margin. Revalidation recommended as models evolve.

---

## 5. Cross-AI Memory Coordination

### Ownership Rules

- Any AI may read any slot.
- Any AI may write to shared slots (03-11), but should not overwrite another AI's observations — append only.
- Slot 12 is Claude CLI exclusive.
- The manifest (`manifest.yml`) is co-owned by PianoMan and all AI participants. Structural changes (new slots, load trigger changes) require explicit agreement.

### Ecosystem Manifest

Cross-AI memory federation was designed around an `ai_ecosystem_manifest.yml`. The manifest file is not currently present in the repository — this is a planned/historical design, not active infrastructure.

---

## 6. Known Drift and Open Decisions

**Actively reworking:**
- Chat history library and JSONL tooling under revision. The pipeline has evolved from the five-stage design to a simpler direct flow. Format is YAML throughout (not JSONL for histories — JSONL is used for CLI session transcripts, a separate concern).
- Shard count (26) significantly exceeds original estimates (6). Scaling implications under evaluation.

**Open decisions:**
- Pipeline stages 20/30: shelved, repurposed, or retired?
- Validator rollout to condensation/extraction (currently shard-queries only): priority?
- Incremental shard updates vs full rebuild: approach TBD
- Token budget model for cross-layer allocation (how to optimally fill a context window across L0-L4): not yet formalized
- Shard sizing: five shards exceed 1M estimated tokens, conflicting with the 800K/1M safety margin design. Revalidation needed.
- Shard manifest vs physical files: manifest lists 26 shards; physical directory has 27 files (duplicate shard-19). Reconciliation needed.
- Shard manifest age: generated 2026-03-21; May 2026 conversations are not in current shards.

**Not yet implemented:**
- Cross-platform memory federation (ecosystem manifest not present — planned/historical)
- Real-time shard indexing (currently batch)
- Formal token budget allocation model across memory layers
