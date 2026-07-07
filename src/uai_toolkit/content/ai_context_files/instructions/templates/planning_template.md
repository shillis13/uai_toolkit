# Request #{{REQ_ID}}: Sub-Task Planning - {{TARGET}}

**Type:** Planning | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}

## Context

{{CONTEXT}}

## Task

Break down this complex task into manageable sub-tasks.

**NOT for orchestration plans** - the orchestrating session creates those in conversation.

Use this when:
- A single task is too large to execute in one pass
- You need to plan internal breakdown before executing
- Delegating sub-work to other agents

### Required Outputs

1. **task_breakdown.md** with:
   - Sub-task list with descriptions
   - Dependencies between sub-tasks
   - Suggested execution order
   - Estimated complexity per sub-task (S/M/L)

### Guidelines

- Keep sub-tasks atomic where possible
- Identify what can be parallelized
- Flag anything needing clarification
- Note assumptions made

## Completion

After breakdown:
```bash
touch {{OUTPUT_DIR}}/planning.completed
```

Then either:
- Execute sub-tasks yourself, OR
- Create tasks for other agents using the workflow MCP (workflow_gen_task)
