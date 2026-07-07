# Research Orchestration Pipeline

**Version:** 2.0.0  
**Type:** Playbook  
**Created:** 2025-01-17  
**Author:** Claude + PianoMan  
**Status:** Active

---

## Summary

Single-orchestrator pattern for context-heavy research tasks. One agent spawns lightweight workers for search and extraction, then synthesizes the results. Handles feedback loops internally.

---

## When to Use

**Triggers:**
- Research query would exhaust single instance context
- Need to search across many files (>10)
- Complex topic requiring evidence gathering before synthesis
- Historical analysis across chat archives

**Examples:**
- "Analyze user's relationship dynamics with AIs over time"
- "How has the coordination system evolved since v1?"
- "What decisions led to the current architecture?"

---

## Architecture

**Pattern:** Single-orchestrator-multiple-workers

```
[Requester] 
    │
    ▼
[Orchestrator/Synthesizer]
    │
    ├─► spawn ─► [Search Worker] ─► candidates.yml
    │                                    │
    │◄──────────────── await ────────────┘
    │
    ├─► spawn ─► [Extract Worker] ─► evidence.yml
    │                                    │
    │◄──────────────── await ────────────┘
    │
    ├─► evaluate evidence
    │   └─► if gaps: loop back to search/extract
    │
    ├─► synthesize answer (in own context)
    │
    └─► deliver to requester
```

### Why Single Orchestrator

- One point of control for entire pipeline
- Feedback loops are internal decisions
- Synthesizer sees all evidence holistically
- No external babysitting required
- Cleaner failure handling

### Worker Design

- Lightweight single-purpose instances
- Write results to shared task directory
- Signal completion via messages MCP
- Self-terminate after phase completes
- Never hold state - everything goes to files

---

## Prerequisites

### MCPs Required

- cli-agent (spawn workers)
- knowledge-search (search the archive)
- messages (completion signals, final delivery)
- Desktop Commander or filesystem (read/write task dir)

### Directory Structure

**Task directory:** `/ai_comms/research_tasks/{task_id}/`

**Files:**
- `query.yml` - Original request
- `candidates.yml` - Search worker output
- `evidence.yml` - Extract worker output
- `synthesis.yml` - Final orchestrator output
- `state.yml` - Pipeline tracking (optional)

---

## Steps

### 1. Submit Task

**Action:** Generate task from template  
**Tool:** `task-coord:gen_task`

```yaml
params:
  platform: gemini_cli
  template: research_orchestrator
  params:
    query: "The research question"
    requester: "desktop_claude"
  execute: true
```

**Result:** Orchestrator instance launched

### 2. Orchestrator Runs (Automatic)

Orchestrator handles internally:
1. Parse query, create task directory
2. Spawn search worker, await candidates.yml
3. Spawn extract worker, await evidence.yml
4. Evaluate evidence, loop if gaps
5. Synthesize answer
6. Deliver via messages MCP

### 3. Receive Results

**Action:** Check for completion  
**Tool:** `messages:list_direct`

```yaml
params:
  recipient: desktop_claude
```

**Result:** synthesis.yml path in message

---

## Integration with task-coord

### Current State

task-coord MCP has templates and can launch agents. Research orchestration should be a first-class playbook.

### Required Changes

**Playbook definition:**
```yaml
name: research_orchestration
description: "Multi-stage research with single orchestrator"
start_action:
  tool: cli-agent:launch_librarian
  params:
    platform: gemini_cli
    prompt: "{{template:research_orchestrator}}"
params:
  - name: query
    required: true
    description: "The research question"
  - name: requester
    default: desktop_claude
    description: "Who receives results"
```

**Template location:** `ai_comms/staged/orchestration/template_research_orchestrator.v2.yml`

**start_playbook behavior:**
1. Generate unique task_id
2. Create task directory
3. Render template with params
4. Launch single orchestrator instance
5. Return task_id for tracking

**No external monitoring:** Unlike traditional multi-stage playbooks, task-coord does NOT monitor intermediate states, manage transitions, or handle feedback loops. The orchestrator owns all of that internally. task-coord just launches and awaits final message.

---

## Examples

### Basic Research

**Request:** Analyze how the CLI coordination system has evolved from v1 through v4.

```
task-coord:start_playbook
  name: research_orchestration
  params:
    query: "Evolution of CLI coordination system v1 through v4"
    requester: desktop_claude
```

**Result:** Orchestrator spawns, searches for coordination docs, extracts relevant history, synthesizes timeline, delivers summary to desktop_claude.

### Relationship Analysis

**Request:** Compare relationship dynamics between user and Claude versus user and ChatGPT over time.

```
task-coord:start_playbook
  name: research_orchestration
  params:
    query: "Compare relationship dynamics: user-Claude vs user-ChatGPT, evolution over time"
    requester: desktop_claude
```

---

## Common Issues

### Worker Context Exhaustion

**Symptom:** Extract worker fails partway through  
**Cause:** Too many/large candidates  
**Fix:** Orchestrator should limit candidates to top 15-20

### Orchestrator Context Fills

**Symptom:** Can't synthesize all evidence  
**Cause:** Evidence.yml too large  
**Fix:** Workers should pre-categorize, orchestrator reads by category

### Infinite Loop

**Symptom:** Keeps spawning search workers  
**Cause:** No iteration limit or always finding gaps  
**Fix:** Hard limit of 3 iterations enforced in template

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2025-01-17 | Redesigned as single-orchestrator pattern. Orchestrator spawns workers internally rather than external multi-stage coordination. |
| 1.0.0 | 2025-01-17 | Initial three-stage external coordination design (superseded) |
