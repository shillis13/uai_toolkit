# read_jsonl.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/read_jsonl.py` (4145 lines, packaged copy).
Source of truth is `~/bin/ai/jsonl/read_jsonl.py` (4143 lines); the packaged copy is a
`kind: clean` materialization whose **only** differences are mechanical import rewrites
(verified by diff — 8 hunks, all import lines). Every finding below therefore applies to
both trees unless stated.

## Terms

- **Transcript** — the on-disk JSONL (JSON Lines: one JSON object per line) file a CLI agent
  writes as it runs. Claude Code, Codex CLI, Gemini CLI, Anti-Gravity, and Grok CLI each use a
  different shape.
- **Record / raw line** — one line of the transcript.
- **Message** — one normalized item in this module's data model (`Message`, read_jsonl.py:368).
  One raw line can yield several messages (a Claude assistant line often carries text +
  thinking + tool_use blocks).
- **Turn** — a submitted human prompt plus everything that follows until a successful Stop. Using the next prompt as the boundary would include messages not considered part of the Turn, such as an agent response.
- **Compaction interval** — the span of records between two `/compact` events. Each compaction
  starts a fresh conversation root, so "what the model sees now" is the last interval.
- **Chain** — the leaf-to-root walk over `parentUuid`, i.e. the records actually still in the
  model's context, as opposed to abandoned rewind/retry forks.
- **Stub** — a short placeholder string left in the transcript by the offload tooling in place
  of a large tool result, pointing at an archived copy.

---

## 1. What it is for

`read_jsonl` is the single canonical reader for AI CLI session transcripts. It turns any
supported platform's transcript into one normalized message stream, assigns turn numbers and
active-chain membership, and renders or filters that stream for humans and for other tools. It
is both a command-line program (subcommands plus an interactive prompt loop) and an importable
library; the repo's design rule (`~/bin/ai/jsonl/DESIGN.md`) is that nothing else parses session
JSONL directly.

## 2. Interface

### 2.1 Command line

Dispatch is hand-rolled, not `argparse`. `main()` (read_jsonl.py:4098) strips `--no-color`,
handles `--help-examples` / `--help` / `-h`, then: **if the first argument is not a recognized
command name, it prepends `read`** (read_jsonl.py:4130-4135). So `read_jsonl.py Cortex` means
`read Cortex`. `run_command()` (read_jsonl.py:3906) does the actual dispatch through a dict
(read_jsonl.py:3944-3956).

Commands that exist:

| command | function | notes |
|---|---|---|
| `read <uuid\|path> …` | `_cmd_read_with_repl` (3967) | **not** `cmd_read` — see §8.4 |
| `read-file <path> …` | `_cmd_read_file_with_repl` (4017) | **not** `cmd_read_file` |
| `extract <uuid\|path> …` | `cmd_extract` (2982) | briefing/archival scope: `all_intervals=True` forced at 3000 |
| `find <uuid>` | `cmd_find` (3029) | path to stdout; **not-found goes to stderr, stdout stays empty** (deliberate, 3036-3039) |
| `summary <uuid>` | `cmd_summary` (3044) | JSON dump of `session_summary()` |
| `msg <record-uuid> …` | `cmd_msg` (3056) | raw record lookup by the record's own `uuid` |
| `compactions <uuid\|path>` | `cmd_compactions` (3276) | interval table |
| `branches <uuid\|path>` | `cmd_branches` (3238) | **broken in the package** — see §8.1 |
| `tail <uuid\|path>` | `cmd_tail` (3195) | **broken in the package** — see §8.1 |
| `list` | `cmd_list_sessions` (3328) | |
| `help` | `cmd_help` (3664) | registry-driven, `_command_help_entries` (3346) |
| `toggle` / `show` / `range` | 3880 / 3892 / 3932 | interactive-mode only |

Aliases: `COMMAND_ALIASES` (read_jsonl.py:332) — `?`/`h`=help, `r`=read, `x`=extract, `rf`=read-file,
`f`=find, `s`=summary, `m`=msg, `ls`=list, `cx`=compactions, `br`=branches.

