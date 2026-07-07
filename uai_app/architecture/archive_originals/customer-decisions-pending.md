# Customer Decisions — Pending Review

Decisions made on the customer's behalf by the team. PianoMan should review and confirm, correct, or override when available. Anyone on the team can add items.

## How to use this file
- **Add items** when you make a judgment call the customer would normally make
- **Include your recommendation** and reasoning
- **Mark CONFIRMED/OVERRIDDEN** after customer review with date and notes
- Route review requests to PianoMan via Hamilton or direct notification

---

## Pending

| # | Date | Decision/Question | Decided By | Recommendation | Confidence | Status |
|---|------|-------------------|------------|----------------|------------|--------|
| 1 | 2026-04-01 | P1.4/P1.5 acceptable as known gaps for MVCR-1 gate? | Pixel | Yes — both require live terminal, low risk since P1.1/P1.2 are the real gate | Medium | PENDING |
| 2 | 2026-04-01 | P1.5: Should Escape close a terminal pane? | Pixel | No (safety rail against accidental close) — but PianoMan may want fast-dismiss workflow | Medium | PENDING |
| 3 | 2026-04-01 | PianoMan's 12 feedback items: MVCR-1 vs MVCR-2 triage | Pixel | 11 items to MVCR-1, 4 to MVCR-2, 2 to MVCR-3. See story_backlog_v2.0.md "PianoMan Feedback Stories" section | Medium | PENDING |
| 4 | 2026-04-01 | Replace [FOCUS] text tag with bright border | Pixel | Yes — standard idiom, PianoMan found text label confusing | High | PENDING |
| 5 | 2026-04-01 | Worker panel below prompt box (layout reorder) | Pixel | Yes — PianoMan feedback, input-at-bottom convention | High | PENDING |
| 6 | 2026-04-01 | Card state definitions: "sessionless" = no terminal backing; "dead/gone" = terminal cleaned up but registry remains | Pixel | Proposed definitions, need customer confirmation on semantics | Low | PENDING |
| 7 | 2026-04-03 | 2x2 grid/split view is MVCR-2, not MVCR-1 — don't invest more in it now | Pixel | Grid partially works but is SV2.1-SV2.4 scope. Core single-session path first. | High | PENDING |
| 8 | 2026-04-03 | Rename "Context" panel to "Session Details" | Pixel | PianoMan's language — "Context" is overloaded (context window, context panel). "Session Details" is clearer. | High | PENDING |
| 9 | 2026-04-03 | "Open as Tab Group" should NOT change grid layout | Pixel | It creates a Tab Group bracket in the tab bar. Center pane shows one tab at a time. Split view is separate MVCR-2 feature. This is DEF-4. | High | PENDING |

## Confirmed

| # | Date | Decision | Decided By | Customer Verdict | Date Confirmed |
|---|------|----------|------------|-----------------|----------------|
| 7 | 2026-04-01 | P1.4: Double-Esc clears input, Triple+ Esc cancels AI | Pixel (corrected) | PianoMan corrected original spec to match actual CLI behavior | 2026-04-01 |

---

*Maintained by: Pixel (primary), open to all team members*
*Review cadence: Batch for PianoMan when he's available; route via Hamilton if urgent*
