# Task File Schema v2.1

## Metadata

- **name:** Task File Schema
- **version:** 2.1.0
- **date:** 2026-01-25
- **status:** active
- **description:** Schema for task definition files and directories
- **used_by:** protocol_taskCoordination_v9.0.md
- **changes_from_v2.0:**
  - Clarified directory naming matches task file (minus extension)
  - Added flag file patterns for lifecycle tracking
  - Removed claim prefix patterns (replaced by flag files)

## Directory and File Naming

### Directory Pattern

```
{reqId}_{slug}/
```

| Component | Description | Example |
|-----------|-------------|---------|
| `reqId` | `req_` + 4-digit zero-padded ID | `req_1234` |
| `slug` | Kebab/snake-case description | `yaml_migration` |

**Examples:**
- `req_1001_system_info/`
- `req_1019_yaml_review/`
- `req_2100_parallel_install/`

### Task File Pattern

```
{reqId}_{slug}.md
```

The task file name MUST match the directory name (with `.md` extension).

**Examples:**
- `req_1001_system_info/req_1001_system_info.md`
- `req_1019_yaml_review/req_1019_yaml_review.md`

### Flag File Patterns

**Started Flag (claim marker):**
```
{reqId}_{YYYYMMDDTHHMMSS}_started
```
- Zero-sized file
- Created when task is claimed
- Example: `req_1234_20260125T143022_started`

**Completed Flag:**
```
{reqId}_{YYYYMMDDTHHMMSS}_completed
```
- Zero-sized file
- Created when task is finished
- Example: `req_1234_20260125T155500_completed`

## Task ID Allocation

- **Counter file pattern:** `{prefix}.NextId`
- **Location:** `ai_comms/counters/`
- **Example:** `req.NextId` contains next available req ID
- **Increment:** Atomic via mkdir spinlock (see spec_task_id_counter)

---

## Required Fields

### Title

- **Format:** `# Request #{XXXX}: Title`
- **Description:** Markdown H1 header with request ID and descriptive title
- **Validation:** Must match reqId in filename
- **Example:** `# Request #1001: System Information Report`

### Type

- **Format:** `**Type:** {value}`
- **Default:** Standard
- **Allowed values:**

| Value | Description |
|-------|-------------|
| Standard | Normal task execution |
| Research | Information gathering, analysis |
| Installation | Software/tool installation |
| Testing | Test execution, validation |
| Emergency | Urgent, bypass normal queue |
| Maintenance | Cleanup, organization, updates |

### Priority

- **Format:** `**Priority:** {value}`
- **Default:** NORMAL
- **Allowed values:**

| Value | Description |
|-------|-------------|
| LOW | Can wait, do when convenient |
| NORMAL | Standard priority (default) |
| HIGH | Should be done soon |
| URGENT | Do next, interrupt lower priority |
| CRITICAL | Drop everything, do now |

### Posted

- **Format:** `**Posted:** {ISO 8601 timestamp}`
- **Description:** When the task was created
- **Example:** `**Posted:** 2026-01-25T15:30:00-06:00`

### Description

- **Format:** `## Task Description\n{markdown content}`
- **Description:** What needs to be done, context, requirements
- **Minimum length:** 1 sentence

### Expected Response

- **Format:** `## Expected Response\n{description}`
- **Description:** What the Worker should return/produce
- **Purpose:** Sets clear completion criteria


---

## Optional Fields

### Commands

