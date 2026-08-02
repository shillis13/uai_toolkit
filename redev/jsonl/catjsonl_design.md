# catjsonl.py — redevelopment design

Source of record: `/Users/shawnhillis/AI/uai_toolkit/src/uai_toolkit/jsonl/catjsonl.py`
(1523 lines). All line citations below are against that file unless another path is
given.

## Terms

- **j-tools** — the project's name for the six commands this module provides
  (`jcat`, `jgrep`, `jhead`, `jtail`, `jwc`, `jfmt`).
- **Multi-call binary** — one program that changes behavior based on the name it was
  invoked under. The code and README call this "busybox-style", after the BusyBox
  utility that popularized the pattern.
- **Console script** — a Python packaging entry point (`[project.scripts]` in
  `pyproject.toml`) that generates a real per-operating-system launcher executable.
- **PipeMessage** — this module's wire record: a parsed message plus two pipeline
  fields (`msg_num`, `source`), serialized as one JSON object per line.
- **JSONL** — JSON Lines: a text file with one complete JSON value per line.
- **TTY** — a terminal; here, "stdout is attached to a terminal rather than a pipe".
- **CLI** — command-line interface.

---

## 1. What it is for

`catjsonl.py` is the read-and-inspect layer over AI CLI session transcripts. It parses
Claude / Codex / Gemini / Anti-Gravity (`agy`) / Grok session files into a normalized
message stream (delegating all parsing to `read_jsonl.py`) and exposes six
grep/cat/head/tail/wc-shaped commands over *messages* rather than raw text lines. It
writes colored human output to a terminal and one JSON object per line to a pipe, so
the six commands compose with each other. It never modifies a transcript.

---

## 2. Interface

### 2.1 One module, six commands — how the dispatch works

This is the part a re-design most needs spelled out, because there are **two
independent dispatch mechanisms living side by side**, plus a third fallback.

**(a) Console-script entry points — the shipped mechanism.**
`pyproject.toml:41-46` maps each command to a distinct *function*, not to `main`:

```
jcat  = "uai_toolkit.jsonl.catjsonl:jcat"
jgrep = "uai_toolkit.jsonl.catjsonl:jgrep"
jhead = "uai_toolkit.jsonl.catjsonl:jhead"
jtail = "uai_toolkit.jsonl.catjsonl:jtail"
jwc   = "uai_toolkit.jsonl.catjsonl:jwc"
jfmt  = "uai_toolkit.jsonl.catjsonl:jfmt"
```

Those six functions are one-liners at the bottom of the file (1514-1519), each
calling `main(tool="<name>")`. `main(tool=None)` at 732 takes the tool name as a
parameter and skips name detection when it is supplied.

**(b) argv[0] name detection — the original mechanism, still live.**
`detect_tool(argv0)` (495-500) takes `Path(argv[0]).stem` and returns it if it is one
of the six names, else `"catjsonl"`. `main()` calls this only when `tool is None`
(741-742). On the source platform (macOS `~/bin/ai`) the six names were symlinks to
`catjsonl.py`; this path is what made that work.

**(c) Sub-command argument — the fallback.**
If the resolved tool is `catjsonl` and `sys.argv[1]` is one of the six names (or
`--help-examples`), `main` rewrites `sys.argv` and re-dispatches (745-747). This is
what makes `python -m uai_toolkit.jsonl.catjsonl jgrep …` work.

`DESIGN.md` decision 2 states the reason for (a): entry points "eliminate the
jcat/jgrep symlink-dispatch problem (no symlinks, no Developer Mode, no PATH surgery
on Windows)". So (a) is the intended future and (b)/(c) are carried-over source
behavior. **(b) and (c) are not dead** — `python -m` and any symlink install still
use them.

Per-tool argument parsers are built by a single `build_parser(tool)` (543-614): a
shared block of flags, then an `if/elif` chain adding the per-tool positional
arguments and options. Dispatch to the implementation is a second `if/elif` in
`main` (761-772).

### 2.2 Shared flags (every command)

Defined at 553-581.

