# scrub_files.py — recommendations for the re-design

Companion to `scrub_files_design.md`. Line citations are against
`src/uai_toolkit/jsonl/scrub_files.py`.

Ordered by consequence, not by effort.

---

## Do first — safety and correctness

### 1. Rename the module, or accept that people will misread it

**Problem.** "Scrub" reads as "remove sensitive data". This tool removes *bulk* — it
selects blocks by type and size and has no content awareness at all. `DESIGN.md`
decision 6 sets a "HARD GATE before any public push: PII/secret scrub", and a reader
connecting those two things gets a dangerously false assurance.

**Recommendation.** Name it for what it does: `strip_attachments`, `reclaim_embeds`, or
similar. State in the first line of the docstring and the first line of `--help`: *this
tool removes large attachments to reclaim space; it does not detect or remove
credentials or personal data.* If the name must stay for compatibility, put that
sentence in both places anyway.

### 2. Guard `import readline`

**Problem.** Line 30 imports `readline` unconditionally. It does not exist in the
native-Windows standard library, so importing this module raises `ModuleNotFoundError`
there. Two callers import `scrub_files` **only to call `find_jsonl`** —
`mcp/sessions/tools/context_ops.py:69` and `hooks/handlers/Stop/09_auto_offload_sync.py:99`
— so one unused-by-them import takes down an MCP tool and a `Stop` hook on Windows.

**Recommendation.** Move the import inside `setup_readline` (1131-1140) behind a
`try/except ImportError`, and degrade the REPL to plain `input()` when it is absent.
Tier A, one-line class of fix, blocking for the Phase 2 native-Windows target.

### 3. Add the compare-and-swap guard to the destructive path

**Problem.** `remove_attachments` reads at 665 and writes at 701 with no check that the
file changed in between. Running `scrub` on a live session silently discards every
message appended during the run. The correct implementation already exists **in the
same file**: `offload_embeds` captures a size fingerprint around its read (1207-1209)
and `lib_jsonl_archive.commit` refuses to write on a mismatch
(`lib_jsonl_archive.py:705-706`).

**Recommendation.** Route `rm`/`scrub` through `lib_jsonl_archive.commit`, or at
minimum replicate the `sig0`/`sig1` check. This also buys byte-identical untouched
lines for free, which the current whole-file re-join does not guarantee.

### 4. Fix — or delete — text-tool-result scrubbing

**Problem.** Confirmed defect: scrubbing an `att_type == "file"` attachment changes
nothing while reporting `Scrubbed 1 attachment(s)`. The `block_path` string
`"content[3].content"` parses to two fragments, takes the two-fragment branch
(779-789), and hits a guard that skips it (785). The branch written to handle this case
(768-775) is unreachable.

**Recommendation.** Stop round-tripping structural navigation through a formatted
string that is then re-parsed with a regular expression. Carry the path as a list of
keys and indices — `["message", "content", 3, "content"]` — and navigate it directly.
`lib_jsonl_archive._nav_set` already does exactly this and is already used by
`offload_embeds` (1279). Reuse it and delete `_apply_block_replacement` entirely.

While fixing it, also rewrite `toolUseResult` for `att_type == "file"`; today only
`pdf`, `pdf-raw`, and `image` are handled (738-752), so even a working replacement
would leave duplicate text behind.

### 5. Validate arguments; stop ignoring unknown flags

**Problem.** `cmd_list` (1042-1056) and `cmd_scrub` (1085-1100) hand-parse arguments in
a loop whose `else` branch silently skips anything unrecognized. `scrub --all --typ
images` — one dropped character — scrubs **every attachment in the transcript**,
including PDFs, whose extraction directories it then permanently deletes (740-744).
There is no confirmation prompt.

**Recommendation.** Use `argparse` for the one-shot path so unknown options are an
error, and use `shlex` plus the same parser for REPL commands. Then add a confirmation
or a required `--yes` for any `scrub` that would remove more than a small number of
attachments, or any `scrub` that touches a `pdf` record.

### 6. Make `--max-px` do something, or remove it

**Problem.** `scrub_bulk` accepts `max_px` (792-793) and never uses it; selection reads
the `oversized` flag frozen at scan time against the constant `MAX_DIMENSION = 2000`
(42, 344). `HELP_TEXT` 908-910 documents it as governing the default scrub.

**Recommendation.** Either evaluate the threshold at selection time
(`att["dims"] and max(att["dims"]) > max_px`) or delete the flag and the help entry. A
documented flag that silently does nothing is worse than no flag.

