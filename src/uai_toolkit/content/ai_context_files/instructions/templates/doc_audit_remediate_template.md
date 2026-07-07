# Request #{{REQ_ID}}: Doc Audit Remediation - {{TARGET_DIR}}

**Type:** Remediation | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Playbook:** doc_audit | **Phase:** 2 of 2

## Context

Scan phase identified issues in: `{{TARGET_DIR}}`

## Scan Results

{{SCAN_PATH}}

## Approved Remediation Scope

{{REMEDIATION_SCOPE}}

## Task

Address identified documentation issues.

### Required Outputs

1. **remediation_log.md**:
   - Issue addressed
   - Action taken
   - Before/after summary
   - Issues deferred (with reason)

2. **updated_docs_list.md**:
   - Files modified
   - Modification type (content/metadata/structure)
   - Brief description of changes

### Remediation Guidelines

**DO:**
- Update stale dates/versions in frontmatter
- Fix broken internal links
- Correct YAML syntax errors
- Remove clearly obsolete content
- Add missing frontmatter

**DON'T:**
- Rewrite content without approval
- Delete files without approval
- Change document structure significantly
- Add substantial new content

**ESCALATE:**
- Documents needing major rewrites
- Unclear whether content is current
- Structural reorganization needed
- Conflicting information across docs

### User Approval Gate

Remediation plan requires **user approval** before execution.

Review issues_found.md with user, get approval for specific actions.

## Completion

After approved remediation:
```bash
touch {{OUTPUT_DIR}}/remediation.completed
comms_send_prompt(target="claude-cli", message="Doc audit remediation complete for {{TARGET_DIR}}. See remediation_log.md for changes made.")  # via comms MCP
```
