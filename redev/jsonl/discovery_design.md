# discovery.py — redevelopment design

Source of record: `/Users/shawnhillis/AI/uai_toolkit/src/uai_toolkit/jsonl/discovery.py`
(82 lines). All line citations are against that file unless another path is given.

**Read this before deciding to replace it with a library.** This module is not an
under-built utility — it is a deliberate, documented removal of a ~3,500-line
dependency, and the things it gave up were considered. Section 6 lists what was given
up so a re-designer can re-decide on the facts rather than reverse the decision by
reflex.

## Terms

- **`file_utils`** — a general-purpose file-search library in the author's personal
  Python tree (`~/bin/all_languages/python/src/file_utils/`). Its `fsFind` and
  `fsFilters` modules were what `catjsonl` originally used for recursive search.
- **Shim** — a small hand-written stand-in that provides just the slice of a larger
  dependency that a caller actually used.
- **Native module** — in this repository's vocabulary (`DESIGN.md`, "Sync from source"),
  a package file with **no upstream source counterpart**, which `materialize.py`
  never touches.
- **mtime** — a file's last-modified time.
- **Epoch seconds** — a time expressed as seconds since 1970-01-01 UTC.
- **JSONL** — JSON Lines: one complete JSON value per line.

---

## 1. What it is for

`discovery.py` answers one question for the j-tools: *given a directory and an optional
modified-time window, which session transcript files are under it, and in what order?*
It exists so that `jcat -r` / `jgrep -r` / `jwc -r` can walk `~/.claude/projects/` or
`~/.codex/sessions/` without dragging in a large third-party file-search library.

---

## 2. Interface

Two public functions and three module constants. No CLI, no class, no state.

### `parse_time_spec(spec: str | None) -> float | None` (24-40)

Converts a time specification to epoch seconds.

- Falsy input → `None`.
- Relative: `_REL = re.compile(r"(\d+)\s*([mhdw])")` matched with `fullmatch` against
  the lower-cased string (19, 32-34). Units come from `_UNIT_SECONDS` (21):
  **`m` = minutes**, `h` = hours, `d` = days, `w` = weeks. Returns
  `time.time() - n*unit`.
- Absolute: the first of `_ABS_FORMATS` (20) that parses — `%Y-%m-%d`,
  `%Y-%m-%dT%H:%M:%S`, `%Y/%m/%d` — converted with `datetime.strptime(...).timestamp()`,
  which interprets a naive datetime in the **local** time zone.
- **Anything else returns `None`, documented as "treated as no bound"** (27-28, 40).

### `discover_files(directory, since=None, before=None, sort="newest") -> list[Path]` (48-82)

