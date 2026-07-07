# Design Tokens — migration contract (todo_0384)

Single source of truth for the UAI token migration. Every subagent migrating a
surface MUST use this map so the whole app converges on one palette. Themes then
work by overriding these tokens in a `[data-theme="…"]` block — see `themes.css`.

## The rule
Replace hardcoded color/size literals in inline React styles and in `styles.css`
rules with `var(--token)`. A wrong token shows immediately in the build, so
migrate → `tsc` the file → move on.

## Token vocabulary (defined in `app/renderer/styles/styles.css :root`)

| Token | Value | Use for |
|---|---|---|
| `--bg-deep` | #0a0c10 | app/page background, input field fills |
| `--bg-panel` | #12151c | panels, selects, content blocks |
| `--bg-card` | #1a1e2a | cards, raised/active list rows |
| `--bg-hover` | #222838 | hover fills, neutral buttons |
| `--border` | #2a3148 | default borders/dividers |
| `--border-strong` | #3d4663 | emphasized borders |
| `--border-bright` | #606d94 | brightest borders |
| `--text` | #e0e8ff | primary text |
| `--text-sec` | #9ca4c4 | secondary text/labels |
| `--text-muted` | #667090 | dim text, placeholders, disabled |
| `--accent-blue/green/yellow/red/purple/orange/cyan` | Tokyo Night | semantic accents (text/lines/icons) |
| `--status-green` | #00c896 | RUNNING/resume only |
| `--accent-blue-bg` | #23304e | accent button FILL |
| `--accent-blue-solid` / `--accent-purple-solid` | #2f6df0 / #7c4ddb | saturated overlay-header fills |
| `--overlay-note-bg` / `--overlay-hamilton-bg` (+ `-border`) | | colored dialog bodies |
| `--size-xs…lg` | 10–14px | font sizes |
| `--sp-xs…lg` | 4–16px | spacing |
| `--radius-sm/md` | 3/6px | corner radii |
| `--font-mono` / `--font-ui` | | font families |

## Exact hex → token map (apply verbatim)

```
# backgrounds
#0a0c10 #0c0e14 #0b0e14                -> var(--bg-deep)
#12151c #11141c #10141d                -> var(--bg-panel)
#1a1e2a #161b27 #172633                -> var(--bg-card)
#222838 #1b2230                        -> var(--bg-hover)
# borders
#2a3148 #232a3a #181c26 #1c2230 #24384a -> var(--border)
#3d4663 #333a4a #2b3446 #294056        -> var(--border-strong)
#606d94 #414868                        -> var(--border-bright)
# text
#e0e8ff #cfd4de #dce3ef #d0d8f0 #c0caf5 #cdd6ee -> var(--text)
#9ca4c4 #9aa3b3 #8a93a6                -> var(--text-sec)
#667090 #7b8696 #566270 #565f89 #565f80 -> var(--text-muted)
# accents (exact palette matches)
#7aa2f7 #3b5bdb -> var(--accent-blue)      #23304e -> var(--accent-blue-bg)
#9ece6a #5cd693 #8ce0ad -> var(--accent-green)
#e0af68 -> var(--accent-yellow)            #f7768e -> var(--accent-red)
#bb9af7 -> var(--accent-purple)            #ff9e64 #e8915c -> var(--accent-orange)
#7dcfff -> var(--accent-cyan)              #00c896 -> var(--status-green)
```

For any hex NOT above: map to the **nearest token by ROLE** (is it a bg? a
border? text? an accent?). If a color is genuinely semantic and has no home,
add it to `## Proposed tokens` at the bottom of THIS file (name + value + why)
— do NOT invent a silent one-off literal.

## EXCLUSIONS — do NOT migrate these

1. **`utils/session-color.ts`** — the per-session identity hash palette. It is
   deliberately its own color space; leave every hex literal alone.
2. **Any `USER_COLOR` / identity swatch** (e.g. `#e8c07a`) — leave literal.
3. **xterm `theme: { … }` objects** in `TerminalPane.tsx` / `StandaloneTerminal.tsx`
   — that's the TERMINAL's ANSI color identity, not app chrome. Leave the theme
   object literal; DO tokenize the surrounding UI chrome (toolbars, borders, labels).
4. **`TerminalFormatOverlay.tsx` (Memorex)** — deferred entirely this pass; it has
   hard design constraints (see `components/DESIGN.md` + `docs/designs/memorex.md`).
5. Pure `#fff` / `#000` / `transparent` and `rgba(…)` — leave unless it's clearly a
   chrome color with an obvious token; when in doubt, leave it.

## Per-file protocol (for each migrating subagent)
1. Apply the exact map above (script or edit) to the file's inline styles.
2. Review contextual cases (same hex, two roles) and pick the right token by role.
3. Run `npx tsc --noEmit -p packages/renderer-ui/tsconfig.json` and confirm YOUR
   file has no new errors (ignore pre-existing errors in other files).
4. Report: file, count of literals migrated, any residual literals (with reason),
   any `## Proposed tokens` you added.
5. Do NOT run the deploy build (`uai.sh`) — the orchestrator does the integrated
   build. Do NOT touch `styles.css` or files outside your assignment.

## Proposed tokens
(subagents append here: `--name: #value;  /* why */`)

--attention-bg: #160f0c;  /* warm-dark background for the "Needs PianoMan" attention region in LiveBoardPane (paired with --accent-orange text); no existing bg token fits this amber-tinted alert surface. Used in code as var(--attention-bg, #160f0c). */

<!-- AskHamiltonLine.tsx — Ask Hamilton warm/orange pill + needs-PianoMan counter.
     Same warm "attention" family as --attention-bg above (pill bg reuses --attention-bg;
     icon/text oranges map to var(--accent-orange)). These are the remaining warm
     FILL/BORDER surfaces with no neutral home (all bg/border tokens are blue-neutral). -->
--attention-border: #3a2a1c;        /* Ask Hamilton pill border — warm */
--attention-badge-bg: #3a1f12;      /* needs-PianoMan counter badge fill */
--attention-badge-border: #6b3d22;  /* needs-PianoMan counter badge border */

<!-- SessionTitleBar/Navigator migration: platform & web-AI BRAND-identity colors, left literal per exclusion #2 (distinct brand hues, NOT the Tokyo Night accent palette). Proposing named tokens so brand literals can converge; if accepted, migrate the referenced literals, else they stay literal as identity. -->
--platform-claude:  #e07a4a;  /* Claude CLI brand orange — SessionTitleBar.PLATFORM_COLORS + Navigator web-AI 'C' marker */
--platform-codex:   #8b5cf6;  /* Codex CLI brand purple — SessionTitleBar.PLATFORM_COLORS */
--platform-gemini:  #4285f4;  /* Gemini/Google brand blue — SessionTitleBar.PLATFORM_COLORS + Navigator web-AI 'G' marker */
--brand-chatgpt:    #74aa9c;  /* ChatGPT brand green — Navigator web-AI 'G' marker */
--brand-perplexity: #bb9af7;  /* Perplexity marker (coincides w/ --accent-purple) — Navigator web-AI 'P' marker */
