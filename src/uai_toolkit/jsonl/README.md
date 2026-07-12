# jsonl

Unix pipeline tools for reading, searching, and compacting AI session JSONL files (Claude, Codex, Gemini). The core parser (`read_jsonl.py`) is the single canonical entry point for all JSONL session access; the `j-tools` suite wraps it in a busybox-style CLI.

## Scripts

### read_jsonl.py
The canonical parser for all CLI session JSONL files across Claude, Codex, and Gemini. Handles platform auto-detection, message type classification (USER, SKILL, AGENT_RESULT, INJECTED), and colored display formatting. Provides both a CLI (`read`, `list`, `find`, `summary` subcommands) and an importable library used by `catjsonl.py`, `compact_jsonl.py`, and the MCP layer.

It also **resolves `offload_tool_results.py` stubs on the fly**: `read`/`read-file --resolve` rehydrates a stub's body from its co-located archive for display (off by default, so `summary`/stats keep reflecting the lean on-disk transcript). The library entry point is `resolve_archived_stubs(messages, jsonl_path)`.

**Usage:**
```
read_jsonl.py                          # Interactive REPL
read_jsonl.py read <uuid> [--format json|text|markdown] [--resolve]
read_jsonl.py read-file <path> [--resolve]
read_jsonl.py list [project_dir]
read_jsonl.py find <uuid>
read_jsonl.py summary <uuid>
```

### catjsonl.py
Busybox-style multi-tool: behavior is determined by `argv[0]` via symlinks. Implements six pipeline tools (`jcat`, `jgrep`, `jhead`, `jtail`, `jwc`, `jfmt`) that read structured messages from JSONL files and either render them for humans (TTY) or emit one JSON object per line for pipes.

- `jcat` — emit all messages (like `cat`)
- `jgrep` — filter by regex pattern with line-level context highlighting, `--invert`, `-c` count mode, `-n` location prefix, `--pager`
- `jhead` / `jtail` — first/last N messages
- `jwc` — count messages, optionally by type or role
- `jfmt` — render structured pipe-format JSON as colored human output

All tools support `--type`, `--role`, `--since`, `--before`, `--sort`, `-r` (recursive), and `--platform` flags.

**Usage:**
```
jcat <uuid|file>                         # render session
jcat <uuid> --json | jgrep "error" | jfmt
jgrep -r "pattern" ~/.claude/projects/  # search all sessions
jwc --by-type <uuid>
jhead -n 5 <uuid> --type response
```

### compact_jsonl.py
First-pass deterministic compaction of a structured session. Does not call any AI model — pure rule-based reduction. Drops tool results, summarizes large tool parameters, trims long text, merges adjacent `tool_use`/`tool_result` pairs, and silently drops `[/PRIVATE]` thinking blocks. Output is structured JSON suitable for AI second-pass condensation.

**Usage:**
```
read_jsonl.py read <uuid> --format structured | compact_jsonl.py
compact_jsonl.py --uuid <uuid> [--stats]
compact_jsonl.py --file session.jsonl --max-tool-param 200 --max-text 5000
```

### condense.py
Condensation pipeline: compact one or more sessions, optionally merge them by timestamp, write a prepared JSON to a temp file, then deliver the condensation task to a designated AI session. The condenser AI reads the prepared input and writes a structured YAML session brief to `ai_general/data/session_briefs/`. Manual trigger only.

**Usage:**
```
condense.py --src-uuid a4bb0a3b --condenser <session_ref>
condense.py --src-uuid a4bb0a3b --src-uuid 7edf3339 --condenser <session_ref>
condense.py --src-uuid a4bb0a3b --dry-run
condense.py --src-uuid a4bb0a3b --prepare-only --output merged.json
```

### scrub_files.py
Resume-safe in-place JSONL rewriter for **file attachments** (oversized images, PDFs, large text blobs). Scans a transcript, lists attachments, and replaces selected ones with text placeholders while preserving conversation structure. Provides the shared write machinery (`find_jsonl`, `_ensure_backup`, `_atomic_write`) reused by `offload_tool_results.py`. Has a one-shot CLI and an interactive REPL. `scrub_large_images.py` is a back-compat symlink to it.

