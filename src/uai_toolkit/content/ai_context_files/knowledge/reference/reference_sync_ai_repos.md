---
name: reference_sync_ai_repos
description: sync_ai_repos.sh = PianoMan's intentional manual git backup sweep; blind
  git add -A is by design, not a hazard
status: active
---

`~/bin/all_languages/bash/sync_ai_repos.sh` (PATH-symlinked as `sync_ai_repos`) is PianoMan's **intentional, manually-run backup tool**. It runs `git add -A` + `git commit -m "sync: auto-commit <timestamp>"` across the AI repo submodule list (includes `ai_general`).

The blind capture — committing *everything* dirty, including deletions — is **by design**: git/GitHub is the versioned backup, and this force-captures state that sessions hold onto or delay committing. It is **NOT a data-loss hazard**; do not propose "protected-path guards" or hardening. If it commits a deletion, the content is fully recoverable via `git restore --source=<commit>^ -- <path>`.

It is manually invoked (no scheduler/cron/hook). It only *records* working-tree state — if a file is missing, something else removed it from the tree; the sync merely commits that fact. Reinforces [[reference_environment_invariants]] (single dev env → git = backup → commit-don't-wait).