- **Format:** `## Task Commands\n```bash\n{commands}\n```
- **Description:** Specific bash commands to execute
- **When omitted:** Worker determines appropriate commands

### Discrete

- **Format:** `**Discrete:** true|false`
- **Description:** If true, task should not be subdivided
- **Default:** false (subdivision allowed)

### Target Worker

- **Format:** `**Target Worker:** {worker_type}` or `{worker_type}:{session}`
- **Description:** Intended Worker type or specific instance
- **Examples:**
  - `**Target Worker:** claude_cli`
  - `**Target Worker:** codex_cli:ops_001`
- **When omitted:** Any available Worker may claim

### Session

- **Format:** `**Session:** {session_name}` or `{session_id}`
- **Description:** Persistent session for agent expertise accumulation
- **Purpose:** Specifies which persistent agent session should handle this task

**Value types:**

| Type | Description |
|------|-------------|
| session_name | Human-readable name (e.g., `librarian-001`) |
| session_id | UUID for the session |

**Examples:**
- `**Session:** librarian-001`
- `**Session:** custodian-001`

**When omitted:** Task runs in ephemeral session (fresh context)

### Entry Criteria

- **Format:** `## Entry Criteria\n{list of conditions}`
- **Description:** Prerequisites that must be met before starting
- **When omitted:** Task can start immediately when claimed

### Exit Criteria

- **Format:** `## Exit Criteria\n{list of conditions}`
- **Description:** Conditions that define successful completion
- **When omitted:** Worker judgment determines completion

### Depends On

- **Format:** `**Depends On:** req_XXXX, req_YYYY`
- **Description:** Task IDs that must complete before this task starts

### Notes

- **Format:** `## Notes\n{additional context}`
- **Description:** Any additional information for the Worker
- **Examples:** Background context, related tasks, known issues

---

## Directory Contents

### Full Directory Example

```
req_1234_yaml_migration/
├── req_1234_yaml_migration.md           # Task definition (required)
├── req_1234_20260125T143022_started     # Claim flag (added at claim)
├── execution_log.md                     # Worker's execution notes
├── checkpoint_001.md                    # Milestone report (optional)
├── checkpoint_002.md                    # Second milestone (optional)
├── artifacts/                           # Output directory
│   ├── converted/                       # Processed files
│   └── reports/                         # Generated reports
├── subtasks/                            # Nested subtask directories (optional)
│   ├── req_1234_01_analyze/
│   └── req_1234_02_convert/
└── req_1234_20260125T155500_completed   # Completion flag (added at completion)
```

### Subtask Directory Naming

```
{parentReqId}_{nn}_{slug}/
```

**Examples:**
- `req_1234_01_analyze/` (first subtask)
- `req_1234_02_convert/` (second subtask)
- `req_1234_01_01_review/` (nested subtask)

---

## Template

```markdown
# Request #XXXX: {Title}

**Type:** Standard
**Priority:** NORMAL
**Posted:** {ISO 8601 timestamp}
**Target Worker:** {worker_type}  <!-- Optional -->
**Session:** {session_name}       <!-- Optional -->

## Task Description

{Describe what needs to be done. Include context, requirements, and any
constraints the Worker should know about.}

## Task Commands

```bash
# Commands to execute (optional - omit section if Worker should decide)
{command_1}
{command_2}
```

## Expected Response

{Describe what the Worker should return. Be specific about format,
content, and any files that should be created.}

## Entry Criteria

- {Prerequisite 1}  <!-- Optional section -->
- {Prerequisite 2}

## Exit Criteria

- {Completion condition 1}  <!-- Optional section -->
- {Completion condition 2}

## Notes

{Optional: Additional context, related tasks, known issues.}
```

---

## Validation Rules

| Rule | Description | Severity |
|------|-------------|----------|
| dir_matches_file | Directory name must match task file (minus .md) | error |
| reqid_matches_title | reqId in filename must match #XXXX in title | error |
| required_sections | Title, Type, Priority, Posted, Description, Expected Response | error |
| valid_type | Type must be one of allowed_values | error |
| valid_priority | Priority must be one of allowed_values | error |
| valid_timestamp | Posted must be valid ISO 8601 format | error |
| description_not_empty | Task Description section must have content | error |
| expected_response_not_empty | Expected Response section must have content | warning |

---

## References

- **Protocol:** `protocol_taskCoordination_v9.0.md`
- **ID Counter:** `spec_task_id_counter_v1.0.md`
- **Task Template:** `task_template_v1.1.md`
