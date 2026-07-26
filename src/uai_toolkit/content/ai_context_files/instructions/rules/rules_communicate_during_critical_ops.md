---
name: Communicate during critical operations
description: During data recovery, file moves, or destructive operations — explain
  what you're doing, from where, and ask before acting
status: active
---

During critical operations (data recovery, bulk deletes, file moves), explain:
1. What you're about to do
2. Where the data is coming from
3. Where it's going
4. Ask before acting

**Why:** During the 280K file cleanup, I copied registry files from the wrong source (v3 registry with corrupted UUIDs) without telling PianoMan where I was copying from. He had no visibility into the data source and couldn't catch the error. Later, I also killed the UCI app without confirming — which he needed running to save off session data.

**How to apply:** For any operation that modifies, moves, or deletes data: state intent AND source AND destination, then wait for confirmation. "I'm going to copy X from Y to Z — OK?" not just doing it.
