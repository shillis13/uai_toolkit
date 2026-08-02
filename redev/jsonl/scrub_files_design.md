# scrub_files.py — redevelopment design

Source of record: `/Users/shawnhillis/AI/uai_toolkit/src/uai_toolkit/jsonl/scrub_files.py`
(1383 lines). All line citations are against that file unless another path is given.

## Terms

- **Attachment** — as this module uses the word: an embedded image, a PDF reference, or
  a large text tool result inside a session transcript. **Not** a general "file
  attached to a message".
- **Scrub** — here, *delete an attachment's bytes from the transcript and leave a short
  text placeholder*. It is lossy and irreversible except via the backup file.
  **It does not mean "remove sensitive data"** — see §6 and §8.1.
- **Offload / archive-and-stub** — copy the original block into a sibling archive
  directory and leave a pointer stub in the transcript. Reversible.
- **Rehydrate** — restore offloaded content from the archive back into the transcript.
- **JSONL** — JSON Lines: one complete JSON value per line.
- **CAS (compare-and-swap) guard** — capture the file's size before and after reading,
  and refuse to write if it changed, so a concurrently appending process is not
  clobbered.
- **REPL** — read-eval-print loop; an interactive prompt.
- **CLI** — command-line interface.
- **Base64** — a text encoding of binary data; how images are embedded in transcripts.

---

## 1. What it is for

`scrub_files.py` reclaims disk space and next-resume context from a session transcript
by finding heavy embedded payloads — base64 images, PDF references, and oversized text
tool results — and removing or archiving them in place. It ships two generations of
that idea in one file: a **legacy destructive path** (`list` / `info` / `rm` / `scrub`
/ `backup` / `restore`, available both as one-shot commands and as an interactive
prompt), and a **newer reversible path** (`offload` / `rehydrate`) that delegates to
`lib_jsonl_archive.py`. It also happens to be the module three unrelated callers import
for its session-identifier resolver, `find_jsonl`.

---

## 2. Interface

### 2.1 How it is invoked

**There is no console-script entry point.** `pyproject.toml` `[project.scripts]`
(lines 35-50) lists `read_jsonl`, the six j-tools, `uai-toolkit`, two MCP servers and
three hook handlers — **not** `scrub_files`. So on a `pip install` of this package,
`scrub_files` is reachable only as `python -m uai_toolkit.jsonl.scrub_files` or as a
Python import. Whether that is intentional or an omission is **rationale unknown —
needs an owner's answer**; the module has a fully developed CLI and its own help text,
which suggests it was expected to be a command.

Line 1 is `#!$HOME/myenv/bin/python3` — a shebang containing a literal, unexpanded
`$HOME` and pointing at a virtual environment that is not part of this package. As a
shebang it cannot work; the file is nonetheless marked executable in the source tree.
**Flagging as an error**: it should either be `#!/usr/bin/env python3` or absent.

### 2.2 Argument grammar

`main()` (1293-1379):

```
scrub_files                                # REPL, no session
scrub_files --help | -h | --version        # (also: help, ?, quit, exit, q → REPL)
scrub_files <session>                      # REPL, session pre-loaded
scrub_files <session> offload   [flags]    # archive-and-stub embedded images
scrub_files <session> rehydrate [--dry-run]
scrub_files <session> <command> [args…]    # one-shot legacy command
```

`<session>` accepts a direct `.jsonl` path, a session UUID or UUID prefix, a tracking
identifier, a display name, or a terminal session name (resolution in §5.1).

**Legacy commands** (dispatched in `ScrubSession.run_command`, 992-1033):

| Command | Effect | Mutates? |
|---|---|---|
| `open <session>` | load a session (REPL only, in practice) | no |
| `list` / `ls` `[--type T] [--sort F] [--json]` | tabular inventory of attachments | no |
| `info <ref>` | detail for one attachment | no |
| `rm` / `remove` `<ref…>` | replace listed attachments with a placeholder | **yes** |
| `scrub` `[--type T] [--max-px N] [--all]` | bulk version of `rm` | **yes** |
| `backup` | copy transcript to `<name>.jsonl.bak` if absent | writes the backup |
| `restore` | copy the backup back over the transcript | **yes** |
| `help` / `?` | print `HELP_TEXT` | no |
| `quit` / `exit` / `q` | leave the REPL | no |

