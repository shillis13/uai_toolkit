---
name: ref_reminder_delivery
title: Reminder Delivery
description: Reminders are prompt injections, not alerts — delivered per schedule globally or per-session, possibly role-based
status: active
---

Reminders are trait content (ai_traits/reminders/) that get injected into prompts to reinforce agent behaviors. NOT scheduled alerts/notifications.

**Why:** Agents forget instructions over long sessions. Reminders re-inject key instructions periodically.

**How to apply:** Each reminder has a delivery schedule (every N turns, every N minutes, on specific events). Schedule can be set globally, per-session, or per-role. Dynamic reminders generate content at injection time (e.g., current_datetime). Static reminders are fixed text.
