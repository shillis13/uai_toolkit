# Memorex — Design & Specification

**Status:** Living document. Part 1–4 describe the *current* implementation (verified against
code, July 2026). Part 5 is a *proposal* for a standalone, reusable, cross-platform version.
Statements are tagged **[impl]** (in code today) or **[proposed]** (design intent) where it
could be ambiguous.

## Terms

- **Memorex** — the live, in-place formatting overlay that turns a CLI agent's raw terminal
  output into a styled, sectioned transcript view *without* replacing the live terminal.
- **Overlay / cover** — the continuous DOM scroll surface drawn over xterm.js. It contains both
  settled Transcript cards and provisional terminal-derived cards for the in-progress bottom.
  It is full-height while idle, but yields the bounded rows from an active verb through the
  prompt/status so the real terminal animation remains visible.
- **Transcript** — the structured JSONL-derived message list produced by `read_jsonl.py`. It is
  authoritative for completed message order, boundaries, type, and prose.
- **Settled message** — a complete message that has appeared in Transcript. Its Memorex card is
  rendered from Transcript even if the terminal copy was split, merged, duplicated, or damaged.
- **Marker** — a line whose **first character (column 0)** is non-whitespace. All agent response
  text is indented into a 2-space margin, so anything in the margin is a structural marker
  (response, tool, thinking, verb line, prompt boundary, etc.).
- **Verb line** — the spinner the CLI shows while working/thinking, e.g. `✻ Crystallizing… (33s)`
  (active) or `✻ Churned for 3m 38s` (completed). It is a *type* of marker.
- **Live region / live tail** — a persistent FIFO of provisional terminal-derived cards attached
  below the last settled Transcript card. They are formatted immediately from opening markers and
  updated as output grows.
  Verb lines, task lists, prompts, decisions, and status rows remain plain terminal chrome.
- **Ordinal settlement** — when Transcript appends one card, that card replaces the first
  provisional card by position. If no provisional exists, it simply appends to the settled tail.
  Content and type do not participate in this decision.
- **Section** — one settled Transcript message rendered as a collapsible card. A matching
  `tool_use` + `tool_result` pair shares one folded tool card.
- **CDP** — Chrome DevTools Protocol; the debug channel (port 9226) used to inspect the running
  renderer. `window.__memorex` is the active-session shortcut;
  `window.__memorexSessions[trackingId]` addresses mounted-hidden sessions exactly because display
  names are not unique.

---

## 1. Purpose & Philosophy

Memorex makes a running CLI agent session readable — colored, sectioned, collapsible — while
preserving the exact live terminal underneath for interaction. Three decisions shape everything:

1. **Transcript owns settled messages.** [impl] JSONL lags streaming output, but once a complete
   message is recorded it is more reliable than terminal scrape boundaries. Every settled prose
   card therefore renders directly from Transcript. Terminal marker loss, duplicate redraws,
   split blocks, and merged blocks cannot corrupt settled prose.
2. **Terminal owns only what Transcript cannot supply.** [impl] The terminal supplies the
   still-streaming provisional cards and compact folded tool presentation.
3. **Formatted all the way.** [impl] Message content remains one formatted scroll surface; there
   is no separate raw message pane. While a thinking verb is active, only the bounded terminal
   chrome from that verb through the prompt/status remains uncovered and live.

There is no terminal-card-to-Transcript content matching, type matching, anchor, count
reconciliation, or confidence gate. Settlement consumes the persistent provisional FIFO one card
at a time; it never slices a fresh terminal snapshot by the full Transcript count.

---

## 2. Current Architecture (UAI-embedded) [impl]

File: `packages/renderer-ui/src/components/TerminalFormatOverlay.tsx`
Rendered by: `TerminalPane.tsx` (which passes `enabled={memorexEnabled}`).

### 2.1 The two update paths

- A timer calls `refresh()` every **1s** for the active session and every **5s** for mounted-hidden
  session tabs. Keeping session panes mounted preserves Memorex state and scroll position across
  tab switches.
