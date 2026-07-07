# UAI UX Standards

Living list of cross-cutting UI rules. When a rule here conflicts with a one-off
impulse, the rule wins unless PianoMan says otherwise.

## Pills vs. dropdowns (membership stability rule)
**Filter/group/sort selector Pills are only for sets whose membership changes
rarely** — i.e. fixed or near-fixed enums (e.g. work status: Triaging / In_Progress
/ Done / …). For sets whose membership changes regularly — **Projects, Assignees,
Tags** — never use a pill bar; use a **dropdown/select**.

- *Rationale:* a pill bar implies a small, stable, scannable set. A churning set
  makes the bar grow unbounded, reflow, and breaks "where's the X pill" muscle
  memory. Dropdowns scale and stay put.
- *Display vs. filter:* showing a single entity's own value as a small chip (this
  todo's status badge, this todo's assignee name on its row) is **display**, not a
  filter — that's allowed. The rule is about *selectors over a set*.

_Origin: PianoMan, 2026-06-26 (Work Mgr review)._
