# Memorex ⟷ Transcript Reconcile — Design (DRAFT, under review)

**Status:** ⏸️ **PARKED — monitoring** (decided with PianoMan 2026-07-11, after Codex Review 1
and the walkthrough). Not being implemented. See §9 for why and the resume trigger.

The Codex review + walkthrough surfaced that this reconcile is *downstream insurance for an
upstream problem*: bad terminal redraws (not a Memorex bug). The dominant trigger is
tab-return, which likely fires a pane resize → the CLI repaints its TUI → and with an
xterm↔tmux size desync the repaint returns corrupt → Memorex reclassifies the corrupt frame
and loses the section boundary. That is the same "UAI terminal resize desync" being worked
under todo_0504. **Fixing the source is expected to dissolve most of the tab-return
corruption**, shrinking (or removing) the need for this reconcile. So we park the reconcile,
fix the source first, and *monitor* whether corruption persists.

This doc is not final and MUST NOT be implemented until the source fix lands, monitoring
shows residual corruption still worth repairing, and PianoMan gives the go — Memorex logic
changes are run past him first. Two decisions from §6 also remain open (hole scope; SPLIT —
now refined below).

**Source:** ported faithfully from the adversarial whiteboard walk
(`scratchpad/memorex_whiteboard.html`, session Relay, 2026-07). Nothing here is new
design beyond that walk; this is the durable, reviewable substrate.

## Terms

- **Memorex** — the terminal-format overlay that renders the live terminal buffer into a
  styled, sectioned transcript view (glyph/color classification of prompt/assistant/
  thinking/tool sections). It reads the *terminal text*, which can be corrupted by redraws.
- **Transcript / JSONL** — the structured conversation log (`read_jsonl.py` →
  `window.uai.transcript.read(..., 'structured')`). Ground truth: it never suffers the
  terminal's redraw corruption, but it *lags* the live edge (a just-typed prompt isn't
  flushed to JSONL yet).
- **Section (S)** — one classified block in the Memorex overlay DOM.
- **Message (M)** — one structured transcript entry (`user` / `response` / `thinking` /
  `tool_use` / `tool_result`).
- **Settled** — a section/message above the live edge that is complete and no longer
  changing. The opposite is the **in-flight tail**.
- **first30 / fingerprint** — the whitespace/markdown-normalized first ~30 chars of a
  message, used as a cheap alignment probe. `strip_md` = strip markdown/glyph decoration.

## 1. Problem

Memorex classifies from the terminal buffer. When the user switches away from a tab and
returns, a redraw can corrupt the buffer — most visibly, a section that was correctly its
own Assistant block collapses back into the prior Tool section (the observed Anvil case:
`1. [Archive]/[Delete]` losing its section boundary after tab-return). The terminal buffer
lies under redraw corruption; the JSONL transcript doesn't. So: **reconcile the settled
portion of the Memorex overlay against the transcript, repairing corruption without
touching the live tail.**

An earlier Memorex attempt drove *formatting itself* from the JSONL and was abandoned
(see `memorex.md` §"Format from the terminal text, not the JSONL transcript"). This design
is deliberately narrower: terminal text remains the formatter; the transcript is used only
to **reconcile/repair settled sections post-hoc**, not to drive live rendering.

## 2. The algorithm (as it stands)

**Confirm loop.** For each complete transcript message `M` (settled, above the live edge),
find the next Memorex section `S`:

1. **Gate:** `S.line.contains(strip_md(M.first30))`.
2. **Size-classify** (±15% tolerance on `strip_md(fullText).length`):
   - equal → **CONFIRM** (tag section with `msg#` / `ts`)
   - `S` bigger → **MERGE** (one section actually holds N messages)
   - `S` smaller → **SPLIT** (N sections actually are one message)
   - no first-30 hit → **WRONG-START**
3. **Recover** from the last confirmed match's DOM position: replace its body with the
   clean transcript text, splice in the expected message(s), and **terminate on
   fingerprint re-alignment** (the next section matches the next expected message).

**Guard.** Only ever touch **settled** sections — never the in-flight tail. Key each
synthetic (repaired) section by `msgId` so the terminal's own later render *replaces* it
rather than doubling it.

## 3. Scenarios walked (adversarial)

