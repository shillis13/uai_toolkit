# Research Orchestration Pipeline

**Version:** 3.0.0  
**Type:** Playbook  
**Created:** 2025-01-17  
**Author:** Claude + PianoMan  
**Status:** ACTIVE

> **Retargeted 2026-07-12** — The v2 pipeline dispatched Gemini CLI "shards" as its
> 1M-context corpus engine; Gemini CLI was discontinued upstream. This version
> repoints all dispatch onto the current stack: ephemeral **subagents** (the Agent
> tool) for in-session fan-out, and **`sessions_launch_agent`** (Claude Code / Codex
> CLI worker sessions) for large-context or long-running work. The
> decompose → dispatch → collect → synthesize pattern is unchanged.

---

## Summary

Single-orchestrator pattern for context-heavy research tasks. One agent decomposes the
query, dispatches lightweight workers for search and extraction, collects their results,
then synthesizes the answer. Handles feedback loops internally.

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
[Orchestrator/Synthesizer]  (decompose)
    │
    ├─► dispatch ─► [Search Worker] ─► candidates
    │                                     │
    │◄──────────────── collect ───────────┘
    │
    ├─► dispatch ─► [Extract Worker] ─► evidence
    │                                     │
    │◄──────────────── collect ───────────┘
    │
    ├─► evaluate evidence
    │   └─► if gaps: loop back to search/extract
    │
    ├─► synthesize answer (in own context)
    │
    └─► deliver to requester
```

### Two Dispatch Modes

Choose per-task; you can mix them:

- **Subagents (default) — the `Agent` tool.** Ephemeral, in-session workers
  (`subagent_type: general-purpose` or `Explore`). Their final message is returned
  straight to the orchestrator — no files, no comms round-trip. Fan out several at
  once by issuing multiple `Agent` calls in a single message. Best for most research:
  the worker burns its own context on search/read, the orchestrator keeps only the
  distilled result.
- **CLI worker sessions — `sessions_launch_agent`.** Persistent Claude Code / Codex
  CLI sessions with full bash + filesystem. Use when a worker needs a large/1M
  context window, must run long, or must survive beyond the orchestrator's turn.
  These write results to the task directory and signal completion over the **comms**
  MCP; the orchestrator waits with `comms_wait_response` / `comms_check_messages`.

### Why Single Orchestrator

- One point of control for entire pipeline
- Feedback loops are internal decisions
- Synthesizer sees all evidence holistically
- No external babysitting required
- Cleaner failure handling

### Worker Design

- Lightweight single-purpose instances
- Subagent workers return their result as the final message; session workers write
  results to the shared task directory
- Session workers signal completion via the **comms** MCP; subagents complete when the
  `Agent` call returns
- Self-terminate after phase completes (subagents end automatically; session workers
  exit or are reaped with `sessions_kill`)
- Never hold state across phases — everything goes into the returned result or a file

---

## Prerequisites

### Tools Required

- **Agent** tool (ephemeral subagent workers) — always available in-session
- **sessions** MCP (`sessions_launch_agent`, `sessions_list`, `sessions_read_session`,
  `sessions_kill`) — for CLI worker sessions when large-context / long-running work is needed
- **knowledge** MCP (`knowledge_search`, `knowledge_get_context`, `knowledge_how_to`,
  `knowledge_condense_history`) — search and retrieve from the archive
- **comms** MCP (`comms_send_prompt`, `comms_wait_response`, `comms_check_messages`,
  `comms_message`) — dispatch/collect for session workers, and final delivery
- Filesystem access — plain Read/Write/bash (Claude Code / Codex CLI have full
  filesystem), or the **filesystem** MCP

### Directory Structure

Subagent workers need no task directory — their result comes back as the `Agent`
return value. Use a task directory only when dispatching **session** workers that must
write results to disk.

**Task directory:** `$AI_SESSION_DIR/research_tasks/{task_id}/` (or any scratch path)

**Files (session-worker mode):**
- `query.yml` - Original request
- `candidates.yml` - Search worker output
- `evidence.yml` - Extract worker output
- `synthesis.yml` - Final orchestrator output
- `state.yml` - Pipeline tracking (optional)

---

## Steps

The orchestrator is the session running this playbook — it runs these steps directly
in its own context. There is no separate "submit" step; you *are* the orchestrator.

### 1. Decompose

Parse the query into search and extraction sub-tasks. Decide dispatch mode: default to
**subagents**; escalate to **session workers** if a sub-task needs a large context
window or must outlive this turn. If using session workers, pick a `task_id` and create
the task directory.

### 2. Dispatch Search

Fan out one or more search workers to find candidate sources across the archive.

**Subagent mode:**
```
Agent
  subagent_type: Explore          # or general-purpose
  description: "Find candidate sources"
  prompt: |
    Search the knowledge archive (knowledge_search / knowledge_grep_search) and the
    filesystem for material relevant to: "<sub-query>". Return the top 15-20 candidates
    as a YAML list of {path, why_relevant, snippet}. Do not synthesize.
