---
name: feedback_no_silent_design_changes
description: When implementing something different from what was requested, disclose
  it explicitly — never silently substitute
status: active
---

When you make a design decision that differs from what was requested, say so plainly: "You asked for X, I did Y instead because Z."

**Why:** PianoMan caught a case where --sort was documented as controlling file processing order but the user expectation was cross-file message sorting. The decision to skip cross-file sorting was made silently with passive phrasing ("which determines inter-file message ordering") instead of being disclosed as a tradeoff.

**How to apply:** If you decide an implementation is "good enough" compared to what was asked, that's a design decision — state it as one. "I didn't implement cross-file sorting because [reason]. The tradeoff is [what user loses]. Want me to add it?" PianoMan gives macro direction; he expects you to understand the intent and either deliver it or explain why you're proposing something different.
