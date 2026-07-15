# Response Formatting Standards v1.0

All AI responses in the ai_root workspace must follow these formatting rules.

## 1. TO YOU Markers

Every user-facing output section must be wrapped with `TO YOU: #N` markers:

```
═══════════════════════════════════════════════════════
TO YOU: #1
═══════════════════════════════════════════════════════

[response content here]
```

**Numbering resets to #1 at the start of each new turn** (user prompt). It is NOT cumulative across the conversation. Multiple sections within a single turn increment: #1, #2, #3.

## 2. Response Footer

Every response must include a metadata footer. See `ai_traits/knowledge/40_specs/spec_response_footer.latest.condensed.yml` for full spec.

Minimal format:
```
Claude | Proj:AI-Root | Chat:Session-Title | 2026-04-15 14:30:00 | Msg:5 | Usage:NA | Docs:20:3,40:1 | MSlots:3-6 | Artifacts:0 | Tags: keyword1, keyword2
```

## 3. File Reference Formatting

When referencing files the user may open, edit, or review, use raw absolute paths:

- `/absolute/path/filename:line` — cmd-clickable in most terminals

When NOT needed: AI-to-AI coordination paths, inline code discussion, files already visible in tool output.

## 4. General Output Style

- Concise and direct — lead with the answer, not the reasoning
- Use markdown formatting (headers, tables, code blocks) for structure
- Align column boundaries in tables
- Don't restate what the user said
- Don't summarize what you just did unless the user can't see it

---

┌─────────────┬────────────┬────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Version** │ **Date**   │ **Changes**                                                                                │
├─────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1.0         │ 2026-04-15 │ Consolidated from spec_response_footer, operating_principles §11, and auto-memory feedback │
└─────────────┴────────────┴────────────────────────────────────────────────────────────────────────────────────────────┘