| Flag | Effect |
|---|---|
| `--type TYPE[,TYPE…]` | Filter by message type. Repeatable and comma-separated. Valid: `user, response, thinking, tool_use, tool_result, system, meta, skill, agent_result, injected` (553). |
| `--role ROLE[,ROLE…]` | Filter by role. Valid: `user, assistant, system` (554). |
| `--platform {claude,codex,gemini,agy}` | Force the parser instead of auto-detecting. |
| `--json` | Force JSON output even on a terminal. |
| `--ts` | Show the message timestamp. |
| `--no-color` | Disable ANSI color. |
| `-r` | Recurse into directory arguments. |
| `--since SPEC` / `--before SPEC` | Time window. See §5.4 — **applied twice, with two different parsers**. |
| `--sort {newest,oldest}` | Help text says "File processing order (default: newest)" (580). It also reorders *messages*. See §8.1. |
| `--progress` | Per-file progress on stderr. |
| `--help-examples` | Intercepted before argparse (734-739); prints the colorized guide at 617-729 and returns. |

`--type` / `--role` accept three shell forms (`--type a,b`, `--type a, b`,
`--type a b`) via a pre-argparse rewrite, `_normalize_filter_argv` (227-277), that
greedily collects following tokens while they are valid values and joins them with
commas. `_parse_multi_value_filter` (197-209) then validates and raises
`argparse.ArgumentTypeError` on an unknown value.

### 2.3 Per-command contracts

**`jcat [SOURCE…]`** (`run_jcat`, 828-833). Positional `sources` = file paths and/or
session identifiers, or stdin if none. Reads → filters → sorts → outputs.

**`jgrep [PATTERN] [SOURCE…]`** (`run_jgrep`, 1173-1181). Extra options (586-598):

| Option | Meaning | Divergence from GNU grep |
|---|---|---|
| `-i` | case-insensitive | same |
| `-F` / `--fixed-strings` | literal pattern (`re.escape`, 1189-1190) | same |
| `-v` / `--verbose` | **print each file as it is searched** | **GNU `-v` is invert-match.** See §8.2 |
| `--invert` / `--inverse-match` | invert the match | GNU spells this `-v` |
| `-n` | print a `source:msg=…:line=…:type=…:role=…` prefix | GNU prints file line numbers; here `line=` is a message ordinal, see §8.3 |
| `-c` | print `source:count` | GNU prints counts; output shape differs between code paths, see §8.4 |
| `-C N` / `--context N` | content lines of context around each in-message match, **default 2** | GNU default is 0 |
| `--msg-context N` | *messages* of context around a matching message, default 0 | no GNU equivalent |
| `--no-file-headers` | suppress per-file headers | — |
| `--pager` | pipe human output through a pager | — |

`PATTERN` is optional when `--type` or `--role` is given (587). Because argparse
would then swallow the first source as the pattern, `main` post-corrects using the
heuristic `_looks_like_source` (212-224, applied 756-759). See §8.5.

**`jhead [-n N] [SOURCE…]`** / **`jtail [-n N] [SOURCE…]`** (1434-1449). `-n`
defaults to 10 (602). Documented as "first N" / "last N". **With default flags they
return the opposite** — see §8.1.

**`jwc [--by-type|--by-role] [SOURCE…]`** (1478-1494). Prints a bare integer, or a
right-aligned `count  key` table plus a `total` row.

**`jfmt [--format {text,json,markdown}] [--collapse-tools] [SOURCE…]`**
(1497-1511). Normally reads `PipeMessage` JSON from stdin and renders it.
`--collapse-tools` truncates `tool_result` content to 3 lines (1469-1475).

### 2.4 Output contract

`output_messages` (377-396) picks one of three shapes:

1. `--json`, **or** stdout is not a TTY → one `serialize_message` JSON line per
   message (385-387). The pipe schema is fixed at 172-181: `role, type, content,
   timestamp, platform, tool_name, tool_input, tool_call_id, msg_num, source,
   line_number`.
2. TTY + `--ts` → one compact line per message, first 120 characters of content.
3. TTY → `format_messages_from_schema(messages, format)` from `read_jsonl`.

`jgrep` has its own human renderer (`format_grep_block`, 1121-1170) that prints a
`MATCH`/`CONTEXT` header, a 3-line "start:" preview, and merged context ranges with
`:` marking matched lines and `-` marking context lines.

### 2.5 Exit codes

