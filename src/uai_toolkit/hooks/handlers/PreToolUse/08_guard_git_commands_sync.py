#!/usr/bin/env python3
"""PreToolUse hook — block git write commands unless caller is Git Guardian.

Allowlist-based: if the git subcommand isn't explicitly read-only, it's blocked.
This is safer than a blocklist — new git commands default to blocked.

Guardian identity is resolved via session_store.resolve_uri("uai://service/git-guardian").
No YAML config, no display name/tag fallback.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

# ─── Read-only subcommands (always allowed for any session) ───────────

ALWAYS_READONLY = {
    "status", "diff", "log", "show", "blame", "shortlog",
    "ls-files", "ls-tree", "ls-remote", "check-ignore",
    "rev-parse", "rev-list", "cat-file",
    "describe", "name-rev", "merge-base",
    "for-each-ref", "count-objects", "fsck", "verify-pack",
    "grep", "help", "version",
}

# Subcommands that are read-only only with specific first args
# If the first arg after the subcommand is in the set, it's read-only.
# Otherwise it's a write (e.g., `git branch new-name` = create = write).
CONDITIONAL_READONLY = {
    "branch": {"-l", "--list", "-a", "--all", "-r", "--remotes",
               "-v", "--verbose", "-vv", "--no-color", "--color",
               "--contains", "--merged", "--no-merged", "--sort"},
    "tag": {"-l", "--list", "-n", "--contains", "--merged", "--no-merged",
            "--sort", "-v", "--verify"},
    "remote": {"-v", "--verbose", "show", "get-url"},
    "stash": {"list", "show"},
    "config": {"--get", "--get-all", "--list", "-l", "--get-regexp",
               "--get-urlmatch", "--show-origin", "--show-scope"},
    "reflog": {"show", "--no-walk"},
    "submodule": {"status", "summary", "foreach"},
}

# DevTree path prefix
DEVTREE_PREFIX = "$HOME/AI/devTrees/AI_ROOT_"
# Also check Documents path
DEVTREE_PREFIX_ALT = "$HOME/AI/devTrees/AI_ROOT_"


def _extract_git_invocations(command_str):
    """Extract git subcommands from a bash command string.

    Handles:
    - git <subcommand>
    - git -C /path <subcommand>
    - git --no-pager <subcommand>
    - git -c key=val <subcommand>
    - env git <subcommand>
    - command git <subcommand>
    - Compound commands (&&, ||, ;, newline)

    Returns list of (subcommand, first_arg, git_c_path) tuples.
    """
    results = []

    # Split on command boundaries
    parts = re.split(r'&&|\|\||;|\n', command_str)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Tokenize with shlex (best effort — may fail on complex shell)
        try:
            tokens = shlex.split(part)
        except ValueError:
            # Unbalanced quotes etc. — fall back to simple split
            tokens = part.split()

        if not tokens:
            continue

        # Strip prefix wrappers: env, command
        while tokens and tokens[0] in ("env", "command"):
            tokens = tokens[1:]

        if not tokens or tokens[0] != "git":
            continue

        # Parse git global options to find the subcommand
        tokens = tokens[1:]  # skip 'git'
        git_c_path = None
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "-C" and i + 1 < len(tokens):
                git_c_path = tokens[i + 1]
                i += 2
            elif tok.startswith("-C"):
                git_c_path = tok[2:]
                i += 1
            elif tok == "-c" and i + 1 < len(tokens):
                i += 2  # skip -c key=val
            elif tok.startswith("-c"):
                i += 1
            elif tok in ("--no-pager", "--paginate", "--no-optional-locks",
                         "--literal-pathspecs", "--no-replace-objects"):
                i += 1
            elif tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
                i += 1
            elif tok == "--git-dir" and i + 1 < len(tokens):
                i += 2
            elif tok == "--work-tree" and i + 1 < len(tokens):
                i += 2
            elif tok.startswith("-"):
                # Unknown global flag — skip
                i += 1
            else:
                break  # This is the subcommand
            # (continued from while)

        if i >= len(tokens):
            continue  # No subcommand found (just flags)

        subcmd = tokens[i]
        first_arg = tokens[i + 1] if i + 1 < len(tokens) else ""
        results.append((subcmd, first_arg, git_c_path))

    return results


def _is_read_only(subcmd, first_arg):
    """Check if a git subcommand invocation is read-only.

    Returns True if definitely read-only, False if write/mutation.
    """
    if subcmd in ALWAYS_READONLY:
        return True

    if subcmd in CONDITIONAL_READONLY:
        allowed_args = CONDITIONAL_READONLY[subcmd]
        # No args at all = listing (read-only for most conditional commands)
        if not first_arg:
            return True
        # First arg is an allowed read-only flag
        if first_arg in allowed_args:
            return True
        # First arg is a flag not in our list — might be read-only, might not.
        # Default to blocked for safety.
        return False

    # Not in any read-only category — blocked
    return False


def _is_devtree(cwd, git_c_path):
    """Check if the operation targets a devTree."""
    for path in (git_c_path, cwd):
        if path and (path.startswith(DEVTREE_PREFIX) or path.startswith(DEVTREE_PREFIX_ALT)):
            return True
    return False


def _is_git_guardian(context):
    """Check if the calling session is the Git Guardian via URI resolution."""
    tracking_id = context.tracking_id
    if not tracking_id:
        return False

    ai_root = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
    _sm = ai_root / "ai_general" / "scripts" / "session_mgmt"
    if str(_sm) not in sys.path:
        sys.path.insert(0, str(_sm))
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
        guardian_ids = store.resolve_uri("uai://service/git-guardian")
        if guardian_ids and tracking_id in guardian_ids:
            return True
    except Exception:
        pass

    return False


BLOCK_MSG = """\
BLOCKED: Restricted Git command: {cmd}

