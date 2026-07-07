# Worker-Page Ideas Canvas — filling out Session Work / Projects / Teams

**Author:** Mullion · **Date:** 2026-07-01 · **Status:** idea canvas (awaiting PianoMan's reactions)
**Applies to:** the shared `ProjectEditor` worker page — renders for **session · project · team**.
**Trigger:** PianoMan, 2026-06-30 — "the Work subtab is a start but needs work… I imagine [ideas]
will apply across Session's Work and Projects/Teams. I wonder if you could canvas for some ideas."

## Terms
- **Worker page** — the one `ProjectEditor` component; a *worker* is a session, project, or team.
- **Aspect** — the nav sections: session = Overview / Work List / Comms; project|team add Team.
- **Vital-signs bar** — a proportional, per-status colored segmented bar summarizing a todo set.
- **Turn-Link** — a link from a todo to a specific transcript turn / conversation `message_id`.

## Canvassing method
Three idea agents, distinct lenses (content-density · interaction/nav · visual/layout), each grounded
in the real code (`ProjectEditor.tsx`, `WorkMgrPane.tsx`, `ProjectComms.tsx`, the `--pe-*`/`--sst-*`
vars). Below is the synthesis — ideas ranked by **cross-worker leverage × how alive-it-makes-the-page**.
Convergence was high: the top four were independently named by 2–3 agents.

## The gap that makes it "need work"
`WorkDetail` (the session Work List detail) currently dead-ends at a read-only scaffold — it can
*show* a todo but not change status, reassign, or open files. Every command-bus verb it needs
(`todo.setStatus/assign/move/create/writeNotes`) **already exists and is wired in `WorkMgrPane`.**
So making the session Work view *actionable* is plumbing, not new backend.

---

## Tier 1 — highest leverage (recommend building first)

1. **Status "vital-signs" bar under the titlebar** *(all 3 agents, #1 twice)*
   A full-width segmented bar, one BACKGROUND-colored block per todo status (IP/BL/RV/RD/TR/DN),
   sized proportionally to counts, each showing letter + number. Reuses `STATUS_COLORS`, promoted to
   `--pe-stat-*` vars. *Why:* the single densest signal UAI has — "how much work, what state, anything
   blocked" in one squint. Directly replaces the dead "Assigned work: 0 todos" line. **All workers.**

2. **Right panel: rich default instead of "Select an item…"** *(all 3 agents)*
   When nothing is selected, render a live *worker digest*: top open todos, needs-input conversations,
   roster health (running/stopped dots), last-activity, blocked-count alert. When something IS selected,
   a typed inspector (todo → status/assignee/provenance; conversation → participants + linked work;
   session → member panel; file → file meta). *Why:* the amber right zone is the biggest dead patch;
   this makes it the most-glanced surface. **All workers.**

3. **Overview as a card GRID, not a stacked key/value list** *(visual #6)*
   Replace the single-column `pe-meta` rows (which leave two-thirds of the pane empty) with a 2–3 col
   grid of small stat cards, each with a tinted header. *Why:* the flat list is the main source of
   "empty and flat"; a grid uses the full width and reads dense-but-scannable. **All workers.**

4. **Wire the command-bus verbs into WorkDetail (make Work actionable)** *(interaction #3)*
   Drop `StatusSelect`, the grouped Assigned-to dropdown, and Open-folder into the Work detail — all
   already implemented in `WorkMgrPane`. *Why:* a session's Work view should let you *do* your next
   action, not just read it. Low risk (verbs exist). **All workers.**

## Tier 2 — makes it feel alive

5. **Live status dots + "breathing" for running sessions** — slow opacity pulse on running roster
   members, static-dim when stopped. Cheapest high-impact aliveness cue. *(content #8, visual #3)*
6. **Token-budget micro-bars** — thin green→amber→red fill per session (roster rows + session
   Overview); context pressure is the key operational constraint on a live CLI session. *(content #6, visual #4)*
7. **Enriched Work-list rows** — add `todo_####`, relative last-updated, priority `!` flag, assignee
   dot; lets you triage without opening each item (fields already loaded). *(content #4, interaction #12)*
8. **Recency heat-tint on timestamps** — every "last active" chip warms grey→amber→hot with recency,
   so a busy worker literally glows. Page-wide ambient aliveness. *(visual #12)*
9. **Comms: needs-input as a bold background block, not a 6px dot** — actionable conversations should
   pass the squint test as a colored card. *(visual #9)*

## Tier 3 — makes it connected (the "Activity" spine)

10. **Turn-Links / todo↔chat↔conversation graph** — light up the already-declared-but-inert
    `Conversation.linked_work`: a todo's Activity lists linked conversation turns (real `message_id`s
    exist now); clicking jumps to Comms + highlights the message, and conversations show a jump-back
    chip. This is the backbone of the planned **Activity area** (Decisions & Pivots / Open Questions /
    Turn-Links). *(interaction #2/#6/#8)*
11. **Activity timeline = `history.log` + decisions + turn-links, merged chronologically** — one
    scrollable "what happened & why" per todo; the history half already renders in WorkMgr. *(interaction #8)*
12. **Selection-sync across aspects + navigable breadcrumb** — carry a "focus entity" so Work→Comms
    filters to conversations touching the focused todo; make the titlebar crumb segments clickable
    (aspect switcher, hop to parent project/team). *(interaction #7/#10)*
13. **Jump-to-assignee's-session** — a todo's `uai://session/<id>` becomes a one-click
    `workspace.tabs.open`; from a project's Work list you reach the running agent in one hop. *(interaction #4)*
14. **Open Questions & Recommendations as actionable rows** — each gets "answer in chat" (opens a
    conversation pre-linked to the todo), "convert to child todo", "resolve". *(interaction #9)*

## Cross-cutting notes
- Everything above is **kind-switched content in one component** — build once, all three workers benefit.
- Tiers 1 & 2 need **no new backend** (reuse `STATUS_COLORS`, command-bus verbs, existing data).
- Tier 3 is the one net-new data surface (the Activity model) — but `Conversation.linked_work` and real
  `message_id`s already exist, so it's linking, not inventing.
- All new colors land as `--pe-*` vars (status-lane, token-heat, recency-heat, breathe) per the
  all-colors-configurable rule.

## Recommended first build
**Tier 1 as a set** (vital-signs bar + rich right panel + Overview card grid + actionable WorkDetail) —
it converts the sparse page into a dense, actionable dashboard with zero new backend, and every piece
generalizes across session/project/team. Tier 2 (aliveness) layers on cheaply after. Tier 3 (Activity/
Turn-Links) is its own design pass once the shell is solid.
