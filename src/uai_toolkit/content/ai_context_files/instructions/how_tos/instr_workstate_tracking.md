# Agent Workstate Tracking

**Version:** 1.0.0
**Created:** 2026-02-27
**Status:** Active
**Priority:** High
**Tool:** mcp-tasks v1.6.1 ([flesler/mcp-tasks](https://github.com/flesler/mcp-tasks))

## Purpose

Track per-agent work progress across context compactions and session restarts. Eliminates "where did we leave off?" exchanges that waste the first several turns of every resumed conversation.

Every agent writes its own file in `ai_general/workstate/`. Any agent can read all files for cross-visibility.

## Directory

```
ai_general/workstate/
  CONVENTIONS.yml          # Full reference documentation
  desktop_1.md             # Desktop Claude instance 1
  desktop_2.md             # Desktop Claude instance 2 (if running)
  cli_dev_lead.md          # CLI dev_lead agent
  cli_researcher.md        # CLI researcher agent
  cli_tester.md            # CLI tester agent
  cli_ops.md               # CLI ops agent
  cli_custodian.md         # CLI custodian agent
  cli_librarian.md         # CLI librarian agent
  cli_peer_review.md       # CLI peer_review agent
  cli_validator.md         # CLI validator agent
```

Files are created dynamically via `tasks_setup` on first use. Not all files will exist at all times.

## Session Start Protocol

**BEFORE doing any work**, every agent instance must:

1. **Register your workstate file:**

   Desktop Claude:
   ```
   tasks_setup desktop_1.md $AI_ROOT/ai_general/workstate/
   ```
   Use `desktop_1` by default. If PianoMan says you're the second instance, use `desktop_2`.

   CLI Agents:
   ```bash
   npx mcp-tasks setup cli_{role}.md /path/to/ai_general/workstate/
   ```

2. **Read existing state to recover context:**
   ```
   tasks_search
   ```
   This shows what a previous instance left behind. Resume from there.

## Runtime Rules

- **Log state changes AS THEY HAPPEN.** Not later. Not batched. Now.
- **Task text must include enough context for cold-start resume.**
  - Bad: "Working on the thing"
  - Good: "Refactoring memory slot loading - completed manifest parse, next: slot content loader in mem_slot/03.yml"
- **Write only to YOUR file.** Read any file for visibility.

## Statuses

| Status | Meaning |
|--------|---------|
| In Progress | Actively working now |
| To Do | Queued for this session |
| Done | Completed |
| Blocked | Can't proceed (include why in task text) |
| Backlog | Known work, not this session |

## MCP Configuration

### Desktop Claude

Server name `workstate` in `claude_desktop_config.json`. No hardcoded SOURCES — files registered dynamically via `tasks_setup` at session start.

Tools available (prefixed): `tasks_setup`, `tasks_add`, `tasks_search`, `tasks_update`, `tasks_summary`

### CLI Agents

Use CLI directly (no MCP server needed):
```bash
STATUSES="In Progress,To Do,Done,Blocked,Backlog" \
npx mcp-tasks setup cli_dev_lead.md "$(pwd)"
npx mcp-tasks add "Description of current work" "In Progress"
npx mcp-tasks update <id> Done
npx mcp-tasks summary
```

## Cross-Agent Visibility

To read another agent's state, add their file as an additional source:
```
tasks_setup cli_dev_lead.md /path/to/workstate/
```
Now `tasks_search` returns tasks from both your file and theirs.

## Integration with Existing Systems

| System | Scope |
|--------|-------|
| todos-mgr | Project-level work tracking (lifecycle, tags, hierarchy) |
| CLI Coordination v4 | Delegation lifecycle (assigned → executing → done) |
| workstate (this) | Agent-level step tracking (what step am I on) |
| memory slots | Learnings and observations |

These are complementary layers, not overlapping.