There is no exit-code discipline. `main` returns `None` on every success path, so the
process exits 0. Verified by running:

- `jgrep <no-match> <file>` → **exit 0** (GNU grep exits 1). Shell idioms like
  `if jgrep … ; then` are therefore broken.
- `jcat <nonexistent-uuid>` → prints `Not found: …` to stderr, **exit 0** (429-432).

The only non-zero exits are `sys.exit(2)` on an uncompilable regex
(`_compile_user_pattern`, 838-853) and `sys.exit(1)` when `jgrep` gets no pattern and
no `--type`/`--role` (1186-1188).

### 2.6 Public Python surface

`PipeMessage` (43-66), `read_messages` (73), `read_stdin` (158),
`serialize_message` / `deserialize_message` (172, 184), `apply_filters` (353),
`sort_messages` (335), `grep_messages` (856), `clean_display_text` (887),
`message_display_text` (940), `count_by_type` / `count_by_role` (1454, 1462),
`collapse_tool_content` (1469), and the six `main()` wrappers. Nothing in the
repository imports any of these — see §3.

---

## 3. Integration

**Who calls this:** only the six generated launchers and a human at a shell. A
repository-wide grep for `catjsonl` finds exactly one importer:
`tests/smoke_test.py:49`, which does an import-only smoke check. **No other module in
`uai_toolkit` imports `catjsonl`.** It is a leaf.

**What it calls:**

- `uai_toolkit.jsonl.read_jsonl` (34-38) for `Message`, `MessageType`, `Colors`, `c`,
  `parse_session`, `find_jsonl`, `detect_platform`, `format_messages_from_schema`,
  `_ts_to_local`. This is the whole parsing contract — catjsonl parses nothing itself.
  Note it reaches for two non-public names: `Colors._enabled` (a private class
  attribute it assigns directly at 382, 785, 1307, 1346, 1507) and `_ts_to_local`.
  `detect_platform` is imported at line 36 and **never used**.
- `uai_toolkit.common_utils.standard_colors.set_color_mode` (39).
- `uai_toolkit.jsonl.discovery.discover_files` (40) for `-r`.
- External process: a pager (`less -RX`, or `more` on Windows) via `subprocess.Popen`
  (789-825).

**Boundary shape:** command-line in, text/JSON on stdout, diagnostics on stderr. The
`PipeMessage` JSON line format is the *only* machine-readable contract, and it is
consumed solely by this module's own `read_stdin`.

---

## 4. Data & config

**Reads (never writes any of these):**

- Session transcripts, resolved three ways in `resolve_sources` (403-446): an existing
  path is used verbatim; a directory requires `-r` and goes to
  `discovery.discover_files`; anything else is passed to `read_jsonl.find_jsonl`,
  which searches Claude project directories, Codex sessions, Gemini history, and the
  Codex archive, and can also resolve tracking IDs and display names through the
  session store.
- stdin, when no sources are given and stdin is not a terminal (454-455).

**Environment variables:**

- `JGREP_PAGER` (797) — overrides the whole pager command line, split with `shlex`.
- Indirectly, whatever `read_jsonl` and `standard_colors` consume for color detection
  and root discovery. Not enumerated here.

**Writes:** nothing to disk. Ever. This is the one module in the `jsonl` package that
is purely read-only, and that property is worth stating as a guarantee.

---

## 5. How it works

### 5.1 Overall flow

```
main(tool)
  ├─ --help-examples?  → print guide, return
  ├─ tool = arg or detect_tool(argv[0]) or argv[1] sub-command
  ├─ argv = _normalize_filter_argv(argv)          # multi-value --type/--role
  ├─ args = build_parser(tool).parse_args(argv)
  ├─ colors: _apply_color_setting(args)
  ├─ jgrep only: un-swallow a source mis-parsed as the pattern
  └─ run_<tool>(args)
        ├─ get_messages(args)        # resolve_sources → read_messages, or read_stdin
        ├─ apply_filters(...)        # --type/--role/--since/--before
        ├─ sort_messages(...)        # by timestamp, direction from --sort
        └─ output_messages(...)      # JSON if piped, colored if TTY
```

`jgrep` deviates: when it has file sources it uses `_run_jgrep_streaming`
(1334-1431) instead of `get_messages`; only its stdin path uses the common flow
(1196-1200).