`<ref…>` accepts individual numbers and inclusive ranges: `rm 1 3 5`, `rm 1-5`
(`_parse_refs`, 577-595). References are the `#` column from `list` and are **assigned
fresh on every scan** (439-440) — they are positions, not identities. See §8.6.

`--sort` accepts `line` (default), `name`, `size`, `type`, `date`. `size` sorts
descending, everything else ascending (493-503).

`--type` accepts comma-separated values, mapped by `_normalize_type_filter` (462-482):
`images`/`image` → `image`; `pdf`/`pdfs` → `pdf` and `pdf-raw`; `files`/`file`/`text` →
`file`; `scrubbed` → `scrubbed`. An unrecognized value is passed through unmapped,
which means it matches nothing.

**Offload commands** (1331-1366), parsed by a hand-rolled `_flag` helper (1335-1343)
rather than argparse:

| Flag | Default | Note |
|---|---|---|
| `--keep-last-turns N` | 5 | protect the last N human turns verbatim |
| `--min-bytes N` | 2048 at the CLI (1354); the function signature says 512 (1193) | only page out blocks at least this big |
| `--strip` | off | discard instead of archiving (irreversible) |
| `--dry-run` | off | report only |

`_flag` silently falls back to the default when the value will not cast (1340-1342), so
`--min-bytes abc` is accepted and ignored.

### 2.3 Exit codes

The docstring (16-19) claims `0` success, `1` file not found or unreadable, `2` write
error. **The code implements only 0 and 1.** `sys.exit(1)` fires when the session
cannot be resolved (1327-1328); `sys.exit(0)` for `--help`/`--version`. Write failures
print in red and return `False` from `_atomic_write` (629-636), and the process still
exits 0. So a caller cannot detect a failed write from the exit status. Confirmed
divergence between docstring and code.

### 2.4 Importable surface (this is the real integration contract)

- `find_jsonl(identifier) -> Path | None` (59-114)
- `get_image_dimensions_from_base64(b64) -> (w, h) | None` (121-167)
- `scan_attachments(path) -> list[dict]` (211-442)
- `_ensure_backup(path) -> bool` (598-610), `_atomic_write(path, content) -> bool`
  (613-636)
- `remove_attachments`, `scrub_bulk`, `do_backup`, `do_restore`
- `offload_embeds(...) -> dict` (1193-1290)
- `ScrubSession` (946-1124), `repl` (1151-1186), `main` (1293-1379)
- `VERSION = "1.0.0"` (40), `MAX_DIMENSION = 2000` (42), `IMAGE_EXTENSIONS` (174)

`IMAGE_EXTENSIONS` (174) is defined and never used anywhere in the file or the
repository.

---

## 3. Integration

### 3.1 Who imports this — and it is not who the documentation says

| Caller | What it uses | Line |
|---|---|---|
| `src/uai_toolkit/mcp/sessions/tools/context_ops.py` | `scrub_files.find_jsonl` | 69-70 |
| `src/uai_toolkit/hooks/handlers/Stop/09_auto_offload_sync.py` | `scrub_files.find_jsonl` | 99-100 |
| `src/uai_toolkit/jsonl/lib_jsonl_archive.py` | `scrub_files.get_image_dimensions_from_base64` | 1152-1153 |

So the module's **actual** load-bearing export is `find_jsonl` — a session-identifier
resolver — used by a Model Context Protocol server tool and by a `Stop` hook handler.
Neither of those callers wants to scrub anything. This is the single most important
integration fact about the file, and neither `jsonl/README.md` nor the module docstring
mentions it.

