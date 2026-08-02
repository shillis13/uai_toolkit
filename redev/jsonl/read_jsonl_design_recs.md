# read_jsonl.py — recommendations for the re-design

Companion to `read_jsonl_design.md`. Only items with a concrete change and a reason.

## 1. Fix the three unresolvable imports before anything else

`lib_cli_common.py`, `lib_branch_index.py`, `lib_jsonl_tail.py` exist in the source tree but are
absent from `tools/manifest.py`, so the packaged `read_jsonl` raises tracebacks on `--turns`
(any command), `branches`, and `tail`. Reproduced in §8.1 of the design doc.

Two options, and they are not equivalent:

- **Materialize them** — add three `kind: clean` manifest entries and let `materialize.py` rewrite
  `import lib_branch_index` → `from uai_toolkit.jsonl import lib_branch_index`. Cheapest; restores
  the current feature set. But `lib_branch_index` pulls in the whole branch-resolver subsystem,
  which nobody has scoped for the port.
- **Drop `branches` and `tail` from the ported command set** and keep only `--turns` (which needs
  just `lib_cli_common.select_turn_numbers` — a small, self-contained grammar parser that could be
  inlined or moved to `common_utils`). `tail` exists for the Electron/Memorex live pipeline;
  `branches` is a diagnostic. If neither ships in phase 1, drop them rather than shipping broken
  commands.

Either way: **no command should be reachable that raises an uncaught traceback.** Whatever is not
ported should be removed from `run_command` and from `_command_help_entries`, not left to fail.

## 2. Decide between the two read paths — this is unfinished work

`cmd_read` / `cmd_read_file` (branch-aware, `--legacy-scope`) versus `_cmd_read_with_repl` /
`_cmd_read_file_with_repl` (not branch-aware, what the CLI actually runs). Two copies of the same
flag parsing and load loop, diverging in behavior. The code comments date a branch-aware cutover
to 2026-07-20; the dispatch table was apparently never repointed.

Ask the owner which is intended, then delete the other. Do not port both. If branch-awareness is
kept, note it is currently a no-op (see item 3).

## 3. `_filter_to_live_chain` never filters anything — fix or delete

```python
# read_jsonl.py:2828
return [m for m in msgs if (not m.raw.get("uuid")) or (m.raw.get("uuid") in live)]
```

`Message.raw` holds `{"standardized_record": …, "session_header": …}` (read_jsonl.py:785), so
`.get("uuid")` is always `None` and every message passes. If branch-aware scoping is meant to
ship, the record `uuid` has to survive normalization — the natural fix is to carry it as a
first-class `Message` field (or in `platform_extras`) rather than fishing it out of a nested
envelope. That is a data-model change, so decide it during the re-design, not after.

## 4. Cut the stranded stats subsystem

~1250 lines (read_jsonl.py:1075-2333 plus 3121-3192) with no CLI command and no caller in either
tree. Its successor, `context_stats.py` on `lib_context_analysis`, is not in the package.

Recommendation: **do not port it**. Port `context_stats` + `lib_context_analysis` when the
context-reclaim ladder is ported, and let read_jsonl keep only `session_summary`. This removes
roughly a quarter of the file and removes the risk that two generations of accounting code report
different numbers for the same transcript.

Before cutting, confirm the UAI app does not shell out to any of it — that was not verifiable
from this side.

## 5. Fix the `context_stats` MCP tool's dead command (tracked defect)

`mcp/sessions/tools/context_ops.py:306` runs `read_jsonl.py stats <path> --interval live`. No
`stats` command exists in either tree, so `main()`'s "unknown first argument means `read`" rule
(read_jsonl.py:4134) turns it into `read stats …` and the tool returns `Session not found: stats`.
Verified against the source tree — this is broken in production today.

Fix belongs in `context_ops.py` (point it at `context_stats.py`), not here. Flagged so it is not
lost.

## 6. Replace the hand-rolled argument parser with `argparse`

`_parse_flag` / `_strip_flags` (2493/2523) are positional and order-sensitive, cannot express
`--flag=value`, and force every command to hand-list its boolean flags for removal (2965, 3003,
3985, 4033). Several near-identical lists have already drifted apart — `cmd_read_file` strips
`--branch-aware` (2965) which nothing else knows about, while `_cmd_read_with_repl` strips
`--show-private` and `--resolve` (3984) which `cmd_read_file` does not.

`argparse` with subparsers also gives real `--help` for free, which would let the 320-line
hand-maintained help registry (3346-3663) go away.

## 7. Give the program real exit codes

`main()` returns 0 unconditionally (4141). Three subprocess callers in the MCP layer
(`knowledge_jsonl.py`, `comms_prompting.py`, `context_ops.py`) have to string-match stdout to tell
success from failure. Minimum viable: 0 success, 1 not found, 2 usage error. `cmd_find`'s existing
stdout/stderr discipline (3036-3039) is the right model — generalize it.

## 8. Parse the file once

`parse_session` reads the transcript twice (adapter `from_file`, then `_chain_and_prompt_meta`),
and each stats function reads it again. On a live session those reads can see different file
states. Read the raw lines once into a list and pass it to both the adapter and the chain walk.
This also removes the assumption, currently invisible, that the file does not change mid-parse.

## 9. Trim the import-time side effects

Delete `import readline`, `import atexit`, `import warnings` (41/36/44) — all unused, and
`readline` alone makes the module unimportable on native Windows. Delete the three
`sys.path.insert` calls (53/57/69); in a proper package none of them is needed, and line 57 puts
a user *data* directory on `sys.path` for every importer.

## 10. Stop hard-coding fallback copies of shared constants

`_stub_prefixes` (1240-1256) and `model_facing_ledger` (1558-1572) both carry literal copies of
`lib_jsonl_archive.STUB_PREFIXES` and `MIN_BYTES` for use when the import fails. If the real
constants change, the fallback silently produces wrong numbers. Either make the dependency hard
(let the import error) or move the constants somewhere with no import cycle. The comment at 1236
says the laziness exists to avoid a circular import at module load — that is a packaging problem
with a packaging fix.

## 11. Smaller defects worth fixing rather than carrying

- `_apply_private_filter` (2687-2693) rebuilds `Message` objects on the `--show-private` path and
  drops `source_line`, `turn_number`, `on_chain`, `raw`. Mutate a copy of the dataclass instead
  (`dataclasses.replace`).
- `cmd_msg` shells out to `grep -lF` (3088). Not available on native Windows; also an unbounded
  scan of every Claude transcript. Reimplement in Python with an early exit.
- Bare `except: pass` at 2349 and 2377 (`list_sessions`) — catches `KeyboardInterrupt` too.
- `catjsonl.py` imports the private `_ts_to_local` (catjsonl.py:37). Promote it to a public name
  in the re-design so the seam is honest.
- Move `~/.read_jsonl_history` (108) under `AI_ROOT`.
