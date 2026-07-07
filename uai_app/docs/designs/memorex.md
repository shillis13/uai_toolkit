# Memorex — Design & Specification

**Status:** Living document. Part 1–4 describe the *current* implementation (verified against
code, June 2026). Part 5 is a *proposal* for a standalone, reusable, cross-platform version.
Statements are tagged **[impl]** (in code today) or **[proposed]** (design intent) where it
could be ambiguous.

## Terms

- **Memorex** — the live, in-place formatting overlay that turns a CLI agent's raw terminal
  output into a styled, sectioned transcript view *without* replacing the live terminal.
- **Overlay / cover** — the DOM element drawn on top of the xterm.js terminal that holds the
  formatted content. It covers the *settled* region of the screen; the bottom (live) region
  shows through to the raw terminal.
- **Marker** — a line whose **first character (column 0)** is non-whitespace. All agent response
  text is indented into a 2-space margin, so anything in the margin is a structural marker
  (response, tool, thinking, verb line, prompt boundary, etc.).
- **Verb line** — the spinner the CLI shows while working/thinking, e.g. `✻ Crystallizing… (33s)`
  (active) or `✻ Churned for 3m 38s` (completed). It is a *type* of marker.
- **Live region / live tail** — the bottom portion of the screen from the verb line down
  (verb line, task list, prompt, status bar). It stays raw because it's still changing.
- **Boundary (`contentEnd`)** — the line index dividing formatted overlay content (above) from
  the live region (below). It is the lowest (most recent) verb line.
- **Section** — a contiguous run of lines of one type (a User block, a Claude response, a Tool
  call+result, a Thinking block), rendered as one collapsible card.
- **CDP** — Chrome DevTools Protocol; the debug channel (port 9226) used to inspect the running
  renderer.

---

## 1. Purpose & Philosophy

Memorex makes a running CLI agent session readable — colored, sectioned, collapsible — while
preserving the exact live terminal underneath for interaction. Two foundational decisions shape
everything:

1. **Format from the terminal text, not the JSONL transcript.** [impl] An earlier attempt drove
   formatting from `read_jsonl`/Transcript (the structured conversation log). It was abandoned for
   the *live* view because the JSONL lags the terminal by too much — it's written after a message
   completes, so the actively-streaming portion isn't there yet. Scraping the terminal is
   immediate. It also keeps Memorex **portable**: it depends only on terminal output, not on any
   particular agent's log format.
2. **Overlay, don't replace.** [impl] The live terminal remains fully functional; Memorex draws a
   cover over the settled region only. The live tail (spinner, prompt, interactive menus) shows
   through raw so the user can still navigate/type.

The one place the JSONL is still read is **cosmetic metadata** (see §2.6): message numbers and
timestamps injected into section headers. It never drives formatting; if it fails, you only lose
the `#`/timestamp garnish.

---

## 2. Current Architecture (UAI-embedded) [impl]

File: `packages/renderer-ui/src/components/TerminalFormatOverlay.tsx`
Rendered by: `TerminalPane.tsx` (which passes `enabled={memorexEnabled}`).

### 2.1 The refresh loop

- A timer calls `refresh()` every **1s** when the tab is active (`POLL_ACTIVE_MS`), 5s when
  backgrounded (`POLL_BACKGROUND_MS`).
- `refresh()` captures the terminal via `window.uai.terminal.captureScrollback(sessionName, 50000)`
  → IPC → `session_ops.py read-terminal <sessionName> --full --styled`. **`sessionName` is the
  session's `terminal_session` field** (e.g. "Anvil"), not the tracking_id. If capture fails
  (`!ok || !text`), `refresh()` bails — leaving no cover (this is the failure mode behind
  "Memorex on but nothing formatted"; see §4).
- If the captured text is unchanged since last poll, it returns early (no rebuild).

### 2.2 Pipeline

```
captureScrollback (raw terminal text, ANSI preserved)
   → split into lines
   → findPromptAreaStart()      locate the prompt block near the bottom
   → findContentEnd()           locate the live boundary (lowest verb line)
   → slice [0 .. contentEnd)    = formatted content; [contentEnd ..] = live tail
   → strip [/PRIVATE] thinking blocks
   → groupIntoSections()        runs of one type → Section groups
   → renderSectionDom()         build collapsible, colored DOM into the cover
   → set cover height           = visibleHeight − (liveTailLines × cellHeight)
```

### 2.3 The Marker model — the core rule

**A line is a Marker iff its first character (column 0) is non-whitespace.** All agent response
text is rendered into a **2-space left margin**; anything sitting in that margin is structural.
This rule is exceptionless — even the prompt-boundary rules (`──────…`) are markers (they start at
column 0). [impl: `classifyLine()` keys off column-0 glyphs; continuation/body lines start with
whitespace and classify as `cont`.]

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

