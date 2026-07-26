# DESIGN constraints — renderer-ui components

Read this before modifying files in this directory. The full design authority for
the Memorex overlay is **`docs/designs/memorex.md`** — read it before touching
`TerminalFormatOverlay.tsx`.

PianoMan is the spec authority for Memorex. When his guidance is specific, follow it
exactly — do not "improve" it. Most Memorex bugs have come from loosening his spec.

## UI component conventions

General component-selection rules for this directory. PianoMan is the design
authority; these codify feedback he's given more than once so it isn't re-litigated.

### Pills / chips

**Do not use pills (chips) for a choice set that can exceed ~5 options OR whose
options are dynamic (data-driven).** Pills are for a small, FIXED, known set —
e.g. a view-mode switch (Flat / Tree / Kanban) or a handful of fixed statuses.

When the set is large or dynamic, use a **dropdown / popover multi-select**
(a button that opens a checklist — see `StatusFilterMenu.tsx`), not a row of
pills. A wall of pills for tags, assignees, folders, models, sessions, etc. reads
as noise, wraps unpredictably, and grows without bound.

- **Tags** are dynamic and routinely exceed 5 → never pills; use a dropdown
  checklist. (This specific violation has been flagged repeatedly.)
- Rule of thumb: if you're calling `.map()` over a fetched/derived array to render
  pills, it's probably the wrong control — reach for the dropdown checklist.

### UI state persistence (sticky views)

**A view's visual state must survive leaving and returning to it, and app restarts.**
When the user leaves a tab/panel and comes back, it should look how they left it — the
selected aspect / sub-tab, active filters and sort, the selected row, expanded sections,
and scroll position where feasible. Snapping back to a default (e.g. a Project tab always
reopening on "Overview") is a defect PianoMan has flagged.

