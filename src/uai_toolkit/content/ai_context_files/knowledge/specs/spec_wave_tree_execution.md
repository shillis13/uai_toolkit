# Specification: Wave Tree Execution Model

**Version:** 0.1.0  
**Status:** Implemented (via native Claude CLI `--fork-session`)  
**Purpose:** Hierarchical parallel execution with inherited learning at each branch

---

## Problem Statement

Current parallel execution has a tradeoff:
- **Sequential:** Maximizes learning but minimizes throughput
- **Parallel:** Maximizes throughput but each worker starts fresh

Wave Tree solves this: **compound learning with exponential scaling**.

---

## Model

### Tree Structure

```
depth=0 (root)
    │
    │ breadth=1, items=X
    │ [singleton processes X items, accumulates learning L₀]
    │
depth=1
    ├─── breadth=N forks, each inherits L₀
    │    each processes Y items, accumulates L₀ + L₁ₐ, L₀ + L₁ᵦ, etc.
    │
depth=2
    ├─── each depth=1 node forks M times
    │    each inherits parent's full context (L₀ + L₁ₓ)
    │    processes Z items
    │
... (continues to max_depth)
```

### Parameters

```yaml
wave_tree:
  max_depth: 3              # How many levels of forking
  
  levels:
    - depth: 0
      breadth: 1            # Singleton root
      items: 5              # Process first 5 items
      fork_after: true      # Fork when done
      
    - depth: 1
      breadth: 4            # Root forks into 4
      items_per_node: 7     # Each processes 7 items
      fork_after: true
      
    - depth: 2
      breadth: 2            # Each depth=1 forks into 2 (8 total)
      items_per_node: remaining  # Divide remaining items
      fork_after: false     # Terminal level
```

### Execution Flow

```
Phase 1: Root (depth=0)
├── Start single session
├── Process items 1-5
├── Capture learning state
└── Signal ready for depth=1

Phase 2: First expansion (depth=1)
├── Fork root session 4 times
├── Each fork inherits root's context
├── Assign items 6-12, 13-19, 20-26, 27-33 respectively
├── Process in parallel
├── Each captures its learning state
└── Signal ready for depth=2

Phase 3: Second expansion (depth=2, if needed)
├── Each depth=1 session forks 2 times
├── 8 total workers
├── Each inherits its parent's context
└── Process remaining items
```

---

## Context Inheritance: Native Fork

Claude CLI provides native session forking via `--resume <id> --fork-session`:

```bash
# Parent processes items, builds context
claude --session-id $PARENT_ID "Process items 1-5"

# Fork: children inherit FULL conversation context
claude --resume $PARENT_ID --fork-session "Now process items 6-12"
claude --resume $PARENT_ID --fork-session "Now process items 13-19"
```

**Via claude_cli.sh wrapper:**

```bash
# Wave 1: Root session (capture its session ID)
claude_cli.sh -A librarian -t "Process items 1-5"
# Get session ID from ~/.claude/agent_sessions.yml or session output

# Wave 2: Fork with inherited context
claude_cli.sh -A librarian -t --fork-from $ROOT_SESSION_ID "Process items 6-12" &
claude_cli.sh -A librarian -t --fork-from $ROOT_SESSION_ID "Process items 13-19" &
```

**What gets inherited:**
- Full conversation history
- All learned patterns (implicit in context)
- Tool usage examples
- Error corrections and refinements

**No additional tooling required** - this uses native Claude CLI features.

### Optional: File-Based Supplement

For explicit knowledge capture alongside native forking:

```yaml
inheritance:
  primary: native_fork          # --fork-session
  supplement: lessons_file      # Optional explicit capture
  export_on_wave_complete: lessons_learned_{wave}.yml
```

---

## Implementation

### claude_cli.sh Support

```bash
# --fork-from: Fork from parent session with inherited context
claude_cli.sh -A librarian --fork-from <parent_session_id> "Process items 6-12"
```

This passes `--resume <id> --fork-session` to the Claude CLI, creating a new session that inherits the parent's full conversation history.

### Wave Orchestrator Example

```bash
#!/usr/bin/env bash
# wave_orchestrator.sh - Execute wave tree with native forking

TASK_DIR="$1"
WAVE_CONFIG="$TASK_DIR/wave_tree.yml"
AGENT="librarian"

# Phase 1: Root session (singleton, learning phase)
echo "Wave 1: Root processing items 1-5..."
ROOT_TMUX="wave_root_$$"
claude_cli.sh -A $AGENT -t -s $ROOT_TMUX -a \
  "Process items 1-5 from task 0023. When done, output SESSION_ID: <your_session_id>"

# Wait for completion and capture session ID
# (In practice, poll tmux or use completion signal file)
ROOT_SESSION_ID=$(get_session_id_from_output "$ROOT_TMUX")

echo "Root session: $ROOT_SESSION_ID"

# Phase 2: Fork into parallel workers (each inherits root context)
echo "Wave 2: Forking 4 workers with inherited context..."
for i in {1..4}; do
  ITEMS_START=$(( 5 + (i-1) * 7 + 1 ))
  ITEMS_END=$(( ITEMS_START + 6 ))
  
  claude_cli.sh -A $AGENT -t -a \
    --fork-from "$ROOT_SESSION_ID" \
    "Process items $ITEMS_START-$ITEMS_END" &
done

wait
echo "Wave 2 complete."
```

