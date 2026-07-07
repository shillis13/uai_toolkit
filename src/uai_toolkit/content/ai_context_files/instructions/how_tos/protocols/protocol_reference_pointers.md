# Reference Pointer Protocol

**Version:** 1.0.0
**Created:** 2025-12-05
**Status:** active

## Related
- Schema: `../50_schemas/schema_pointer_syntax_latest.yml`
- Instructions: `../70_instructions/instr_pointer_loading_latest.yml`

## Purpose

Transform Claude's 30 native memory slots (6KB total) from content storage into an INDEX system that references unlimited external context.

**Instead of:** "User is a software developer who likes..."
**Store:** `STARTER:ai_memories/60_knowledge/about_user/identity.yml | PRIORITY:1`

## Problem Solved

Native memory slots are:
- Limited to 30 slots × 200 chars = 6KB total
- Flat (no hierarchy)
- Static (can't reference dynamic state)

Reference Pointers enable:
- Hierarchical context loading (files can contain pointers to more files)
- Dynamic queries against long-term memory
- Lazy loading (load only what's relevant)
- Unlimited effective memory through external files

## Core Concepts

### Pointer
- **Definition:** A compact string that identifies WHERE to find context
- **Format:** `<TYPE>:<TARGET> [| <MODIFIER>:<VALUE>]*`
- **Max Length:** 200 (must fit in native memory slot)

### Destination File
- **Definition:** YAML file containing actual context content
- **Location:** `ai_memories/` or `ai_general/` hierarchy
- **Structure:** header (metadata + summary) + content + optional pointers

### Lazy Loading
- **Definition:** Load context on-demand based on relevance, not upfront
- **Triggers:**
  - `PRIORITY:1 + LOAD:AUTO` → Load at conversation start
  - `PRIORITY:2 + LOAD:TOPIC` → Load when topic area detected
  - `PRIORITY:3 + LOAD:DEMAND` → Load only when explicitly needed

## Pointer Types

### PATH
- **Purpose:** Direct file reference
- **Format:** `TYPE:relative/path/to/file.yml`
- **Resolution:** Read file via Desktop Commander
- **Example:** `STARTER:ai_memories/60_knowledge/about_user/identity.yml`

### QUERY
- **Purpose:** Dynamic search against long-term memory
- **Format:** `QUERY:<search terms> [| modifiers]`
- **Resolution:** Search ai_memories/ using memory_search tool
- **Example:** `QUERY:CLI coordination issues | SINCE:14d | LIMIT:5`

### RECENT
- **Purpose:** Retrieve N most recent items from a category
- **Format:** `RECENT:<category> [| modifiers]`
- **Categories:** session_summaries, task_completions, decisions, errors
- **Example:** `RECENT:session_summaries | COUNT:3`

## Load Behaviors

| Behavior | Description | Typical Priority | Use For |
|----------|-------------|------------------|---------|
| AUTO | Load without AI decision at conversation start | 1 | Identity, core preferences, communication style |
| TOPIC | Load when related topic detected in conversation | 2 | Project context, domain knowledge, tool patterns |
| DEMAND | Load only when explicitly needed or referenced | 3 | Reference material, specs, deep documentation |

## Workflow

### Conversation Start
1. Claude receives native memory slots
2. Recognizes pointer format in slots
3. Loads all PRIORITY:1 + LOAD:AUTO pointers silently
4. Has rich context ready before first response

### Mid-Conversation
1. User mentions topic matching PRIORITY:2 pointer tags
2. Claude loads relevant TOPIC pointers
3. Context expands dynamically as conversation evolves

### On-Demand
1. Claude needs specific reference information
2. Explicitly loads PRIORITY:3 pointer
3. May announce: "Let me check the spec for that..."

## Slot Allocation Guidance

**Total Slots:** 30

| Category | Recommended | Description |
|----------|-------------|-------------|
| Identity/Prefs | 3-5 | WHO user is, HOW to communicate |
| Current Project | 3-5 | WHAT user is working on |
| Tool Configs | 2-3 | HOW tools are configured |
| Reference Material | 5-10 | WHAT to look up on demand |
| Reserved | 5-8 | Future expansion, temp context |

## Anti-Patterns

| Anti-Pattern | Correct Approach |
|--------------|------------------|
| Storing content | Don't put actual facts in slots - put pointers |
| Loading everything | Don't load all pointers upfront - lazy load |
| Deep chains | Limit pointer chain depth to 3 to prevent runaway loading |
| Circular refs | Track loaded paths to prevent infinite loops |

## Integration Points

### memory_user_edits_tool
- **Purpose:** CRUD for native memory slots
- **Pattern:** Use to add/remove/update pointers

### desktop_commander
- **Purpose:** Read destination files
- **Pattern:** view or read_file for PATH pointers

### memory_search (todo_0039)
- **Purpose:** Execute QUERY pointers
- **Pattern:** Search ai_memories/ for relevant chunks

## Success Metrics

- Conversation starts with rich context without user re-explaining
- Context grows naturally as topics are discussed
- Reference material loads only when needed
- New Claude instances have same contextual awareness
