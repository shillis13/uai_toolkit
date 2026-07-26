---
name: feedback_version_bump_build_increment_default
description: UAI version bumps are ALWAYS build (patch/3rd-element) increments by
  default — never choose --minor/--major on my own judgment; higher element only when
  a todo specifies it or PianoMan draws the line. Build version ≠ commit version (no
  matching convention).
status: active
---

PianoMan's correction (2026-06-29), after I bumped UAI 1.2.20 → **1.3.0** with `uai.sh --minor` on my own judgment ("multi-feature batch → minor"). He: "You shouldn't have done it, but it's not worth backing out... just don't do it again."

**The rule:**
- **Default = build increment** (the 3rd/patch element): `uai.sh --rebuild --patch` (or plain default). This is the ONLY increment I choose autonomously.
- **NEVER** pick `--minor` / `--major` / `--set` on my own. A higher-element bump happens ONLY when **(a)** a todo explicitly indicates the version-increment type, OR **(b)** PianoMan explicitly "draws a line in the sand."
- **Build version ≠ commit version.** There is NO convention that the deploy/build version matches the commit version — don't conflate them, don't assume or assert such a standard. (I had been treating them as coupled and putting "(vX.Y.Z)" framing as if it were a standard.)

**Why:** version semantics (when a minor/major milestone happens) is PianoMan's call, not an agent's judgment — the slightest unsanctioned bump churns the number across the many parallel sessions all patch-bumping in lockstep. Stay on the build/patch line until told otherwise.

**How to apply:** when building/deploying UAI, use `uai.sh --rebuild --patch --no-launch` (build increment, don't disturb his running app). Only deviate if a todo states the increment type or he says so. Still state the deployed version when telling him to relaunch — see [[feedback_version_on_deploy]]. Related: [[feedback_no_silent_design_changes]] (this was a silent judgment call I should have flagged or defaulted-safe on).
