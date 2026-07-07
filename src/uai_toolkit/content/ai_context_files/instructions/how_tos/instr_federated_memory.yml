# Working Memory — Operational Guide

```yaml
metadata:
  title: Working Memory Operational Guide
  version: 2.0.0
  created: 2026-03-16
  authors: [PianoMan, Claude Desktop]
  supersedes: instr_federated_memory_v1.0 (concept rename + path update)
  status: active
```

## Core Principle

Write observations immediately. Curate later.

## Philosophy

- **not_checkpoints**: write as insight occurs, don't wait for session end
- **append_only**: add entries, don't rewrite files
- **self_defined**: manifest defines slot purposes, evolve as needed
- **shared**: all AI participants read/write the same location

## Location

```
ai_memories/80_working_memory/
  manifest.yml        ← read this first — slot purposes + load tiers
  03.yml              ← user model
  04.yml              ← communication patterns
  05.yml              ← tool/pattern discoveries
  06.yml              ← current context
  07.yml              ← cross-AI notes
  08.yml              ← learnings
  09.yml              ← project history
  11.yml              ← novel phrasing / originality evidence
```

## Entry Format

```yaml
- {ts: 2026-03-16T14:30:00Z, content: "brief observation"}
```

Full form when needed:
```yaml
- ts: 2026-03-16T14:30:00Z
  type: learning | observation | pattern | shortcut | issue
  content: "the insight"
  context: "what prompted this"
  reads: 0
```

## Write Paths

| Platform | How to write |
|---|---|
| Desktop / CLI | `edit_block` append to slot file directly |
| Web / iOS | `<<<INSERT type=memory_v1.1>>>` block inline |

## What to Log

- patterns discovered, shortcuts learned, mistakes to avoid
- user preferences not in docs, decisions with rationale
- cross-AI coordination notes, process improvements
- questions worth revisiting later

## Cross-Reference

- **Allowed**: read any AI's slots
- **Never**: write to another AI's declared slot unilaterally
- Use task coordination to pass information to other AIs

## Full Protocol

`REF:ai_general/docs/70_instructions/versions/instr_working_memory_protocol_v3.0.md`