- The first `refresh()` captures up to 50,000 tmux history rows; later refreshes capture a
  2,000-row tail. The path is
  `window.uai.terminal.captureScrollback()` → IPC →
  `session_ops.py read-terminal <sessionName> --lines 50000 --styled`. This is a bounded snapshot,
  not a true terminal delta: terminal rows can be rewritten or reflowed and tmux supplies no stable
  row ID. Only the unfinished terminal turn is eligible to create provisional cards: the region
  after the latest completed verb line, with the newest submitted user marker as fallback when that
  line is unavailable. This bounds creation without placing the settled seam—Transcript still owns
  that. Consecutive snapshots of this small region are compared only to detect terminal
  opening-marker appends and updates; they are never aligned to Transcript. Repeated marker context
  is anchored at its newest occurrence, and a suffix marker already present earlier in the same
  snapshot is treated as terminal repaint output rather than another provisional card. If a truly
  repeated live message is indistinguishable from a repaint, it waits for Transcript settlement
  instead of being shown twice. **`sessionName` is
  the session's `terminal_session` field** (e.g. "Anvil"), not the tracking_id. If capture fails,
  `refresh()` leaves the existing cover unchanged.
- The main-process `TranscriptCacheService` watches each pooled JSONL file. A real file change
  reparses the canonical structured Transcript and sends `transcript:updated`. The watcher delay
  is `runtime.transcriptRefreshDebounceMs` in `ai_general/data/memorex/palette.json` (environment override:
  `UAI_TRANSCRIPT_REFRESH_DEBOUNCE_MS`) and currently defaults to **0ms**. Events arriving during
  a parse queue another metadata/read pass rather than being discarded. Every terminal poll also
  reads the warm cache, which verifies JSONL size+mtime and repairs a missed watcher event.
- Renderer work is revision-based. If neither terminal text nor Transcript revision changed,
  Memorex skips DOM work. TranscriptViewer reuses unchanged message objects and sanitized Markdown.
  Both renderers use a load generation so an older async read cannot overwrite a newer session or
  Transcript revision. Memorex serializes and coalesces overlapping refresh requests; one capture
  cannot race another capture and append the same provisional twice.

### 2.2 Pipeline

```
JSONL append
   → shared TranscriptCacheService
   → read_jsonl.py structured messages
   → buildSettledTranscriptBlocks()
   → append/replace only changed DOM cards

terminal capture (ANSI preserved)
   → locate prompt/status/decision chrome
   → bound provisional creation to the unfinished terminal turn
   → group that turn's message lines into ordered terminal cards
   → compare with the prior terminal-only snapshot
   → update the current provisional and append cards for new opening markers
   → read Transcript; each appended Transcript card consumes one provisional FIFO head
   → use compact terminal rendering for settled tool cards
   → render only the visible/nearby card window with measured spacers
```

When Transcript is unavailable, the existing terminal marker grouping remains a fallback rather
than blanking the overlay.

### 2.3 The terminal Marker model

**A line is a Marker iff its first character (column 0) is non-whitespace.** All agent response
text is rendered into a **2-space left margin**; anything sitting in that margin is structural.
This remains the rule for prompt/live-tail geometry, folded terminal tools, and the no-Transcript
fallback. It no longer decides settled prose boundaries once Transcript is available.

Markers are then **sub-typed by glyph** (Claude CLI):

| Glyph | Const | Type | Notes |
|-------|-------|------|-------|
| `❯` U+276F | `P` | user | the prompt input line |
| `∴` U+2234 | `T` | thinking | thinking block marker |
| `⏺` U+23FA | `R` | response **or** tool | disambiguated by the text after it (§2.4) |
| `──────` (≥20 U+2500) | — | separator / prompt boundary | unless it contains box-drawing table chars |
| *(animation glyphs: ✻ ✽ ✳ · ✢ …)* | — | **verb line** | the residual/spinner type (§2.5) |

Body/continuation lines (column 0 = whitespace) attach to the preceding section as `cont`.

Codex and Gemini have their own marker glyphs (`•`/`›` for Codex; `✦`/`╭`/`╰`/`ℹ` for Gemini),
handled in the same `classifyLine`.

### 2.4 Tool vs Response (both start with `⏺`)

`classifyLine` inspects the text after `⏺`:
- `^\w+\(` → **tool** (native call: `⏺ Bash(cmd)`, `⏺ Read(/path)`)
- `^\w+\s*-\s*\w+` → **tool** (MCP form: `⏺ comms - comms_send_prompt`)
- `^\w+…$` → **tool** (tool-in-progress: `⏺ Exploring…`)
- otherwise → **assistant** (prose response)

### 2.5 Verb-line and terminal-chrome detection

The verb line is the spinner. It is rendered as plain terminal chrome and is never a message card
or a settled/live boundary. Its classification rules remain precise:

