# summarizer.py — recommendations

Companion to `summarizer_design.md`.

## 1. Defect — `SHADOW_LOG` writes into the installed package. Fix before shipping.

```python
SHADOW_LOG = Path(__file__).resolve().parents[2] / "data" / "summarizer_shadow" / "comparisons.jsonl"   # :62
```

In the live source tree (`ai_general/scripts/jsonl/summarizer.py`) `parents[2]` is
`ai_general/` and the log lands where the docstring (`:236-238`) and the shipped how-to
both promise. In the package (`src/uai_toolkit/jsonl/summarizer.py`) `parents[2]` is
`src/`, so it resolves to `<install-root>/data/summarizer_shadow/comparisons.jsonl` —
**inside the read-only package**. Verified by resolution, 2026-08-01.

Consequences:
- Violates `DESIGN.md` decision 1 (package read-only and upgradeable; the writable
  instance is `AI_ROOT`). The log is destroyed on every upgrade.
- On a `pipx` install into read-only site-packages, `os.makedirs` (`:142`) fails, the
  failure is swallowed by `shadow_summarize`'s bare `except` (`:174`), and **the A/B log
  silently never exists** — losing exactly the data the shadow design was built to
  collect.
- The log contains verbatim conversation summaries and transcript paths. `DESIGN.md`
  decision 6 makes personal data a hard gate for public promotion; this is personal data
  landing in a package-relative directory.

**Fix.** Resolve under `AI_ROOT`, e.g. `AI_ROOT / "data" / "summarizer_shadow" /
"comparisons.jsonl"`, via `uai_toolkit.paths`. Make the path a parameter with that
default so tests and callers can redirect it (`log_comparison` and `shadow_summarize`
already accept `log_path`; only the default is wrong). This is the same class of defect as
`deferred_self_compact.py:34-41` — a source-tree-relative constant that survived
materialization unchanged. **Audit every `parents[N]` in the package for the same
mistake.**

## 2. Preserve the "no endpoint = feature off" contract explicitly

The packaged copy is `kind: "curated"` (`tools/manifest.py:243-245`) precisely because it
replaced a non-vendored `scripts/lllm` import with the shared per-feature client. That is
the intended direction — `DEPENDENCIES.md:79` flags `lllm_prompt` as "not vendored, not a
pip pkg". **Do not regress to a direct local-model import when porting.**

Write the contract down as a test rather than a comment, because it is easy to break by
accident:

- `is_configured("consolidation_summary")` false ⇒ `summarize_via_local_llm` returns
  `{"ok": False, …}` and performs **no network call**.
- Any exception inside the client ⇒ still `{"ok": False, …}`, never propagated.
- `shadow_summarize` returns the caller's summary **unchanged** in all of the above.
- With no config file at all, importing and calling this module makes zero outbound
  connections.

The one legitimate inversion is `reclaim_and_stage.py:294-298`, where the user asked for
`--summarizer local-llm` and an `ok=False` correctly becomes a hard error. Keep that
asymmetry and keep it at the call site, not in this module.

## 3. Break the dependency on `lib_engram` internals

`extract_turn_range` (`:96-108`) uses three private functions: `lib_engram._load`,
`lib_engram._chain_records`, `lib_engram._is_human_prompt`. Two problems follow.

- **Fragility.** `lib_engram`'s writer is retired upstream; when this package follows, the
  three helpers move or vanish and this file breaks with them.
- **Inherited bug.** `_is_human_prompt` is the *diverged* turn predicate (see
  `lib_engram_design.md` §6.2), so `extract_turn_range` inherits the over-counting — it can
  select a range starting at something that is not a real prompt.

**Fix.** Depend on public chain primitives (`active_chain` / a shared `chain_records`) and
on `lib_jsonl_archive.is_turn_start`. This lands naturally if the chain primitives are
split out of `lib_engram` as recommended in `lib_engram_design_recs.md` rec 6.

## 4. Give `SUMMARY_INSTRUCTION` a length budget

Under the retired mechanism the summary replaced a record's content and its length barely
mattered. Under the upstream mechanism (`chain_skip.summarize_turn`) the summary is
spliced back onto the chain as a live user+assistant **residue pair**, so
`net reclaim = removed-turn contribution − residue contribution`
(`FINDING_wholeturn_calibration.md`, 2026-07-30). **A verbose summary directly reduces the
reclaim it was written to enable.**

`SUMMARY_INSTRUCTION` (`:34-59`) currently says "Be compressed but complete — favor
density" and nothing more. Add an explicit budget — a character or token target, ideally
derived from the range size — and record the target in the comparison log next to
`claude_chars` / `lllm_chars` so the A/B analysis can measure adherence. A residue gate is
already being designed upstream; this module should supply the number it gates on.

## 5. Decide the shadow experiment's end state

The shadow apparatus exists to answer one question, asked 2026-06-23 (`:5-7`): *would the
configured model have been good enough, and would an instruction tweak help?* Every real
run appends a comparison record. Nothing in the package analyses them, and (per rec 1) in a
packaged install nothing is even written.

**Recommendation.** Either commit to the experiment — fix the path, add a small analysis
step, and set a criterion for deciding — or retire it. A permanent A/B harness that nobody
reads is pure overhead on every consolidation: an extra full range extraction (`:153`, the
caller already extracted it at `reclaim_and_stage.py:83`), an extra model call, and a log
of conversation content with no rotation, no size bound and no scrub.

If it stays, add rotation and a size bound to the log, and decide deliberately whether it
should store the summaries verbatim or only their hashes and lengths.

## 6. Smaller items

- **Stop re-extracting the range.** `shadow_summarize` (`:153`) re-runs
  `extract_turn_range` on data the caller already has. Accept an optional pre-extracted
  range.
- **Make the truncation limits parameters.** Tool payloads are cut at 2,000 characters
  before the summarizer sees them (`:84`, `:87`). That is a real information boundary — a
  range that was not offloaded first loses its tool detail into a gist. At minimum record
  in the comparison log that truncation occurred, and how much was dropped.
- **Rename `summarize_via_local_llm`.** The docstring already admits the name is
  historical (`:119-120`) and the endpoint may be local, hosted, or absent.
  `summarize_via_configured_model` describes it. Keep an alias for one release.
- **Either honour the third CLI argument or drop it.** `leaf_uuid` is documented in the
  usage text (`:206`) and ignored by `__main__` (`:249`).
- **Replace `__import__("hashlib")`** (`:170`) with a module-level import.
- **`run_local_llm=False` records `lllm_error: "skipped"`** (`:154`). Use a distinct field
  so analysis can separate "not attempted" from "attempted and failed".