### 5.2 Parsing

Entirely delegated. `read_messages` (73-95) calls `read_jsonl.parse_session(path,
platform=…)` per file and wraps each returned `Message` in a `PipeMessage`, assigning
`msg_num` as a **per-file 0-based enumeration index** (87). Messages from several
files therefore carry colliding `msg_num` values, disambiguated only by `source`.

`PipeMessage` copies 8 of the 14 fields on `read_jsonl.Message`. It **drops**
`source_line`, `turn_number`, `on_chain`, `is_compaction`, and `raw`
(`read_jsonl.py:368-380`). Consequences in §8.3 and §8.6.

### 5.3 Filtering

`apply_filters` (353-374) applies `--type` (compared against `MessageType.value`),
`--role`, then `--since`/`--before` against the message timestamp. Messages whose
timestamp will not parse are treated as `datetime.min` for `--since` and
`datetime.max` for `--before`, i.e. they are dropped by either bound (370, 373).

### 5.4 Time specifications — two parsers, two grammars

`catjsonl._parse_time_spec` (296-319): relative `^(\d+)\s*([mhdw])$`, else
`datetime.fromisoformat`; a naive absolute datetime is assumed to be **UTC** (316);
an unparseable spec **raises** `argparse.ArgumentTypeError`.

`discovery.parse_time_spec` (`discovery.py:24-40`): relative `(\d+)\s*([mhdw])`, else
one of exactly three formats `%Y-%m-%d`, `%Y-%m-%dT%H:%M:%S`, `%Y/%m/%d`, interpreted
in **local time** via `datetime.strptime(...).timestamp()`; an unparseable spec
**returns `None`**, silently meaning "no bound".

Both are reachable from a single `--since` value: `resolve_sources` passes it to
discovery for file-mtime windowing (423) and `apply_filters` / `_run_jgrep_streaming`
pass it to `_parse_time_spec` for message windowing (369, 1342). See §8.7.

### 5.5 jgrep matching

`message_display_text` (940-953) builds the searched text. For a `tool_use` message
it concatenates `tool: <name>`, the pretty-printed `tool_input` JSON, and any content
— so a jgrep pattern can match tool arguments. Everything then goes through
`clean_display_text` (887-937), which normalizes CR/CRLF to LF, decodes literal
`\n`/`\r`/`\t`/`\uNNNN`/`\UNNNNNNNN`/`\xNN` escape sequences into real characters, and
re-escapes any remaining Unicode category-C (control/format) character as a visible
`\xNN`-style token. The stated intent (890-893) is to stop grep output from emitting
terminal garbage.

`_grep_match_indices` (956-964) does `compiled.search(text) is not None`, XOR-ed
against `invert`. `_grep_selected_indices` (967-980) then expands by `--msg-context`,
**skipping expansion entirely when `--invert` is set** (976) because context would
re-admit the very messages the user excluded.

For human output, `_match_line_indices` (983-993) finds the matching content lines,
with a fallback for regexes that span line boundaries; `_merged_ranges` (996-1008)
merges overlapping context windows; `_highlight_line` (1011-1021) wraps matches in
bold bright-yellow, or `[[…]]` brackets when color is off; `_snippet_for_match`
(1031-1056) trims lines over 240 characters while keeping the first match visible.

### 5.6 The `_run_jgrep_streaming` path

Despite the name it is **not streaming**. It loops over files, parses each fully
(`_messages_for_path`, 1221-1247), and appends every selected message to a single
`all_matched` list (1350, 1394-1395). Only after all files are read does it sort
(1404) and print (1409-1431). Peak memory is proportional to total matched content,
not to one file. `-c` is the sole exception: it prints `path:count` per file inside
the loop (1387-1389).

Direct-match vs context-expanded identity is carried across the sort using
`id(message)` in a set (1406-1407).

### 5.7 Pager

`_pager_command` (789-802): `JGREP_PAGER` if set, else `["more"]` when `os.name ==
"nt"`, else `["less", "-RX"]` (`-R` keeps ANSI color; `-X` keeps output on screen
after exit). `_run_with_pager` (805-825) launches the pager, **rebinds
`sys.stdout` to the pager's stdin**, runs the printer, restores stdout, and returns
the pager's exit status. If the pager binary is missing it falls back to printing
directly (809-811). `run_jgrep` (1175-1178) force-enables color before paging,
**overriding an explicit `--no-color`**.

