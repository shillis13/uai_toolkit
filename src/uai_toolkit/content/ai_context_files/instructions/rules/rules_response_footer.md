# Response Footer Specification

**Version:** 1.6.0
**Last Updated:** 2026-07-04
**Maintainer:** PianoMan
**Status:** active

## Summary

Canonical metadata footer appended to every AI response. Claude MUST include this footer on every response.

**Todo discipline (MANDATORY):** if you **modified any file(s)** this turn (code, config, docs, data — anything committed or written to the repo), you MUST include the `Todo` field naming the todo id(s) the work belongs to. All meaningful work is done under a todo (see `instr_todo`); if the work has no todo yet, create one first, then cite it. If no files were changed this turn, omit the `Todo` field.

## Format

**Delimiter:** ` | `

**Field Order:**
1. AI_Name
2. Persona
3. Proj
4. Chat
5. Timestamp
6. Msg
7. Docs
8. MSlots
9. Artifacts
10. Todo
11. Tags

## Field Definitions

| Field | Description | Example |
|-------|-------------|---------|
| AI_Name | Display name for the responding persona | `Claude` |
| Persona | Persona version with optional delta marker (Δ, Δ+, Δ*) | `Persona:v1.0` |
| Proj | Short project identifier (CamelCase or hyphenated) | `Proj:AI-Root` |
| Chat | Human-readable chat title | `Chat:Manifest-Validation` |
| Timestamp | Local timestamp in ISO format with seconds | `2025-12-31 14:30:00` |
| Msg | Zero-indexed assistant message counter | `Msg:12` |
| Docs | Doc files loaded by directory tier | `Docs:20:5,70:3` |
| MSlots | Memory slots loaded (ranges for compactness) | `MSlots:3-7` |
| Artifacts | Count of artifacts created in this message | `Artifacts:1` |
| Todo | Todo id(s) the work belongs to — **REQUIRED when any file was modified this turn**; comma-separate multiple; omit entirely if no files changed | `Todo:todo_0384` |
| Tags | 2–8 descriptive keywords, comma-separated | `Tags: footer, validation` |

## Docs Field

Shows count of documentation files loaded per directory tier:

| Tier | Directory | Content |
|------|-----------|---------|
| 10 | 10_architecture | Foundational concepts |
| 20 | 20_registries | Indexes, inventories |
| 30 | 30_protocols | Communication patterns |
| 40 | 40_specs | Detailed specifications |
| 50 | 50_schemas | Data structures |
| 60 | 60_playbooks | How-to guides |
| 70 | 70_instructions | Operational rules |

**Format:** `Docs:20:5,70:3` (only show tiers with >0 files, omit zeros)

## MSlots Field

Shows which memory slots from ai_memories/80_working_memory/ were loaded:

**Format:** `MSlots:3-7` or `MSlots:3-5,8,11` (use ranges for compactness)

## Rules

### Persona Deltas
- **Δ:** Minor refinement or parameter adjustment
- **Δ+:** Significant update or behavioral expansion
- **Δ*:** Experimental or transient branch
- Only emit delta marker in the message that causes or announces the change

### Context Usage — REMOVED in v1.5 (2026-06-12)
Do NOT include context %/usage in footers or any model-generated output.
Context monitoring is infrastructure's job (statusline, UAI Recent Sessions,
threshold hooks). A self-narrated gauge induces context anxiety — premature
self-compaction and work avoidance were observed fleet-wide. You have ample
context; infrastructure handles compaction when needed.

### Docs Field
- Count files actually read via tool calls, not just referenced
- Update count as more docs loaded during conversation
- Tier numbers match ai_general/docs/ directory structure

### MSlots Field
- Show slot numbers from manifest (03-30 range)
- Use hyphenated ranges for consecutive slots (3-7 not 3,4,5,6,7)
- Comma-separate non-consecutive (3-5,8,11)

### Artifacts Field
- Count only artifacts created in the current message
- Typical items: canvas documents, generated files, external attachments

## Examples

**Fresh session after bootstrap:**
```
Claude | Persona:v1.0 | Proj:AI-Root | Chat:Footer-Spec | 2025-12-31 14:30:00 | Msg:0 | Docs:20:5,70:3 | MSlots:3-7 | Artifacts:0 | Tags: bootstrap, spec
```

**Mid-conversation with more docs loaded:**
```
Claude | Persona:v1.0 | Proj:AI-Root | Chat:Footer-Spec | 2025-12-31 14:45:00 | Msg:5 | Docs:20:5,40:2,70:3 | MSlots:3-7,9 | Artifacts:1 | Tags: iteration
```

**Minimal (quick response):**
```
Claude | Proj:AI-Root | 2025-12-31 15:00:00 | Msg:8 | Docs:20:5,70:3 | MSlots:3-7 | Tags: quick
```

<!-- 
## Boot Field (DEPRECATED v1.3 - commented out for potential future use)

Shows startup checklist completion status:

| Symbol | Meaning |
|--------|---------|
| M | manifest_valid - manifests validated against filesystem |
| T | tools_loaded - tools_manifest.condensed.yml read |
| D | dirs_loaded - directory_structure_reference read |
| Y | memory_checked - memory manifest read |
| C | context_file - notes_to_myself.md checked |

**Format:** `Boot:[MTDYC]` where each position is ✓ (done) or - (skipped)
-->

## Enforcement

Claude MUST include this footer on every response when operating in the ai_root workspace.

## Related Documents
- `ai_general/docs/20_registries/_knowledge_manifest.latest.yml`
- `ai_memories/80_working_memory/manifest.yml`