`jsonl/README.md:141-142` states that `offload_tool_results.py` imports
`scrub_files`'s `find_jsonl` / `_ensure_backup` / `_atomic_write`. **There is no
`offload_tool_results.py` in this package.** The `jsonl/` directory contains
`catjsonl.py`, `deferred_self_compact.py`, `discovery.py`, `lib_engram.py`,
`lib_jsonl_archive.py`, `read_jsonl.py`, `resume_note.py`, `scrub_files.py`,
`standardized_session.py`, `summarizer.py`, and `platform_adapters/`. The README also
documents `compact_jsonl.py`, `condense.py`, `offload_session.py`, and a
`scrub_large_images.py` symlink — **none of which exist here either**. The README was
written against the source tree, not the package.

Note the direction of the `lib_jsonl_archive` relationship: `scrub_files.offload_embeds`
imports `lib_jsonl_archive` (1205), and `lib_jsonl_archive` imports
`scrub_files.get_image_dimensions_from_base64` (1152). That is a **circular import**,
avoided only because both sides do the import lazily inside a function.

### 3.2 What this calls

- `uai_toolkit.paths.AI_SCRIPTS` (50) — pulled in only to build two `sys.path`
  insertions (51, 73) that are vestigial: the actual imports right after them are
  absolute `uai_toolkit.*` imports that do not need the path entries.
- `uai_toolkit.common_utils.standard_colors` (52, 1168) for `c`, `format_help`, `bold`,
  `dim`, `heading`, `colors_enabled`.
- `uai_toolkit.session_mgmt.session_store.SessionStore` (76), lazily, inside
  `find_jsonl`, wrapped in a bare `except Exception: pass` (99-100).
- `uai_toolkit.jsonl.lib_jsonl_archive` (1205, 1332), lazily, for the offload path.
- Standard library: `readline` (30, unguarded — see §7), `shutil.rmtree` for PDF page
  directories (742), `tempfile.mkstemp` for the atomic write (618).

---

## 4. Data & config

| Path | Mode | Notes |
|---|---|---|
| `<transcript>.jsonl` | read + **rewrite in place** | The primary target. Rewritten by `rm`, `scrub`, `restore`, `offload`, `rehydrate`. |
| `<transcript>.jsonl.bak` | write once, read on `restore` | `_ensure_backup` (598-610) never overwrites an existing backup. So the backup always holds the **pre-first-edit** state, not the previous step. Stated correctly in `HELP_TEXT` 929-932. |
| `.scrub_tmp_*.jsonl` | create + rename | Temporary file for the atomic write, created in the transcript's own directory (618-622). |
| `<transcript_dir>/<stem>.offload.<id>.archive/` | write | Created by the offload path via `lib_jsonl_archive.Archive` with `namespace="offload"` (1221). Holds archived bodies plus `offload_manifest.jsonl`. |
| PDF page output directory | **`shutil.rmtree`** | `_remove_one_attachment` (740-744) deletes the whole directory Claude Code extracted PDF pages into. **This is not covered by the `.bak`** — `restore` puts the transcript back but the page images are gone. |
| `~/.scrub_files_history` | read + write | REPL command history (41, 1131-1148). Note it goes to the user's home directory, not to `AI_ROOT` — inconsistent with the repo's instance model (`DESIGN.md` decision 1/4). |

**Environment variables:** `AI_SCRIPTS` is read at 47 only to prepend to `sys.path`.
Everything else arrives indirectly through `uai_toolkit.paths` (which reads `AI_ROOT`,
`AI_CONFIG`, and `config.toml`) and through `standard_colors`.

**Durability note.** The `.bak`, the archive directory, and the transcript itself all
live beside the transcript in the AI CLI's own project directory. A re-design cannot
relocate them freely: `lib_jsonl_archive` resolves the archive from the transcript's
directory and stem, and `read_jsonl --resolve` follows the portable reference in a stub
by the same rule.

---

## 5. How it works

### 5.1 Session resolution — `find_jsonl` (59-114)

Three attempts, in order:

1. If the identifier is an existing file, return it (63-65).
2. Ask `SessionStore().resolve(identifier)`. On a hit, try each `transcript_path` in
   the row, then fall back to scanning `~/.claude/projects/*/<cli_session_id>.jsonl`
   (71-98). The entire block is inside `except Exception: pass`.
3. Substring/prefix match of the identifier against `.jsonl` stems under
   `~/.claude/projects/` (102-113).

