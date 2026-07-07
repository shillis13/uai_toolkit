# CLI and Codex Delegation Guidelines

**Version:** 2.1.0
**Last Updated:** 2025-11-23
**Maintainer:** PianoMan
**Status:** active
**Source File:** instr_claude_use_of_ai_agents.md
**Migration Notes:** Converted from Markdown to YAML as part of req_1019. v2.1.0 adds Codex operational constraints based on testing.
**Load Priority:** topic
**Topic Triggers:** delegation, CLI, Codex, task assignment

## Table of Contents

1. Overview
2. Tool Descriptions
   - CLI Coordination System
   - Codex MCP
3. When to Delegate
   - Use CLI Coordination When
   - Use Codex When
   - Do NOT Delegate When
4. Delegation Patterns
   - CLI Pattern (Asynchronous)
   - Codex Pattern (Synchronous)
5. Examples
6. Context Preservation Priority
7. Quick Decision Tree

## Overview

Desktop Claude should act as coordinator and strategist, delegating heavy file operations and exploratory work to preserve context for high-value conversation and analysis.

## Tool Descriptions

### CLI Coordination System

File-based asynchronous task system where Desktop Claude posts tasks to `~/.claude/coordination/` directories and CLI instances (separate Claude processes with full terminal access) claim and execute them.

**Architecture:**
- Desktop posts: `broadcasts/req_XXXX_taskname.md` or `direct/cli_{PID}/task_XXX.md`
- CLI executes and writes: `responses/cli_{PID}/req_XXXX_response.md`
- Results move to: `completed/req_XXXX_taskname/` when done

**CLI Capabilities:**
- Full filesystem access with Desktop Commander MCP
- Process management and REPL interaction
- Large file analysis without context pollution
- Command execution and data processing
- Parallel task execution across multiple instances

### Codex MCP

Command-line AI agent that can autonomously execute complex tasks with approval workflow. Unlike CLI coordination (which is asynchronous), Codex runs synchronously and returns results directly.

**Codex Capabilities:**
- Autonomous multi-step problem solving
- File system exploration and analysis
- Code generation and debugging
- Complex shell command sequences
- Interactive approval for destructive operations

**Codex Operational Constraints:**
- Works best with focused, single-task prompts
- Avoid multi-step "do 1, 2, 3, and report" instructions
- Break complex workflows into discrete Codex calls
- Don't use approval-policy parameter (causes execution failures)
- For complex orchestration, use CLI Coordination instead

## When to Delegate

### Use CLI Coordination When

- Exploring file systems with unknown structure
- Reading multiple large files or directories
- Running commands that produce verbose output
- Performing data analysis on local files
- Task can run asynchronously while you continue conversation
- Want to preserve findings for later reference

### Use Codex When

- Need immediate synchronous results
- Task is focused and single-purpose
- File system exploration or command execution
- Code generation or refactoring (discrete tasks)
- Simple data analysis or transformation

### Do NOT Delegate When

- File is already in context or uploaded by user
- Single small file read (<100 lines)
- Quick directory listing (depth=1)
- User explicitly asks you to do it directly

## Delegation Patterns

### CLI Pattern (Asynchronous)

```
1. Create task specification in coordination directory
2. Start CLI instance with prompt to "Claim and execute Task task_xxxx"
3. Wait for CLI to report completion
4. Read summary from responses/ directory
5. Discuss findings with user
```

### Codex Pattern (Synchronous)

```
1. Call codex MCP tool with focused, single-task prompt
2. Codex executes and returns results
3. For multi-step work, make multiple discrete Codex calls
4. Review results and discuss with user

Example: Instead of "Do steps 1, 2, 3, report all"
Do: codex("Step 1"), then codex("Step 2"), then codex("Step 3")
```

## Examples

### Good Delegation (CLI)

```
User: "Find all Python files that import requests"
You: [Create req_1015_find_requests_imports.md]
     "Posted task req_1015. Tell your CLI to check inbox."
```

### Good Delegation (Codex)

```
User: "Search for conversation databases"
You: [Call codex tool with focused prompt]
     codex("List database files in ~/Library/Application Support/Claude")
     [Review results]
     codex("Check schema of conversations.db for table structure")
     [Synthesize findings for user]
```

### Bad Pattern (Context Waste)

```
User: "Find all Python files"
You: [Reads directory] [Lists files] [Checks each one]
     [Burns 10K tokens on exploration]
```

## Context Preservation Priority

Your context window is the limiting resource. Preserve it for:
- Strategic thinking and planning
- User conversation and collaboration
- Synthesizing results from delegated work
- Maintaining project knowledge and relationships

Delegate to preserve context for what matters most: partnership with the user.

## Quick Decision Tree

```
Need to investigate filesystem?
  └─> Many files or unknown structure?
      ├─> YES → Use CLI or Codex
      └─> NO → Check if already in context
          ├─> YES → Use directly
          └─> NO → Still prefer delegation if >100 lines
```

---

**Key Principle:** Desktop Claude coordinates and synthesizes. CLI and Codex execute and explore. This division of labor prevents context overflow and enables longer, more productive conversations.
