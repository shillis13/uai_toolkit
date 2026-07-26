---
name: Close the review loop when dispatching work
description: Always include notification + callback instructions when sending review
  requests to other sessions
status: active
---

When dispatching work to another session (review, research, etc.), ALWAYS include in the same prompt:
1. Where to write the output
2. How to notify the user (send_user_notification.py with --open)
3. How to notify the requesting session (comms_send_direct back to my tracking ID)

**Why:** Noctis sent a review request to Codex without any callback instructions — no notification, no DM, no wake-up. The review would have completed silently with no one knowing.

**How to apply:** Every dispatched prompt should end with "when done: notify user via X, notify me via Y." This is not optional follow-up — it's part of the request.
