# discovery.py — recommendations for the re-design

Companion to `discovery_design.md`. Line citations are against
`src/uai_toolkit/jsonl/discovery.py`.

**The headline recommendation is: keep it.** Replacing ~3,500 lines of `file_utils`
(plus a third-party YAML dependency, plus a hard-coded path into a personal machine
directory) with 82 lines of standard library was the right call and is a precondition
for this package shipping at all. Do not reverse it because the module looks small. The
items below are corrections *within* that decision.

---

## Fix

### 1. Fail loudly on an unparseable time specification

**Problem.** `parse_time_spec` returns `None` for anything it does not recognize (40),
and `discover_files` reads `None` as "no bound" (75-78). `--since 7dd`, `--since 1y`,
`--since "last week"` all silently search the entire tree. The predecessor raised
`ValueError` (`fsFilters.py:147`); the shim dropped that.

**Why it matters.** A filter that fails open returns *more* than the user asked for,
which reads as success. There is no error to notice.

**Recommendation.** Raise on an unparseable spec, and have the caller validate at
argument-parse time so the failure lands before any work starts.

### 2. Guard the sort's `stat` call

**Problem.** The walk carefully wraps `p.stat()` in `try/except OSError` (69-74), then
line 81 calls `p.stat().st_mtime` again as a sort key **unguarded**. A file removed
between the walk and the sort — normal in a live transcript directory, and more likely
if a `scrub` or `offload` runs concurrently — raises `FileNotFoundError` out of
`sorted()` and kills the whole `jgrep -r` run.

**Recommendation.** Collect `(mtime, path)` pairs during the walk and sort on the cached
mtime. This removes the crash and halves the `stat` calls. `catjsonl.resolve_sources`
already does exactly this, with a comment saying why
(`catjsonl.py:437-442`) — the lesson was learned there and never applied here.

### 3. Skip archive directories

**Problem.** Confirmed: `lib_jsonl_archive` writes `offload_manifest.jsonl` into
`<transcript_dir>/<stem>[.<ns>].<id>.archive/`, inside the tree the j-tools search.
`_is_session_file` accepts any `.jsonl` name, so every manifest comes back as a session
file. On this machine `discover_files("~/.claude/projects")` returns 2,002 files, 13 of
them manifests. They parse to zero messages, so nothing crashes — but they are opened
and parsed, they show up as file headers under `jgrep -v`, and they appear as `path:0`
rows in `jgrep -c`. The count grows with every offload.

**Recommendation.** Prune any directory whose name ends in `.archive` during the walk.
Pruning the directory is better than filtering the manifest by name, because archives
also hold `.txt` and `.json` bodies that a future discovery rule could pick up.

While there, consider ignoring `.scrub_tmp_*.jsonl` (`scrub_files.py:620`) — a much
narrower window, but a recursive search running during a scrub can see one.

### 4. Decide the `m` unit deliberately, and write it down

**Problem.** In the replaced `fsFilters`, `m` meant **months**
(`fsFilters.py:143-144`). In the shim, `m` means **minutes** (21). So
`jgrep -r … --since 3m` used to select the last three months of files and now selects
the last three minutes. That is a silent reversal of an existing flag's meaning, not an
omission — and nothing in the code or the commit history says whether it was intended.

It is *defensible*: `catjsonl._parse_time_spec` has always used `m` = minutes for
message filtering (`catjsonl.py:309`), so the shim made the two halves of `--since`
agree. But an accidental fix and a deliberate one leave the same code and different
risk.

**Recommendation.** Confirm the intent with the owner, then make it unambiguous.
Preferred: drop the single-letter ambiguity entirely — accept `min`, `h`, `d`, `w`,
`mo`, `y` — and reject bare `m` with a message naming both alternatives. If bare `m`
must stay, document it in `--help` in the same breath as the value.

### 5. Restore the lost date formats, or state that they are gone

Dropped relative to the predecessor: `%Y-%m-%d %H:%M`, `%m/%d/%Y`, and relative `Ny`
(years). Added: relative `Nh` (hours). None of this is written down anywhere.

**Recommendation.** Fold this into recommendation 6 below — pick one grammar, document
it in one place, and make `--help` list it.

---

## Merge

### 6. One time parser for the whole package — the seam is here

**Problem.** Two parsers run on the same `--since` value, and they disagree on three
axes:

| | `discovery.parse_time_spec` (24-40) | `catjsonl._parse_time_spec` (`catjsonl.py:296-319`) |
|---|---|---|
| relative units | `m` min, `h`, `d`, `w` | same |
| absolute grammar | 3 fixed `strptime` formats | `datetime.fromisoformat` |
| bare date time zone | **local** midnight | **UTC** midnight |
| unparseable input | returns `None` (no bound) | **raises**, uncaught, traceback |

Concrete consequences, from `catjsonl_design.md` §8.7: `--since 2026/04/09` is accepted
here and crashes there; `--since 2026-04-09T14:30` is silently ignored here and accepted
there; `--since 2026-04-09` selects a different set of files than it selects messages,
by the size of the local UTC offset.

**Recommendation.** Extract one parser into `common_utils` (it is not a file-discovery
concern) and have both file selection and message selection call it. It must: accept one
documented grammar; interpret a bare date in one stated zone — recommend **local**, since
users think in local dates and the repository's global convention is local time — and
say so in `--help`; and raise on anything else, at argument-parse time.

This is the single highest-value change across `discovery.py` and `catjsonl.py`
together, because it eliminates a whole class of "the filter did something other than
what I asked" bugs in one move.

---

## Tidy

### 7. Resolve who owns ordering

`discover_files` sorts by mtime (81) and `catjsonl.resolve_sources` immediately re-sorts
the same paths by mtime (`catjsonl.py:436-444`). The `sort` parameter is computed and
discarded. Pick one owner and delete the other. Given the caller must sort anyway —
directories and explicit file arguments can be mixed in one invocation — the caller is
the natural owner, so `discover_files` should probably return unsorted results and drop
the parameter.

### 8. Case-fold the filename test

`_is_session_file` (43-45) compares `.jsonl` and `logs.json` case-sensitively. Windows
and macOS filesystems are case-insensitive by default, WSL/Linux is not, so a file
written as `Session.JSONL` exists on all three and is found on none. Use a case-folded
comparison. Low likelihood; near-zero cost.

### 9. Add tests — this is the cheapest suite in the package

82 lines, no dependencies, no side effects, every function a direct input-to-output
mapping. Nothing currently asserts any behavior (`tests/smoke_test.py:49` only imports
the module). Worth covering:

- every accepted relative unit and every accepted absolute format
- an unparseable spec raises (after recommendation 1)
- `since`/`before` boundaries are exclusive as written (75-78)
- `logs.json` is found; `logs.JSON` is found (after recommendation 8)
- a file deleted mid-walk does not crash the sort (after recommendation 2)
- a `*.archive` directory is skipped (after recommendation 3)
- a non-directory argument returns `[]` rather than raising
