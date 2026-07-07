# UX Design Principles (UAI & any AI-built UI)

**Status:** active · **Maintainer:** PianoMan · **Since:** 2026-07-06

Durable, cross-session rules for designing UI surfaces (primarily the Unified AI
Interface, UAI). These are defaults, not dogma — when PianoMan gives a specific
instruction it wins. Capture new rules here as they're learned rather than
re-litigating them per feature.

## Terms
- **Fitts's Law** — a UX/HCI model: the time to move a pointer to a target grows
  with the distance to it and shrinks with the target's size. Practical takeaway:
  put controls close to where they're used, and make frequent targets big enough.
- **Action control** — a button/affordance that executes something (Delete,
  Refresh, +New, Archive), as opposed to a display element.

## Principles

### 1. Minimize mouse travel to actions (Fitts's Law)
It is **bad UX to require long mouse movements to execute actions.** Place an
action control **next to the thing it acts on or the control you just used** — not
across the panel. Concretely:
- "To the right/left of X" from PianoMan means **immediately adjacent to X**, not
  "somewhere on that side / the far edge." Do not `margin-left: auto` an action
  group to the panel edge when it belongs beside a specific element.
- Context actions for a tab/selection sit right by that tab/selection, so the
  cursor barely moves from the click that selected the context to the action.
- Don't strand a frequent action in a far corner "for tidiness" — proximity beats
  alignment for anything clicked often.

### 2. Persistence persists — without being persnickety
UI state (selected item, active sub-tab, filters, view toggles, panel widths)
should **persist across tab switches, remounts, and reloads** so returning lands
you exactly where you left off. But persistence must not fight the user:
- When you **change a default**, don't silently override a value the user already
  chose. Use a **one-time migration** (a schema-version marker): existing state
  adopts the new default once, then the user's own toggle persists normally.
- Never re-assert a default every load against an explicit user choice — that's
  the "persnickety" failure. Persist their choice; migrate once; then leave it.

### 3. Vary color to carry meaning
Color is a channel — use it to distinguish semantic roles, don't flatten
everything to the same text color. A **count** next to a label should not look
identical to the label; give it a distinct (accent) color so it reads as a count.
More generally: when two adjacent elements mean different things (label vs count,
outbound vs inbound, status vs name), let color help tell them apart. (Tokens
only — see the design-token system; no raw hex in inline styles.)

## Related
- Design tokens / theming: `docs/designs/design-tokens.md`, `styles.css` `:root`.
- Operating principles (work behavior, not UX): `perspective_operating_principles.md`.