- `Path(directory).expanduser()`; returns `[]` if it is not a directory (58-60).
- Walks with `root.rglob("*")` (66) and keeps entries where `_is_session_file(name)` is
  true (43-45): the name ends in `.jsonl`, **or** the name is exactly `logs.json`
  (Gemini's format). The comment at 44 records that this matches the original's
  `add_file_pattern` behavior.
- Per entry: skip non-files, skip anything whose `stat()` raises `OSError` (69-74).
- Window: keep only files with `mtime > since_ts` and `mtime < before_ts`
  (strict — 75-78).
- Sort by mtime, descending when `sort == "newest"` (the default), ascending for any
  other value (81).
- Returns a fully materialized `list[Path]`.

### Constants

`_REL`, `_ABS_FORMATS`, `_UNIT_SECONDS` (19-21). Private by convention, but the unit
map and format list are the module's real contract and a re-design should treat them
as such.

---

## 3. Integration

**Who calls it:** `catjsonl.py:40` imports `discover_files`; it is invoked from
`resolve_sources` (`catjsonl.py:423`) whenever a positional source is a directory and
`-r` was given. `tests/smoke_test.py:49` imports the module for an existence check.
That is the entire consumer set — `parse_time_spec` has no caller outside this file.

**What it calls:** `re`, `time`, `datetime`, `pathlib` — standard library only. That is
the point of the module.

**Boundary shape:** a plain Python function call returning a list of `Path` objects,
ordered. `catjsonl.resolve_sources` immediately converts them to strings and **re-sorts
them by mtime itself** (`catjsonl.py:436-444`), so the ordering `discover_files`
computes is discarded for the `-r` case. The `sort` argument is therefore effectively
dead for the only caller.

---

## 4. Data & config

Reads directory entries and file metadata. Writes nothing. Reads no environment
variable, no configuration file, no database. It does not open or read the *contents*
of any file.

`tools/manifest.py:247` records it as a **native** file — `# jsonl/discovery.py =
native shim (no source) — omitted` — so `materialize.py` will never overwrite it, and
there is no upstream copy to reconcile against. Of the four modules in this review, it
is the only one with no source/package divergence problem.

---

## 5. How it works

```
discover_files(dir, since, before, sort)
  ├─ root = Path(dir).expanduser();  not a dir → []
  ├─ since_ts = parse_time_spec(since);  before_ts = parse_time_spec(before)
  ├─ for p in root.rglob("*"):
  │     name ends .jsonl or == "logs.json"?
  │     is a regular file, and stat() works?
  │     mtime inside (since_ts, before_ts)?
  │        → collect
  └─ sort by mtime (desc if "newest") → list[Path]
```

Measured on this machine against `~/.claude/projects` — 26,871 directory entries,
3.6 GB, 2,002 matching files — the walk completes in about 0.12 seconds with a warm
cache. **Performance is not a problem worth re-designing around.**

---

## 6. The design decision this module represents

`DESIGN.md`'s status section states it directly:

> The heavy `file_utils.fsFind/fsFilters` (~2.5k LoC + common_utils + yaml) dependency
> **replaced** by a 90-line stdlib shim `jsonl/discovery.py` (recursive .jsonl/logs.json
> + since/before mtime window; gitignore-respect dropped as moot for transcript dirs).

I verified the size claim: `fsFind.py` is 1,185 lines and `fsFilters.py` is 1,306 —
2,491 together. Their import closure pulls in more:
`common_utils.lib_logging`, `common_utils.lib_argparse_registry`,
`common_utils.lib_outputColors`, `file_utils.lib_extensions` (599 lines),
`file_utils.lib_fileInput` (386 lines), and the third-party `yaml` package
(`fsFind.py:33-37`, `fsFilters.py:32, 40-43`). So the real replaced surface is roughly
3,500 lines plus a third-party dependency plus a second personal library tree that is
not part of this package at all.

**Why this matters for the port specifically:** `catjsonl.py.materialized` — the
source-tree copy — still does
`sys.path.insert(0, Path.home()/"bin"/"all_languages"/"python"/"src")` and then imports
`file_utils`. That is a hard-coded path into the author's personal machine. It cannot
ship, and it cannot work on a Windows or WSL box that does not have that tree. Replacing
it was not an optimization; it was a precondition for the package existing at all.

### What was deliberately given up

Documented in the module docstring (8-10):

1. **gitignore-respect.** The original called `fs_filter.enable_gitignore([directory])`.
   Session-transcript trees (`~/.claude/projects`, `~/.codex/sessions`) are not git
   working copies, so the filter had nothing to act on.

Not documented anywhere, but equally real. A re-designer should know these were lost,
whether or not they were noticed at the time:

2. **A different and larger date grammar.** `fsFilters.parse_date`
   (`fsFilters.py:108-148`) accepted `%Y-%m-%d`, `%Y-%m-%d %H:%M`,
   `%Y-%m-%d %H:%M:%S`, `%Y/%m/%d`, and `%m/%d/%Y`, plus relative `Nd`, `Nw`, `Nm`,
   `Ny`. The shim accepts three absolute formats and relative `Nm`, `Nh`, `Nd`, `Nw`.
   Net: `%Y-%m-%d %H:%M`, `%m/%d/%Y`, and `Ny` (years) were dropped; `Nh` (hours) was
   added.

3. **`m` changed meaning.** In `fsFilters` (`fsFilters.py:143-144`) `m` meant
   **months** (approximated as 30 days). In the shim (21) `m` means **minutes**. So
   `jgrep -r … --since 3m` selected files from the last three months before the shim
   and selects files from the last three minutes after it. **This is a silent
   behavioral reversal on an existing flag, not an omission.**

   In fairness to the change: `catjsonl._parse_time_spec` (`catjsonl.py:309`) has
   always used `m` = minutes for its *message*-level filter. So before the shim, one
   `--since 3m` meant "three months" for file selection and "three minutes" for message
   selection simultaneously. The shim made the two consistent. Whether that was the
   intent or a coincidence is **rationale unknown — needs an owner's answer.**

4. **Failing loudly.** `fsFilters.parse_date` raises `ValueError("Invalid date format")`
   on an unparseable string (147). The shim returns `None`, which `discover_files`
   treats as "no bound" (75-78). A typo like `--since 7dd` or `--since last-week` now
   silently widens the search to everything instead of stopping.

5. **Directory pruning, ignore patterns, size filters, extension metadata, and
   YAML-configured filters.** All present in `fsFilters` and all unused by `catjsonl`.
   No loss in practice.

6. **Streaming.** `fsFind.find_files` could yield results; the shim materializes a list.
   Irrelevant at the measured scale.

### The decision in one line

Trading ~3,500 lines and a machine-specific path for 82 lines of standard library was
correct and should be carried forward. **The three things worth reconsidering are the
`m` unit reversal, the silent-`None` failure mode, and the shrunken date grammar** —
not the replacement itself.

---

## 7. Essential vs incidental

### Essential

1. **Standard library only.** This is the whole reason the module exists. A re-design
   that reintroduces a heavyweight file-search dependency undoes a deliberate,
   documented decision — and reintroduces a hard-coded personal path.
2. **Recognizing both `*.jsonl` and `logs.json`.** Gemini writes the latter. Dropping it
   silently makes Gemini sessions invisible to `-r`.
3. **Windowing on modified time, not on message timestamps.** File-level pre-filtering
   is what keeps a recursive search from parsing 2,000 transcripts. The message-level
   filter is a separate, later stage in `catjsonl`.
4. **Tolerating unreadable and vanishing entries.** The `try/except OSError` at 69-74
   is load-bearing: transcript directories are live, and files appear and disappear
   during a walk.
5. **Returning `[]` for a non-directory** rather than raising (58-60).

### Incidental

1. The `sort` parameter (53, 81). `catjsonl.resolve_sources` re-sorts the result
   itself (`catjsonl.py:436-444`), so it is computed and thrown away. Either the caller
   should stop re-sorting or this parameter should go.
2. The exact `_ABS_FORMATS` list (20) — three formats chosen without a stated reason.
   **Rationale unknown — needs an owner's answer.** A re-design should adopt one
   documented grammar (see `catjsonl_design_recs.md` item 6) rather than preserve this
   list.
3. Building a list rather than yielding. At the measured scale it does not matter.
4. `parse_time_spec` living in this module at all. Time parsing is not file discovery;
   it is here because `discover_files` needed it and `catjsonl` already had its own
   incompatible copy.

---

## 8. Platform notes

Tiers per `DESIGN.md`: **A** = inline portability fix, **B** = genuinely OS-divergent,
**C** = platform-impossible.

This is the most portable module in the review. Everything below is Tier A or a
non-issue.

| Concern | Where | Tier | Detail |
|---|---|---|---|
| Path handling | 58, 66 | **A — clean** | `pathlib` throughout; `expanduser()` resolves `~` on Windows via `USERPROFILE`. No string path surgery, no separator assumptions. |
| Case sensitivity | 43-45 | **A — needs attention** | `name.endswith(".jsonl")` and `name == "logs.json"` are case-**sensitive**. Windows and macOS default to case-insensitive filesystems, Linux/WSL does not. A file written as `Session.JSONL` is found on none of them by this test but exists on all of them. Low likelihood, but it is a real divergence: use a case-folded comparison. |
| Symlink loops | 66 | **A — safe** | `Path.rglob` does not recurse into symlinked directories on the supported Python versions, so a cycle cannot hang the walk. Worth an explicit test if the walk is ever rewritten with `os.walk`, which does not have that property by default. |
| Unreadable directories | 66-74 | **A** | `rglob` skips directories it cannot enter; the per-entry `try/except OSError` covers stat failures. Windows junction points and locked directories are handled by the same paths. |
| mtime resolution | 72, 81 | **A** | NTFS, APFS, and ext4 all provide sub-second mtime through `st_mtime`. FAT32 has 2-second granularity — only relevant on a removable drive. |
| Local vs UTC in absolute dates | 37 | **A — see §9.2** | `strptime(...).timestamp()` uses the local zone. Correct in itself, but it disagrees with `catjsonl._parse_time_spec`, which assumes UTC. |
| Line endings, file locking, processes, signals, terminals | — | n/a | This module reads no file contents, spawns nothing, and holds no handles. |

Nothing here belongs in `platform_compat/`, and nothing here is Tier C.

---

## 9. Risks & sharp edges

### 9.1 An unparseable time specification silently disables the filter

`parse_time_spec` returns `None` for anything it does not recognize (40), and
`discover_files` reads `None` as "no bound" (75-78). So `--since 7dd`, `--since 1y`,
`--since "last week"`, and `--since 2026-04-09 14:30` all quietly widen the search to
the entire tree instead of raising. The predecessor raised (`fsFilters.py:147`). A
filter that fails open is a bad failure mode: the user gets more results than asked
for, which looks like success.

### 9.2 Two time parsers, two time zones, two failure modes

Fully described in `catjsonl_design.md` §8.7. Summarized here because this module owns
half of it: `discovery.parse_time_spec` treats a bare date as **local** midnight and
fails silently; `catjsonl._parse_time_spec` treats it as **UTC** midnight and **raises**
`argparse.ArgumentTypeError` outside argparse, producing an uncaught traceback. Both run
on the same `--since` value. `--since 2026/04/09` is accepted by this module and crashes
the other one.

### 9.3 The sort re-stats every file without a guard — a real crash path

The walk carefully guards `p.stat()` inside `try/except OSError` (69-74), and then line
81 calls `p.stat().st_mtime` again as the sort key **with no guard**. A file deleted
between the walk and the sort — entirely possible in a live transcript directory, and
more likely if a `scrub` or `offload` is running concurrently — raises `FileNotFoundError`
out of `sorted()` and takes down the whole `jgrep -r` run.

The fix is trivial: cache each mtime during the walk and sort on the cached value, which
also halves the number of `stat` calls. `catjsonl.resolve_sources` already guards its
own mtime sort for exactly this reason (`catjsonl.py:437-442`, comment: *"Guard the stat
so a vanished/unstattable path can't crash the sort"*). The same lesson was learned there
and not applied here.

### 9.4 Archive manifests are returned as if they were session transcripts — confirmed

`lib_jsonl_archive` writes `offload_manifest.jsonl` into
`<transcript_dir>/<stem>[.<namespace>].<id>.archive/`, i.e. **inside the directory tree
the j-tools recursively search**. `_is_session_file` accepts any name ending in
`.jsonl`, so every manifest is returned as a session file.

Verified on this machine: `discover_files("~/.claude/projects")` returns 2,002 files, of
which **13 are `offload_manifest.jsonl`**. `jwc --by-type <manifest>` reports `0 total` —
so the parser does not choke — but the files are still opened and parsed, they appear as
per-file headers under `jgrep -v`, and they appear as `path:0` lines in `jgrep -c`
output.

Low severity today, and it will grow with every offload. Two ways to fix it: skip
directories matching `*.archive`, or skip the manifest by name. The first is better,
because archives also contain `.txt` and `.json` bodies that a future discovery rule
might otherwise pick up.

The related case — `scrub_files`' temporary `.scrub_tmp_*.jsonl` files (`scrub_files.py:620`)
— is narrower, since they exist only for the instant between `mkstemp` and `os.replace`,
but a recursive search running concurrently with a scrub can see one.

### 9.5 The `sort` parameter is computed and discarded

`discover_files` sorts (81); `catjsonl.resolve_sources` then re-sorts the same paths by
mtime (`catjsonl.py:444`). Harmless, but it means the parameter is untested by use and
anyone reading either function alone will draw the wrong conclusion about who owns
ordering.

### 9.6 No tests

`tests/smoke_test.py:49` imports the module. Nothing asserts any of its behavior. For
82 lines of pure, dependency-free, side-effect-free code this is the cheapest test suite
in the package to write — every function is a direct input-to-output mapping.

---

## 10. What I could not determine

- **Whether the `m` = minutes change was a deliberate alignment** with
  `catjsonl._parse_time_spec` or an unnoticed consequence of writing the shim fresh.
  Rationale unknown — needs an owner's answer. It matters, because it silently changed
  what an existing flag value means.
- **Why `_ABS_FORMATS` contains exactly those three formats** and not the five the
  predecessor accepted. Rationale unknown — needs an owner's answer.
- **Why unparseable specs return `None` instead of raising**, given the predecessor
  raised. Rationale unknown — needs an owner's answer.
- Whether any Gemini transcript directory in current use actually contains a
  `logs.json`. I confirmed the code path exists and matches the documented intent, but
  found no such file on this machine to test against.