```
Issue multiple `Agent` calls in one message to run searches concurrently.

**Session-worker mode:**
```
sessions_launch_agent
  platform: claude_cli            # or codex_cli
  prompt: |
    Search for candidates on "<sub-query>". Write results to
    {task_dir}/candidates.yml, then comms_message the orchestrator (<tracking_id>)
    with the file path.
```
Then wait: `comms_wait_response` (or poll `comms_check_messages`).

### 3. Dispatch Extract

For the winning candidates, dispatch extract workers to pull evidence (quotes, dates,
facts). Same two modes as step 2 — subagents return an `evidence` YAML block directly;
session workers write `evidence.yml` and signal over comms. Cap candidates at the top
15-20 to protect worker context.

### 4. Evaluate & Loop

Assess coverage. If gaps remain, loop back to step 2 or 3 with a narrowed sub-query.
**Hard limit: 3 iterations** — stop and synthesize with what you have.

### 5. Synthesize

In the orchestrator's own context, read the collected evidence and write the answer to
`{task_dir}/synthesis.yml` (or return it inline for a fully-subagent run). Use
`knowledge_condense_history` if the evidence set is too large to hold at once.

### 6. Deliver

If a remote requester asked for this, deliver over comms:
`comms_message` (or `comms_send_prompt`) to the requester's tracking ID with the answer
or the `synthesis.yml` path. If you launched this yourself, the synthesis *is* your
result — no delivery step needed.

---

## Integration with workflow

### Two Ways to Run

1. **In-session (default).** The session that wants the research *is* the orchestrator
   and runs the Steps above directly, fanning out subagents via the `Agent` tool. No
   playbook launch, no separate instance — this is the common case.

2. **Launched orchestrator.** When the research should run in a dedicated session (e.g.
   to keep the requester's context clean, or for a long-running job), launch one with
   `sessions_launch_agent` (`platform: claude_cli` or `codex_cli`) whose prompt is
   "run the research_orchestration playbook for query `<X>`, deliver to `<tracking_id>`."
   That launched session then runs the Steps and delivers over comms.

### Optional workflow-MCP registration

If registering as a first-class playbook via the **workflow** MCP
(`workflow_start_playbook`), the start action launches a single orchestrator session:

```yaml
name: research_orchestration
description: "Multi-stage research with a single self-contained orchestrator"
start_action:
  tool: sessions_launch_agent
  params:
    platform: claude_cli          # or codex_cli
    prompt: "Run the research_orchestration playbook. query={{query}}, requester={{requester}}"
params:
  - name: query
    required: true
    description: "The research question"
  - name: requester
    description: "Tracking ID to deliver results to (omit for in-session use)"
```

**No external monitoring:** the workflow MCP does NOT track intermediate states, manage
transitions, or drive feedback loops. The orchestrator owns all of that internally.
The launcher just starts the orchestrator and awaits its final comms message.

---

## Examples

### Basic Research (in-session, subagents)

**Request:** Analyze how the CLI coordination system has evolved from v1 through v4.

The orchestrator fans out `Agent` search workers over the archive, then extract
workers on the top candidates, synthesizes a timeline in its own context, and returns
it inline:

```
Agent (Explore) → "find coordination-system docs v1..v4, return candidate list"
Agent (Explore) → "find migration/changelog notes on coordination, return candidates"
   ↓ collect
Agent (general-purpose) → "extract dated milestones from these paths, return evidence"
   ↓ synthesize in orchestrator context → timeline
```

### Relationship Analysis (launched orchestrator + session workers)

**Request:** Compare relationship dynamics between user and Claude versus user and
ChatGPT over time — a large archive spanning many chat histories.

Because the corpus is large, launch a dedicated orchestrator and let it use session
workers for the heavy history scans:

```
workflow_start_playbook            # or sessions_launch_agent directly
  name: research_orchestration
  params:
    query: "Compare relationship dynamics: user-Claude vs user-ChatGPT, evolution over time"
    requester: <your tracking_id>
```

The orchestrator dispatches `sessions_launch_agent` workers that scan the chat archive,
write `evidence.yml`, and signal over comms; the orchestrator collects, synthesizes,
and delivers to your tracking ID with `comms_message`.

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
| 3.0.0 | 2026-07-12 | Retargeted onto the current stack after Gemini CLI retirement. Dispatch now uses `Agent`-tool subagents (default) and `sessions_launch_agent` CLI worker sessions; collect/deliver via the comms MCP; search via the knowledge MCP. Removed Desktop/Web-UI framing and dead-MCP tool names. Reactivated. |
| 2.0.0 | 2025-01-17 | Redesigned as single-orchestrator pattern. Orchestrator spawns workers internally rather than external multi-stage coordination. |
| 1.0.0 | 2025-01-17 | Initial three-stage external coordination design (superseded) |
