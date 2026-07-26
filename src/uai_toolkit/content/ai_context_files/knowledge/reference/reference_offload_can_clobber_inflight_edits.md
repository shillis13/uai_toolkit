---
name: reference_offload_can_clobber_inflight_edits
description: context_offload can race in-flight Edits and write archive-stub text
  to disk
status: active
---

After a `context_offload` (esp. `dry_run=false` with **no bounce**, on a resumed session), Edit tool calls whose `new_string` is large can be written to disk as the **offload archive STUB** instead of the real content — literally a line like `[input archived: Edit(new_string) · N chars … → ref offload.<id>/…]`. Observed 2026-07-14: two edits (a ContextTab.tsx component + a styles.css rule) landed as stubs, clobbering the surrounding real code (the `export default function` signature line, a CSS rule opener).

**Why:** the offload archives tool-input payloads to a sidecar; an Edit issued around that splice reads the stub as its own argument. **Root correlate is PAYLOAD SIZE, not offload** (Anvil 2026-07-15, 4 incidents/3 files): every corruption was a LARGE multi-line `new_string`/`content` (1,013 / 2,360 / 3,700 chars); small edits NEVER corrupted. One case (NoteDialog.tsx line 698) corrupted with **no offload that turn** — so the large-tool-input archival substitution is the trigger; offload only correlates. The generator is `offload_tool_results.py::_stub()`; the harness can land that stub as the actual write.

**tool_result LIES:** the Edit/Write returns SUCCESS ("file updated") while the bytes on disk are the stub. The AI's only signal that an edit landed is the tool_result, and it's decoupled from reality. A follow-up **Read returns the same stub too** — so neither the tool_result nor Read is ground truth; only raw bytes (`awk`/`grep`/`sed`) are.

**Detect:** `tsc` is NOT a reliable sole detector — it flagged the JSX/TS cases (`·` "Invalid character", `3,700` numeric-literal error) but the CSS/NoteDialog case passed tsc CLEAN. The dependable detector is a **stub-prefix grep on every changed file** post-edit: `grep -n "^\[input archived: \(Edit\|Write\)" <file>` (or the `[input archived:`/`[input stripped:` prefixes). The live guard `data/hooks/PostToolUse/05_guard_write_stub_sync.py` only checks **line 1**, so it catches whole-file `Write` corruption but MISSES mid-file `Edit` stubs (Anvil's were at lines 244/3267/698) — [[reference_environment_invariants]] gap to fix.

**Fix:** re-author the intended content to a scratch file and splice it over the single stub line via Python (`lines[idx:idx+1] = repl.split('\n')`) — matching the garbled bytes with Edit is unreliable.

**Avoid:** after any offload, re-verify each subsequent edit landed (tsc + a stub grep) before building. Relates to [[feedback_self_context_management_autonomy]], [[feedback_verify_with_real_execution]].
