# Request #{{REQ_ID}}: Doc Audit Scan - {{TARGET_DIR}}

**Type:** Audit | **Priority:** NORMAL | **Posted:** {{TIMESTAMP}}
**Playbook:** doc_audit | **Phase:** 1 of 2

## Task

Scan documentation directory for freshness and issues.

### Target

`{{TARGET_DIR}}`

### Scope

{{SCOPE}}

### Staleness Threshold

{{MAX_AGE_DAYS}} days

### Required Outputs

1. **audit_inventory.yml**:
```yaml
scan_date: {{DATE}}
target: {{TARGET_DIR}}
total_files: N
by_type:
  md: N
  yml: N
  other: N
files:
  - path: relative/path.md
    last_modified: 2025-12-01
    days_since_update: N
    size_bytes: N
    has_frontmatter: true/false
    status: current|stale|ancient
```

2. **staleness_report.md**:
   - Summary stats
   - Files exceeding staleness threshold
   - Oldest files
   - Recently updated files

3. **issues_found.md**:
   - Broken internal links
   - Missing referenced files
   - Malformed YAML/frontmatter
   - Empty or stub files
   - Orphaned files (not in any manifest)
   - Duplicate content

### Scan Guidelines

- Check file modification dates
- Validate YAML syntax
- Check internal `REF:` pointers resolve
- Flag files with TODO/FIXME/NEEDS_UPDATE
- Identify files not in any registry/manifest

## Completion

After scan:
```bash
touch {{OUTPUT_DIR}}/scan.completed
comms_send_prompt(target="claude-cli", message="Doc audit scan complete for {{TARGET_DIR}}. Review issues_found.md before remediation.")  # via comms MCP
```