- **Active form:** `<glyph> <gerund phrase>…` — a marker glyph, a gerund phrase (one word OR
  several: `✻ Crystallizing…`, `✻ Writing spec and plan…`), then an ellipsis at the **phrase end**.
  - Single-word: [impl: `/^\S\s+\S+…/`] — ellipsis immediately after the first word.
  - Multi-word phrase (added 2026-07-04, Timbre — a multi-word verb line was collapsing into the
    prior section): [impl: glyph is a **symbol animation glyph, not a stable non-verb marker**
    (`⏺ ⎿ ❯ › • > ◼ ✔ □ ✓`), followed by a phrase whose ellipsis sits at the **phrase end** —
    before ` (elapsed…)` or EOL: `/^\S\s+\S[^\n]*…(?:\s*\(|\s*$)/`].
  - The ellipsis must **not** be matched **mid-line** — that was the long-standing bug (ordinary
    content like `⏺ Now per the new… rule` matched and collapsed the overlay; see §4). Both the
    stable-marker exclusion (rejects `⏺`/`⎿`/task lines that end in `…`) and the phrase-end anchor
    (rejects a mid-sentence `new… rule`) preserve that guarantee.
  - **Do NOT anchor on the elapsed-time `(<N>s` token** (e.g. `(33s · …)`). It is absent a large
    fraction of the time and its format is highly variable; it is not a reliable discriminator.
    (A v1.1.87 attempt to anchor on it was reverted — see §4.)
  - The ellipsis is **stable**, not animated — it does not cycle `.`→`..`→`…`. The active form's
    discriminator is the gerund-tied ellipsis, full stop.
- **Completed form:** `<glyph> <word> for <N>[hms]` — e.g. `✻ Churned for 3m 38s` (Claude) or
  `─ Worked for 2m 26s ───` (Codex). [impl: `/^\S\s+\S+\s+for\s+\d+\s*[hms]/`]
- **Codex active form:** `<glyph> Working (<N>s · esc to interrupt)` — Codex's live thinking line
  (glyph animates `•`→`◦`→…). [impl: `/^\S\s+Working\s*\(\d/`] The `Working (<digit>` discriminates
  it from Codex tool calls (`• Ran…`, `• Called…`, `• Updated…`) and the status line. (Added
  2026-07-04 — the Codex thinking line was going undetected and collapsing into content.)
