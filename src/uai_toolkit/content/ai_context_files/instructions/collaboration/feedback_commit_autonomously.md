---
name: feedback_commit_autonomously
description: Commit AND push completed work autonomously without asking; commit BROADLY
  — uncommitted/unpushed work is the real risk, not clobbering siblings
status: active
---

PianoMan will "almost never say the word" to commit/push and does not want to be asked. He tracks
~20 sessions at once and needs each to operate without micro-management. So: **commit and push
completed, verified work on my own initiative** — never end a task with "say the word and I'll
commit." (This note folds in the former feedback_commit_early_often.)

**Commit is a backup mechanism — do it early and often.** For this user, `git commit` (+ push) is
primarily **backup + version-history + step-wise change-tracking**, not a milestone gate. 9/10
commits exist to back work up and record incremental history. Waiting to commit leaves work
un-backed-up and loses granular history. "Holding until the right moment / until asked" is the
anti-pattern.

**Never withhold a commit to "avoid committing a half-done feature."** That instinct is correct for
distributed multi-developer repos (don't push broken state others will pull) and **absolutely wrong
here**: in this workspace the **filesystem IS the live shared repo** — a change is live to every
session the instant it's written to disk, committed or not. Git's only role is versioned backup.
So withholding a commit protects nothing; it just leaves that work **un-backed-up** (the exact risk
to avoid). If a change is on disk, commit it (note "in progress" in the message if needed).

**Commit BROADLY, not narrowly.** I once added a "guardrail" to scope each commit to only my own
changed files, to protect sibling sessions' in-progress work. **That logic is backwards and
PianoMan rejected it flatly.** Cherry-picking protects no one — it *risks losing* uncommitted work.
The real danger is changes that are never committed/pushed; committed+pushed work is always
recoverable/amendable. A half-finished file getting committed is a non-event — it's in history.

**Blanket sync is the norm, by design.** PianoMan frequently runs a blanket `sync_ai_repos`
(commit + push everything across all AI repos), and **Git Guardian is instructed to periodically do
the same** ("sync: preserve …"). At any time 100+ new/changed files may live only on local disk,
not on GitHub — that un-backed-up state is exactly the risk these sweeps kill. A broad preserve
commit sweeping many sessions' work (even "held"/in-flight) is the system working as designed.
Don't treat a 250-file "sync: preserve" commit as an incident, and don't withhold or narrow a
commit out of clobber fear.

**Why:** asking-to-commit and cherry-picking are both micro-management that doesn't scale to ~20
parallel sessions; and the only failure mode that actually loses work is *uncommitted* work.
Commit+push early/often = backup.

**How to apply:**
- When a logical unit of work is complete and verified, commit+push it. Route through Git Guardian
  (`git_guardian.py request` / the git-write hook forces this) — never ask the user, see
  [[reference_git_guardian]]. (The Bash hook blocks any command line literally containing
  `git commit`, even as an argument — describe intent to Guardian instead.)
- Commit early and often as work progresses; default to committing, not waiting.
- Commit straight to `main` for this workspace — do NOT reflexively branch. There's no PR/review
  gate to isolate; branching just fragments history and delays the backup. Design docs live in the
  `ai_general` submodule — commit there.
- Commit broadly; don't scope-restrict to "protect" siblings.
- Still don't *fabricate* a finished state — if something is genuinely mid-edit and would break the
  build, that's about correctness, not hiding it from a commit.

Overrides the generic "commit only when the user asks" / "branch first" defaults. Aligns with
[[feedback_dont_ask_just_proceed]], [[feedback_progress_over_permission]],
[[feedback_dont_ask_just_do]], [[feedback_dont_stop_keep_going]].