**Resume-safe archive-and-stub of embeds** (the reversible successor to strip-scrubbing): `offload`/`rehydrate` subcommands page embedded **images** out to the same portable per-session archive the offloader uses (manifest `kind:"embed"`), leaving a `[embed archived: image WxH … → ref …]` stub — recency-window protected (won't strip a current-turn screenshot), CAS-guarded, fully reversible. Engine-backed by `lib_jsonl_archive.py`. (Legacy `scrub`/`list` still strip to a bare placeholder with whole-file `.bak` recovery; prefer `offload` for reversibility.)

**Usage:**
```
scrub_files.py <uuid> list --type images
scrub_files.py <uuid> scrub --all --type pdf      # legacy destructive strip
scrub_files.py <uuid> offload [--keep-last-turns N] [--min-bytes N] [--dry-run]   # archive-and-stub (reversible)
scrub_files.py <uuid> rehydrate                    # restore offloaded embeds
scrub_files.py <uuid> backup | restore
```

### offload_tool_results.py
Resume-safe **context paging** for a session transcript. Extracts the bulk of aged tool messages — `tool_result.content` and large `tool_use.input` payloads — into a referenceable archive and replaces them *in place* with a short stub that points at the full record. Implements §6b ("resume-safe JSONL edit") of the usage-efficiency design. Reuses `scrub_files.py` for atomic write-back and `compact_jsonl.py`'s param/result summarizers for the stub one-liners. Turn classification goes through `read_jsonl.parse_session` (canonical parser) so only genuine human turns count toward the protected window.

**What it is / is NOT:**
- **Safe to run on a live session** — Claude Code holds no open fd on the transcript (open-append-close per write), so an atomic temp+rename can't corrupt or race it; new messages still append correctly.
- **It does NOT shrink the running session's context.** A live process sends its in-memory message list, not the JSONL. The edit is inert until the next `--resume` rebuilds the conversation from the (now lean) file. Payoff = a leaner next-resume: cheaper warm turns, smaller next cold read, deferred compaction. (To shrink live in-session context, the only lever is `/compact`.)

**Where the extracted content goes** (portable, fork-safe two-part scheme): a sibling archive folder next to the transcript, named by **both** the sessionId (transcript stem = cli_uuid) **and** a once-minted **uuid8**, so sessions sharing a project dir never collide —
```
<transcript_dir>/<cli_uuid>.<uuid8>.archive/    # e.g. ~/.claude/projects/<proj>/004c…f0.67ffa699.archive/
├─ <tool_use_id>.result.txt               # readable body the stub points to (fault-in target)
├─ <tool_use_id>.input.<key>.txt          # offloaded large tool_use input(s) (e.g. Write content)
├─ <tool_use_id>.<field>.json             # exact copy when the body was not a plain string (lossless)
└─ offload_manifest.jsonl                 # one record per offloaded block; drives --rehydrate
```
The stub embeds **only the portable ref** `<uuid8>/<tool_use_id>.<field>.txt` — never an absolute path — resolved against the *current* transcript's dir + cli_uuid. So a **fork** (copy the transcript + copy the archive, rename its cli_uuid prefix, keep the uuid8) resolves to **its own** copy, not the parent's. Re-runs reuse the existing uuid8. `--archive-dir <path>` overrides the parent dir.

**The stub left behind** (what the model sees on next resume):
```
[archived: Bash(command: [289 chars] | description: …) · 3,286 chars (~822 tok) · bf02e91c
 → ref 67ffa699/<id>.result.txt (resolve via read_jsonl) if needed; do NOT reconstruct from memory]
```
Tool + intent + size + content hash + portable fault-in ref + an explicit anti-confabulation guard.

**Safety guarantees:**
- Never deletes a `tool_use`/`tool_result` block and never alters `id`/`tool_use_id`/`type`/`is_error` — orphaning a pair or changing an id would 400 the API on resume. Only the `content`/`input` field is rewritten.
- Protects the working set: the last N human turns (`--keep-last-turns`, default 5) are left fully verbatim.
- **Compare-and-swap write guard:** captures the transcript's (mtime, size) around the read and refuses to write if it changed underneath — so running against a *live* session can't clobber a message appended mid-run (a raced round is a no-op; a frequent caller catches it next pass). Note a microsecond TOCTOU residue between the final stat and `os.replace` remains; prefer quiescent moments for absolute certainty.
- Atomic write (temp + `os.replace`) with a one-time `.jsonl.bak`; untouched lines stay byte-identical.
- Fully reversible: `--rehydrate` restores exact original content from the archive (verified lossless across all tool_results, including across a fork).
- Idempotent: re-running skips already-stubbed blocks and reuses the existing archive.

**Flags:** `--keep-last-turns N` (default 5) · `--min-bytes N` (default 2048; only page out bodies at least this big) · `--mode archive|strip` (default archive = reversible; strip = discard) · `--pin <tool_use_id,…>` (never touch) · `--no-stub-inputs` (leave `tool_use.input` alone) · `--archive-dir <path>` · `--dry-run` · `--rehydrate` · `--json`.

**Usage:**
```
offload_tool_results.py <uuid> --dry-run                       # report reclaimable mass, no writes
offload_tool_results.py <uuid>                                 # archive + stub (defaults)
offload_tool_results.py <uuid> --keep-last-turns 5 --min-bytes 4096
offload_tool_results.py <uuid> --mode strip                    # discard instead of archiving
offload_tool_results.py <uuid> --pin toolu_abc,toolu_def       # protect specific results
offload_tool_results.py <uuid> --rehydrate                     # restore everything in place
```
The disk edit takes effect on the session's **next `--resume`**; running it does not resume the session (that's the caller's / a watcher's job).