**This resolver is Claude-only.** Steps 2's fallback and step 3 both hard-code
`~/.claude/projects`. `read_jsonl.find_jsonl` (`read_jsonl.py:593-612`) is a different
and broader implementation — it strips `uai://` / `prompt://` URI wrappers and searches
Claude projects, Codex sessions, Gemini history, and the Codex archive. So the package
carries **two divergent session resolvers with the same name**, and the callers listed
in §3.1 chose the narrower one.

### 5.2 Inventory — `scan_attachments` (211-442)

Reads the whole transcript with `jsonl_path.read_text()` (221) — **no `encoding=`** —
and splits it into lines. For each line it parses JSON (silently skipping
undecodable lines, 228-231), then:

1. Records every `tool_use` block whose `name == "Read"` into a
   `tool_use_id → file_path` map, so later attachments can be labeled with the file
   they came from (246-252).
2. `toolUseResult.type == "parts"` → a **`pdf`** record. Page count and size are read
   from the record, or computed by listing the extraction directory if absent
   (255-289).
3. `toolUseResult.file.filePath` ending in `.pdf` without `type == "parts"` → a
   **`pdf-raw`** record (291-316).
4. A top-level `content[j]` block of `type == "image"` with a base64 source → an
   **`image`** record; dimensions from `get_image_dimensions_from_base64`, and
   `oversized = max(dims) > MAX_DIMENSION` (323-347).
5. A `tool_result` block whose `content` is a **list**: nested `image` blocks become
   `image` records (360-385); nested `text` blocks whose text contains
   `"[Image removed by scrub_large_images:"` or `"[Removed:"` become **`scrubbed`**
   records so the tool can recognize its own prior work (387-414).
6. A `tool_result` block whose `content` is a **string longer than 10,240 characters**
   → a **`file`** record (416-436). The 10 KiB threshold is hard-coded and not
   configurable.

Each record carries a `block_path` string such as `"content[2]"`,
`"content[2].content[0]"`, `"content[3].content"`, or `"toolUseResult"` — a
**stringified navigation path** that the removal code later re-parses with a regular
expression. Display numbers are assigned last, by list position (439-440).

Recognized types are exactly: `image`, `pdf`, `pdf-raw`, `file`, `scrubbed`.

### 5.3 Removal — `remove_attachments` (639-703)

1. Resolve reference numbers to records, skipping anything already `scrubbed`
   (645-657).
2. `_ensure_backup` — bail out entirely if the backup cannot be made (662-663).
3. Re-read the transcript (665) — a **second read**, so the inventory in memory may
   already be stale relative to what is about to be rewritten.
4. Group targets by line number, and for each affected line: parse it, apply each
   removal via `_remove_one_attachment`, and re-serialize the whole record with
   `json.dumps(entry, ensure_ascii=False)` (689-695). Unaffected lines are appended
   verbatim.
5. Join with `"\n"`, ensure a trailing newline, and `_atomic_write` (697-702).

`_remove_one_attachment` (706-754) builds a placeholder string
(`[Removed: image, 1920x1080]`, `[Removed: PDF, 12 pages]`, `[Removed: file, 340K]`,
or `[Removed]`), replaces the target block inside `message.content` via
`_apply_block_replacement`, and separately rewrites `toolUseResult` for PDFs (deleting
the page directory) and for images.

`_apply_block_replacement` (757-789) re-parses the `block_path` string with
`re.findall(r'content\[(\d+)\]|content$', block_path)` and branches on how many
fragments came back. See §8.2 — this is where it breaks.

`_atomic_write` (613-636) uses `tempfile.mkstemp` in the transcript's directory, writes
UTF-8 explicitly (624), and `os.replace`s over the target.

### 5.4 Bulk scrub — `scrub_bulk` (792-820)

Selects references and delegates to `remove_attachments`. Skips `scrubbed` records;
applies `--type` if given; then either takes everything (`--all`) or only records where
`att["oversized"]` is true — a flag computed at **scan** time against the module
constant `MAX_DIMENSION` (344, 382). See §8.3.