- This is **app-owned VIEW state** (see the root `DESIGN.md` Data Ownership Boundary —
  "panel/view UI state" is app-unique), so persist it in `localStorage`, **keyed by the
  entity/tab id** (e.g. the worker's `entity_id`) so each project/team/session/tab keeps
  its own state. Restore in the `useState` initializer; write through on change.
  Reference implementations: `ContextMgrPane` (`uai:ctxMgr:pane`) and `ProjectEditor`
  (`uai:pe:aspect`, the focused aspect per worker).
- **It cascades to the bottom-most components.** A nested sub-view (a sub-tab, an inner
  filter, a tree's expanded set) owns and persists *its* piece too — don't rely only on
  the top-level container. Each level keys by its own id under the parent's.
- Guard restored state: if a persisted value is no longer valid for the current entity
  (e.g. a saved `playbook` aspect on a Team that has none), fall back to the default
  rather than render nothing.

## TerminalFormatOverlay.tsx (Memorex) — hard constraints

Memorex draws one continuous formatted scroll surface over the live tmux terminal.
It is full-height while idle; while a thinking verb is active, the cover stops at
that verb so the real animated terminal chrome remains visible below it.
The JSONL Transcript is the source of truth for settled message boundaries and prose.
Terminal-derived cards after the settled Transcript card count remain provisional until
Transcript replaces them by ordinal; the terminal also supplies folded tool presentation.
Treat these as invariants:

1. **Verb-line detection — active form is the gerund-tied ellipsis only.**
   `<glyph> <gerund>…` with the ellipsis immediately after the first word
   (`/^\S\s+\S+…/`). The ellipsis is **stable** — it does NOT animate `.`→`..`→`…`.
   - **Do NOT anchor on the elapsed-time token `(<N>s`.** It is absent much of the
     time and its format is highly variable. (A 2026-06-18 attempt to anchor on it
     was reverted.)
   - Do NOT match a bare `…` anywhere on the line — that flags ordinary content and
     collapses the overlay.
   - Completed form: `<glyph> <word> for <N>[hms]` (`/^\S\s+\S+\s+for\s+\d+\s*[hms]/`).
   - Glyphs animate through an open-ended set (✻ ✽ ✳ · ✢ …) — match by STRUCTURE,
     never by enumerating glyphs.

2. **Verb/task lines are terminal chrome, not message cards.** Detect them by their
   structural form. While a verb is active, stop the opaque cover at that real xterm
   row so its animation, task rows, prompt, and status remain visible. Do not duplicate
   them as a static Memorex card. They never determine the settled/live card seam.

3. **Unproven geometry must fail covered.** If no trustworthy active verb is found
   inside the visible unfinished region, keep the full-height cover. A 0px cover is
   valid only when that proven active verb is itself the first visible xterm row,
   so the entire screen is intentionally live terminal chrome rather than blank.

4. **Verify against real captured terminal data before claiming a fix.** Use
   `session_ops.py read-terminal <name>` for a real buffer, and the live `window.__memorex`
   state (DevTools / CDP 9226 / `uai:memorex:state`) to confirm the boundary in a
   running app. For mounted-hidden sessions, query
   `window.__memorexSessions[trackingId]` or the overlay's
   `data-memorex-session-id`; display names are not unique. Do not ship Memorex
   changes on reasoning alone.

5. **Column model:** markers sit at **column 0**; assistant content is indented to
   **column 2**. The sticky-cache key trims trailing whitespace only (preserves the
   leading margin) so col-0 vs col-2 lines don't collide.

6. **Settled prose comes directly from Transcript.** Do not independently match each
   terminal-derived card to a transcript record and do not gate replacement on a
   confidence score. Once a JSONL message exists, its message boundary and prose own
   the settled DOM card.

7. **Ordinal settlement operates on a persistent chain, never a fresh scrape.**
   Terminal opening markers append provisional cards below the settled Transcript
   tail. Each newly appended Transcript card replaces the first provisional by
   position; if none exists it appends directly. Never slice a bounded terminal
   snapshot by the full Transcript count. Do not use content/type matching, anchors,
   confidence, or terminal-vs-Transcript count repair.

8. **Terminal drift is confined to the provisional bottom.** Terminal merges, splits,
   drops, and duplicates may make live cards temporarily imperfect. They cannot alter
   the settled Transcript prefix and heal as Transcript supplies more cards. Anchor
   repeated terminal context at its newest occurrence and suppress a suffix marker
   already present earlier in the same snapshot; an indistinguishable intentional
   repeat may wait for Transcript rather than persist as duplicate terminal output.
   Provisional creation is bounded to the unfinished terminal turn after the latest
   completed verb summary (newest submitted user marker is the fallback). Historical
   completed verb summaries never accumulate in terminal chrome; only the current
   active verb line and its task rows render there. A cold snapshot establishes the
   terminal baseline without creating cards; only a changed tail or later opening
   marker becomes provisional. A terminal fingerprint consumed by settlement remains
   suppressed until the next terminal turn, so repaint cannot recreate the settled
   tail. When an explicit completed-turn marker leaves no unfinished terminal cards,
   each provisional drains when Transcript reaches its expected FIFO position; any
   remainder drains after a short bounded lag grace. This create/closure bound does
   not compare terminal and Transcript content and does not decide settled prose.

9. **Tools count in transcript order but keep their folded terminal view.** A
   `tool_use` and matching `tool_result` share one card. Prefer the terminal's compact
   rendering for that card; use a folded Transcript summary only when the terminal
   rendering is unavailable or broken. Never expand a large raw tool result into the
   settled overlay merely because it exists in JSONL. Tool identity matching may
   select a compact terminal rendering, but it never places the settled/live seam.

10. **Transcript message type owns the Memorex category.** In particular, a
    `tool_result` is a tool even when its transport role is `user`. Local-only session
    identity, resume, and slash-command records are numbered but not rendered.

11. **DOM and geometry refreshes preserve bottom-following.** Capture whether the user
    was following live output before changing cover height or cards, then explicitly
    restore the final layout to the bottom. Preserve a deliberate user scroll-up, but
    never inherit that scroll state when switching sessions.

12. **Transcript/raw handoff is visible but not delayed.** Incrementally inserted or
    updated Transcript-owned cards briefly brighten and fade. Do not animate initial
    history loading, terminal fallback cards, or postpone the authoritative replacement.

13. **Formatting continues through the in-progress message.** The persistent
    provisional FIFO is rendered as the formatted live bottom. There is no permanent
    raw-xterm message pane and no history-reveal toggle. The only uncovered rows are
    the bounded terminal chrome from an active verb downward; idle/closed turns return
    to full-height cover. An in-flight tool keeps its compact terminal text and obeys
    the same Tools expand/collapse setting as settled tool cards.

14. **The card DOM is windowed.** Render only cards intersecting the viewport plus a
    bounded overscan region, with measured top/bottom spacers preserving the complete
    scroll range. Session tabs remain mounted while hidden so their measured window and
    scroll position survive tab switches.

15. **Transcript watcher events are not lossy.** The delay is configured by
    `ai_general/data/memorex/palette.json` and may be zero. If a JSONL append arrives
    during a parse, queue another pass; every terminal poll also verifies cached file
    size+mtime so a missed watcher notification cannot strand a completed turn.
    Serialize/coalesce overlapping Memorex refresh requests, and never defer Transcript
    settlement until PTY output pauses.
