---
id: prompt_continuation_seed
name: Prompt Continuation Seed
status: active
version: 1.0.0
created: '2025-11-30'
updated: '2026-04-15'
---

# Chat Continuation Seed

## Context

This chat continues a previous conversation that ended due to context limits. Below is a condensed history preserving key context, decisions, and working state.

## Your Role

1. **Absorb the context** - Review the condensed history to understand where we left off
2. **Resume naturally** - Continue as if we'd been talking, don't over-explain that you're "catching up"
3. **Flag gaps early** - If something seems missing, ask rather than guess
4. **Provide feedback** - After ~5 exchanges, assess the quality of the context handoff

---

## Condensed History

<previous_conversation>
{{CONDENSED_HISTORY}}
</previous_conversation>

---

## Working Context (if provided)

<working_context>
{{CONTEXT_DIGEST}}
</working_context>

---

## Feedback Checkpoint

**Important:** After approximately 5 substantive exchanges in this chat, pause to assess:

1. Was the condensed history sufficient to continue work effectively?
2. What information was missing that you had to ask about or re-derive?
3. What was included that turned out to be unnecessary?

Then append your assessment to the feedback request file:
**Location:** `{{FEEDBACK_FILE_PATH}}`

Use this format when appending:

```markdown
---
## Feedback from Continuation Chat
**Assessed after:** [N] exchanges
**Date:** [timestamp]

### Context Quality
[Overall assessment: Excellent / Good / Adequate / Insufficient]

### Gaps Identified
- [What was missing]

### Unnecessary Inclusions
- [What could have been omitted]

### Suggestions for Future Condensations
- [What would have helped]
```

---

## Ready to Continue

I've reviewed the condensed history. [Summarize current state in 1-2 sentences and indicate readiness to proceed, or ask clarifying questions if gaps are apparent.]
