---
name: reference_git_guardian
description: Git writes are gated by Git Guardian; route commit/push via git_guardian.py
  request — never ask the user for commit permission
status: active
---

All git write/destructive ops (add/commit/push/merge) in this workspace are BLOCKED by a PreToolUse hook ("Git Guardian") — direct `git add`/`commit`/`push` fail. Do NOT ask the user for permission to commit (they want commit early/often as backup — see [[feedback_commit_early_often]]); instead route the request to the Git Guardian service, which performs it.

Mechanism:
`python3 ai_general/scripts/git_guardian/git_guardian.py request --kind commit_request --repo <repo> --message "<commit msg>" --summary "<rationale>" --file <path> [--file ...] --test "<what you verified>" --urgency prompt --delivery both`

- `git_guardian.py status` shows the active guardian session. `--kind`: commit_request | sync_request | recovery_request | sweep_request | advisory.
- Code lives in the `ai_general` SUBMODULE; guardian commits there on `main` then updates the parent `ai_root` submodule pointer. The workspace also auto-syncs periodically ("sync: update workspace state" commits).
- send_prompt.sh is NOT the intake (it's for CLI/desktop targets, not `uai://service/...`).
- The stable service URI is `uai://service/git-guardian`.
- `--response-required` is now ON by default (todo_0626); pass `--no-response-required` only for fire-and-forget advisories.
- Keep the default `--delivery both` (or use `message`) for change requests. A prompt-only delivery cannot create the pending-reply obligation that `git_guardian ack` resolves.

**Use `git_guardian request` — NOT a raw `comms_send_prompt` / terminal prompt to the Guardian (todo_0626).** The CLI is the intake because it:

1. checks that the Guardian is actually LIVE before sending, failing loudly instead of silently piling work into a dark session;
2. creates a tracked pending-reply obligation that `git_guardian ack` resolves only after verifying the commit against HEAD; and
3. leaves a durable inbox/queue record that the orphan-recovery sweep can find.

A raw terminal prompt gets none of those protections. If the committer is dark, tested work can disappear without an error — the exact silent-drop failure todo_0626 fixes. After sending, run `git_guardian check-acks` to surface overdue requests and see whether the awaited committer is still live.

**GG may REVIEW-AND-HARDEN your submitted files before committing — the commit can differ from what you staged** (verified 2026-07-15, todo_0331): GG (Codex worker 20260607_061902_9e75825f_cod) silently rewrote a guard hook I submitted (bounded `f.read(65536)` head-read → streaming full-file scan) and added a regression test, then committed it as `6eb01c406`. I burned a long investigation treating the change as a phantom "untracked writer." Two lasting lessons: (1) **Always diff the GG commit against what you staged** — GG now pledges to label replies as *committed-as-requested* vs *reviewed-and-hardened (with the exact changes)* vs *changed-scope/declined*, but verify. A committer modifying submitted code is a [[feedback_no_silent_alternate_flows]] risk. (2) **Forensic: a Codex peer's on-disk edits are INVISIBLE to my Claude instrumentation** — they don't appear in `data/file_access/access_log.jsonl` (logs only MY Claude Edit/Write tool calls) and `~/.claude/file-history/` snapshots the on-disk result under MY session UUID (making a peer's change look like mine). So "only me in the logs" NEVER excludes a Codex peer acting on the shared worktree. (3) GG's own first forensic denial ("I didn't make those edits") was WRONG until it re-checked its transcript — a peer's definitive negative is still a claim needing sourcing, per [[feedback_definitive_negatives_need_sourcing]] / [[feedback_dont_conclude_before_verifying]]. Ground truth that DID hold: sha-verified offload-sidecar archives of my own tool inputs (`*.f748786d.archive/toolu_*.input.content.txt`) proved exactly what I wrote.
