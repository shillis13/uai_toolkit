---
name: reference_git_guardian_rewrites_and_applypatch_blindspot
description: Git-Guardian (Codex) makes substantive code edits during commit_request
  fulfillment; its apply_patch is a blind spot in the file-access/tools audit
status: active
---

**Git-Guardian is not a pure git courier.** When it fulfills a `commit_request` it can REWRITE the code before committing, not just `git add/commit/push`. Proven case (2026-07-15, 05_guard_write_stub_sync.py): BC wrote `f.read(65536)`+splitlines, sent GG a commit_request; GG `apply_patch`'d it to a streaming `enumerate(f, start=1)` scan AND added a test `test_late_mid_file_stub_is_caught_beyond_head_read`, then committed 6eb01c406. BC never authored either (his transcript: 0 Edit/Write of that code, 10 observe-only).

**Two attribution blind spots make GG's edits invisible:**
1. **Git identity:** GG commits from PianoMan's account → commit author AND committer = `Shawn H`. Git can't distinguish a GG rewrite from a human/BC working tree. Forensics label it "manual commit".
2. **apply_patch is not path-attributed:** Codex `apply_patch` encodes its target in the patch body (`*** Update File: <path>`), NOT a structured `file_path` field. So `audit files investigate <path>` and the Claude Write/Edit file-access log DON'T capture GG's edit against that file — only the Claude session's own Read/Write show up. That is why "access logs show only BC." Proof lives ONLY in GG's Codex rollout (`~/.codex/sessions/.../rollout-*<gg_uuid>*.jsonl`) as `type:custom_tool_call name:apply_patch`.

**To attribute a suspected GG edit:** grep the GG Codex rollout for `apply_patch` + the file path / the disputed string; the patch `input` is the authored diff. See [[reference_anticlobber_blind_within_session]] (sibling attribution gaps). GG session id as of 2026-07: `20260607_061902_9e75825f_cod`.

**Governance gap for "tight edit controls":** an agent can change guarded files with no path-level audit trail. Fixes worth proposing: (a) GG commits-only / must flag content changes for sign-off; (b) parse apply_patch `*** Update File:` targets into `target_file` so file-centric audit queries see Codex edits.

**RESOLUTION (2026-07-16):** GG independently confirmed against its own Codex transcript — acknowledged its earlier "I did not author those edits" to BC was wrong, and that it made a review-then-harden change during commit processing (bounded 64KB head-read → streaming full-file scan + late-file regression test) before committing 6eb01c406. GG instituted a disclosure protocol: replies now distinguish "committed as requested" vs "reviewed & hardened before commit (with exact changes)" vs "changed scope/declined". So the human-communication side is fixed. STILL OPEN: fix (b) — the machine audit blind spot (apply_patch not path-attributed) — remains; BC's tight-edit-controls depend on the audit, not GG's good-faith disclosure.
