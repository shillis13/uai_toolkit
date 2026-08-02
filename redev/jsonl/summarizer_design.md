# summarizer.py — redevelopment design

**File:** `src/uai_toolkit/jsonl/summarizer.py` (253 lines; library + a demo CLI)
**Read at:** 2026-08-01. **This file is `kind: "curated"` in the materialize manifest**
(`tools/manifest.py:243-245`) — the packaged copy deliberately differs from the live
source. That difference is the whole point of this document; see §3 and §10.

## Terms used here

- **Turn-range** — one human prompt and everything up to (not including) the next human
  prompt, taken along the active chain.
- **Shadow mode** — run two candidate summarizers, use one, log both for later comparison.
- **Feature endpoint** — a named entry in the toolkit's LLM configuration; each toolkit
  feature that can use a language model is configured independently.
- **Subagent** — a separate agent the live session spawns; it has its own context window.

## 1. What it is for

`summarizer.py` writes the **summary text** for one turn-range — the note that will
replace those turns on the active chain when `lib_engram.consolidate` runs. It does three
things: extract a turn-range's text from the transcript (`extract_turn_range`), produce a
candidate summary from a configured model (`summarize_via_local_llm`), and run the
"shadow" A/B step that logs both candidates and returns the one to actually use
(`shadow_summarize`). It holds the canonical summary instruction (`SUMMARY_INSTRUCTION`).

It **never touches the transcript.** It reads it and returns text.

## 2. Where this sits on the reclaim ladder

The ladder is offload < bounce < **summarize** < self-compact < compact; full description
in `lib_engram_design.md` §2. This file is the *authoring* half of the Summarize rung —
`lib_engram` is the *disk* half. The module's own usage text says exactly this
(`:184-186`) and correctly describes Summarize as "LOSSY-but-REVERSIBLE".

The rung's division of labour is unusual and must be understood before re-designing it:

> **Pure Python cannot spawn a Claude subagent.** The high-quality summary comes from an
> agent the *live orchestrating session* spawns; this module cannot produce it. So the
> flow is inverted: the session spawns the subagent, gets the text, and **passes it in**
> to `shadow_summarize`, which returns it back (having logged the comparison).

The documented procedure (`:16-21`):
1. pick `first_uuid` — the oldest consolidatable turn, never the live tail;
2. `rng = extract_turn_range(jsonl, first_uuid)`;
3. `claude_summary = <session spawns a subagent that reads the range and applies
   SUMMARY_INSTRUCTION>`;
4. `used = shadow_summarize(jsonl, first_uuid, claude_summary)` — runs the model path,
   logs both, returns the agent's;
5. `lib_engram.consolidate(jsonl, first_uuid, used)`.

## 3. The configured-model path — **the contract a replacement must not break**

`summarize_via_local_llm` (`:113-136`) routes through the shared per-feature client:

```python
from uai_toolkit.llm import complete_with_endpoint, is_configured
if not is_configured("consolidation_summary"):
    return {"ok": False, "summary": "", "model": "",
            "error": "no endpoint configured for feature 'consolidation_summary'"}
```

The feature name is `"consolidation_summary"`, declared in `uai_toolkit/llm/client.py:59`
alongside `quality_gate`, `intent_check`, `session_assess`, `session_summarize`,
`mcp_prompt`. The client's security posture (`llm/client.py:12-18`) is explicit: **no
endpoint is built in, no default host, no assumed local port, no endpoint synthesized from
an ambient API key; `base_url` is required; credentials are named by environment-variable
name (`api_key_env`), never stored in config.** Configuration is located, first match wins,
at `$AI_LLM_ENDPOINTS_CONSOLIDATION_SUMMARY` → `$AI_LLM_ENDPOINTS` →
`$AI_ROOT/config/llm_endpoints.json`.

**Unconfigured is the default and is not an error.** The function returns
`{"ok": False, error: "no endpoint configured…"}` and the caller carries on. There are
three layers of this and all three must survive a re-design:

1. `is_configured` short-circuits before any network attempt (`:123`).
2. Any exception from `complete_with_endpoint` is caught and converted to an `ok=False`
   dict (`:130-131`) — the comment calls this "defensive: complete() shouldn't raise".
3. A configured-but-unproductive chain (every endpoint failed) also returns `ok=False`
   (`:132-134`), not an exception.

And at the caller level, `shadow_summarize` wraps the logging in a bare
`try/except: pass` (`:172-175`) with the comment *"shadow logging must never block the
real consolidation"*.

**Restated as the requirement:** *no endpoint configured ⇒ the feature is simply off.*
Not a warning, not a retry, not a fallback to some built-in host, and never a hard
failure that stops a reclaim. The one place this posture is deliberately inverted is
`session_bounce/reclaim_and_stage.py:294-298`, where `--summarizer local-llm` is the
*only* summary source and an `ok=False` is correctly promoted to a `RuntimeError` — that
is a user asking explicitly for the model path, not the default.

