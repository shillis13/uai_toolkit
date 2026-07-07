# Developer Instructions — Git Guardian Workflow

**Version:** 1.0  
**Status:** draft implementation target  
**Created:** 2026-06-08

## Core Rule

You may edit files and inspect Git state. You may not run restricted Git mutation commands unless you are the active Git Guardian.

If you need Git write operations, send a request to:

```text
uai://service/git-guardian/prompt
```

Do not bypass hooks. Do not retry blocked commands.

## Allowed

Read-only commands such as:

```bash
git status
git diff
git diff --cached
git log
git show
git blame
git branch --list
git remote -v
git config --get user.name
git stash list
```

## Restricted

Do not run mutation commands such as:

```bash
git add
git commit
git push
git pull
git fetch
git merge
git rebase
git reset
git restore
git checkout
git switch
git clean
git stash pop
git rm
git mv
git cherry-pick
git revert
```

If it mutates Git state, assume Git Guardian owns it.

## How to Request Git Work


Preferred helper command:

```bash
git_guardian request \
  --repo $AI_ROOT/ai_general \
  --message "fix: concise commit message" \
  --file path/to/file1 \
  --file path/to/file2 \
  --summary "Task complete; files implement requested change." \
  --test "python3 -m py_compile path/to/file1"
```

`gg` is a symlink alias for `git_guardian`. Use `git_guardian status` / `gg status` to verify Guardian registration.

Preferred AI request:

```yaml
type: git_command_proposal
repo: $AI_ROOT/ai_general
commands:
  - git add path/to/file1 path/to/file2
  - git commit -m "fix: concise message"
  - git push
rationale: "Task complete; files implement requested change."
files_changed:
  - path/to/file1
  - path/to/file2
tests:
  - "python3 -m py_compile path/to/file1"
```

If you do not know commands, state intent and relevant files/tests.

## DevTree Rule

Inside `$HOME/AI/devTrees/AI_ROOT_<id>/`, raw Git mutation is especially dangerous. Ask Guardian to use lifecycle tools: `commit_dev_env.py`, `refresh_dev_env.py`, `push_dev_env.py`, `pr_dev_env.py`, `merge_dev_env.py`, `destroy_dev_env.py`.

File editing in devTrees is expected. Git mutation in devTrees is guarded.

## Subagents

Subagents use the same working directory as the parent instance. If parent is in a devTree, subagent is in that same devTree. Subagents inherit the same policy.

## If Blocked

Stop. Use `git_guardian request` / `gg request`, or send a request to `uai://service/git-guardian/prompt`, with blocked command, repo/path, intent, files changed, tests run. Do not retry or work around the hook.

## End-of-Task Habit

Run read-only inspection:

```bash
git status --short
git diff --stat
```

Then send Guardian a commit request with `git_guardian request` / `gg request` if changes are ready.