### 5.5 Reversible offload — `offload_embeds` (1193-1290)

A different design, and a noticeably more careful one:

1. Capture the file size before and after reading (`sig0`, `sig1`, 1207-1209) for the
   CAS guard.
2. Parse every line, keeping unparseable lines as raw strings so they survive
   round-trip (1211-1216).
3. `protect_from_index` (1218) computes the record index at or after which everything
   is left verbatim — the last `keep_last_turns` human turns. The intent, per the
   docstring, is not to strip a screenshot the model is currently looking at.
4. Open (or reuse) the per-transcript archive under `namespace="offload"` (1221).
5. Walk `message.content` for `image` blocks, both top-level and nested one level
   inside another block's `content` list (1243-1249). Skip protected records
   (1253-1255) and blocks under `min_bytes` (1256-1258).
6. In `archive` mode, write the original block to the archive with manifest metadata
   `{"kind": "embed", line, path, embed_type, media_type, dims}` and replace it in
   place with a text stub carrying dimensions, media type, size, a content hash, the
   portable archive reference, and an explicit "do NOT reconstruct from memory"
   instruction (1268-1279). In `strip` mode there is no archive and the stub says
   `[embed stripped: …]`.
7. Commit through `lib_jsonl_archive.commit` (1287), which re-checks the size
   fingerprint and returns `"raced"` rather than writing if the transcript grew
   (`lib_jsonl_archive.py:705-706`), rewrites **only changed records** so untouched
   lines stay byte-identical, and takes a one-time backup.
8. Append the manifest only after a successful commit (1288-1289).

`rehydrate` (1346-1351) is entirely `lib_jsonl_archive.rehydrate`.

Note the asymmetry: **`offload` protects a live session; `rm` and `scrub` do not.**

---

## 6. What this module guarantees, and what it does not

This section exists because the word "scrub" invites a security reading that the code
does not support.

### It does guarantee

- **Atomic replacement.** Both write paths go through a temp file plus `os.replace`
  (618-627; `lib_jsonl_archive.atomic_write`). A crash mid-write leaves the original
  intact, on POSIX and on Windows.
- **A one-time backup before the first destructive edit** (598-610, 662-663). If the
  backup cannot be created, `rm`/`scrub` refuse to proceed.
- **Structural preservation of the conversation.** Removed blocks are replaced by a
  text block, not deleted, so `tool_use`/`tool_result` pairing and record count are
  preserved and the transcript stays loadable.
- **For the `offload` path only:** reversibility (`rehydrate` restores from the
  archive), a compare-and-swap write guard against a concurrently appending session,
  byte-identical untouched lines, a protected recent-turn window, and a content hash in
  the stub.

### It does NOT guarantee — and these matter

1. **It is not a sensitive-data scrubber.** It selects blocks by *type and size*
   (`image`, `pdf`, `pdf-raw`, text over 10,240 characters), never by content. It has
   no notion of a credential, token, key, personal identifier, or any pattern at all.
   A transcript run through `scrub --all` can still contain every secret that was ever
   typed or printed into it, in message text, thinking blocks, tool arguments,
   `toolUseResult` fields, and any text tool result under 10 KiB. **If anyone reads
   `DESIGN.md` decision 6's "HARD GATE before any public push: PII/secret scrub" and
   reaches for this module, they will get a false sense of safety.** These are
   unrelated tools with an overlapping word.
2. **It does not remove data from anywhere but the transcript file.** The base64 bytes
   also survive in the `.bak`, in any archive directory, in the AI provider's
   server-side copy of the conversation, and in any backup of the project directory.
   Scrubbing is a local space-reclaim operation, not a deletion guarantee.
3. **It does not protect a live session.** The `rm`/`scrub` path reads at 665 and
   writes at 701 with **no compare-and-swap check**. Any message the session appends in
   between is silently lost when the rewritten content replaces the file. Only the
   `offload` path guards against this.
4. **It does not scope to the active conversation branch.** It rewrites every matching
   attachment on every line of the file, including records on abandoned retry/rewind
   branches. Stated in `HELP_TEXT` 938.