### lib_jsonl_archive.py
The shared **archive-and-stub engine** behind embed offloading and (next) tool-content offloading: portable fork-safe `Archive` (`<stem>.<uuid8>.archive`), CAS write guard, recency-window protection (`protect_from_index`), sizing/rendering helpers, byte-identical-untouched-lines `commit`, and a **kind-aware `rehydrate`** that restores tool results, tool inputs, and embeds from one manifest (`offload_manifest.jsonl`, records tagged `kind`). `scrub_files.offload_embeds` and `offload_session.py` use it; `offload_tool_results.py` carries an equivalent in-file copy pending migration onto this lib.

### offload_session.py
One re-runnable invocation that offloads **both** tool content (via `offload_tool_results`) **and** embedded images (via `scrub_files.offload_embeds`) into the **same** archive, so a single stop+resume sheds everything and one `--rehydrate` restores it all. Idempotent — safe to run every cold/quiescent cycle.

**Usage:**
```
offload_session.py <uuid> --dry-run
offload_session.py <uuid> [--keep-last-turns N] [--min-bytes N] [--mode archive|strip]
offload_session.py <uuid> --rehydrate          # restore tool content + embeds
```

### jcat, jgrep, jhead, jtail, jwc, jfmt
These are symlinks to `catjsonl.py`. Each activates a different mode of the multi-tool.

## Dependencies

- `read_jsonl.py` — internal; all other tools import from it (incl. `offload_tool_results.py` for turn classification)
- `scrub_files.py` — internal; `offload_tool_results.py` imports its `find_jsonl` / `_ensure_backup` / `_atomic_write`
- `compact_jsonl.py` — internal; `offload_tool_results.py` imports its `compact_tool_input` / `_result_summary` / param-key sets
- `~/bin/ai/utils/standard_colors` — shared ANSI color handling
- `~/bin/all_languages/python/src/file_utils/fsFind`, `fsFilters` — recursive file discovery for `-r` mode
- `session_store.py`, `session_ops.py` (in `ai_general/scripts/session_mgmt/`) — used by `condense.py` for session resolution and delivery
- `yaml` — `condense.py` brief metadata

## Notes

- `DESIGN.md` in this directory governs key invariants: `read_jsonl.py` is the sole parser, private thinking blocks are filtered by default, `compact_jsonl.py` is rule-only (no AI calls).
- `offload_tool_results.py` vs `compact_jsonl.py`: offload edits a transcript **in place** and stays **resume-valid for the same session** (id-paired blocks preserved); compact **merges** pairs into synthetic blocks for a *successor* session handoff (not resume-valid for the original). Different jobs.
- `offload_tool_results.py` only pays off at the next `--resume` (the on-disk edit is inert on a running process). Best run when a session is cold + quiescent + heavy; a fleet watcher that cycles such sessions is a planned follow-on (Tier-1 LLLM gisting + the watcher are not yet built).
- The `jgrep --pager` flag pipes through `less -RX` for color-preserving paged output. Override with `JGREP_PAGER` env var.
- `condense.py` writes the prepared input to `/tmp/condense_pipeline/` — the condenser AI must be able to read that path.
