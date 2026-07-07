# Architecture: Wave Execution Model

**Version:** 1.0.0  
**Status:** Active  
**Purpose:** Self-orchestrating parallel execution with inherited context

---

## Overview

Wave execution enables exponential parallelism while preserving learned context. Each worker inherits its parent's full conversation history, allowing implicit learning to compound through generations.

```
         ┌─────┐
         │Root │ processes X items, learns patterns
         └──┬──┘
            │ forks N children (--fork-from)
    ┌───────┼───────┐
    ▼       ▼       ▼
  ┌───┐   ┌───┐   ┌───┐
  │ A │   │ B │   │ C │  each inherits Root context
  └─┬─┘   └─┬─┘   └─┬─┘  each processes Y items
    │       │       │    each may fork M children
   ...     ...     ...
```

**Key properties:**
- Context inheritance via native `--fork-session`
- Self-similar recursion (each node follows same algorithm)
- Automatic termination (stop when items exhausted or depth reached)

---

## Core Algorithm

Every wave node executes the same logic:

```
WAVE_NODE(items, depth, config):
  1. Process my assigned items (up to config.items_per_wave)
  2. remaining = items - processed
  3. IF remaining > 0 AND depth < config.max_depth:
       partition remaining into config.breadth chunks
       FOR each chunk:
         FORK self with (chunk, depth+1, config)
  4. Write completion status
```

This is self-orchestrating - no external controller needed after initial launch.

---

## Wave Configuration

```yaml
wave_config:
  max_depth: 3              # Maximum fork generations
  items_per_wave: 5         # Items to process before forking
  breadth: 4                # Number of forks at each level
  min_items_to_fork: 3      # Don't fork if fewer items remain
```

**Scaling behavior:**

| Depth | Workers | Items (5 per wave, breadth 4) |
|-------|---------|-------------------------------|
| 0     | 1       | 5                             |
| 1     | 4       | 20                            |
| 2     | 16      | 80                            |
| 3     | 64      | 320                           |

Total capacity: 425 items with max 64 parallel workers at depth 3.

---

## Task Prose Pattern

For self-orchestrating waves, the task must include:

```markdown
## Wave Execution

You are a wave node. Follow this algorithm:

### Parameters
- items_per_wave: {{N}}
- max_depth: {{D}}  
- breadth: {{B}}
- current_depth: {{DEPTH}}  (0 for root)

### Your Items
{{ITEM_LIST}}

### Algorithm

1. **Process** the first {{N}} items from your list
2. **Check remaining:** If items remain AND current_depth < max_depth:
   - Partition remaining items into {{B}} roughly-equal chunks
   - For each chunk, fork yourself:
     ```
     claudeCli -A {{AGENT}} --fork-from $SESSION_ID \
       "Continue wave task 0023. Your depth: {{DEPTH+1}}. Your items: [chunk]"
     ```
3. **Complete:** Write status to progress.yml
```

The agent reads this, processes items, then spawns children with updated parameters. Each child is a complete wave node.

---

## Session ID Discovery

For forking, agents need their own session ID. Methods:

1. **Environment variable** — `$AI_TRACKING_ID` (workspace primary key) and `$AI_CLI_SESSION_ID` (platform UUID), exported into every session
2. **Query session registry:** `session_store.py` (SQLite `ai_general/data/sessions.db`)
3. **Self-identification prompt:** "Output your session ID"
4. **File signal:** Write session ID to known location on start

Current approach: Agent reads `$AI_TRACKING_ID` from its environment; the session registry (`session_store.py`, `ai_general/data/sessions.db`) is the lookup of record.

---

## Termination Conditions

Waves terminate when ANY of:
- All items processed
- `current_depth >= max_depth`
- `remaining_items < min_items_to_fork`

Each terminal node writes completion status. Orchestrator (or root) can poll for all completions.

---

## Naming Convention

Sessions follow hierarchical naming:

```
wave_0023_d0           # Root (depth 0)
wave_0023_d1_a         # First child of root
wave_0023_d1_b         # Second child of root
wave_0023_d2_a_1       # First grandchild of 'a'
wave_0023_d2_a_2       # Second grandchild of 'a'
```

Encoded: `wave_{task}_{depth}_{path}`

---

## Progress Tracking

Each node appends to shared progress file:

```yaml
# progress.yml (append-only, atomic writes)
- node: d0
  items: [1,2,3,4,5]
  completed: 2025-12-24T22:30:00Z
  forked: [d1_a, d1_b, d1_c, d1_d]
  
- node: d1_a
  items: [6,7,8,9,10]
  completed: 2025-12-24T22:32:00Z
  forked: []  # terminal
```

---

## Avalanche Mode (Future)

For very large batches, waves can trigger based on completion rather than fixed depth:

```yaml
avalanche:
  trigger: completion_threshold
  threshold: 0.8           # Fork when 80% of items done
  max_concurrent: 16       # Cap total workers
```

This enables adaptive scaling based on observed throughput.

---

## CLI Support

```bash
# Start wave root
claudeCli -A librarian "Process wave task 0023"

# Agent forks itself (from within session)
claudeCli -A librarian --fork-from $MY_SESSION \
  "Continue wave 0023. Depth: 1. Items: [6-12]"
```

The `--fork-from` flag:
- Resumes parent session with `--fork-session`
- Creates new session ID (not reusing parent's)
- Inherits full conversation context

---

## Related

- `spec_wave_tree_execution.latest.md` - Detailed specification
- `spec_task_id_counter.latest.md` - Atomic ID generation
- `protocol_taskCoordination.latest.md` - Task lifecycle
- `cli_orchestration.latest.md` - CLI agent patterns