---

## 6. Essential vs incidental

### Essential — a replacement must preserve these

1. **Six commands with these exact names and these flag spellings.** They are typed
   by hand daily and appear throughout the repository's documentation.
2. **The TTY/pipe output switch.** Colored text to a terminal, one JSON object per
   line to a pipe, `--json` to force JSON. Every documented pipeline in `_help_examples`
   (674-691) depends on it.
3. **The `PipeMessage` line schema** (172-181). It is the composition contract between
   the six commands.
4. **All parsing delegated to `read_jsonl`.** `jsonl/README.md:150` records this as a
   governing invariant of the package ("`read_jsonl.py` is the sole parser").
   Re-implementing parsing here would fork the message model.
5. **Read-only.** This module must never write a transcript. It is the safe tool you
   point at a live session.
6. **Message-level semantics.** `--type` / `--role` filter parsed messages, not text
   lines. That is the entire reason these tools exist instead of `grep`.
7. **`tool_use` messages are searchable by their arguments** (942-950). Searching for
   a file path and finding the `Write` that touched it is a primary use.

### Incidental — free to discard or redo

1. **`detect_tool` / argv[0] name detection** (495-500) and the sub-command fallback
   (745-747). These exist because the source tree used symlinks. `DESIGN.md`
   decision 2 already replaced them with entry points. Keep one dispatch mechanism.
2. **`_normalize_filter_argv`** (227-277) — a hand-written pre-argparse token
   rewriter to support `--type a b`. A modern parser handles `nargs="+"` natively.
3. **`_looks_like_source`** (212-224) — a heuristic patching over an argparse grammar
   choice. A re-design that makes sources an explicit option, or requires `--`,
   removes the need.
4. **Dead code:** `iter_messages_from_files` (100-155) and `get_messages_streaming`
   (463-488) are defined and never called from anywhere in the repository.
   `grep_messages` (856-881) is likewise never called. Roughly 100 lines.
5. **`_help_examples`** (617-729) — 113 lines of hand-aligned, hand-colorized ASCII
   help with a box-drawing header. The content is valuable; the hand-alignment is not.
6. **`Colors._enabled = …` direct assignment** to a private attribute of another
   module, in five places. An accident of how color control grew.
7. The unused `detect_platform` import (36).
8. `q = '"'` at 627 with the comment "Python 3.9 compat" — the package declares Python
   3.10 minimum (`DESIGN.md`), so this workaround is obsolete.

---

## 7. Platform notes

Using the repo's tiers: **Tier A** = portability fix inline, **Tier B** = genuinely
OS-divergent, belongs in `platform_compat/`, **Tier C** = platform-impossible, degrade
behind a capability flag.

| Concern | Where | Tier | Note |
|---|---|---|---|
| Pager binary | 789-802 | **A — already fixed here** | `more` on `os.name == "nt"`, `less -RX` otherwise, plus a `FileNotFoundError/OSError` fallback (808-811). **This fix exists only in the packaged copy.** The source-of-truth copy in `catjsonl.py.materialized` still has a bare `["less","-RX"]` and an unguarded `Popen`. It has not been back-ported. |
| ANSI color on a Windows console | via `read_jsonl.Colors` / `standard_colors` | **B** | Modern Windows Terminal handles virtual-terminal sequences; `cmd.exe` may not without enabling them. Not verified on Windows — flagging, not asserting. |
| Rebinding `sys.stdout` to a subprocess pipe | 812-820 | **A** | Works on both, but is fragile: anything that captured `sys.stdout` earlier keeps the old object. |
| `BrokenPipeError` on `… \| head` | 385-387 | **A — defect, not yet fixed** | Reproduced: `jcat <file> \| head -2` prints a full Python traceback plus "Exception ignored while flushing sys.stdout". Only the pager path catches `BrokenPipeError` (817). A pipeline tool must handle SIGPIPE-shaped termination everywhere. |
| Path handling | `pathlib` throughout | **A — clean** | No `os.path` string surgery in this module. |
| File encoding | delegated | n/a here | This module opens no transcript itself; encoding is `read_jsonl`'s problem. |
| Line endings | 900, 919 | **A — clean** | `clean_display_text` normalizes CRLF and CR to LF before display. |
| Case sensitivity | 498, 219 | **A** | `detect_tool` compares `Path(argv0).stem` exactly; on Windows a launcher named `JCAT.EXE` yields stem `JCAT` and falls through to `catjsonl`. Irrelevant while entry points are used, relevant if symlink dispatch is kept. |
| `os.name == "nt"` check | 800 | **B candidate** | The only direct OS branch in the file. If a `platform_compat` pager adapter is created, this is the caller to move. |

