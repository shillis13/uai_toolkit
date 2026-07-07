# Request #{{REQ_ID}}: Testing Phase - {{TARGET}}

**Type:** Testing | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Playbook:** mid_dev | **Phase:** 5 of 6

## Context

{{CONTEXT}}

## Integration Reference

{{INTEGRATION_PATH}}

## Task

Comprehensive system integration testing with test-fix-test cycles.

### Required Outputs

1. **test_plan.md** (if not already defined):
   - Test scenarios
   - Test data requirements
   - Expected outcomes
   - Edge cases to cover

2. **test_results.md** with:
   - Tests executed
   - Pass/fail status per test
   - Actual vs expected results
   - Performance observations
   - Coverage assessment

3. **known_issues.md** with:
   - Issues found
   - Severity (critical/high/medium/low)
   - Steps to reproduce
   - Workarounds (if any)
   - Fix status

### Testing Guidelines

- Test happy path first
- Then error paths
- Then edge cases
- Document all failures before fixing
- Re-run full suite after fixes
- Don't mark done with critical issues open

### Test-Fix-Test Cycle

1. Run test suite
2. Document failures in known_issues.md
3. Fix issues (or escalate)
4. Re-run affected tests
5. Update test_results.md
6. Repeat until stable

### Peer Review Gate

Test results require **peer review by Codex** before acceptance.

```
comms_send_prompt(target="codex-cli", message="Review test_results.md and known_issues.md for {{TARGET}}. Assess coverage adequacy and issue severity. Provide testing_review.md")
```

## Completion

After peer review approval:
```bash
touch {{OUTPUT_DIR}}/testing.completed
```