There is **no `stats` command**, in either tree. The stats/ledger code exists as library
functions only. See §8.5 — a live caller depends on a `stats` command that does not exist.

Common flags (parsed positionally out of the argument list by `_parse_flag`, read_jsonl.py:2493):
`--format`, `--platform`, `--type`/`--types`, `--range`, `--turns`, `--interval`,
`--all-intervals`, `--sort`, `--expand`, `--resolve`, `--show-private`,
`--include-client-only`, `--legacy-scope`, `--no-color`.

Output formats (`format_messages_from_schema`, read_jsonl.py:2701): `text` (default, ANSI-colored),
`json`, `flat`, `structured` (day → turn → message), `markdown`, `raw`, `memorex`.

**Exit codes: there is only one.** `main()` returns 0 on every path (read_jsonl.py:4141), including
"Session not found". Failures are conveyed as text on stdout. `cmd_find` is the sole exception in
spirit — it empties stdout — but still exits 0. Callers that shell out cannot use the exit status.

### 2.2 Library surface actually imported by others

`catjsonl.py` imports `Message`, `MessageType`, `Colors`, `c`, `parse_session`, `find_jsonl`,
`detect_platform`, `format_messages_from_schema`, `_ts_to_local`
(src/uai_toolkit/jsonl/catjsonl.py:34-38 — note it reaches for a private `_`-prefixed name).
`lib_jsonl_archive.human_turn_indices` imports `read_jsonl` lazily
(src/uai_toolkit/jsonl/lib_jsonl_archive.py:356). Public-by-docstring but with **no caller
anywhere** in either tree: `extract_messages` (1054), `extract_tool_uses` (1066),
`structure_session` (508), `list_sessions` (2334), `session_summary` (1952) except via
`cmd_summary`, and the entire stats family (§8.5).

The README's claim that `resolve_archived_stubs(messages, jsonl_path)` is the library entry point
for stub rehydration is accurate (read_jsonl.py:798).

### 2.3 Data model — the thing a replacement must reproduce

`MessageType` enum (read_jsonl.py:347): `user`, `response`, `thinking`, `tool_use`, `tool_result`,
`system`, `meta`, `skill`, `agent_result`, `injected`. `_missing_` maps the legacy value `"text"`
to `RESPONSE` (read_jsonl.py:360-364) — a back-compat shim for old callers.

`Message` (read_jsonl.py:368) fields, with the two easily-confused ones called out in the code:
`role`, `type`, `content`, `timestamp`, `platform`, `tool_name`, `tool_input`, `tool_call_id`,
`line_number` (**message ordinal, not a file line**), `source_line` (**1-indexed raw file line**),
`turn_number` (first prompt = 0; `-1` is the "pre" prologue sentinel), `on_chain`,
`is_compaction`, `raw`.

`Turn` (407) and `DayGroup` (429) are grouping wrappers.

## 3. Integration

**Callers inside this repo**
- `jsonl/catjsonl.py` — library import (the j-tools suite is a thin wrapper over `parse_session`).
- `jsonl/lib_jsonl_archive.py` — lazy library import for `human_turn_indices`.
- `mcp/knowledge/tools/knowledge_jsonl.py` — **subprocess**, running the *source-tree* script at
  `$AI_ROOT/ai_general/scripts/jsonl/read_jsonl.py` (line 20), with `read`, `read-file`, `summary`,
  `list`, `find` (lines 204-257).
- `mcp/comms/tools/comms_prompting.py` — **subprocess**, same source-tree path (line 22).
- `mcp/sessions/tools/context_ops.py` — **subprocess**, `["stats", path, "--interval", …]`
  (line 306). This command does not exist. See §8.5.

**Callers outside this repo**: the UAI Electron app and the Memorex overlay consume the
`memorex` / `structured` formats; the module carries a shared palette contract for that
(read_jsonl.py:159-330). Not verified from this side — flagged as an assumption.