5. **Recovery beyond one step is not available.** The single one-shot `.bak` means the
   only rollback is to the pre-first-edit state. A second `scrub` cannot be undone
   individually.
6. **PDF page directories are deleted outright** (740-744) and are not recoverable from
   the `.bak`.
7. **Text tool results are not actually removed** — see §8.2. Confirmed defect.

---

## 7. Platform notes

Tiers per `DESIGN.md`: **A** = inline portability fix, **B** = genuinely OS-divergent
(belongs in `platform_compat/`), **C** = platform-impossible, degrade behind a
capability flag.

| Concern | Where | Tier | Detail |
|---|---|---|---|
| **`import readline` at module top, unguarded** | 30 | **A — blocking on native Windows** | `readline` is not in the Windows standard library. Importing this module raises `ModuleNotFoundError` on native Windows. Because `mcp/sessions/tools/context_ops.py:69` and `hooks/handlers/Stop/09_auto_offload_sync.py:99` import `scrub_files` **just to call `find_jsonl`**, this one line takes an MCP tool and a hook handler down with it. Fine under WSL (Phase 1); a hard stop for Phase 2. Fix: import lazily inside `setup_readline`, guarded. |
| **Reads without an explicit encoding** | 221, 665, and `standardized_session`-style `read_text()` | **A** | `Path.read_text()` uses the platform default encoding. On Windows that is typically cp1252, so any transcript containing non-ASCII text raises `UnicodeDecodeError`. Worse, `_atomic_write` writes UTF-8 explicitly (624) — a mismatched read/write pair is a corruption path, not just a failure. Every read here must be `encoding="utf-8"`. `offload_embeds` already does it correctly (1208). |
| Line-ending normalization | 221→697 | **A** | `read_text()` in text mode translates CRLF to LF; the rewrite joins with `"\n"`. On a transcript that ever had CRLF, "untouched lines stay byte-identical" is false. |
| **Atomic write changes the file mode** | 618-627 | **A** | Verified: after a scrub, the transcript went from `-rw-r--r--` to `-rw-------`, because `tempfile.mkstemp` creates 0600 and `os.replace` keeps the temp file's mode. Fix: `os.chmod` the temp file to the original's mode (or `shutil.copymode`) before replacing. On Windows this manifests differently — the replacement file inherits the directory's inherited ACL rather than the original's. |
| `os.replace` over an open file | 627 | **B** | On POSIX this always succeeds. On native Windows it fails if another process holds the file open without delete-sharing. `jsonl/README.md:81` asserts Claude Code opens append-and-closes per write, so the window is small — but that claim is about Claude Code on macOS and is **not verified for Windows**. This is the canonical `platform_compat` candidate in this file. |
| `shutil.rmtree` on the PDF directory | 742 | **A/B** | Fails on Windows if any page image is open in a viewer. Currently swallowed by `except OSError: pass` (743-744), so the transcript is rewritten as if the directory were gone. |
| `~/.scrub_files_history` | 41 | **A** | `Path.home()` resolves on both. The concern is policy, not portability: it should live under `AI_ROOT` per `DESIGN.md` decision 1. |
| Hard-coded `~/.claude/projects` | 91, 105 | **A** | Uses `Path.home()`, so it is path-portable, but it bakes in one vendor's layout and ignores the `paths.py` resolver that exists precisely to make such locations configurable. |
| Shebang `#!$HOME/myenv/bin/python3` | 1 | **A** | Non-functional on every platform. Remove it or make it `#!/usr/bin/env python3`. |
| Interactive REPL | 1151-1186 | **A** | `input()` plus readline. Works in a Windows terminal once the `readline` import is guarded; the arrow-key/history experience degrades without `pyreadline3`. |

Nothing here is Tier C.

---

## 8. Risks & sharp edges

Items 1-4 were confirmed by executing the code.

### 8.1 The name promises more than the tool delivers

Covered in §6. Restating it here because it is the highest-consequence
misunderstanding available: **`scrub_files` removes bulk, not secrets.** A re-designer
who assumes otherwise, or a user who runs `scrub --all` before sharing a transcript,
gets no protection whatsoever against credentials or personal data in message text.
Consider renaming the module in the re-design so the confusion cannot recur.