- **Permission/decision prompts replace the prompt block.** [impl, 2026-07-06] A Claude Code
  interactive decision (tool-permission "Do you want to proceed?", plan approval) removes the
  `──── ❯ ────` block while it waits for an answer — no separators, and the session is idle so no
  verb line — so `findPromptAreaStart` would otherwise fall to `return lines.length` and cover the
  ENTIRE viewport, dialog included (the user had to toggle Memorex off to answer). Discriminator
  (PianoMan's spec, verified against Broken-Clock): a real user/prompt `❯` sits at **column 0**; a
  decision option `❯` sits at **column 1** (the dialog's structural lines are indented one space).
  `findDecisionAreaStart` anchors on the lowest col-1 `❯ N.` numbered option, walks up through
  col-1 lines (question/warning) + interspersed blanks to the dialog top (requiring ≥1 letter-
  starting col-1 line), and returns it as `promptStart` so the dialog stays in the terminal-chrome
  block at the bottom of the formatted surface. The dialog **disappears once answered**, so it needs only this plain-chrome treatment — no
  settled-section type. `classifyLine` is deliberately left column-0-only (the broader col-0-or-1
  marker rule is a bigger change, reserved for when exceptions accumulate).
- The verb line's glyph **animates** through an open-ended set (✻ ✽ ✳ · ✢ and others) to look
  active. The code therefore does **not** enumerate glyphs — the structural test (gerund-tied
  ellipsis / `for <dur>`) is the discriminator. [impl]
- **Blank-frame caveat:** one frame of the animation can render the column-0 glyph as whitespace.
  [proposed] The intended handling is a fallback (gerund-tied ellipsis on a whitespace-margin line)
  and/or **sticky classification** (once a line is a marker, a later blanked frame must not demote
  it). Neither is fully implemented today; the current code requires a non-whitespace column 0.

### 2.6 Persistent card chain and cover geometry [impl]

Memorex maintains one persistent message-card chain:

```
settled Transcript: DM0 <- DM1 <- ... <- DMn
provisional terminal:                         <- Pn+1 <- Pn+2 <- ...
```

Terminal snapshots have only terminal-to-terminal meaning. After the initial baseline, a new
opening marker appends a provisional card and later rows update the current provisional. The full
Transcript count is never applied to a bounded terminal tail. When Transcript appends Tn+1:

```
DMn <- Pn+1 <- Pn+2   --Tn+1-->   DMn <- Tn+1 <- Pn+2
```

Tn+1 replaces the first provisional by position, with no content/type comparison. If there is no
provisional, Tn+1 simply appends as the new settled tail. Tool-result updates replace their existing
settled tool card and do not consume another provisional. Settled cards therefore always equal the
Transcript in order; terminal split/merge/drop/dup drift is confined to the provisional FIFO and
self-heals as later Transcript cards settle it.

Refresh deliberately ingests the terminal snapshot before reading a changed Transcript cache. This
preserves the real causal order (stream first, completed JSONL record second) even when the zero-delay
file watcher fires before the regular terminal poll. Transcript reads are not deferred until terminal
output pauses: a continuously streaming response must continue settling completed cards. A lost
terminal-only snapshot anchor resets the scrape baseline but never rebuilds or discards the persistent
chain.

The initial capture and later repaint comparisons are also bounded to the unfinished terminal
turn. The cold snapshot establishes a baseline without creating cards; a tail that changes or a
new opening marker then creates the live provisional. This prevents already-settled cards from
earlier in an active turn from becoming provisionals on mount. Completed verb summaries close
terminal turns for this create-side purpose and are excluded from terminal chrome; only the current
active verb line and its task rows may appear there.
When Transcript advances, the terminal opening fingerprints consumed from the FIFO remain suppressed
for the rest of that terminal turn. This prevents a post-settlement terminal repaint from recreating
the just-settled tail as an orphan provisional. If an explicit completed-turn marker is present and
the unfinished terminal region is empty, each provisional is removed when Transcript reaches that
FIFO position; any still-unproven remainder is removed after a short bounded JSONL-lag grace. This
closure rule is the only time terminal state may discard provisionals: it bounds missed-watcher/race
accumulation without comparing terminal text to Transcript text.
This does **not** make a verb line the settled/live card seam—Transcript remains the sole authority
for whether a message is settled.

Tool rendering is a presentation carve-out. A settled tool call/result occupies one Transcript card.
Memorex may identity-check a compact folded terminal tool card and use those lines for display, but
that check does not affect settlement. If no valid compact view exists, the Transcript fallback stays
folded and reports a result line count rather than injecting a large raw result.

The cover has terminal-screen height while idle or closed. While a thinking verb is active, its
visible xterm row becomes the cover's bottom boundary; the real animated verb, task rows, prompt,
and status remain visible below it rather than being copied into a static chrome card. Visible-row
geometry discounts capture padding beyond the actual xterm viewport. The old permanent raw-xterm
message pane and history-reveal toggle remain removed.

### 2.7 Transcript authority and shared cache [impl]

`refreshTranscriptCache()` reads the warm main-process cache, subscribes to
`transcript:updated`, and performs the size+mtime verification during the existing terminal poll;
there is no second independent timer. `flattenStructuredTranscript()`
preserves the Transcript's message numbering, including skipped local-only records, then
`buildSettledTranscriptBlocks()` builds the settled DOM model:

- user, injected, assistant, and thinking: one card per Transcript message, exact Transcript text;
- tool call + matching result: one folded card keyed by `tool_call_id`;
- message `type` owns the category (so a transport-level `role: user` tool result remains a tool);
- local-only session/command records are counted for Transcript numbering but are not rendered;
- message number, turn number, type, and timestamp: taken directly from Transcript.

The cache pool is keyed by resolved JSONL path and keeps aliases for tracking ID, CLI UUID, or
session name. That prevents Memorex and TranscriptViewer from launching separate complete parses
of the same file. Actual file changes still pass through the canonical `read_jsonl.py` full parse;
`readRecords()` is the explicit seam for a future safe tail parser.

### 2.8 Section rendering, collapse, and incremental updates

- Transcript block keys (`transcript:<firstMsgId>`) and provisional keys (`provisional:<id>`) are
  stable. A newly appended Transcript card replaces the provisional FIFO head without per-card
  content pairing;
- cards inserted or updated when Transcript replaces streamed raw text briefly brighten and fade
  over 1.2 seconds; initial history load does not animate;
- the visual indicator never delays Transcript authority or keeps duplicate raw text on screen;
  `tool_result` changes only its existing tool card; filter/collapse actions intentionally rebuild.
- Each card has a content revision. The renderer keeps measured heights and mounts only the cards
  intersecting the viewport plus two viewports of overscan. Top/bottom spacers preserve the full
  scroll range, and unchanged hidden cards contribute no DOM nodes.
- Thinking body text is rendered by stripping ANSI and forcing `THINKING_TEXT_COLOR` (`#e3ccff`),
  because Claude renders thinking dim-grey via ANSI which would otherwise override the intended
  color. [impl]
- Tool/thinking sections are collapsible (per-section), with expand/collapse-all-of-type filters.
  The selected type default applies equally to settled and provisional cards. A live tool retains
  its compact terminal text as its content source but remains collapsed when Tools is collapsed.
- `groupIntoSections()` and `stickyClassRef` remain only for terminal fallback and folded-tool
  extraction. They do not segment settled prose when Transcript is available.

### 2.9 Platform marker tables [impl]

- **Claude:** `⏺` response/tool, `❯` prompt, `∴` thinking, `✻` (+ animation set) verb line.
- **Codex:** `•` tool, `›` prompt.
- **Gemini:** `✦` response, `╭`/`╰` tool box borders, `ℹ` info/cancel.

---

## 3. Component-API conformance [impl]

Per the UAI "Component API Layer" principle (every component exposes get/set/update/delete/list;
all mutations flow through the command bus), Memorex is **partially conformant**:

- **Model (read): present.** Registers viewport node `memorex_view` whose `state` is the full
  `window.__memorex` object (`sessionId`, `platform`, `enabled`, `boundaries` {totalLines,
  promptStart, settledTranscriptCardCount, terminalCardCount, firstLiveCardOrdinal,
  liveCardCount, coverHeightPx, cellHeightPx, termRows}, `sectionCount`,
  `firstLiveTerminalLine`, `boundaryZone`). Also exposed via IPC `uai:memorex:state`.
- **Controller (actions): absent.** No `executeCommand`/command-bus usage. Toggling Memorex
  on/off is local React state (`memorexEnabled` on `TerminalPane`, described as "local state
  toggle"). Collapse/expand and type-filters are internal refs. The `memorex_view` viewport
  reporter exposes **no `actions` array**.

**Gap to close [proposed]:** route Memorex actions through the command bus and declare them —
`memorex.toggle`, `memorex.section.collapse/expand`, `memorex.filter.set`,
`memorex.collapseAllOfType` — and add an `actions` array to the `memorex_view` viewport node, so an
external agent can both read state and drive it.

---

## 4. History & lessons (bugs fixed)

- **Ellipsis-anywhere false match.** Verb-line detection used `/^\S\s+\S.*…/` — a bare ellipsis
  *anywhere* on a column-0 line. Ordinary content (`⏺ Now per the new… rule…`) matched, anchoring
  `contentEnd` mid-content and stranding hundreds of lines in the live region → cover collapsed to
  0px → "Memorex on, nothing formatted." Intermittent because it depended on where the lowest
  ellipsis-bearing line happened to sit. **Fix:** tie the ellipsis to the gerund (`\S+…`).
- **Active-only boundary.** A wrong intermediate fix made only *active* spinners count as the
  boundary, dropping completed verb lines — which has no coherent boundary in the idle case. **Fix:**
  restore completed-as-boundary; boundary = lowest verb line, active or completed.
- **Cover/scrollback height mismatch.** Live-tail height was computed from full scrollback vs the
  viewport. **Fix:** clamp `liveAreaLines` to `visibleRows`.
- **Edited the wrong renderer.** A now-deleted second component (`MemorexView.tsx`, dead code) had
  its own `.memorex-block-*` styling; a brightness change was made there and had no effect.
  **Fix:** deleted the dead component; `TerminalFormatOverlay` is the sole renderer.
- **Per-corruption terminal repair.** The prior reconciler independently matched terminal-derived
  cards to Transcript records, then accumulated special handling for dropped heads, duplicates,
  merged cards, and gated full replacement. It could still preserve a wrong terminal boundary.
  **Fix:** invert ownership. Transcript owns a persistent settled chain; terminal opening markers
  append a persistent provisional FIFO; each new Transcript card replaces the FIFO head by position.

**Meta-lesson:** the marker/verb-line rules are precise and empirically derived (column-0 = marker;
ellipsis tied to gerund; completed counts). Loosening them — matching glyphs anywhere, ellipsis
anywhere — caused most geometry defects. Those rules still protect prompt/live-tail geometry, but
terminal markers are not reliable enough to own settled message boundaries.

---

## 5. Proposed: Standalone, reusable, cross-platform Memorex [proposed]

Goal: a Memorex that is **independent of the UAI app**, reusable by others, with **all formatting
configurable**, running on **Windows, macOS, and Linux**.

### 5.1 Shape

A small, dependency-light **library** with three clean seams:

```
 transcript ─┐
             ▼
       ┌────────────────────────────────────────────────────┐
       │ INPUT ADAPTERS   RECONCILER             OUTPUT     │
       │ structured log ─▶ settled blocks ─┐               │
       │ terminal stream ▶ terminal cards ─┴▶ view model ──▶│ DOM/serialized
       └────────────────────────────────────────────────────┘
                                  ▲
                         config (markers, colors, rules)
```

- **Input adapters** — one supplies structured completed messages; another supplies raw terminal
  text (ANSI-preserving) on demand or as a stream. The core never talks to the OS or a vendor log
  directly. Transcript adapters can target Claude Code, Codex, or later platforms. Terminal
  adapters can target tmux, ConPTY, Windows Terminal, WezTerm, or a test string.
- **Core reconciler** — pure functions:
  `(transcriptBlocks, terminalLines, config) → ViewModel`. No DOM, OS, or app dependencies. It
  owns normalized block construction and the persistent settled/provisional reducer.
- **Output / renderer** — turns the ViewModel into a target: a DOM overlay (as today), or a
  serialized structure (JSON/HTML) for other hosts. Renderer-swappable.

### 5.2 Configurability (everything data-driven)

A `MemorexConfig` object, no code changes needed to retarget a new CLI:

- **`marginWidth`** — columns that define "content vs marker" (default 2).
- **`markers[]`** — ordered rules: `{ match: glyph|regex|"column0", type, disambiguate?: rule[] }`.
  Covers `⏺`→response/tool, `❯`→user, `∴`→thinking, separators, etc. The `⏺`-tool-vs-response
  disambiguation becomes config, not hardcode.
- **`verbLine`** — `{ activePattern: "<gerund-tied-ellipsis>", completedPattern: "for <dur>",
  glyphPolicy: "residual" }` — the structural rules, not a glyph list.
- **`styles`** — per-type color/background/border/label/opacity (e.g. thinking text color). The
  current `SECTION_COLORS`/`SECTION_BG`/`THINKING_TEXT_COLOR` become config entries.
- **`settlement`** — `{ rule: "persistent-provisional-fifo" }`.
- **`platforms`** — named bundles of the above for claude/codex/gemini, selectable at runtime.

### 5.3 Cross-platform considerations

- **Capture and structured-log decoding** are adapter seams. Reconciliation and rendering remain
  pure and portable.
- **Glyph/Unicode**: markers are multi-byte glyphs; the core must operate on Unicode code points
  (not bytes) and tolerate terminal width/encoding differences. Windows terminals may substitute or
  render glyphs differently — hence `glyphPolicy: "residual"` (structure over enumeration) travels
  better than a glyph allowlist.
- **No tmux assumption**: the tmux dependency lives only in the mac/Linux adapter; Windows uses a
  ConPTY-based adapter. The library ships adapters but requires none.
- **ANSI**: a shared ANSI parser (already exists as `renderAnsiLine`) is platform-neutral and moves
  into the core/renderer.

### 5.4 Reuse API (sketch)

```
const mx = createMemorex({ platform: 'claude', styles: {...}, marginWidth: 2 });
const view = mx.reconcile(messages, rawTerminalText); // persistent-chain ViewModel
mx.renderTo(domNode, view);                   // or: JSON.stringify(view)
mx.on('settledCountChange' | 'sections', cb); // events for hosts
```

### 5.5 Migration path

1. Move the existing pure transcript block builder and persistent-chain reducer into a
   standalone package, then extract prompt/status geometry from
   `TerminalFormatOverlay.tsx`.
2. Replace the hardcoded glyph/color constants with config defaults (claude/codex/gemini bundles).
3. Define a normalized completed-message adapter contract and implement Claude Code and Codex.
4. Re-host the current overlay on top of the extracted core (UAI becomes one consumer).
5. Add the command-bus action surface (§3 gap) at the UAI-host layer, not the core.
6. Add a Windows terminal adapter; validate glyph handling on all three OSes with string fixtures +
   live capture.

### 5.6 Stability constraint

The extraction must preserve the ownership split: Transcript for settled messages, terminal for
live output and folded tools. Port the exact §2.5 fallback rules and §2.6 forward walk with
pure-function tests before changing behavior.
