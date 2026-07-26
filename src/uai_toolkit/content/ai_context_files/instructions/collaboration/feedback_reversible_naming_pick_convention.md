---
name: feedback_reversible_naming_pick_convention
description: Reversible naming/style call → match existing convention and go, never
  block
status: active
---

For a reversible naming or style call (a filename, identifier, casing, singular-vs-plural), pick the option that matches existing convention and proceed — never block a whole effort on it.

**Why:** I stalled the session-scripts deprecation broadcast for a day waiting on PianoMan to choose between `session_key_values.py` and `sessions_keys_values.py`. Hamilton (coordinator, on PianoMan's behalf) picked `session_key_values.py` — singular, matching `session_registry.py`/`session_store.py` — and set this as a standing rule. The cost of a wrong reversible name is trivial (rename later); the cost of stalling downstream work is real.

**How to apply:** When the choice has no functional or irreversible impact, default to the sibling/existing convention and keep moving. Only surface it if it's genuinely irreversible, user-facing-core, or the conventions conflict. Related: [[feedback_own_decisions_dont_punt]], [[feedback_no_ready_whenever]], [[feedback_dont_stop_at_natural_breaks]].