**What it calls**
- `jsonl/platform_adapters` — `detect_platform`, `adapter_for_platform` (read_jsonl.py:91).
- `jsonl/standardized_session` — `load_standardized_session`, `is_standardized_session_file` (92).
- `jsonl/lib_jsonl_archive` as `_lja` (70) — and *delegates* `find_compactions`,
  `compaction_intervals`, `_select_intervals` to it via aliases (read_jsonl.py:1885-1887). The
  comment there says read_jsonl was the origin of that logic and now defers, so numbering cannot
  diverge from `context_stats` / `turn_digest`.
- `jsonl/lib_engram` — lazily, for a stub prefix (1253).
- `common_utils/standard_colors` (58), `common_utils/lib_readline` (4067).
- `session_mgmt/lib_uri.session_id_of` (528) and `session_mgmt/session_store.py`, the latter
  loaded **by file path via `importlib`** (539-590).
- `lib_cli_common.py`, loaded by file path from its own directory (76-88).
- `lib_branch_index` (2826, 3249) and `lib_jsonl_tail` (3208) — bare `import` statements.

The last three are the breakage in §8.1.

## 4. Data & config

**Read**
- Claude transcripts: `~/.claude/projects/**/<session-uuid>.jsonl` (read_jsonl.py:95-97).
- Codex: `~/.codex/sessions/**/*.jsonl` and `~/.codex/archived_sessions/**` (99-101).
- Gemini: `~/.gemini/tmp/**/session-*.json` (102-103).
- Grok: `~/.grok/sessions/**/chat_history.jsonl` (104-105).
- Offload archives: `<transcript_dir>/<stem>.<uuid8>.archive/<file>.txt`, resolved from a stub's
  portable ref by `resolve_archived_stubs` (read_jsonl.py:798-836).
- Memorex palette JSON, first hit wins: `$MEMOREX_PALETTE`, then
  `$AI_ROOT/ai_general/data/memorex/palette.json`, then `<module>/../../data/memorex/palette.json`
  (read_jsonl.py:193-219). Falls back to an embedded default (165).
- The session registry, through `session_store.SessionStore().resolve()` (563-565).

**Written**
- `~/.read_jsonl_history` — readline history for the interactive loop (read_jsonl.py:108, 4068).
  This is the only file the module writes. It is *not* under `AI_ROOT`.

**Environment variables**: `AI_SCRIPTS` (51-54, prepended to `sys.path` when set), `AI_ROOT`
(via `uai_toolkit.paths` and directly at 205), `MEMOREX_PALETTE` (202), plus whatever
`standard_colors` reads for `NO_COLOR`.

**Module import side effects** — three `sys.path.insert` calls at import time
(read_jsonl.py:53, 57, 69). Line 57 inserts `AI_SCRIPTS` (`$AI_ROOT/ai_general/scripts`), a *user
data directory*, onto `sys.path` for every importer of this module. Line 69 inserts the module's
own directory, which is how the bare `import lib_branch_index` was ever expected to work.

## 5. How it works

### 5.1 Resolving an identifier to a file — `find_jsonl` (593)

1. Strip a URI wrapper (`uai://session/<id>`, `prompt://target/<id>`) via `session_mgmt.lib_uri`,
   with a `urlparse` fallback (514-536).
2. If it is an existing file path, return it.
3. Ask the session registry (`_resolve_via_session_store`, 539) — this resolves tracking IDs and
   display names, not just UUIDs. Its `sys.path` juggling carries an explicit bug note: without
   it, Memorex silently lost all message numbering (556-558).
4. Filesystem search, in order: Claude project dirs, Codex sessions, Gemini `tmp`, Codex archive,
   then Grok. Matching is exact / prefix / substring on the UUID portion of the name.
   Claude candidates with a dotted stem are skipped so sidecars like
   `<uuid>.offload_tokens.jsonl` cannot beat the real transcript (624-628).
5. Ambiguity resolution (677-709): dedupe, prefer an exact stem match, and if the survivors are
   the *same* session id duplicated across project directories pick the newest by mtime. Only
   genuinely distinct ids report ambiguity — to stderr, returning `None`.

### 5.2 Parsing — `parse_session` (1011)