Git write/destructive operations are handled by Git Guardian.

To commit/push your own work, route it through the CLI — NOT a raw prompt to the
Guardian. The CLI checks the Guardian is live, tracks an ack, and leaves a durable
record, so your work can't be silently dropped if the committer goes dark (todo_0626):

  python3 "${{AI_ROOT:-$HOME/AI/ai_root}}/ai_general/scripts/git_guardian/git_guardian.py" request \\
    --kind commit_request --repo <repo> --message "<commit msg>" \\
    --summary "<why>" --file <path> [--file ...] --todo todo_#### \\
    --test "<what you verified>"

  (git_guardian.py status = active Guardian; check-acks = surface un-acked requests;
   a change request must cite --todo.)

For a higher-level need — sync, merge, refresh, PR, or a plain-language request from
PianoMan — use the same CLI with the appropriate --kind and preserve the intent in
--message, e.g.:
- "Commit and push my changes to the hook framework"
- "Merge main into my branch"
- "I need a refresh from main"

Do not retry or bypass this hook."""

BLOCK_MSG_DEVTREE = """\
BLOCKED: Restricted Git command in devTree: {cmd}

DevTrees use sparse checkout + symlinks. Raw git mutation is dangerous.
Git Guardian uses lifecycle tools (commit, push, merge, refresh, destroy).

Route the request through the CLI rather than a raw prompt to the Guardian: it checks
Guardian liveness, tracks the ack, and leaves a durable record (todo_0626):

  python3 "${{AI_ROOT:-$HOME/AI/ai_root}}/ai_general/scripts/git_guardian/git_guardian.py" request \\
    --kind commit_request --repo <devtree_repo> --message "<intent>" \\
    --summary "<why>" --todo todo_#### --test "<what you verified>"

Describe your intent in the request — the Guardian will use the appropriate lifecycle
tool. For a plain-language need (sync, PR, refresh, or PianoMan asking directly), choose
the appropriate --kind, preserve the request in --message, and let the Guardian
translate it.

Do not retry or use raw git commands in devTrees."""


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        return HookResult.skip("not a Bash call")

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        return HookResult.skip("no command")

    # Quick check: does the command contain 'git' at all?
    if "git " not in command and "git\t" not in command and not command.startswith("git"):
        return HookResult.skip("no git command")

    # Extract all git invocations from the command
    invocations = _extract_git_invocations(command)
    if not invocations:
        return HookResult.skip("no parseable git subcommand")

    # Check each invocation
    cwd = hook_input.get("cwd", "")
    for subcmd, first_arg, git_c_path in invocations:
        if _is_read_only(subcmd, first_arg):
            continue

        # Write command detected — check if caller is Git Guardian
        if _is_git_guardian(context):
            return HookResult.allow(f"git guardian: git {subcmd}")

        # Blocked
        cmd_display = f"git {subcmd}" + (f" {first_arg}" if first_arg else "")
        if _is_devtree(cwd, git_c_path):
            return HookResult.block(
                BLOCK_MSG_DEVTREE.format(cmd=cmd_display),
                f"blocked git write in devTree: {cmd_display}"
            )
        return HookResult.block(
            BLOCK_MSG.format(cmd=cmd_display),
            f"blocked git write: {cmd_display}"
        )

    return HookResult.allow("all git invocations are read-only")


if __name__ == "__main__":
    sys.exit(run_hook("guard_git_commands", "PreToolUse", handler))