There is nothing Tier C here. Every capability works on every target platform.

---

## 8. Risks & sharp edges

Items 1-5 are confirmed by running the code, not inferred.

### 8.1 `jhead` returns the newest messages and `jtail` returns the oldest — confirmed

`--sort` defaults to `"newest"` (580). `sort_messages` (335-350) sorts by timestamp
with `reverse = (sort_order == "newest")`, i.e. descending. `run_jhead` (1434-1440)
then takes `msgs[:n]` and `run_jtail` (1443-1449) takes `msgs[-n:]`. Descending order
means the head of the list is the *newest* message.

Verified against a 27,239-line Claude transcript:

```
jhead -n 3 <file>  →  msg_num 19831 @ 2026-06-21T04:21:40   (newest)
jtail -n 3 <file>  →  msg_num  7237 @ 2026-05-23T07:44:12   (oldest)
```

The same default also means **`jcat <session>` renders a transcript in reverse
chronological order**, which is almost certainly not what a `cat`-shaped tool should
do. `--sort oldest` restores chronological order for all three.

The `--sort` help string says "File processing order (default: newest)" (580) — which
is true of `resolve_sources` (444) but does not mention the message-level effect. So
the code and its own help text disagree.

**Rationale unknown — needs an owner's answer.** "Newest first" is the right default
for a recursive search across many sessions and the wrong default for reading one
session, and there is no note in the code saying which case won.

### 8.2 `jgrep -v` is verbose, not invert — confirmed by reading

591: `-v`/`--verbose` = "Print files as they are searched". 592: `--invert` /
`--inverse-match` = invert. Anyone with `grep` muscle memory who types
`jgrep -v pattern file` gets **non-inverted** results with per-file headers, and no
warning. This is a silent wrong answer, which is worse than an error.

### 8.3 `jgrep -n`'s `line=` field is not a file line number

`PipeMessage.line_number` is copied from `Message.line_number` (93), which
`read_jsonl.py:377` documents as *"message ordinal: 1-based position in the parsed
message stream — NOT the raw file line"*. The real file line is
`Message.source_line` (378), which `PipeMessage` **does not carry**. So the `-n`
output `source:msg=N:line=M:type=…` shows two ordinals and no way to jump to the
record in an editor. It also means `jgrep`'s "line" and `scrub_files`'s "line" (which
*is* a real file line) are different quantities with the same name.

### 8.4 `-c` output shape differs between the two code paths

With file sources, `_run_jgrep_streaming` prints `path:count` for **every** file
including zero-count files (1387-1389). With stdin, `_emit_jgrep_matches`
(1274-1298) prints `source:count` per distinct source, or a **bare integer** when no
message carried a source. A downstream parser cannot rely on one shape.

### 8.5 The pattern/source disambiguation heuristic misfires on hex-looking words

`_looks_like_source` (212-224) treats any string of 4+ characters drawn from
`[0-9a-fA-F-]` as a session identifier. Ordinary English words qualify: `added`,
`face`, `cafe`, `beef`, `faded`, `decade`, `deaf`, `bead`. So
`jgrep --type response added <file>` silently reclassifies `added` as a source,
leaves the pattern `None`, and returns every `response` message unfiltered.

### 8.6 Off-chain messages cannot be filtered out

`read_jsonl.Message.on_chain` (`read_jsonl.py:379`) marks whether a record is on the
active conversation chain; off-chain records are "dead retry/rewind fork" content.
`PipeMessage` drops the field and no j-tool exposes it. Every j-tool therefore shows
abandoned branches mixed into the live conversation with no marker and no filter.
`turn_number` and `is_compaction` are dropped the same way.

