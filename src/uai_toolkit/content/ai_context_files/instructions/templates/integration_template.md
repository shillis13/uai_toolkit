# Request #{{REQ_ID}}: Integration Phase - {{TARGET}}

**Type:** Integration | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Playbook:** mid_dev | **Phase:** 4 of 6

## Context

{{CONTEXT}}

## Completed Components

{{COMPONENT_LIST}}

## Task

Integrate all implemented components into working system.

### Required Outputs

1. **integration_report.md** with:
   - Components integrated
   - Integration approach
   - Configuration changes
   - Issues encountered and resolutions
   - Smoke test results
   - Remaining integration gaps (if any)

2. **Updated configuration files** (if needed)

3. **Integration test results**

### Integration Guidelines

- Start with core/foundational components
- Add components incrementally
- Test after each addition
- Document configuration requirements
- Capture integration-specific bugs

### Integration Checklist

- [ ] All components present and accessible
- [ ] Dependencies resolved
- [ ] Configuration complete
- [ ] Basic data flow working
- [ ] Error paths tested
- [ ] Logging functional

### Gate

Integration auto-advances to testing phase upon completion.

## Completion

After successful integration:
```bash
touch {{OUTPUT_DIR}}/integration.completed
comms_send_prompt(target="claude-cli", message="Integration complete for {{TARGET}}. Ready for testing phase.")  # via comms MCP
```
