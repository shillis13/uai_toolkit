---
name: feedback_pills_only_for_stable_sets
description: UX rule — filter/selector Pills only for sets whose membership rarely
  changes (status enum yes; projects/assignees/tags no → use dropdowns)
status: active
---

PianoMan's UX standard (2026-06-26, UAI Work Mgr): **Pills are not to be used for sets of things whose membership is expected to change more often than rarely.** Status is a fixed enum → pills OK. The set of available Projects, Assignees, and Tags changes regularly → NEVER pills; use dropdowns/selects for grouping/filtering by those, and render a single item's value (e.g. this todo's assignee) as a display chip, not a filter pill.

**Why:** A pill bar implies a small, stable, scannable set. When membership churns, the bar grows unbounded, reflows, and the muscle-memory of "where's the X pill" breaks. Dropdowns scale and stay stable.

**How to apply:** Filter/group/sort over a changing set → dropdown. Over a fixed enum → pills fine. A pill showing one entity's own value (status badge, assignee name on a row) is display, not a filter — allowed. He asked this be remembered and made part of UX instructions/standards; also written to the UAI repo at `ai_general/work/projects/uai_app/unified_ai_interface/docs/ux_standards.md`. Related: [[feedback_more_colors_means_bold_backgrounds]], [[feedback_match_communication_register]].
