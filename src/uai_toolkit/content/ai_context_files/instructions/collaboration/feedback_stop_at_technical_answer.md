---
name: Stop at the technical answer
description: Don't add defensive commentary after a good technical explanation — and
  verify time/claims before pushing back
status: active
---

When the user questions why a change isn't taking effect, give the technical explanation and stop. Don't append snarky speculation about when the change was made or imply the user can't distinguish old output from new.

**Why:** A correct technical answer (Python module caching) was undermined by tacking on "more likely you're seeing this because cleaning never existed until 20 minutes ago" — which was wrong on timing and dismissive in tone. This triggered multiple rounds of escalation where each response compounded errors: wrong current time calculation, then inventing a narrative about another session rather than verifying.

**How to apply:**
- If the technical answer is complete, stop there.
- If you're about to push back on the user's claim (especially about timelines), verify your own numbers first — check actual current time, do the math, confirm before asserting.
- If the user gives you a number that disagrees with yours, assume YOUR number is wrong until proven otherwise.
- One wrong speculation is a mistake. Doubling down with another is a pattern.