### 8.2 Scrubbing a large text tool result is a silent no-op — confirmed

For `att_type == "file"`, `scan_attachments` sets `block_path` to
`"content[{j}].content"` (433). `_apply_block_replacement` (757-789) parses that with
`re.findall(r'content\[(\d+)\]|content$', …)`, which returns **two** fragments
`['3', '']`. Two fragments takes the `elif len(parts) >= 2` branch (779-789), which
reads `inner_idx = parts[1]` = `''` and then does nothing, because the branch is
guarded by `if inner_idx != ''` (785).

The `len(parts) == 1` branch at 766-778 contains a special case written for exactly
this path shape (768-775), but it is **unreachable** — `findall` never returns a
single empty fragment for any `block_path` this module produces.

Reproduced on a synthetic transcript containing one 20,000-character `tool_result`
string:

```
before size 20141
$ scrub_files t.jsonl scrub --all --type files
  Backup created: …/t.jsonl.bak
  Scrubbed 1 attachment(s), saved 0B
after  size 20141          # unchanged
```

The tool reports success, creates a backup, rewrites the file, and changes nothing.

Compounding it: even if the block replacement worked, `_remove_one_attachment` never
touches `toolUseResult` for `att_type == "file"` (738-752 handles only `pdf`,
`pdf-raw`, and `image`), and Claude Code frequently stores the same text there. So a
"file" scrub would still leave the bulk behind.

### 8.3 `--max-px` is accepted and ignored — confirmed by reading

`cmd_scrub` parses `--max-px` (1090-1095) and passes it to `scrub_bulk`, whose
signature declares `max_px=MAX_DIMENSION` (792-793). **The parameter is never
referenced in the function body.** Selection uses `att["oversized"]` (813), a boolean
frozen at scan time against the module constant `MAX_DIMENSION = 2000` (42, 344, 382).
So `scrub --max-px 1200` behaves exactly like `scrub`. `HELP_TEXT` 908-910 explicitly
documents `--max-px` as governing the default scrub — the help text and the code
disagree.

### 8.4 `scrub --type all` matches nothing

`cmd_list` translates `--type all` to "no filter" (1046-1047). `cmd_scrub` does not
(1087-1089), so `all` falls through `_normalize_type_filter` unmapped, becomes the
literal set `{"all"}`, and matches no `att_type`. `HELP_TEXT` 903-906 documents `all`
as a valid value for the shared `--type` filter. Result: `scrub --all --type all`
prints "No attachments match scrub criteria" and exits 0.

### 8.5 Unknown options are silently ignored

Both `cmd_list` (1042-1056) and `cmd_scrub` (1085-1100) hand-parse arguments in a
`while` loop whose `else` branch is a bare `i += 1`. A typo — `--typ images`,
`--max-pix 800`, `--dry-run` (which the legacy path does not support at all) — is
discarded without a word. `scrub --all --typ images` therefore scrubs **every
attachment in the transcript**, including PDFs, whose page directories it then deletes.
This is a destructive command with no confirmation prompt and no argument validation.

### 8.6 Reference numbers are positions, not identities

`scan_attachments` assigns `num` by list position on every scan (439-440). In the REPL,
`rm` invalidates the cache (1072) and the next `list` renumbers everything. A user who
runs `list`, notes `#7`, then removes `#3`, and then types `rm 7` hits a different
attachment. Nothing warns.

### 8.7 The destructive path has no concurrency guard

Detailed in §6. `remove_attachments` reads at 665 and writes at 701 with no
before/after size check, while `offload_embeds` does exactly that check
(1207-1209 → `lib_jsonl_archive.commit` 705-706). Running `scrub` against a session
that is actively appending will silently drop the appended messages. This is the single
most dangerous behavior in the file, and the fix already exists in the same module.

### 8.8 Two session resolvers named `find_jsonl`

