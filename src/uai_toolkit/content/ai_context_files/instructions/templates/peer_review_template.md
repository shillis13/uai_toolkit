# Request #{{REQ_ID}}: Peer Review - {{TARGET}}

**Type:** Peer Review | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Reviewer:** {{REVIEWER_ROLE}}

## Review Target

{{TARGET_PATH}}

## Review Context

{{CONTEXT}}

## Review Type

{{REVIEW_TYPE}}

## Task

Perform thorough code/design review.

### Review Checklist

**Correctness:**
- [ ] Logic is sound
- [ ] Edge cases handled
- [ ] Error paths covered
- [ ] No obvious bugs

**Quality:**
- [ ] Code is readable
- [ ] Naming is clear
- [ ] Comments where needed
- [ ] No unnecessary complexity

**Security:**
- [ ] Input validation present
- [ ] No hardcoded secrets
- [ ] Proper error messages (no leaks)
- [ ] Authentication/authorization correct

**Maintainability:**
- [ ] Follows existing patterns
- [ ] Testable design
- [ ] No tight coupling
- [ ] Dependencies reasonable

**Completeness:**
- [ ] Meets requirements
- [ ] No missing pieces
- [ ] Documentation adequate

### Required Outputs

1. **{{REVIEW_OUTPUT}}** with:

```yaml
review:
  target: "{{TARGET}}"
  reviewer: "{{REVIEWER_ROLE}}"
  date: "{{DATE}}"
  verdict: approve|request_changes|needs_discussion
  
summary: |
  Overall assessment in 2-3 sentences.

issues:
  - severity: critical|high|medium|low
    location: "file:line or component"
    description: "What's wrong"
    suggestion: "How to fix"

strengths:
  - "What's done well"

suggestions:
  - "Optional improvements"
```

### Review Guidelines

- Be specific about locations
- Provide actionable feedback
- Distinguish blockers from suggestions
- Acknowledge good work
- Stay objective

### Verdict Criteria

- **approve**: No blockers, ready to proceed
- **request_changes**: Has issues that must be fixed
- **needs_discussion**: Requires clarification or design discussion

## Completion

After review:
```bash
touch {{OUTPUT_DIR}}/review.completed
```
Note: Notification is handled automatically by the .callback.yml when the task is moved to completed status.