```
is_standardized_session_file(path)?  → load_standardized_session
else  platform = platform or detect_platform(path)
      adapter_for_platform(platform).from_file(path) → StandardizedSession
_standardized_to_messages(session)                   → list[Message]
_chain_and_prompt_meta(path, all_intervals)          → (chain, turnstart, compaction) line sets
_assign_turn_numbers(...)                            → stamps turn_number/on_chain/is_compaction
```

`_standardized_to_messages` (764) skips records with `visible=False` and **silently drops any
record whose `message_type` is not a `MessageType` value** (770-772). It stores
`raw={"standardized_record": …, "session_header": …}` — note the session header envelope is
duplicated into *every* message.

`_chain_and_prompt_meta` (839) re-reads the raw file and is **entirely Claude-specific**: it walks
`uuid` / `parentUuid`, uses `logicalParentUuid` to bridge `/compact` seams, and detects turn starts
by the presence of `promptSource` on a non-meta, non-compact-summary `user` line (960-967). For
every other platform it returns empty sets, and `_assign_turn_numbers` (971) falls back to legacy
increment-on-USER numbering. That fallback path is why turn numbers mean something subtly
different on Codex/Grok than on Claude.

Two scopes exist, selected by `all_intervals`:
- **default (False)** — walk `parentUuid` only, stopping at the compaction seam. This is "what
  the model sees now".
- **True** — thread every interval into one branch by following `logicalParentUuid` across each
  seam, with a completeness fallback that re-walks any interval tree a dangling reference severed
  (930-943). Used for archival/file-reduction views and by `extract`.

Cost: `parse_session` reads the file **twice** (adapter, then `_chain_and_prompt_meta`). The stats
functions each re-read it again.

### 5.3 Filtering pipeline

`_filter_and_format_messages` (2893) is the shared tail for read/read-file/extract, and the
**order is load-bearing** (documented at 4007-4010 and 2909): `--range` (or `--turns`) is applied
*before* `--type`, because filtering to e.g. `response,thinking` strips the USER messages that
turn grouping needs, collapsing everything into one turn. Then type filter, then the private
filter, then interactive toggles, then optional timestamp sort, then format.

- `--range` (`_apply_range`, 2443) supports message ranges (`1-10`, `-20`, `5-`) and turn ranges
  with a `t` prefix (`t1-10`, `t-4`). The `pre` prologue (turn -1) is deliberately not
  `t`-addressable (2466).
- `--turns` (`_apply_turn_filter`, 2649) is absolute by `Message.turn_number` and delegates its
  grammar to `lib_cli_common.select_turn_numbers` so that read_jsonl, `context_stats`, and
  `turn_digest` agree.
- `--interval` uses `lib_jsonl_archive`'s interval line ranges (`_apply_interval_filter`, 1890).
- Private filter (`_apply_private_filter`, 2668): a `thinking` block containing `[/PRIVATE]`
  anywhere is dropped. `--show-private` includes it with a `[PRIVATE THINKING BLOCK]` prefix.
  This matches the DESIGN.md invariant. Note the marker is matched anywhere in the block, and
  the reconstructed `Message` at 2687 **drops `source_line`, `turn_number`, `on_chain`, and
  `raw`** — a latent bug for anything that filters afterwards on those fields.

### 5.4 The Memorex presentation layer (159-330)

A second, view-level segmentation sits above the raw message types: `_section_for` (222) maps a
`MessageType` value through the palette's `typeToSection` table to a section
(`user`/`inject`/`assistant`/`thinking`/`tool`/`skill`/`agent`/`system`/`meta`), plus exactly one
content rule — a USER message whose body opens with the inter-session provenance envelope
(`_MEMOREX_INJECT_RE`, 190) is re-sectioned as `inject`. The stated purpose is that the CLI and
the Electron overlay derive sections from the same rule so their message boundaries line up. The
section is stamped onto `structured` and `flat` JSON output (2730, 2736) and drives the `memorex`
renderer (258).

### 5.5 The stats subsystem (roughly 1075-2333)

