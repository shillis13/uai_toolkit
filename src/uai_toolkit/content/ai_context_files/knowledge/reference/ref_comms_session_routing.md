---
name: ref_comms_session_routing
title: Comms Session Routing
description: comms_send_prompt must route by tracking ID, not just display name
status: active
---

comms_send_prompt should route by session tracking ID (e.g., 20260607_054120_dd7de4a7_cla), not just display name (e.g., "Flint"). Currently only the display name works, tracking ID returns "Session does not exist."

**Why:** Display names are mutable (sessions rename themselves). Tracking IDs are stable identifiers. Game configs store tracking IDs, not display names. If a session renames itself, the game config breaks.

**How to apply:** File as a comms infrastructure bug. The session lookup in send_prompt.sh needs to check both display name and tracking ID.
