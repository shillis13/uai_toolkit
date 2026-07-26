---
name: feedback_snapshot_colocate_with_source
description: JSONL (and similar) snapshots/backups co-locate in the SAME dir as the
  source file, never the repo data dir
status: active
---

PianoMan, 2026-06-30: "In general, I don't think the data dir is a good place to put jsonl snapshots. They probably go into the same dir as the source jsonl."

**Why:** (1) a snapshot belongs next to what it backs up (discoverable, moves/prunes with it); (2) big JSONLs (Meri's = 18 MB) do NOT belong in the repo/git under `ai_general/data/…` — that's bloat; (3) it matches the tooling's own convention — offload/consolidate already auto-write a co-located `<uuid>.jsonl.bak` next to the transcript before mutating (`lib_jsonl_archive` line ~97), and PianoMan's own manual backups sit there too (`<uuid>.pm_bak.jsonl`).

**How to apply:** write transcript snapshots into the transcript's OWN project dir (`~/.claude/projects/<projectdir>/`), not the repo. Naming: make the stem NON-bare-uuid so Claude Code doesn't scan it as a phantom session (it lists `<bare-uuid>.jsonl`). Both work: `<uuid>.reclaim_snapshot_<ts>.jsonl` (marker-before-ext, matches the global "marker before extension" rule + PianoMan's `.pm_bak.jsonl` style) OR `<uuid>.jsonl.bak` (marker-after; but a later offload OVERWRITES `.jsonl.bak`, so keep a durably-named copy for a specific reclaim). A `/tmp` copy is fine as an ephemeral extra, never the authoritative one.

Ties to [[project_self_bounce_proven]] (Meri's live Tier-1 offload) and [[reference_fork_copies_active_chain_only]] (the project-dir-symlink / co-location facts).