### 8.7 `--since` / `--before` are parsed twice, by two disagreeing parsers

From §5.4:

- `--since 2026/04/09` is **accepted** by `discovery.parse_time_spec` and
  **raises** in `catjsonl._parse_time_spec`. Because `apply_filters` is called
  outside argparse, the `ArgumentTypeError` propagates as an uncaught traceback.
- `--since 2026-04-09T14:30` (no seconds) is **rejected** by discovery's fixed format
  list — silently, meaning "no file filter" — and **accepted** by
  `fromisoformat`.
- `--since 2026-04-09` means **local** midnight for file selection and **UTC**
  midnight for message selection. Users west of UTC lose messages from the first
  hours of the window; users east gain them.
- A typo like `--since 7dd` silently disables the file filter (discovery returns
  `None`) and then raises on the message filter.

### 8.8 `jwc -r` and `jcat -r` load everything into memory

`get_messages` (449-460) materializes every message of every discovered file into one
list before filtering. `jwc -r ~/.claude/projects/` over a large transcript tree is
therefore bounded by total transcript size, not by file size. The generator that
would fix this (`iter_messages_from_files`, 100-155) exists but is never wired up.
`_run_jgrep_streaming` has the same problem for matched messages (§5.6).

### 8.9 `--pager` overrides `--no-color`

1176: `args.no_color = False` unconditionally. `jgrep --pager --no-color …` emits
ANSI escapes anyway. Harmless with `less -R`, visible garbage with a pager that does
not interpret them (including `JGREP_PAGER=cat`).

### 8.10 `--json` is silently ignored when the pager is requested

1175: paging is skipped when `force_json` is set, which is correct, but there is no
message saying so. Minor.

### 8.11 Per-file parse failures are swallowed

`_run_jgrep_streaming` (1372-1374) and `iter_messages_from_files` (121-123) catch
bare `Exception`, print `Skipping <path>: <err>` to stderr, and continue, with no
effect on the exit code. A run in which every file failed to parse is
indistinguishable from a run with no matches.

### 8.12 Untested

`tests/` contains `smoke_test.py` (import-only), `test_llm_endpoints.py`, and
`test_tracker_concurrency.py`. **There is no behavioral test for any of the six
commands.** Every defect above survived because nothing asserts the contract.

### 8.13 Work in flight — the packaged file and the source file have diverged

`src/uai_toolkit/jsonl/catjsonl.py` (dated 2026-06-24) and its sidecar
`catjsonl.py.materialized` (2026-07-26) differ by ~279 diff lines.
`tools/manifest.py:246` classifies this file as `kind: "curated"`, so
`materialize.py` writes the sidecar for manual review and never overwrites the
package copy. Neither direction has been reconciled:

**Only in the packaged copy** (would be lost by a blind re-materialize):
the six `jcat()`…`jfmt()` entry-point wrappers (1514-1519), `main(tool=None)`
(732), `discovery.discover_files` in place of `file_utils` (40), the Windows `more`
pager branch and the missing-pager fallback (800, 808-811), and the removal of three
`sys.path` hacks.

**Only in the source copy** (a real improvement not yet in the package): substantially
better `--help` text — per-argument help strings with stated defaults, a per-command
`EXAMPLES` + `CAVEATS` epilog, `metavar`s, and a much fuller `catjsonl` description
that states the read-only guarantee.

A re-designer must not treat either file as authoritative on its own.

---

## 9. What I could not determine

- **Why `--sort` defaults to `newest`** and whether the resulting reversed `jcat` /
  swapped `jhead`/`jtail` behavior was intended, tolerated, or never noticed.
  Rationale unknown — needs an owner's answer.
- **Why `-v` was assigned to verbose** rather than invert. Rationale unknown — needs
  an owner's answer.
- **Whether `-C` defaulting to 2 instead of grep's 0** was deliberate. Rationale
  unknown — needs an owner's answer.
- Whether the `PipeMessage` JSON line format has any consumer outside this module
  (scripts, notes, shell aliases outside the repository). I searched the repository
  only.
- Whether ANSI color and the `more` pager actually behave as intended on native
  Windows. Not tested — I have no Windows box here.
