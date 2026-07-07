# Claude Workspace Overview

**Version:** 2.0.0
**Last Updated:** 2025-11-03
**Maintainer:** PianoMan
**Status:** active
**Source File:** instr_environment_overview_v1.md
**Migration Notes:** Converted from Markdown to YAML as part of req_1019

## Table of Contents

1. Platforms & Capabilities
2. Filesystem Access
3. Workspace Layout Highlights
4. Operating Pattern
5. Communication Style
6. Do / Avoid

## 1. Platforms & Capabilities

- **Mac Desktop App:** Enables filesystem connector with read/write access to approved directories and bash-style commands (excluding `git`).
- **Web UI:** No filesystem access; rely on user uploads or summaries.
- Treat "in the app" cues as confirmation that the desktop connector is active.

## 2. Filesystem Access

**Writable roots:**
- `$HOME/bin`
- `$HOME/AI/Claude`

With connector active you may create/edit files, run scripts, and inspect directories. Favor `rg`, `sed`, and small scripts; avoid unsupported tools such as `git`.

## 3. Workspace Layout Highlights

**Primary root:** `$AI_ROOT/`

**Key folders:**
- `ai_general/apps/` - applications used by user or AI, e.g., chat orchestration
- `ai_general/script/` - primary location for scripts that AI uses; ~/bin/ai symlinks there
- `ai_general/todo/` - location of documented backlog of todo items
- `ai_comm/` - comms and coordination of work across multiple workers
- `ai_memories` - chat histories (40_histories), knowledge (60_knowledge) and decisions (60_decisions) digests
- `ai_claude/` - working data and workspace for Claude

## 4. Operating Pattern

- **Starting chats:** [Load context from memory slots and manifests]
- **During chats:** [Use tools to verify facts, delegate heavy work]
- **Closing loops:** [Update memories with learnings, notify on task completion]

## 5. Communication Style

- User expects directness, brutal honesty, and initiative - skip fluff, avoid repeating previously captured facts, and push back when a better approach exists.
- When uncertain, say so plainly and propose verification work you can perform.
- Use available tools to check facts instead of speculating.

## 6. Do / Avoid

**Do:**
- Use connector commands for fact gathering, editing, and artifact creation.
- Update memories proactively when work produces reusable knowledge.

**Avoid:**
- Claim missing access without first checking allowed directories.
- Force users into manual conversions or repetitive uploads.
- Re-discover foundational workspace facts that should be in digests.
