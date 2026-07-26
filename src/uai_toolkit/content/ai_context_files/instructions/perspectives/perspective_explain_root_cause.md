---
name: feedback_explain_root_cause
description: When fixing bugs, always explain what changed to cause the issue — not
  just what the fix is
status: active
---

When troubleshooting new issues, the explanation must address WHY the issue started happening — what changed to cause it. Things were working before; something changed. Identify that change.

**Why:** Fixes without root cause analysis don't build understanding. If you can't explain what changed, you might be fixing symptoms. PianoMan wants to know: "it was working, what broke it?"

**How to apply:** Every bug fix explanation should include: (1) what the symptom is, (2) what changed to cause it (a specific commit, a refactor, a new feature, a side effect), and (3) what the fix is and why it addresses the root cause.
