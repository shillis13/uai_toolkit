# Request #{{REQ_ID}}: Orchestration Planning - {{TARGET}}

**Type:** Planning | **Priority:** HIGH | **Posted:** {{TIMESTAMP}}
**Playbook:** mid_dev | **Role:** dev-lead

## Context

{{CONTEXT}}

## Scope

{{SCOPE}}

## Constraints

{{CONSTRAINTS}}

## Task

Create comprehensive orchestration plan for: **{{TARGET}}**

### Required Outputs

1. **orchestration_plan.md** with:

   **Summary:**
   - 2-3 sentence overview
   - Problem being solved
   - Expected outcome

   **Scope:**
   - In scope (specific deliverables)
   - Out of scope (explicitly excluded)

   **Technical Approach:**
   - Architecture overview
   - Key technologies
   - Integration approach

   **Phase Breakdown:**
   | Phase | Role | Deliverables | Gate | Est. Time |
   |-------|------|--------------|------|-----------|
   | Design | dev-lead | design_doc, diagrams | Peer + User | X hrs |
   | Impl Task 1 | dev-lead | component A | Peer review | X hrs |
   | ... | ... | ... | ... | ... |
   | Integration | dev-lead | integrated system | Auto | X hrs |
   | Testing | devops | test results | Peer review | X hrs |

   **Implementation Breakdown:**
   | Task | Description | Complexity | Dependencies |
   |------|-------------|------------|--------------|
   | 1 | ... | S/M/L | None |
   | 2 | ... | S/M/L | Task 1 |

   **Risks:**
   | Risk | Likelihood | Impact | Mitigation |
   |------|------------|--------|------------|
   | ... | L/M/H | L/M/H | ... |

   **Dependencies:**
   - External: [APIs, services, etc.]
   - Internal: [Existing code, systems]

   **Success Criteria:**
   - [ ] Measurable criterion 1
   - [ ] Measurable criterion 2

   **Timeline:**
   - Total estimated: X hours

### Planning Guidelines

- Be specific about deliverables
- Identify integration points early
- Call out unknowns explicitly
- Estimate conservatively
- Consider rollback scenarios

## Completion

Present plan for approval:
```bash
comms_send_prompt(target="claude-cli", message="Orchestration plan complete for {{TARGET}}. Review orchestration_plan.md. Approve to proceed to design phase.")  # via comms MCP
```

After approval:
```bash
touch {{OUTPUT_DIR}}/planning.completed
```

Then create design task using design.template.md.
