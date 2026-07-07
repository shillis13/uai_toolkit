# Request #{{REQ_ID}}: Implementation - {{TARGET}}

**Type:** Implementation | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Playbook:** {{PLAYBOOK}} | **Role:** dev-lead

## Context

{{CONTEXT}}

## Orchestration Plan Reference

{{PLAN_REFERENCE}}

## Task

Implement: **{{TARGET}}**

### Scope

{{SCOPE}}

### Constraints

{{CONSTRAINTS}}

### Required Outputs

1. **Source code** in appropriate location(s)
2. **implementation_notes.md** with:
   - What was built
   - Deviations from plan (if any, with rationale)
   - Known limitations
   - Testing approach
   - Dependencies added

3. **Unit tests** (if applicable)

### Implementation Guidelines

- Follow existing code conventions
- Add inline documentation for complex logic
- Keep changes focused on scope
- Flag blockers immediately via the comms MCP (comms_send_prompt)
- Don't gold-plate - implement to spec

## When Implementation Complete

**YOU** are responsible for setting up peer review.

1. Create peer review task for Codex:
```
workflow_gen_task(template="peer_review", platform="codex_cli", execute=True, params={
  "TARGET": "{{TARGET}}",
  "TARGET_PATH": "{{OUTPUT_DIR}}",
  "CONTEXT": "Implementation of {{TARGET}} per orchestration plan",
  "REVIEW_TYPE": "code",
  "REVIEWER_ROLE": "codex_cli",
  "REVIEW_OUTPUT": "peer_review.yml",
  "NOTIFY_TARGET": "claude_cli",
  "OUTPUT_DIR": "{{OUTPUT_DIR}}"
})
```

2. Notify the orchestrating session via the comms MCP:
```
comms_send_prompt(target="claude-cli", message="Implementation complete for {{TARGET}}. Peer review task created for Codex. Awaiting review.")
```

3. Mark implementation done:
```bash
touch {{OUTPUT_DIR}}/implementation.completed
```

## After Peer Review Returns

If **request_changes**:
1. Address feedback
2. Update implementation_notes.md
3. Re-create peer review task

If **approve**:
1. Proceed to testing (test-fix-test cycle)
2. Document results in test_results.md
3. When stable, notify for acceptance:
```bash
comms_send_prompt(target="claude-cli", message="{{TARGET}} implementation and testing complete. Ready for acceptance review.")  # via comms MCP
touch {{OUTPUT_DIR}}/testing.completed
```
