# Request #{{REQ_ID}}: Acceptance Phase - {{TARGET}}

**Type:** Acceptance | **Priority:** HIGH | **Posted:** {{TIMESTAMP}}
**Playbook:** mid_dev | **Phase:** 6 of 6

## Context

{{CONTEXT}}

## Completed Phases

- Planning: {{PLAN_PATH}}
- Design: {{DESIGN_PATH}}
- Implementation: {{IMPL_PATH}}
- Integration: {{INTEGRATION_PATH}}
- Testing: {{TESTING_PATH}}

## Task

Project review and acceptance testing with user.

### Required Outputs

1. **acceptance_report.md** with:
   - Original requirements recap
   - Delivered functionality
   - Requirements traceability (what maps to what)
   - Outstanding items (if any)
   - Acceptance criteria status
   - Recommendation (accept/conditional/reject)

2. **handoff_doc.md** with:
   - How to use / run
   - Configuration guide
   - Maintenance notes
   - Known limitations
   - Future enhancement ideas
   - Support/escalation paths

3. **demo_script.md** (optional):
   - Walkthrough scenarios
   - Key features to highlight
   - Sample data/inputs

### Acceptance Guidelines

- Be honest about gaps
- Highlight what works well
- Provide clear next steps
- Make handoff self-contained
- User should be able to operate without you

### User Approval Gate

Final acceptance requires **user approval**.

Notify the orchestrating session via the comms MCP:
```
comms_send_prompt(target="claude-cli", message="{{TARGET}} ready for acceptance review. See acceptance_report.md and handoff_doc.md. Approve to close project.")
```

## Completion

After user approval:
```bash
touch {{OUTPUT_DIR}}/acceptance.completed
touch {{OUTPUT_DIR}}/PROJECT_COMPLETE
comms_send_prompt(target="claude-cli", message="Project {{TARGET}} COMPLETE. All phases finished.")  # via comms MCP
```
