---
name: Timestamp Display Convention
description: Display timestamps in local time, store/transport in UTC
status: active
---

Timestamps should always be displayed in local time, not UTC. Under the hood, UTC is
the right storage/transport format, but all user-facing display must be local time.

**Why:** PianoMan needs to see times that match his clock. UTC requires mental math.

**How to apply:** Any spec, UI, or log output that shows timestamps to the user uses local time.
Internal storage, wire format, and cross-system communication use UTC. Conversion happens at
the display boundary.