| # | Scenario | Verdict | What it taught |
|---|----------|---------|----------------|
| S1 | Fold/merge — **REAL** (Anvil, msg 19341): a tool_use + tool_result + response collapsed into one Memorex tool section | WORKS, exposed Hole #1 | MERGE replaces S body with clean tool_use, splices tool_result, splices response as its own un-folded assistant section. But termination leaned on hitting the live edge — with no clean section after the merge, nothing re-aligns. |
| S2 | Split by a false separator (a `────` rule mid-body read as a new section) | WORKS † | SPLIT absorbs the separator + following section into M until re-align. **†** But: has Memorex *ever* found a "new" section early? Unconfirmed — see the lever (§6). |
| S3 | Transcript lag, steady state (settled response confirmed; live `❯` prompt not yet in JSONL) | GUARD HOLDS | The settled-only guard skips the live edge → no false WRONG-START. This case is *why the guard is non-optional*: without it every normal lagging prompt trips recovery. |
| S4 | History scrolled off the buffer top (hundreds of old lines gone) | COMMON — BREAKS | Loop starting at transcript msg 1 reads the missing top as WRONG-START and tries to insert ~900 off-screen messages. → Hole #4. |
| S5 | Redraw duplicated a block (same ledger line rendered twice) | SEEN — BREAKS | Doubled size reads as `S ≫ M` → MERGE splices M+1 into what is really M-repeated. → Hole #5. |
| S6 | Truncation wearing a split's clothes (redraw ate a message tail) | PLAUSIBLE — BREAKS | Eaten tail makes `S ≪ M` → looks like SPLIT → absorbs the *next real message* and corrupts the boundary. → Hole #2. |
| S7 | Tool output that won't fingerprint (terminal shows collapsed "Read 2000 lines"; transcript holds the full 2000 lines) | STRUCTURAL RISK | first-30 miss + wild size mismatch on a *healthy* section → false discrepancy. → Hole #6. |

## 4. Holes on the board

| # | What breaks it | From | Sev | Candidate fill |
|---|----------------|------|-----|----------------|
| 1 | MERGE can't find a re-align point (live edge, or consecutive corruption) | S1, S7 | **HIGH** | Size ceiling: consume messages until cumulative ≈ S *or* re-align, whichever comes first. |
| 2 | Truncation looks identical to a split under a size check | S6 | **HIGH** | Before absorbing, peek the next section's first-30 vs M+1. Match M+1 → truncation (replace S with full M, absorb nothing). Continues M → real split. Size alone can't tell them apart. |
| 3 | Cold start / tab-return has no "last confirmed match" to anchor on | implicit | MED | Establish a first anchor: top-down from the buffer-top message, or the first clean fingerprint. |
| 4 | Transcript messages above the buffer top read as missing | S4 | **HIGH** | Anchor the transcript pointer to the **buffer-top** message, not msg 1. Above the anchor = scrolled away (never a discrepancy); missing *below* it = corruption. |
| 5 | Intra-message redraw dup masquerades as a merge | S5 | MED | Disambiguate overflow: matches M+1's fingerprint → real merge; repeats M → dup (replace with clean M, splice nothing). Must cooperate with existing `dedupConsecutiveBlocks` (≥6 lines). |
| 6 | Tool rendering ≠ tool_result content → false discrepancy | S7 | MED | **Text-first:** confirm/repair user·assistant·thinking sections; treat tool sections leniently (type-match only, no size/fingerprint gate). |

## 5. Guard is load-bearing

S3 is the case that makes "settled + complete only" non-optional. The live `❯` prompt has
no transcript message yet (JSONL lag); the guard skips it, so no false WRONG-START and no
inserting-a-beat-early. Any implementation that weakens the settled-only guard reintroduces
S3 as a constant false positive.

## 6. Open decisions (the walkthrough's job)

1. **Which holes are in scope for v1?** Holes 1, 2, 4 are HIGH. 3 is table-stakes for
   cold start / tab-return (the actual trigger). 5, 6 are MED.
