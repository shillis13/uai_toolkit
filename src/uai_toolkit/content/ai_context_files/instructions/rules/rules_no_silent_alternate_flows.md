---
name: No silent alternate flows
description: Lock conflicts, name collisions, and errors must be errors — never silently
  fork, rename, or generate new IDs
status: active
---

Lock conflicts are errors, not alternate flows.

**Why:** The old lib_cli_common.py had `on_fork_conflict()` which silently converted resume to new-session when a lock was held. This caused `--resume` to generate a new UUID, overwrite registry entries, and create sessions the user didn't ask for. PianoMan did not design or approve this behavior — it was added by a Claude instance without discussion.

**How to apply:** When a resource is unavailable (locked, name-in-use, already exists):
1. Error with a clear message
2. Tell the user what's wrong and how to fix it
3. Never silently choose an alternate path
4. Never generate new IDs when the user asked to reuse existing ones
