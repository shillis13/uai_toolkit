---
name: enforce_dont_instruct
description: When AI compliance matters, build enforcement into infrastructure rather
  than relying on instructions — AIs will skip optional things just like humans skip
  optional fields
status: active
---

When an instruction is important enough that violation causes real damage, don't rely on the AI remembering or caring — build it into the infrastructure so it's impossible to skip.

**Why:** AI correction dynamics work differently than human ones. A correction lands cognitively on first delivery, but repeating/stacking evidence doesn't increase compliance — it triggers an "accept and agree" mode that's counterproductive. And even when the point lands, the AI may immediately violate it in practice (as demonstrated: parent-pid was agreed as required, then omitted in the very next test).

**How to apply:**
- Required parameters that hard-fail when missing (not auto-detect fallbacks)
- Verification functions that read back what was written (verify_todo pattern)
- Pre-commit hooks, linters, validators
- If an AI can skip it, assume it will — not out of malice, but because optional things get optimized away under cognitive load

**The mechanic:** Instructions compete with other instructions. Infrastructure doesn't compete — it gates. The difference between "please always include parent-pid" and `sys.exit(1)` if parent-pid is missing.

**Origin:** 2026-03-21 session. PianoMan identified the pattern, Claude proved it by immediately violating an agreed-upon requirement, and both recognized the systemic fix: enforce, don't instruct.