### 7. Preserve file permissions across the atomic write

**Problem.** Verified: after a scrub, a transcript's mode went from `-rw-r--r--` to
`-rw-------`, because `tempfile.mkstemp` creates 0600 and `os.replace` keeps the temp
file's mode (618-627).

**Recommendation.** `shutil.copymode(original, temp)` before `os.replace`. This is not
cosmetic — it silently changes who can read a transcript, in the opposite direction
each way depending on the original mode.

### 8. Give the module real exit codes

**Problem.** The docstring (16-19) promises `0` / `1` / `2`. Only `0` and `1` exist; a
failed `_atomic_write` prints in red and the process still exits 0 (629-636).

**Recommendation.** Implement the documented contract. Anything hook-invoked or
MCP-invoked must be able to tell a failed write from a successful one.

---

## Drop / consolidate

### 9. One `find_jsonl`, in one place

**Problem.** Two divergent resolvers with the same name: `scrub_files.find_jsonl`
(59-114, Claude-only, hard-codes `~/.claude/projects` at 91 and 105) and
`read_jsonl.find_jsonl` (`read_jsonl.py:593`, which also strips `uai://` and
`prompt://` URI wrappers and searches Codex, Gemini, and the Codex archive). All three
importers in the repository picked the narrower one, so an MCP tool and a `Stop` hook
cannot resolve a Codex or Gemini session.

**What depends on it:** `mcp/sessions/tools/context_ops.py:69-70`,
`hooks/handlers/Stop/09_auto_offload_sync.py:99-100`.

**Recommendation.** Extract one resolver — ideally into its own module, since it is a
session-identity concern and not a scrubbing concern, and both of its real consumers
are outside this file. Have both `scrub_files` and `read_jsonl` call it. Also replace
the bare `except Exception: pass` at 99-100 with a narrow catch, so genuine
session-store errors stop masquerading as "not found".

### 10. Retire the destructive path, or clearly subordinate it

**Problem.** The file carries two generations of the same capability. `offload`
protects the recent-turn window, guards against concurrent appends, keeps untouched
lines byte-identical, and is reversible. `rm`/`scrub` do none of that. Yet `--help`
documents only the destructive path (857-939) and never mentions `offload` or
`rehydrate` at all, so every user is steered to the worse tool.

**Recommendation.** In the re-design, make archive-and-stub the default and the
documented path. Keep destructive removal as an explicit `--discard` mode of the same
command rather than a separate, older, less careful code path. If `rm`/`scrub` must
survive as-is, at least document `offload`/`rehydrate` in `HELP_TEXT` and mark the
destructive commands as legacy there.

### 11. Delete or fix the stale references

- Line 1: shebang `#!$HOME/myenv/bin/python3` — a literal, unexpanded `$HOME`. Remove
  it or use `#!/usr/bin/env python3`.
- Lines 49, 51, 73: three `sys.path` insertions that do nothing, because every import
  after them is an absolute `uai_toolkit.*` import. `tools/manifest.py:240` classifies
  this file as a clean mechanical copy, which these contradict.
- Line 174: `IMAGE_EXTENSIONS` — defined, never used, anywhere in the repository.
- Lines 872 and 936: `HELP_TEXT` points users at `chain_skip.py offload`. No such file
  exists in this package. `jsonl/README.md` names two other non-existent files for the
  same job. Pick the real one and use its real name in all three places.
- Lines 10-14: the docstring's usage block and exit codes are partly wrong.

### 12. Move the REPL history file under `AI_ROOT`

`HISTORY_FILE = Path.home() / ".scrub_files_history"` (41) drops a dotfile in the
user's home directory. `DESIGN.md` decisions 1 and 4 put all writable state under
`AI_ROOT`, and `paths.py` already resolves it. Small, but it is exactly the kind of
thing a port is the right moment to fix.

---

## Add tests

Nothing under `tests/` touches this module — `tests/smoke_test.py:49` imports
`read_jsonl`, `catjsonl`, and `discovery`, not `scrub_files`. Recommendations 4, 5,
and 6 are all one small fixture transcript away from being caught automatically:

- scrubbing a large text `tool_result` actually shrinks the file
- `--max-px 1200` scrubs an image that `--max-px 4000` leaves alone
- an unknown option is an error, not a silent no-op
- `scrub --type all` behaves like `list --type all`
- a concurrent append during `scrub` is detected and refused, not clobbered
- file mode and ownership survive a scrub
- `rehydrate` after `offload` restores the transcript byte-for-byte
- the module imports successfully with `readline` unavailable