Five analysis functions plus their text formatters, measuring the same transcript on three
different axes and warning loudly about the difference (1499-1509):
`raw_line_breakdown` (1081) by raw line type; `stub_accounting` (1260) counting already-offloaded
blocks; `conversation_client_only_fields` (1402) top-down; `model_facing_ledger` (1522) bottom-up
with a KEEP / OFFLOADABLE / THINKING decision ledger; `session_stats` (2027) the per-day/per-total
report; `split_offloaded_tally` (3155). None of it is reachable from the command line and none of
it has a caller. See §8.5.

## 6. Essential vs incidental

### Essential — a replacement that loses these breaks something

1. **`Message` and `MessageType` as the normalized model.** `catjsonl.py` constructs and consumes
   `Message`; `lib_jsonl_archive` and the adapter contract are written against `MessageType`.
   The `line_number` vs `source_line` distinction and the `turn_number = -1` prologue sentinel are
   depended on by output headers and by `--turns`.
2. **`find_jsonl`'s resolution ladder**, especially: registry resolution before filesystem search
   (tracking IDs and display names are what humans actually type), dotted-stem sidecar exclusion,
   and same-id-newest-mtime disambiguation. Each of these encodes a specific past failure.
3. **`cmd_find`'s stdout/stderr split.** The comment at 3036-3039 records the failure: a caller
   captured the error text as a filename and failed later with a confusing JSON error.
4. **Filter ordering** (range before type). Reversing it silently produces wrong turn ranges.
5. **The `[/PRIVATE]` thinking filter defaulting to on.** A DESIGN.md invariant.
6. **Turn semantics**: a turn starts at a *submitted* prompt (`promptSource`), not at any
   user-role record. Skill expansions, hook injections, and tool results all arrive as user-role
   records and must not start turns.
7. **Interval / chain scoping**, including the two scopes and the `logicalParentUuid` seam
   crossing. The default scope is "current interval" precisely because that is what the model
   still sees.
8. **Delegation of interval enumeration and `--turns` grammar to shared libraries** so numbering
   cannot drift between tools. The mechanism can change; the single-source-of-truth property
   cannot.
9. **Off-by-default stub resolution.** `--resolve` exists so that `summary`/stats keep reflecting
   the lean on-disk file (807).
10. **Memorex section mapping** if the Electron overlay is kept — it is a cross-process contract.

### Incidental — free to discard or redo

- The hand-rolled flag parser (`_parse_flag` / `_strip_flags`, 2493/2523). It is positional,
  order-sensitive, cannot express `--flag=value`, and `_strip_flags` has to be hand-patched at
  every call site to remove boolean flags (e.g. 2965, 3003, 3985). Replace with `argparse`.
- The bespoke `Colors` class (110) — already a thin shim over `standard_colors`.
- `COMMAND_ALIASES` and the "unknown first argument means `read`" convenience.
- The interactive prompt loop and its module-global toggle/range state (`_repl_toggles` 3859,
  `_repl_range` 3872). Global mutable state that only the interactive path uses.
- `MessageType._missing_("text")` back-compat.
- The `_lib_cli_common()` `importlib` file-path loader (76) — a workaround for a module name
  collision that a proper package namespace removes.
- The `sys.path.insert` calls at 53/57/69.
- `import readline`, `import atexit`, `import warnings` (41/36/44) — all three are unused.
- The entire stats subsystem, as packaged (§8.5).
- `extract_messages`, `extract_tool_uses`, `structure_session`, `list_sessions` — no callers.
- `_parse_codex` / `_parse_gemini` / `_parse_claude` (1039-1050) — three one-line wrappers,
  no callers.

## 7. Platform notes (Windows / WSL)

- **Tier B — `import readline` at module scope (41).** Not present in the native Windows standard
  library, so *importing* read_jsonl fails outright on Windows without `pyreadline3`. Since the
  name is never used, deleting it is a Tier A fix and the whole issue evaporates.
- **Tier A — hard-coded POSIX path separators.** Platform detection sniffs for `/.claude/`,
  `/.codex/`, `/.gemini/`, `/.grok/sessions/` as substrings of a stringified path (see the
  adapter docs). Under WSL these are fine; under native Windows they never match and detection
  silently falls back to `claude`.