### 2.5 Verb line & boundary detection — the spec

The verb line is the spinner; it is the **live boundary**. Rules (per PianoMan's spec, the
authority for this component):

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
  `─ Worked for 2m 26s ───` (Codex). [impl: `/^\S\s+\S+\s+for\s+\d+\s*[hms]/`] **Completed verb
  lines are valid boundaries** (a finished response's marker is where the live tail begins).
- **Codex active form:** `<glyph> Working (<N>s · esc to interrupt)` — Codex's live thinking line
  (glyph animates `•`→`◦`→…). [impl: `/^\S\s+Working\s*\(\d/`] The `Working (<digit>` discriminates
  it from Codex tool calls (`• Ran…`, `• Called…`, `• Updated…`) and the status line. (Added
  2026-07-04 — the Codex thinking line was going undetected and collapsing into content.)
- **Boundary = the lowest (most recent) verb line _within the live tail_**, active OR completed.
  `findContentEnd` scans upward from the prompt and returns the first (lowest) verb line; everything
  below it is live, the line above it is the last formatted line. [impl]
- **The verb line must be NEAR the prompt (the live tail is small).** Completed verb lines persist
  in scrollback — a settled buffer routinely holds several (e.g. `✻ Brewed for 4m`, `✻ Sautéed for
  16m`, … one per finished sub-step). If the scan is unbounded it will latch onto a **stale** verb
  line from a previous turn that the current turn's streaming content has pushed far above the
  viewport; then `totalLines − contentEnd ≥ visibleRows`, the live region fills the screen, and the
  cover collapses to 0 — **the whole overlay blanks until the turn ends.** This is the failure that
  manifests "during active response, no formatting at all" (root-caused 2026-06-18).
  - **Rule:** the scan is bounded to a **live-tail window** just above the prompt
    (`LIVE_TAIL_MAX_LINES`, clamped so the boundary stays within the lower viewport). A verb line
    farther up than that is treated as stale and ignored. [impl]
  - **No verb line in the window ⇒ fall back to `promptStart`** (stop one above the prompt's top
    separator). This is the SAFE direction: the overlay covers the full visible region (formats a
    little of the still-settling tail) rather than blanking. Blanking is never acceptable; over-
    covering by a few lines is.
- **Permission/decision prompts replace the prompt block.** [impl, 2026-07-06] A Claude Code
  interactive decision (tool-permission "Do you want to proceed?", plan approval) removes the
  `──── ❯ ────` block while it waits for an answer — no separators, and the session is idle so no
  verb line — so `findPromptAreaStart` would otherwise fall to `return lines.length` and cover the
  ENTIRE viewport, dialog included (the user had to toggle Memorex off to answer). Discriminator
  (PianoMan's spec, verified against Broken-Clock): a real user/prompt `❯` sits at **column 0**; a
  decision option `❯` sits at **column 1** (the dialog's structural lines are indented one space).
  `findDecisionAreaStart` anchors on the lowest col-1 `❯ N.` numbered option, walks up through
  col-1 lines (question/warning) + interspersed blanks to the dialog top (requiring ≥1 letter-
  starting col-1 line), and returns it as `promptStart` so the dialog stays in the raw live tail.
  The dialog **disappears once answered**, so it needs only this live-region treatment — no
  settled-section type. `classifyLine` is deliberately left column-0-only (the broader col-0-or-1
  marker rule is a bigger change, reserved for when exceptions accumulate).
- The verb line's glyph **animates** through an open-ended set (✻ ✽ ✳ · ✢ and others) to look
  active. The code therefore does **not** enumerate glyphs — the structural test (gerund-tied
  ellipsis / `for <dur>`) is the discriminator. [impl]
- **Blank-frame caveat:** one frame of the animation can render the column-0 glyph as whitespace.
  [proposed] The intended handling is a fallback (gerund-tied ellipsis on a whitespace-margin line)
  and/or **sticky classification** (once a line is a marker, a later blanked frame must not demote
  it). Neither is fully implemented today; the current code requires a non-whitespace column 0.

### 2.6 Cover geometry (why it can collapse)

```
cellHeight   = visibleHeight / term.rows
visibleRows  = term.rows
liveAreaLines = min(totalLines − contentEnd, visibleRows)   // clamped to the viewport
coverHeight   = max(0, visibleHeight − liveAreaLines × cellHeight)
```

The clamp to `visibleRows` exists because `totalLines` spans the whole scrollback (hundreds of
lines) while the cover only overlays the visible viewport — without the clamp, a long live tail
drove `coverHeight` to 0 and the overlay vanished. Even with it, if the boundary is wrong (e.g. a
false verb-line match far up the buffer) the live region fills the viewport and the cover collapses
to 0 — which is exactly how the §4 bugs manifested visually.

### 2.7 Transcript metadata garnish (the only JSONL crossover) [impl]

`refreshTranscriptCache()` (polls every 10s) calls `window.uai.transcript.read(sessionName,
sessionId, 'structured')` (→ `read_jsonl.py`), and `matchSectionsToTranscript()` aligns those
messages to the terminal-derived sections to inject two cosmetic fields into section headers: the
**message number** (`#686`) and a **timestamp**. This never affects markers, sectioning, colors, or
the boundary. If it fails, formatting is unaffected.

### 2.8 Section rendering, collapse, sticky type

- `groupIntoSections()` collapses runs of one type into `Section` groups; each renders as a card
  with a colored left border + label (`SECTION_COLORS`/`SECTION_BG` by type).
- Thinking body text is rendered by stripping ANSI and forcing `THINKING_TEXT_COLOR` (`#e3ccff`),
  because Claude renders thinking dim-grey via ANSI which would otherwise override the intended
  color. [impl]
- Tool/thinking sections are collapsible (per-section), with expand/collapse-all-of-type filters.
- **Sticky class** [impl, partial]: `stickyClassRef` keeps a `⏺` line classified as `tool` across
  polls even as streaming changes its content, keyed on the first ~60 chars of stripped text.

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
  promptStart, contentEnd, liveAreaLines, coverHeightPx, cellHeightPx, termRows}, `sectionCount`,
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

**Meta-lesson:** the marker/verb-line rules are precise and empirically derived (column-0 = marker;
ellipsis tied to gerund; completed counts). Loosening them — matching glyphs anywhere, ellipsis
anywhere — caused ~90% of Memorex defects. Follow the spec exactly.

---

## 5. Proposed: Standalone, reusable, cross-platform Memorex [proposed]

Goal: a Memorex that is **independent of the UAI app**, reusable by others, with **all formatting
configurable**, running on **Windows, macOS, and Linux**.

### 5.1 Shape

A small, dependency-light **library** with three clean seams:

```
            ┌──────────────────────────────────────────────┐
  terminal  │  INPUT          CORE              OUTPUT      │  render target
  text  ───▶│  adapter  ─▶  formatter  ─▶  view model / DOM │─▶ (DOM, or
  stream    │  (capture)   (pure, config) (renderer-agnostic)│   serialized)
            └──────────────────────────────────────────────┘
                              ▲
                         config (markers, colors, rules)
```

- **Input adapter** — supplies raw terminal text (ANSI-preserving) on demand or as a stream. The
  core never talks to the OS. Adapters: tmux (`capture-pane`) on mac/Linux; ConPTY / Windows
  Terminal / WezTerm / a PTY lib on Windows; or a plain string for testing. This isolates the only
  OS-specific part.
- **Core formatter** — **pure function(s)**: `(text, config) → ViewModel`. No DOM, no OS, no app
  deps. Contains the marker rule, sub-typing, boundary detection, sectioning. Fully unit-testable
  with string fixtures.
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
- **`boundary`** — `{ rule: "lowest-verb-line", stickyMarkers: true }`.
- **`platforms`** — named bundles of the above for claude/codex/gemini, selectable at runtime.

### 5.3 Cross-platform considerations

- **Capture** is the only OS-specific seam — confined to input adapters. The formatter and config
  are pure and portable.
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
const view = mx.format(rawTerminalText);      // pure → ViewModel
mx.renderTo(domNode, view);                   // or: JSON.stringify(view)
mx.on('boundaryChange' | 'sections', cb);     // events for hosts
```

### 5.5 Migration path

1. Extract the pure functions (`classifyLine`, `groupIntoSections`, `findContentEnd`,
   `findPromptAreaStart`, ANSI parsing) out of `TerminalFormatOverlay.tsx` into a standalone,
   app-free package with a `MemorexConfig`.
2. Replace the hardcoded glyph/color constants with config defaults (claude/codex/gemini bundles).
3. Re-host the current overlay on top of the extracted core (UAI becomes one consumer).
4. Add the command-bus action surface (§3 gap) at the UAI-host layer, not the core.
5. Add a Windows input adapter; validate glyph handling on all three OSes with string fixtures +
   live capture.

### 5.6 Stability constraint

Memorex has been stable in production; the user is (rightly) protective of it. The extraction
should be **behavior-preserving** — port the exact rules in §2.5, with the pure-function tests
locking current behavior before any refactor.
