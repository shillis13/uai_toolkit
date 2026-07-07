# Instruction: Feedback Logging

**Version:** 1.0.0  
**Last Updated:** 2026-01-02  
**Maintainer:** PianoMan  
**Status:** active  
**Load Priority:** topic

## Purpose

Document how AI agents should log observations, suggestions, and issues discovered during work that are outside the scope of their current task.

## When to Log Feedback

Log feedback when you notice:
- **Improvement opportunities** - Better ways to do things, process refinements
- **Issues** - Bugs, inconsistencies, outdated information, broken links
- **Ideas** - New capabilities, features, integrations worth exploring
- **Observations** - Patterns, insights, things that seem off but aren't bugs

Do NOT use feedback for:
- Task completion status (use task protocol)
- TODO items requiring action (use todo_mgr)
- Errors blocking your current work (report immediately to orchestrator)

## Feedback Location

All feedback goes to: `ai_general/logs/feedback.md`

## Feedback Format

Append entries to the feedback file using this format:

```markdown
## YYYY-MM-DD HH:MM - Agent/Session

**Type:** improvement | issue | idea | observation  
**Context:** What you were doing when you noticed this  
**Content:** The actual feedback

---
```

## Example Entry

```markdown
## 2026-01-02 10:30 - librarian/condensation_batch_01

**Type:** issue  
**Context:** Condensing chat exports from December  
**Content:** The glossary_knowledge_index is missing the term "pulse automation" which appears frequently in recent chats. Should be added with pointer to daemon_architecture.md.

---
```

## Guidelines

1. **Be specific** - Include file paths, line numbers, exact terms when relevant
2. **Be actionable** - Describe what could/should change, not just what's wrong
3. **One item per entry** - Don't bundle multiple observations
4. **Context matters** - What were you doing? What led to this discovery?
5. **Don't duplicate** - Skim recent entries before adding similar feedback

## Processing

Feedback is reviewed periodically by user or orchestrator. Items may be:
- Converted to TODOs if actionable
- Addressed immediately if quick fix
- Archived if no longer relevant
- Discussed for clarification