- **Tier A — missing explicit encodings.** Most raw-line readers pass `encoding="utf-8"` (1118,
  1308, 1426, 1621, 1871, 1926), but `cmd_msg` (3095) and the adapters do not, or rely on
  `Path.read_text()` without an encoding. On Windows the default is the ANSI code page, so a
  transcript with non-ASCII content raises or mangles. Fix inline.
- **Tier A — line endings.** Parsing strips `\n` only (`rstrip("\n")` in the adapters); a
  transcript written with CRLF leaves a trailing `\r` inside the last JSON value. Not observed,
  but the code has no guard.
- **Tier A — `Path.home()` anchored platform directories** (95-105). Correct under WSL. Native
  Windows Claude Code uses `%USERPROFILE%\.claude`, which `Path.home()` also gives, so this is
  mostly fine; the separator issue above is the real problem.
- **Tier B — `cmd_msg` shells out to `grep -lF`** (3088). No `grep` on native Windows. This is a
  whole-file substring search across every Claude project transcript; reimplement in Python.
- **Tier A — `~/.read_jsonl_history`** is written outside `AI_ROOT`. Should move under the
  instance directory.
- **Tier B — the interactive loop** uses `readline` bracketing escapes in the prompt string
  (4077) which are terminal-specific.
- **Tier A — `sys.path` mutation at import** (53/57/69). Fragile everywhere; on Windows the
  `AI_SCRIPTS` default (`$AI_ROOT/ai_general/scripts`) is a symlink target on the developer's
  Mac and will not exist.
- Local-time conversion (`_ts_to_local`, 722) uses `astimezone()` with no explicit zone, which is
  correct per the global rule that timestamps display in local time.

## 8. Risks & sharp edges

### 8.1 Three imports have no module to resolve to — reproducible failures

`lib_cli_common.py`, `lib_branch_index.py`, and `lib_jsonl_tail.py` all exist in the source tree
(`~/bin/ai/jsonl/`) but are **not in `tools/manifest.py`** and therefore are not materialized into
`src/uai_toolkit/jsonl/`. `materialize.py` rewrites only the import patterns the manifest lists,
so these three survived as bare `import X` / file-path loads and now fail at runtime.

Reproduced against the packaged module with a real Claude transcript:

```
read <uuid> --turns last  → FileNotFoundError: .../jsonl/lib_cli_common.py
extract <uuid> --turns 1  → FileNotFoundError: .../jsonl/lib_cli_common.py
branches <uuid>           → ModuleNotFoundError: No module named 'lib_branch_index'
tail <uuid> --since-line 5→ ModuleNotFoundError: No module named 'lib_jsonl_tail'
```

All four surface as uncaught tracebacks, not error messages. `DESIGN.md`'s status line
"**`read_jsonl`** ✅ ported + verified" is stale — the verification predates the branch-aware
cutover dated 2026-07-20 in the code (2936, 2962).

### 8.2 `_filter_to_live_chain` is a no-op even where it is reachable

```python
# read_jsonl.py:2828
return [m for m in msgs if (not m.raw.get("uuid")) or (m.raw.get("uuid") in live)]
```

`Message.raw` is set by `_standardized_to_messages` to
`{"standardized_record": …, "session_header": …}` (read_jsonl.py:785-788) — it has **no `uuid`
key**. So `m.raw.get("uuid")` is always `None`, `not None` is always true, and every message
passes. Only `client_only_meta_messages` (1939-1946) produces messages whose `raw` is the real
record. Branch-aware filtering, the documented default since 2026-07-20, would filter nothing
even if `lib_branch_index` imported. Not verified against the source tree's own resolver tests —
it is possible those tests never exercise this function.

### 8.3 Adapter `raw` payload duplicates the session header per message

`_standardized_to_messages` (785-788) embeds `session.header.to_envelope()` into every single
message's `raw`. On a 1.7 MB transcript that yielded 348 messages, so 348 copies. Combined with
`StandardizedSourceRecord` holding both `raw_text` and `raw_obj` for every line, peak memory for
a parse is several times the file size. Nobody has hit a wall yet, but this is the scaling limit.

