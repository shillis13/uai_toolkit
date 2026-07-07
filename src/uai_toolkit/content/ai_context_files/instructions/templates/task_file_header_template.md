# Task File Header Template

All task files MUST include protocol reference in frontmatter:

```yaml
---
task_id: {unique_id}
task_type: {type}
created: {ISO timestamp}
protocol: ai_general/docs/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# {Task Title}

**FIRST:** Read the protocol file above. It defines:
- How to claim this task (move to in_progress/)
- How to report completion (create completion file, move to completed/)
- Task lifecycle requirements

{rest of task content...}
```

## Why This Matters

Agents don't automatically know task coordination. The task file itself must:
1. Reference the protocol so the agent knows the rules
2. Remind the agent to read it BEFORE starting work
3. Ensure consistent lifecycle handling across all agents

## Anti-Pattern

Task files without protocol reference → agents ignore lifecycle → tasks stuck in wrong state.
