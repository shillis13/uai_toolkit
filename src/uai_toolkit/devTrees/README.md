# devTrees

Scripts for creating and managing isolated development environments ("dev trees"). Each dev tree is a git worktree of `ai_general` on a `dev/<uuid>` branch, housed under `~/Documents/AI/devTrees/AI_ROOT_<uuid>/`, with production dirs symlinked in and mutable state dirs copied. The `workflow` MCP server exposes these operations as tools; these scripts are the subprocess-callable implementations.

## Scripts

### create_dev_env.py
Creates a new isolated dev environment. Sets up a sparse git worktree (editable dirs: `scripts`, `apps`, `projects`, `docs`), symlinks shared dirs (`ai_comms`, `ai_memories`, etc.) to production, copies `data/` for runtime isolation, writes `.envrc` for direnv, and writes `.claude/settings.local.json` with `AI_ROOT` pointing to the dev tree. Prints `AI_ROOT=<path>` as the last line for machine-readable consumption. Idempotent — exits cleanly if the environment already exists.

**Usage:**
```
create_dev_env.py [--id UUID] [--ai-root-main PATH]
```

### destroy_dev_env.py
Tears down a dev environment: removes the git worktree, deletes the `dev/<uuid>` branch, and removes the entire directory. Checks for uncommitted changes and refuses unless `--force` is passed.

**Usage:**
```
destroy_dev_env.py <uuid> [--force] [--ai-root-main PATH]
```

### list_dev_envs.py
Lists all active dev environments under `~/Documents/AI/devTrees/` with their branch name, clean/dirty status, commit lead/lag vs. `origin/main`, and full path. Supports `--json` for machine-readable output.

**Usage:**
```
list_dev_envs.py [--json]
```

### status_dev_env.py
Shows detailed status for a single dev environment: disk usage, branch, last commit, ahead/behind main, dirty file count, symlink health, and which `ai_general` dirs are real vs. symlinked vs. missing.

**Usage:**
```
status_dev_env.py <uuid>
status_dev_env.py --ai-root PATH
```
Defaults to `$AI_ROOT` if it looks like a dev tree path.

### commit_dev_env.py
Stages and commits changes in a dev environment's branch. Only stages files in the editable dirs (`scripts`, `apps`, `projects`, `docs`) — never the shared symlinked dirs. Refuses to commit if not on a `dev/` branch.

**Usage:**
```
commit_dev_env.py -m "MESSAGE" [--all] [--ai-root PATH]
```

### push_dev_env.py
Pushes the current dev branch to `origin`. Refuses if not on a `dev/` branch.

**Usage:**
```
push_dev_env.py [--ai-root PATH]
```

### merge_dev_env.py
Merges a dev branch back into `main` in the main worktree. Verifies both worktrees are clean before merging. Supports `--squash` for a single combined commit. Warns about differences in the `data/` directory (which was copied, not branched, so won't auto-merge).

**Usage:**
```
merge_dev_env.py [--ai-root PATH] [--ai-root-main PATH] [--squash] [--no-delete]
```

### pr_dev_env.py
Creates a GitHub PR from a dev branch using the `gh` CLI. Pushes the branch first if it hasn't been pushed. Auto-generates a PR title from the branch name and includes recent commit list in the body.

**Usage:**
```
pr_dev_env.py [--title TITLE] [--body BODY] [--draft] [--ai-root PATH]
```

### refresh_dev_env.py
Pulls the latest `origin/main` into the dev branch (via rebase by default, or merge with `--merge`). Can also re-copy `data/` from production to pick up new state, either entirely or for specific files.

**Usage:**
```
refresh_dev_env.py [--merge] [--data [FILE ...]] [--data-only] [--ai-root PATH]
```

## Dependencies

- `git` (required for all worktree operations)
- `gh` CLI (required for `pr_dev_env.py`)
- `direnv` (optional, auto-allows `.envrc` during creation)

## Notes

Dev trees are located at `~/Documents/AI/devTrees/AI_ROOT_<8-char-uuid>/`. The `data/` directory is always copied (not symlinked) so runtime state changes in dev don't affect production. After merging, data differences must be copied manually if needed. All scripts accept `$AI_ROOT` from the environment or `--ai-root` flag, making them usable from within a dev tree session.