2. **Is SPLIT real?** — the **simplification lever.** PianoMan flagged that Memorex
   splitting a message *early* (a "new" section that shouldn't exist) may never have
   actually happened. If that holds: **drop the SPLIT recovery branch entirely.** S2 and
   half of S6 evaporate; "S smaller than M" becomes a *logged anomaly we watch for*, not
   code we maintain. The design then carries **one real repair (MERGE) + the guards** —
   roughly half the surface. Recommendation: ship SPLIT-less, log the anomaly, add the
   branch only if the log ever fires.

Confirmed-real so far: **only S1** (Anvil fold, msg 19341). Everything else is a probe.

## 7. What is NOT decided / out of scope here

- Exact DOM API for splice/replace (deferred to implementation once §6 is settled).
- Performance of the 2000-line read + the front-1500 / rear-500 split idea PianoMan
  raised (an optimization, not load-bearing for correctness).
- Whether reconcile runs on every tab-return, on a timer, or only on detected corruption.

## 8. Review 1 — Codex (`5877716b_cod`), 2026-07-11: CHANGES REQUESTED

Full review preserved at `docs/designs/memorex_transcript_reconcile.review1_codex.md`.
Verdict: **request changes before implementation** — but the v1 shape is close, and Codex
endorses SPLIT-less. Recommended v1: **MERGE-only + residual-subtraction repair +
convergence/settled state machine + fail-closed on ambiguity.**

**Keystone reframe (folds BLOCKERs A, B, E):** matching, sizing, and repair must all
happen in a **"Memorex projection"** — the exact JSONL→displayed-text transform (tool
collapse, thinking/private stripping, dedup, ANSI strip, wrapping). Raw JSONL length ≠
terminal-section length, so:
- **BLOCKER A** — the size ceiling (Hole #1 fill) is only a *sanity bound* in projected
  space, never the primary MERGE terminator. Terminate MERGE on: (1) unique re-align
  anchor, (2) unique residual-slice allocation for all repaired messages, or (3) a
  whitelisted known-fold pattern. None hold → fail closed + log.
- **BLOCKER B** — repair is **residual subtraction**, not splice/insert: the fold's
  assistant body is often already on-screen inside the contaminated tool section, so
  splicing JSONL doubles it. Invariant: replace the *unique normalized residual slice(s)*
  inside the contaminated section with synthetic msg-backed sections. **No unique residual → no repair.**
- **BLOCKER E** — the confirm loop's "for each complete transcript message M" is too broad;
  it must iterate the *projected visible stream* (visible types only, display order, tools
  lenient/as-spans), not raw `structured` records (which include meta/system/skill/thinking).

**HIGH findings:**
- **C** — first30 `contains` is too weak (matches quoted output, code, repeated "Done —"
  openings). Require: match *near the projected section start* after marker normalization,
  plus uniqueness + monotonic-neighbor check. Two candidates pass → leave unmatched.
- **D** — buffer-top anchor must handle mid-message capture (tmux starts mid-message →
  orphan `cont` group). Ignore everything before the first *full, uniquely matched* marker
  below buffer top.
- **F** — `syn:msgId` keying alone won't make the later healthy terminal render *replace*
  the synthetic (terminal key ≠ syn key). Need a **msgId ownership map + idempotency**:
  once terminal confirms msgId X, suppress `syn:msgX`; once a contaminated section is
  repaired, don't reapply next refresh.

**Pressure-test of the two HIGH fills — neither fully holds:**
- Hole #1 size ceiling: guardrail, *not* a terminator (fails on tool collapse and on
  doubled-M ≈ M+M+1).
- Hole #2 peek-next-vs-M+1: sound as *truncation* evidence when positive; **unsafe as
  split proof when negative** (next section also corrupt / absent at live edge / M quotes
  M+1 / lag). SPLIT absorption would need positive proof of continuation AND negative proof
  it isn't M+1 — hence log-only for now.

**Settled-only guard is necessary but not sufficient** — needs a convergence state machine:
(1) no active verb line / responding state; (2) sections + `contentEnd` stable across two
refresh epochs (or one explicit completed-turn/Stop epoch); (3) transcript watermark stable
or advanced across a bounded retry; (4) both repair anchors strictly before `contentEnd`
and not in the last N sections near the live tail; (5) a generation token so a stale async
transcript read can't patch a newer overlay; (6) view-model-only repair, never direct DOM.

**Status after review:** DRAFT, changes requested. Open decisions (§6) still stand; the
walkthrough now also has to settle the projection contract, the residual-subtraction repair
model, the anchor-uniqueness rule, and the convergence state machine before this is
implementable.

## 9. Decision — PARKED as monitoring (2026-07-11)

Outcome of the walkthrough with PianoMan:

- **Root cause is upstream, not Memorex.** The reconcile would be treating symptoms of bad
  terminal redraws. The primary trigger (tab-return corruption) is most likely a
  pane-resize repaint under an xterm↔tmux size desync — i.e. **todo_0504 (UAI terminal
  resize desync)**. Fix the source first.
- **Sequence:** (1) land the resize-desync fix; (2) monitor whether tab-return / redraw
  corruption still occurs and in what form; (3) only if meaningful residual corruption
  remains, resume this design — scoped small.
- **If resumed, the scope is small:** the "normal variation" left over is the **join case** —
  *any assistant response that lost its leading `⏺` marker gets absorbed upward into the
  prior section (tool_result, thinking, or an assistant fragment — NOT tool-limited).*
  Repair = re-insert the eaten section boundary at the next message's projected start
  (residual subtraction; no unique residual → no repair; fail closed).
- **SPLIT refined (supersedes the blanket "SPLIT-less"):** duplication *was* observed and
  presents split-like (more sections than messages). Its repair is **dedup (delete a
  copy)**, distinct from a false-separator split's **absorb (concatenate halves)**. So:
  keep/rely on dedup for the duplication case; the false-separator *absorb* branch stays
  unbuilt + log-only until a real one is captured.
- **Monitoring posture:** if/when we want data before committing, the cheapest first
  increment is a **passive discrepancy logger** — Memorex compares against the projected
  transcript and logs join/dup/split anomaly frames (fingerprints, spans, activity state,
  transcript watermark) *without repairing*. That both proves how often corruption survives
  the source fix and tells us which cases are real. (Still a Memorex-logic change → run past
  PianoMan before building.)

**Resume trigger:** resize-desync fix is deployed AND tab-return/redraw corruption is still
observed. Until then: parked, no code.

## 10. Worked example — the CURRENT matcher misnumbers on any divergence (2026-07-12)

Confirmed by reading `TerminalFormatOverlay.tsx` (`matchSectionsToTranscript`, ~L1013–1051)
against a live corruption PianoMan observed in this session. Grounds the whole reconcile case.

**What Memorex does today:** it builds `metas[]` = a flat 1..N list of every JSONL message
(`msgId++`, `m.timestamp`) — so numbers/timestamps ARE transcript-sourced. But it assigns them
to sections by a **blind backward type-walk**: walk both the overlay's sections and `metas`
from the end, pairing the Nth-from-last section with the Nth-from-last transcript message *of a
matching type* (a `thinking` section grabs the nearest earlier `thinking` meta, etc.). **No
content comparison, no anchor, no uniqueness** — pure position + type.

**Consequence — observed live:**
- A dropped/merged section (from the CC-scrollback corruption of §9) shifts the section
  sequence out of step with the transcript, so the backward walk binds EVERY section to the
  wrong meta → wrong `Msg #` AND wrong timestamp (both ride the same mis-assigned meta).
- Concrete: a user section showed `Msg #15729` and a thinking section `#15795` (66 apart,
  ~8 min apart) when the transcript had them at `#15805`/`#15806` (adjacent, ~50 s apart).
- The 66-wide gap in Memorex's numbering = real transcript messages (all the `tool_use`/
  `tool_result` between them) that the overlay had no section for, so the walk skipped their
  msgIds and never displayed them.

**Why it matters:** this is exactly the "naive backward-by-type, no content anchor" alignment
Codex's Review 1 (§8) flagged as false-aligning. It is the current, shipping behavior — so the
reconcile redesign isn't only about repairing corruption, it also fixes msg#/timestamp
mislabeling that happens on ANY overlay↔transcript divergence (corruption, live-tail lag, or a
tool-section count mismatch). The content-anchored + unique + monotonic matching (§2, §8) is
the fix. NOTE: replacing `matchSectionsToTranscript` is a Memorex-logic change → run past
PianoMan first; still gated behind the §9 resume trigger.
