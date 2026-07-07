# Request #{{REQ_ID}}: Design - {{TARGET}}

**Type:** Design | **Priority:** HIGH | **Posted:** {{TIMESTAMP}}
**Playbook:** {{PLAYBOOK}} | **Role:** dev-lead

## Context

{{CONTEXT}}

## Orchestration Plan Reference

{{PLAN_PATH}}

## Task

Create unified design covering UX and systems architecture for: **{{TARGET}}**

### Required Outputs

1. **design_doc.md** with:

   **UX Design:**
   - User flows / workflows
   - Screen/interface descriptions (or CLI interactions)
   - Input/output specifications
   - Error states and messaging
   - Edge case handling from user perspective

   **Systems Architecture:**
   - Component breakdown
   - Interface definitions (APIs, contracts)
   - Data models / schemas
   - Technology choices with rationale
   - Security considerations
   - Error handling strategy
   - Integration points

2. **architecture_diagram.md** (ASCII or Mermaid):
   - High-level component diagram
   - Data flow diagram
   - Integration points

3. **implementation_breakdown.md**:
   - Discrete implementation tasks
   - Task dependencies
   - Suggested task order
   - Estimated complexity per task (S/M/L)

### Design Guidelines

- Start with user perspective (what are they trying to do?)
- Design systems to support UX, not constrain it
- Reference the approved orchestration plan
- Design for testability
- Document assumptions explicitly
- Note areas needing clarification

## When Design Complete

**YOU** create peer review task:

```
workflow_gen_task(template="peer_review", platform="codex_cli", execute=True, params={
  "TARGET": "{{TARGET}} Design",
  "TARGET_PATH": "{{OUTPUT_DIR}}/design_doc.md",
  "CONTEXT": "UX and systems design for {{TARGET}}",
  "REVIEW_TYPE": "design",
  "REVIEWER_ROLE": "codex_cli",
  "REVIEW_OUTPUT": "design_review.yml",
  "NOTIFY_TARGET": "claude_cli",
  "OUTPUT_DIR": "{{OUTPUT_DIR}}"
})
```

Notify the orchestrating session via the comms MCP:
```
comms_send_prompt(target="claude-cli", message="Design complete for {{TARGET}}. Peer review task created. Awaiting review before user approval.")
```

## After Peer Review Approved

Present design to user for approval:
```
comms_send_prompt(target="claude-cli", message="Design for {{TARGET}} passed peer review. Ready for user approval. Key files: design_doc.md, architecture_diagram.md, implementation_breakdown.md")
```

## Completion

After user approval:
```bash
touch {{OUTPUT_DIR}}/design.completed
```

Then create implementation tasks per implementation_breakdown.md.