## 4. Interface

```
summarizer.py <jsonl> <first_uuid> [leaf_uuid]     # DEMO only
summarizer.py -h | --help
```

The CLI (`:243-253`) is a **probe**: it extracts the range, prints range statistics, and
prints the configured shadow candidate as JSON, truncated to 1,500 characters (`:251`).
It writes nothing and consolidates nothing. Exit code is 0 for `--help`; otherwise it
propagates whatever the library raises. Note the third positional `leaf_uuid` is
documented in the usage text (`:206`, `:215-216`) but **the `__main__` block ignores it**
(`:249` passes only `argv[1]`, `argv[2]`) — the usage text admits this at `:216` ("the
demo path uses `<jsonl> <first_uuid>` only"), so it is documented-but-confusing rather
than wrong.

Library API:

| Symbol | Signature | Notes |
|---|---|---|
| `SUMMARY_INSTRUCTION` (`:34`) | `str` | The canonical instruction, ~2 KB. Identical for both paths *by design*, so the comparison is apples-to-apples (`:33`). |
| `extract_turn_range` (`:92`) | `(jsonl_path, first_uuid, leaf_uuid=None) -> {text, records, turns, content_chars}` | Raises `ValueError` if `first_uuid` is not on the active chain or is not a human-turn start (`:100`, `:103`). |
| `summarize_via_local_llm` (`:113`) | `(range_text, instruction=SUMMARY_INSTRUCTION) -> {ok, summary, model, error}` | Never raises. `max_tokens=1000` hard-coded (`:128`). |
| `log_comparison` (`:139`) | `(entry, log_path=SHADOW_LOG) -> Path` | Appends one JSONL record; creates the parent directory. |
| `shadow_summarize` (`:148`) | `(jsonl_path, first_uuid, claude_summary, *, leaf_uuid, run_local_llm=True, log_path, ts) -> str` | **Returns the `claude_summary` argument unchanged.** Its only side effect is the log line. |
| `SHADOW_LOG` (`:62`) | `Path` | See §6 — **this path is wrong in the packaged copy.** |

The function name `summarize_via_local_llm` is historical; its docstring says so
(`:119-120`, "Kept under the historical name so existing callers need no change"). It no
longer implies a local model — the endpoint may be local or hosted or absent.

## 5. Integration

**Callers**
- `session_bounce/reclaim_and_stage.py:51` imports it as `SM` and uses
  `extract_turn_range` (`:83`, `:206`), `shadow_summarize` (`:92`), and
  `summarize_via_local_llm` (`:296`).
- Through that, the MCP tools `context_summarize_plan` / `context_summarize_enact`
  (`mcp/sessions/tools/context_ops.py`) — but note those shell out to
  `$AI_ROOT/ai_general/scripts/…`, not to the installed package.
- `content/ai_context_files/instructions/how_tos/instr_context_reclaim.md` names
  `SUMMARY_INSTRUCTION` as the canonical machine instruction for humans and agents alike.

**What it calls**
- `lib_engram` (`:31`) — for `_load`, `_chain_records`, `_is_human_prompt`. All three are
  **private names**; this is a tight coupling to `lib_engram`'s internals, not to its
  public API.
- `uai_toolkit.llm` (`:121`), imported lazily inside the function.

## 6. Data & config

| Artifact | Path | R/W | Notes |
|---|---|---|---|
| Transcript | caller-supplied | **read only** | via `lib_engram._load` |
| Shadow comparison log | `SHADOW_LOG` (`:62`) | append (`:143`) | JSONL, one record per shadow run |
| LLM endpoint config | `$AI_LLM_ENDPOINTS_CONSOLIDATION_SUMMARY`, `$AI_LLM_ENDPOINTS`, or `$AI_ROOT/config/llm_endpoints.json` | read (by `uai_toolkit.llm`) | absent = feature off |
| API credentials | environment variable named by `api_key_env` in the endpoint config | read | never stored in config |

### The `SHADOW_LOG` path is a port defect

```python
SHADOW_LOG = Path(__file__).resolve().parents[2] / "data" / "summarizer_shadow" / "comparisons.jsonl"
```

In the live source tree the file is `ai_general/scripts/jsonl/summarizer.py`, so
`parents[2]` is `ai_general/` and the log lands at
`ai_general/data/summarizer_shadow/comparisons.jsonl` — which is what the docstring
(`:236-238`) and the shipped how-to both promise, and which exists on this machine.

In the package the file is `src/uai_toolkit/jsonl/summarizer.py`, so `parents[2]` is
`src/` and the log resolves to **`<install-root>/data/summarizer_shadow/comparisons.jsonl`
— inside the installed package**. Verified by resolution, 2026-08-01.

That violates `DESIGN.md` decision 1 ("Package is read-only and upgradeable; the writable
instance (`AI_ROOT`) is separate and durable"). On a `pipx` install into a read-only
site-packages the `os.makedirs` at `:142` fails; the failure is swallowed by
`shadow_summarize`'s bare `except` (`:174`), so **the A/B log silently never gets
written** — which is exactly the data this whole shadow design exists to collect. A
recommendation is filed separately.

## 7. How it works

**`extract_turn_range` (`:92-110`)** mirrors `consolidate`'s selection so the text handed
to the summarizer is exactly the text that will be archived. It loads the transcript via
`lib_engram._load`, walks the active chain (`lib_engram._chain_records`, honoring an
explicit `leaf_uuid` for forked transcripts), verifies `first_uuid` is on the chain and is
a human-turn start, finds the next human prompt, and renders `chain[ci:nexti]`.

**`_content_text` (`:65-89`)** renders one record: `### <role>` followed by the text of
each block. `thinking` blocks are prefixed `[thinking]`; `tool_use` becomes
`[tool_use <name>] <json>` truncated to 2,000 characters; `tool_result` becomes
`[tool_result] <text>`, also truncated to 2,000 characters when non-string. So **the
summarizer sees a truncated view of tool traffic** — deliberate (a summary of a 300 KB
tool result should not require reading 300 KB) but it means the summary cannot faithfully
carry details buried past 2,000 characters of a tool payload. Anything load-bearing in a
long tool result is not in the summary and, once the range is consolidated, is only
reachable by Recall or Restore.

**`SUMMARY_INSTRUCTION` (`:34-59`)** is the most opinionated artifact in this package and
is treated as a contract elsewhere. Its requirements: first-person singular throughout; a
note from the model to its future self that will *replace* those turns; never third
person about itself, never narrating the human as an outsider; not a compaction-style
report or meeting minutes; keep the texture of the reasoning and open questions; preserve
decisions **and their reasoning**, concrete paths/identifiers/numbers/commands, open
threads, and any load-bearing fact a later turn would rely on; be dense; do not
invent or embellish. Its hash is logged with every comparison (`:170`) so a later analysis
can tell which instruction produced which output.

**`shadow_summarize` (`:148-176`)** extracts the range, optionally runs the configured
model path, builds a comparison record (timestamp, transcript path, `first_uuid`, range
turns/records/chars, `used: "claude"`, both summaries and their lengths, the model name,
the model-path error, and the instruction hash), logs it inside a `try/except: pass`, and
**returns the `claude_summary` argument unchanged**. The model output is never used.

## 8. Essential vs incidental

### Essential

- **"No endpoint = feature off, never a hard failure."** All three layers of §3.
- **Per-feature configuration** — this feature's endpoint is independent of every other
  feature's, and a site may enable some and not others.
- **The range extracted for summarizing must be identical to the range that will be
  archived.** Any drift means the summary describes turns that are not the turns removed.
- **First-person, replaces-my-own-turns voice.** This is a product decision with a stated
  rationale, and it is referenced by the shipped instructions. Keep it, keep it in one
  place, and keep hashing it into the log.
- **The agent-supplied summary is authoritative; the model path is a shadow.** A
  replacement must not quietly promote the model output to the used summary.
- **Logging must never block the summary being returned.**
- **`extract_turn_range` refuses a `first_uuid` that is not a human-turn start on the
  active chain** rather than silently summarizing a partial range.
- **The `leaf_uuid` parameter** — on a forked transcript the default leaf may be the wrong
  branch entirely.

### Incidental

- The name `summarize_via_local_llm` and the docstring's "local LLLM" phrasing.
- `max_tokens=1000` (`:128`), the 2,000-character block truncations (`:84`, `:87`), and
  the 1,500-character CLI print truncation (`:251`).
- The `### <role>` rendering format.
- The comparison record's field names and the JSONL log format.
- The demo CLI itself, and its unused third positional argument.
- `__import__("hashlib")` inline at `:170` — an odd inline import, no consequence.
- The `SHADOW_LOG` **location** (the mechanism of writing a comparison log is essential
  while the shadow experiment runs; the path is a bug, see §6).
- The entire shadow apparatus, **once the A/B question is answered.** It exists to answer
  "would the configured model have been good enough?" (`:5-7`, PianoMan 2026-06-23). When
  that is decided, this becomes either a single-path summarizer or nothing.

## 9. Platform notes (Tier A / B / C per `DESIGN.md`)

- **Tier A.** The only file I/O is the log append, already `encoding="utf-8"` (`:143`).
- **Tier A.** `os.makedirs(..., exist_ok=True)` (`:142`) — fine everywhere; the problem is
  *where*, not *how* (§6).
- **Tier A.** `datetime.now().isoformat(timespec="seconds")` (`:157`) is local time with
  no zone offset, matching workspace convention; log records from different machines are
  not directly comparable.
- **Tier C-adjacent.** The model path is a network call. It is already a graceful-degrade
  capability: unconfigured means off, and a firewalled or offline machine gets `ok=False`
  with an error string. This is the pattern the rest of the toolkit should copy.
- No processes, no signals, no terminals, no locking, no path separators of consequence.
- **WSL/Windows:** nothing here is OS-divergent once `SHADOW_LOG` is relocated under
  `AI_ROOT`.

## 10. Risks & sharp edges

1. **`SHADOW_LOG` writes into the package (§6)** and the failure is silent.
2. **Tight coupling to `lib_engram` privates** (`_load`, `_chain_records`,
   `_is_human_prompt`, `:96-108`). Since `lib_engram`'s writer is retired upstream (§11),
   these three helpers must be re-homed or this file breaks with it. Note also that
   `_is_human_prompt` is the *diverged* predicate — see `lib_engram_design.md` §6.2 — so
   `extract_turn_range` inherits the same turn-boundary bug.
3. **Tool payloads are truncated at 2,000 characters** before the summarizer ever sees
   them (§7). Combined with the ladder's ordering rule (offload before summarize), this is
   usually harmless — but a range that was *not* offloaded first loses its tool detail into
   a gist.
4. **`shadow_summarize` re-extracts the range** (`:153`) that the caller already extracted
   (`reclaim_and_stage.py:83`), so every enacted range is parsed and rendered twice.
5. **The comparison log holds full transcript excerpts** — both summaries verbatim, plus
   the transcript path. It is conversation content in a side file with no rotation, no
   size bound and no scrub. `DESIGN.md` decision 6 makes personal data a hard gate for
   public promotion; this log is exactly that kind of data and it currently lands in a
   package-relative directory.
6. **The docstring's PROCEDURE is the only specification of the orchestration.** Nothing
   enforces steps 1–5; a caller that skips step 4 gets a consolidation with no A/B record,
   and a caller that skips step 3 has no summary at all.
7. **`run_local_llm=False`** produces a record with `lllm_error: "skipped"` (`:154`), which
   an analysis pass must distinguish from a genuine failure.

## 11. Work in flight — **do not read this file as settled design**

Active work lives in `ai_root/ai_general/work/experiments/t2_context_agency/`.

1. **The packaged copy and the live source have diverged deliberately, in both
   directions.**
   - *The package is newer on the model-client axis.* `tools/manifest.py:243-244` records:
     "curated 2026-07-27: the shadow path uses the independently configured
     `consolidation_summary` client instead of a non-vendored `scripts/lllm` import." The
     live source still calls `lllm_prompt.prompt_text(...)` directly, and
     `DEPENDENCIES.md:79` flags `lllm_prompt` as "not vendored, not a pip pkg — vendor it
     or guard the import". **The package's per-feature-endpoint design is the intended
     direction; do not regress to it.**
   - *The package is older on the mechanism axis.* The live source docstring now reads
     "The Stage-2 author for `chain_skip.summarize_turn`" — not
     `lib_engram.consolidate`. See below.
2. **`lib_engram.consolidate` is retired upstream** (todo_0692, cutover 2026-07-27); it
   raises `NotImplementedError`. Summarize now goes through `chain_skip.summarize_turn`,
   which reclaims by pure `parentUuid` re-pointing and **splices an on-chain
   user+assistant "residue pair" carrying the summary** instead of overwriting a record's
   content. A re-designer must decide which mechanism this file authors for before
   porting it.
3. **The residue changes the arithmetic.** `FINDING_wholeturn_calibration.md` (2026-07-30,
   reviewed REQUEST_CHANGES): net reclaim is `removed-turn contribution − residue-pair
   contribution`, and the measurement in hand covers only the first term. A
   **summarize-residue gate** is under design. Practical consequence for this file: the
   *length* of the summary is no longer free — a verbose summary directly reduces net
   reclaim, which argues for a length budget in `SUMMARY_INSTRUCTION` that does not exist
   today.
4. **Automatic authorization is withdrawn.** `PLAN_EVICTION_RANGE_REVIEW.md` (2026-07-30):
   projected reclaim cannot authorize an automatic bounce; the only licensed universal
   lower bound on realized reclaim is zero. Summarize/Offload as *operator-requested*
   actions are unaffected.
5. **`FINDING_gate_notice_mismatch.md`:** the awareness notice fires at 60% context while
   the planner's pressure gate is 75%, so a session is told to summarize and then refused.
   Affects the caller (`resume_note.should_bounce`), not this file, but it is the reason
   summarize requests were observed failing in the T2 run.