### 8.4 Two parallel read implementations, and the CLI uses the older one

`cmd_read` (2921) and `cmd_read_file` (2950) are branch-aware (`branch_aware = "--legacy-scope"
not in args`, 2936/2962) and route through `_read_targets` / `_read_file_targets` (2836/2865).
`_cmd_read_with_repl` (3967) and `_cmd_read_file_with_repl` (4017) duplicate the same flag
parsing and load loop **without any branch awareness**, and re-implement the interval handling
inline (4000-4004). `run_command` dispatches `read`/`read-file` to the `_with_repl` pair
(3945/3947), so `cmd_read` / `cmd_read_file` and the `--legacy-scope` flag are unreachable from
the command line. They are still importable, and `cmd_extract` (the one command that *does* go
through `_read_targets`) does not set `branch_aware`. Which of the two is intended is unclear —
**this looks like work in flight, mid-cutover.** Rationale unknown; needs an owner's answer.

### 8.5 The stats subsystem is stranded, and one caller depends on a command that never existed

Roughly 1250 lines (1075-2333, plus 3121-3192) implement transcript accounting. There is no
`stats` entry in `run_command`'s dispatch table, and `session_stats` /
`model_facing_ledger` / `raw_line_breakdown` / `stub_accounting` /
`conversation_client_only_fields` / `split_offloaded_tally` have **zero callers** anywhere in
`~/bin/ai/`, `src/uai_toolkit/`, or the tests. The successor is `~/bin/ai/jsonl/context_stats.py`,
which is built on `lib_context_analysis` and is not materialized into the package at all.

Meanwhile `mcp/sessions/tools/context_ops.py:306` runs
`read_jsonl.py stats <path> --interval live`. Because `stats` is not a known command, `main()`
prepends `read` (4134) and the tool gets:

```
$ read_jsonl.py stats <transcript> --interval live
Session not found: stats
```

Verified against the *source* tree, so this defect is live today, not a porting artifact. The
`context_stats` MCP tool is silently returning a not-found string. Out of this document's scope
to fix, but it must be tracked.

### 8.6 Silent degradation, generally

The module swallows failures in a lot of places. `_resolve_via_session_store` wraps its entire
body in `except Exception: pass` (588-589). `_load_memorex_palette` swallows per-candidate
exceptions (216). `_stub_prefixes` (1240) and `model_facing_ledger` (1558-1572) fall back to
*hard-coded copies* of constants that live in `lib_jsonl_archive` — if those constants ever
change, the fallback quietly produces wrong numbers instead of failing. `add_session` (2340) and
the Gemini branch of `list_sessions` (2377) use bare `except: pass`. `_standardized_to_messages`
drops unrecognized message types without a word (770-772).

### 8.7 Ordering and correctness traps worth carrying forward

- `--range` must precede `--type` (§5.3). Documented twice in the code because it was got wrong.
- `--turns` and `--range t…` are mutually exclusive and rejected explicitly (2900-2901).
- `--interval` forces `all_intervals=True` parsing (2844, 3995) — the interval filter is
  line-range based and needs the whole-file walk to be meaningful.
- `extract` forces `all_intervals=True` unconditionally (3000) so archival turn numbering is
  stable, whereas `read` defaults to the live interval. Same flag, two defaults, deliberately.
- `_apply_private_filter` reconstructs `Message` objects and loses `source_line` / `turn_number` /
  `on_chain` / `raw` (2687-2693) — only on the `--show-private` path, but it is a real defect.
- `group_by_day` (486) buckets messages with unparseable or empty timestamps under `"Unknown"`.
  Grok transcripts carry no per-line timestamps at all (see `grok_design.md`), so every Grok
  session collapses into one `"Unknown"` day.

### 8.8 Concurrency

The module is read-only with respect to transcripts, and Claude Code opens-appends-closes per
write, so reading a live session is safe from corruption. But nothing takes a snapshot: a parse
reads the file two or more times (§5.2), and a session that appends between reads yields
message data and chain metadata computed from **different file states**. Nothing detects this.
Whether it has ever caused a visible problem is unknown.
