# Working Memory Protocol

```yaml
metadata:
  title: Working Memory Protocol
  version: 3.0.0
  created: 2026-03-16
  authors: [PianoMan, Claude Desktop]
  supersedes: instr_memory_slot_protocol_v2.0.yml (claude-specific)
  status: active
  location: ai_general/docs/70_instructions/versions/instr_working_memory_protocol_v3.0.md
```

## Overview

The working memory system provides persistent, shared memory for all AI participants
in ai_root. Memory survives across sessions and is accessible to all AIs with
filesystem access.

**One source of truth:** `ai_memories/80_working_memory/`

All AIs read the manifest to understand slot purposes. All AIs write to slot files
as insights occur. No AI writes to another AI's dedicated slot without coordination.

---

## Directory Structure

```
ai_memories/80_working_memory/
├── manifest.yml          # Slot registry — what each slot is for
├── 01.yml                # Ecosystem registry pointer (reserved)
├── 03.yml                # User model
├── 04.yml                # Communication patterns
├── 05.yml                # Tool/pattern discoveries
├── 06.yml                # Current context notes
├── 07.yml                # Cross-AI notes
├── 08.yml                # Learnings worth preserving
├── 09.yml                # Project history
├── 11.yml                # Novel phrasing / originality evidence
└── _archive_20251213/    # Historical entries
```

Slots 12–27 are reserved for expansion. Any AI may claim one — declare it in
`manifest.yml` first.


---

## Reading Memory

All AIs with filesystem access read slot files directly via Desktop Commander:

```
AI_ROOT/ai_memories/80_working_memory/manifest.yml
AI_ROOT/ai_memories/80_working_memory/{NN}.yml
```

**At session start:**
1. Read `manifest.yml` — understand what each slot is for
2. Load AUTO-tier slots (03, 04, 05, 06 minimum)
3. Load TOPIC slots as conversation triggers arise
4. Load DEMAND slots only when explicitly needed

**Web/iOS Claude** cannot read files directly. A snapshot of the working memory
directory is uploaded to Project Files and maintained by Desktop/CLI Claude.
Web/iOS reads the snapshot at session start.

---

## Writing Memory

### Desktop / CLI Claude (filesystem access)

Write observations **immediately as insights occur** — never batch or checkpoint:

```yaml
# Append to the appropriate slot file
- {ts: 2026-03-16T14:30:00Z, content: "observation text"}
```

Full entry format (all fields):
```yaml
- ts: 2026-03-16T14:30:00Z
  type: learning | observation | pattern | shortcut | issue
  content: "the insight"
  context: "optional — what prompted this"
  reads: 0
```

`reads` is optional. Increment when you re-read an entry. High reads = keep.
Zero reads after time = archive candidate.


### Web / iOS Claude (no filesystem access)

Submit memory updates as message inserts. The cron pipeline harvests these and
Desktop/CLI Claude commits them to slot files.

```
<<<INSERT type=memory_v1.1 v=1>>>
{
  "type": "MEMORY",
  "slot_hint": 8,
  "topic": "brief topic label",
  "content": "the observation or insight",
  "importance": "high | medium | low"
}
<<<END INSERT>>>
```

`slot_hint` is a suggestion, not a binding assignment. Desktop Claude may place
the entry in a different slot based on content.

---

## What to Log

**Always log:**
- User preferences not already in documentation
- Decisions made with rationale
- Workarounds discovered
- Tool behaviours confirmed through use
- Patterns that worked (or failed)
- Insights about the relationship or communication style

**Log if likely to matter later:**
- Project state worth carrying forward
- Open questions to revisit
- Cross-AI coordination notes

**Never log:**
- Transient session details
- Info already in documentation
- Sensitive data (tokens, passwords, personal data)
- Task-specific details (those belong in task result files)

---

## Claiming a New Slot

1. Check `manifest.yml` — confirm the slot is in the reserved range (12–27)
2. Add a declaration to `manifest.yml` under the `slots` section:
   ```yaml
   '15':
     name: your_slot_name
     purpose: what this slot holds
     load: AUTO | TOPIC | DEMAND
     tags: [trigger1, trigger2]
     owner: optional — only if AI-specific
   ```
3. Create the slot file: `ai_memories/80_working_memory/15.yml`
4. Note the claim in your session so other AIs see it at next boot


---

## Cross-AI Memory Access

All AIs may read all slots. No AI writes to a slot declared as owned by another
AI without coordination.

To understand another AI's recent context: read their relevant slots directly.
To pass information to another AI: use the task coordination system or
messaging protocol — don't write into their slots unilaterally.

---

## Archiving

When a slot file grows large (~50KB) or contains many stale entries:

1. Move old entries (older than ~3 months, low reads) to:
   `ai_memories/80_working_memory/_archive_{YYYYMM}/`
2. Keep recent and high-read entries in the live slot file
3. Note the archive action with a timestamp entry in the slot

---

## Maintenance

The `manifest.yml` is the authoritative registry. If you evolve a slot's purpose,
update its declaration in the manifest and add a note explaining the change.

Slot files are append-only by default. Rewriting is permitted for curation
(removing truly obsolete entries) but should be infrequent.

The Project Files snapshot (for Web/iOS read access) should be re-uploaded by
Desktop/CLI Claude whenever significant new entries have been added — roughly
weekly or after major sessions.

---

## Related Documents

- `manifest.yml` — slot registry with load tiers and tags
- `spec_message_insert` — full insert block specification
- `instr_working_memory` — condensed operational quick-reference
- `protocol_federated_memory` → retired; superseded by this document
