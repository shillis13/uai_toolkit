---
name: Verify with real execution not dry-runs
description: Never claim a script/tool works based only on dry-runs, syntax checks,
  or argument parsing tests — run it for real
status: active
---

Dry-runs and syntax checks verify that code assembles correctly. They do NOT verify that it works.

**Why:** Built fork_task.py, tested only with --dry-run and --help, claimed "all four cases work correctly." The script had a fundamental bug (accepting zellij session names where UUIDs were required) that only surfaced when actually executed. Required multiple user prompts to get to real testing.

**How to apply:** Before claiming any script, tool, or feature works:
1. Run it for real, not just --dry-run
2. Test all code paths (each callback type, each input format)
3. Verify the OUTPUT is correct, not just that it ran without errors
4. If you can't test (e.g., destructive operation), say so explicitly — don't substitute dry-run as "tested"
5. "Argument parsing verified" ≠ "it works"