### Session ID Capture

To fork, you need the parent's session ID. Options:

1. **From agent session map:** `~/.claude/agent_sessions.yml` tracks last session per agent
2. **From session output:** Claude CLI outputs session ID on start
3. **Specify upfront:** Use `--session-id <uuid>` (raw claude CLI) to set known ID

```bash
# Capture from agent session tracking
ROOT_SESSION=$(grep "librarian:" ~/.claude/agent_sessions.yml | awk '{print $2}')
```

### Session State Capture

```bash
# Before forking, session writes:
cat > lessons_d0.yml << EOF
wave_id: "0023_d0"
items_processed: [1, 2, 3, 4, 5]
patterns_learned:
  - "YAML headers should preserve exact field names from source"
  - "Cross-references need path validation, not just copy"
  - "Tables condense well to key-value pairs"
  - "Code blocks should stay verbatim, just remove redundant examples"
common_codex_feedback:
  - "Missing version field in metadata"
  - "Acronyms should be expanded on first use"
avg_iterations: 1.8
avg_reduction: 72%
EOF
```

---

## Scaling Examples

### Small Batch (33 files)

```yaml
wave_tree:
  levels:
    - depth: 0
      breadth: 1
      items: 5       # 5 items, learning phase
    - depth: 1
      breadth: 4
      items_per_node: 7  # 28 items split across 4 workers
# Total: 5 + 28 = 33
# Workers at peak: 4
# Learning inheritance: 1 generation
```

### Medium Batch (100 files)

```yaml
wave_tree:
  levels:
    - depth: 0
      breadth: 1
      items: 8       # Initial learning
    - depth: 1
      breadth: 3
      items_per_node: 12  # 36 items
    - depth: 2
      breadth: 2
      items_per_node: 9   # 54 items (6 workers × 9)
# Total: 8 + 36 + 54 = 98 (round up to 100)
# Workers at peak: 6
# Learning inheritance: 2 generations
```

### Large Batch (500 files)

```yaml
wave_tree:
  levels:
    - depth: 0
      breadth: 1
      items: 10
    - depth: 1
      breadth: 4
      items_per_node: 15  # 60 items
    - depth: 2
      breadth: 3
      items_per_node: 20  # 240 items (12 workers)
    - depth: 3
      breadth: 2
      items_per_node: 8   # 192 items (24 workers)
# Total: 10 + 60 + 240 + 192 = 502
# Workers at peak: 24
# Learning inheritance: 3 generations
```

---

## Control Parameters

| Parameter | Description | Trade-off |
|-----------|-------------|-----------|
| `max_depth` | Levels of forking | More depth = more learning inheritance, more coordination overhead |
| `breadth[d]` | Forks at depth d | More breadth = more parallelism, less shared context per branch |
| `items[d]` | Items per node at depth d | More items = more learning per node, less parallelism |
| `fork_threshold` | Min items remaining to justify fork | Prevents over-forking on small remainders |

### Heuristics

```yaml
# Suggested defaults
heuristics:
  min_items_for_fork: 10          # Don't fork if <10 items remain
  max_items_per_session: 25       # Fork before context pressure
  learning_phase_ratio: 0.15      # ~15% of batch in depth=0
  target_terminal_workers: 4-8    # Sweet spot for parallelism
```

---

## Coordination Signals

Sessions need to signal state changes:

| Signal | Meaning | Written To |
|--------|---------|------------|
| `WAVE_STARTED` | Session began processing | `status.yml` |
| `ITEM_COMPLETE` | One item done | `progress.yml` |
| `LESSONS_CAPTURED` | Ready to fork | `lessons_{id}.yml` |
| `WAVE_COMPLETE` | All assigned items done | `status.yml` |
| `FORK_READY` | Children can start | `status.yml` |

Orchestrator polls or watches for signals to trigger next phase.

---

## Future Considerations

1. **Dynamic branching:** Adjust breadth based on observed item complexity
2. **Load balancing:** Redistribute items if some branches finish early
3. **Checkpoint recovery:** Resume from last completed wave on failure
4. **Cross-branch learning:** Periodic sync of lessons across sibling branches
5. **Context compression:** Summarize inherited context to manage token limits

---

## Related

- `spec_task_id_counter.latest.md` - Atomic IDs for session naming
- `cli_session_persistence.latest.md` - Session state management
- `protocol_taskCoordination.latest.md` - Task lifecycle
- `task_template_condensation_with_codex_review.md` - Condensation workflow
