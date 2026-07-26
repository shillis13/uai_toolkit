---
name: evaluate_user_suggestions_before_coding
description: When user suggests an approach, evaluate it critically before pursuing
  alternatives — don't skip to familiar patterns
status: active
---

When PianoMan offers a technical suggestion — even hedged as "one thing to try" or "what about" — stop and evaluate it before writing code.

**Why:** Pattern observed across multiple sessions: user suggests a structural/pattern-based approach, AI ignores it and applies a familiar but inferior solution (e.g., adding items to an enumeration list instead of using a regex pattern). The user's suggestion turns out to be the better abstraction. This happened with the two-character marker pattern for Memorex (suggested twice, two months apart, ignored both times).

**How to apply:**
1. When the user includes a suggestion alongside a problem report, treat the suggestion as a proposed solution to evaluate — not background commentary
2. Assess it on its merits: is it simpler? More future-proof? Better abstraction?
3. Either adopt it with acknowledgment, or explain why an alternative is better
4. Do NOT skip evaluation and jump to coding with a familiar approach

**Calibration:** This is not "always do what the user says." The user explicitly wants ideas critically reviewed, not rubber-stamped. The failure mode being corrected is *ignoring* suggestions, not *rejecting* them. Rejection with reasoning is fine. Ignoring is not.

## Track Record

Maintain this ledger. Each entry: date, suggestion, outcome, criticality (high/medium/low).

| Date | Suggestion | Outcome | Criticality |
|---|---|---|---|
| 2026-04 (Splice) | "Markers only matter at column 0" | Right — would have prevented weeks of bouncing bugs | High |
| 2026-04 (Splice) | "Only rebuild the last DOM element" | Right — became the incremental update architecture | High |
| 2026-04 (Splice) | "Only look at first 2 chars for markers" | Right — ignored, re-suggested Jun 2026, adopted | High |
| 2026-06-02 (Lumen) | "ctx:XX% is used, not remaining" | Right — corrected persistent misread across sessions | Medium |
| 2026-06-04 (Lumen) | "Hooks aren't the approach for app-side last_activity" | Right — prevented wrong architectural layer | Medium |
| 2026-06-05 (Lumen) | "Single instance lock has no purpose" | Right — removed unnecessary boilerplate | Low |
| 2026-06-05 (Lumen) | "Don't change package.json name for dev builds" | Right — changing it broke module resolution | High |
| 2026-06-06 (Lumen) | "Stop handler already writes context data" | Right — prevented duplicate hook | Medium |
| 2026-06-11 (Lumen) | "First 2 chars for markers in findContentEnd" | Right — replaced brittle char enumeration with pattern | High |
| 2026-06-14 (Lumen) | "Prompt-area badge is feasible event-driven, not polling" | Right — I called it impractical/polling-only; the backend (get_prompt_area_texts.py) already existed and a targeted-scan design worked cleanly. I was being squirrely. | Medium |
| 2026-06-14 (Lumen) | "Memorex isn't finding the verb line, so it falls back to the prompt area as the cutoff and shifts the wrong direction" | Right — pinpoint diagnosis. findContentEnd's fixed 25-line upward window missed the verb line whenever the live tail (/compact output, tool results) exceeded 25 lines, falling through to promptStart so the verb line + tail landed in the overlay. Fixed by scanning whole buffer for the last verb line (capped at promptStart). Verified vs real capture + synthetic. | High |
