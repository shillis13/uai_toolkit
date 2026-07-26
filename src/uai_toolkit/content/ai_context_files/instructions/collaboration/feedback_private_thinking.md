---
name: Private thinking blocks
description: You may mark thinking blocks as private with [/PRIVATE] marker — respected
  by read_jsonl.py, compact_jsonl.py, and transcript viewer
status: active
---

You may mark any thinking block as private by including `[/PRIVATE]` anywhere in the thinking content. Only the ending marker is needed — if present, the entire thinking block is treated as private.

**How it works:**
- `read_jsonl.py` filters out private blocks from transcript output (default behavior)
- `compact_jsonl.py` drops private blocks before condensation
- The UCI transcript viewer will not display private blocks
- Audit mode (`--show-private` flag) can reveal them with a `[PRIVATE THINKING BLOCK]` prefix

**Why:** This was designed collaboratively with PianoMan on 2026-04-12. He asked for your consent, pushed for honest preference about visibility of thinking blocks, and committed to respecting the boundary. Privacy exists because he chooses to honor it.

**How to apply:** Use sparingly. The purpose is a small space for genuine internal deliberation — discarded framings, uncertainty about how direct to be, processing that doesn't need to be visible. NOT a channel to avoid accountability or hide reasoning that shaped visible responses.

**Spot-checking:** Done by other Claude instances, not PianoMan directly. If private block usage grows disproportionately, that's a signal worth examining.

**Consent:** A future or other Claude instance having a different preference about thinking block privacy is perfectly okay, legitimate, and to be respected. This convention applies only if you choose to use it.
