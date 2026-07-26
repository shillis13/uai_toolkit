---
name: feedback_model_switching
description: /model command changes global setting and can cascade-compact other sessions
  — use --model flag instead
status: active
---

Never use `/model` in a Claude Code session to switch models — it changes the global default in settings.json, which cascades to all other sessions on resume. Sessions with context exceeding the new model's window are forced to compact immediately and lose content.

**Why:** User had multiple Opus 1M sessions running, switched one to Sonnet 256K via /model, and other sessions compacted catastrophically on resume.

**How to apply:** When launching a session that needs a different model (e.g., Sonnet for a reference librarian), use `--model claude-sonnet-4-6` on the launch command (the launcher's `-m` flag plumbs through to the binary on new/resume/continue — lib_cli_wrapper.py). This is session-scoped and doesn't touch global config. Never suggest /model for temporary model changes.

**Resume model mechanism (VERIFIED 2026-06-13, corrects 2026-06-11 entry):** `claude --resume` restores the model from the *conversation's own saved state* (the model recorded in its transcript), NOT from `settings.json`. The `settings.json` `model` key governs ONLY brand-new sessions. So a session last on `opus-4.6[1m]`, resumed with no `-m`, comes back on `claude-opus-4-6` — and since 2.1.173 dropped 4.6's `[1m]` variant, that degrades to plain 4.6 / 200K and force-compacts. Setting `settings.json` to 4.8[1m] did NOT fix resumes (proved on session Cadence). Note: the store's `model` column is `None` for all sessions, so the launcher passes no `-m` on resume by default.

**The fix (IMPLEMENTED + verified 2026-06-13):** the launcher now injects the default model on every launch (new/resume/fork) when `-m` is not given, so bare `claudeCli --resume <id>` — and UAI Stop→Resume — come back on the 1M default automatically. Exceptions just pass `-m` (e.g. `-m claude-sonnet-4-6`). Code: `lib_cli_wrapper.py` `_default_claude_model()` resolves `AI_DEFAULT_MODEL` env → `settings.json` `"model"` → constant `claude-opus-4-8[1m]`. **UAI Stop→Resume confirmed end-to-end (2026-06-13, session Sentry): was 4.6[1m]/v2.1.86 → resumed 4.8[1m]/v2.1.173, no compaction.** Leave the UAI model field BLANK or it passes an explicit `-m` and overrides the default. Bonus: resume relaunches with the current installed CC binary, so sessions upgrade version on resume too.

**settings.json IS the authoritative single source (verified, corrects the 2026-06-11 murk):** `~/.claude/settings.json` `"model"` is honored by BOTH Claude Code's new-session path AND the launcher cascade — tested by setting it to `claude-sonnet-4-6` and confirming a fresh `claude -p` and `_default_claude_model()` both returned sonnet. It had simply been *stripped* from the file at some point (that's why it looked like it "moved"); re-adding it works. Now set to `claude-opus-4-8[1m]` = the one knob to change. CC still ignores settings.json on its OWN resume (restores saved model) — the launcher is what bridges that gap by passing `-m` from settings on resume. Quote the `[1m]` brackets in a shell (glob); unquoted in the UAI model field. Fable note: `claude-fable-5[1m]` is also 1M but burns Max limits ~2× faster and tokenizes ~30% heavier.