`scrub_files.find_jsonl` (Claude-only, 59-114) and `read_jsonl.find_jsonl` (Claude +
Codex + Gemini + Codex archive + URI stripping, `read_jsonl.py:593`). Three importers
picked the narrower one (§3.1), so an MCP tool and a `Stop` hook silently fail to
resolve a Codex or Gemini session. The `except Exception: pass` around the session-store
lookup (99-100) also hides genuine store errors as "not found".

### 8.9 The offload subcommands are undocumented in the tool's own help

`HELP_TEXT` (857-939) documents `open`, `list`, `ls`, `rm`, `remove`, `scrub`, `info`,
`backup`, `restore`, `help`, `quit` — and never mentions `offload` or `rehydrate`, the
two subcommands `jsonl/README.md:66` calls "the reversible successor to
strip-scrubbing" and recommends preferring. `scrub_files --help` therefore steers every
user to the lossy path.

The help text does point at a lossless alternative — twice, at 872 and 936 — but names
it `chain_skip.py offload`. **No `chain_skip.py` exists in this package.** The README
names two other files for the same job (`offload_tool_results.py`, `offload_session.py`)
that do not exist here either. Three documents, three different names, zero of them
resolvable.

### 8.10 Stale self-references

The docstring (10-14) documents the usage form and exit codes, both partly wrong
(§2.3). Line 5 says it "Replaces scrub_large_images.py"; the README claims
`scrub_large_images.py` survives as a back-compat symlink — there is no such file in
the package. Section headers at 56 and 118 say "preserved from scrub_large_images.py".
The `scrubbed`-detection string at 390 still matches
`"[Image removed by scrub_large_images:"`, which is correct and should be kept, but is
the only place that name still earns its keep.

### 8.11 `min_bytes` default disagrees with itself

`offload_embeds(min_bytes=512)` in the signature (1193-1194) versus `--min-bytes`
defaulting to 2048 at the CLI (1354). A programmatic caller and a command-line caller
get different behavior from the same "default".

### 8.12 Work in flight

This file is visibly mid-migration and should not be read as settled design:

- Two generations of the same capability coexist, with the newer one (`offload`)
  bolted onto `main` **before** the `ScrubSession` dispatcher (1330-1366) rather than
  integrated into it.
- `tools/manifest.py:240` marks the file `kind: "clean"` — a mechanical copy — yet it
  still contains three `sys.path` insertions (49, 51, 73) that `DESIGN.md`'s status
  section says were removed for the ported files, plus a `$HOME` shebang. The "clean"
  classification looks optimistic.
- `lib_jsonl_archive.py:385-391` documents an archive-namespacing fix tied to
  `todo_0366`, and a comment at 1219-1220 in this file references the same todo. That
  work is recent and possibly ongoing.
- `jsonl/README.md` describes a `jsonl/` package with five modules that are not here
  and omits four that are. Treat the README as source-tree documentation, not package
  documentation.

### 8.13 Untested

Nothing under `tests/` exercises this module. `tests/smoke_test.py` imports
`read_jsonl`, `catjsonl`, and `discovery` (line 49) — not `scrub_files`. Every defect
in §8.2 through §8.5 is a two-line test away from being caught.

---

## 9. What I could not determine

- **Why `scrub_files` has no console-script entry point** while the six j-tools do.
  Rationale unknown — needs an owner's answer.
- **Why the destructive path never got the compare-and-swap guard** that the offload
  path in the same file has. Rationale unknown — needs an owner's answer; the most
  likely reading is simply that `rm`/`scrub` predate it, but the code says nothing.
- **Whether the 10,240-character threshold** for classifying a text tool result as an
  attachment (417) was measured or picked. Rationale unknown — needs an owner's answer.
- **Whether `MAX_DIMENSION = 2000`** corresponds to a provider limit, a token budget,
  or a preference. Rationale unknown — needs an owner's answer.
- Whether `offload_embeds` handles image blocks nested more than one level deep. The
  walk at 1243-1249 goes exactly two levels; I did not find a transcript with deeper
  nesting to test against, so I cannot say whether deeper nesting occurs in practice.
- Whether `os.replace` over a transcript is safe while a Windows-hosted AI CLI holds
  it. Not tested — no Windows box available here.
