# DESIGN constraints — renderer-ui components

Read this before modifying files in this directory. The full design authority for
the Memorex overlay is **`docs/designs/memorex.md`** — read it before touching
`TerminalFormatOverlay.tsx`.

PianoMan is the spec authority for Memorex. When his guidance is specific, follow it
exactly — do not "improve" it. Most Memorex bugs have come from loosening his spec.

## TerminalFormatOverlay.tsx (Memorex) — hard constraints

Memorex draws a formatted "cover" over the **settled** region of the live tmux
terminal (scraped text, NOT the JSONL transcript). The cover height is derived from
where the *live tail* begins (`findContentEnd`). If that boundary is wrong, the cover
collapses to 0px and the overlay vanishes. Treat these as invariants:

1. **Verb-line detection — active form is the gerund-tied ellipsis only.**
   `<glyph> <gerund>…` with the ellipsis immediately after the first word
   (`/^\S\s+\S+…/`). The ellipsis is **stable** — it does NOT animate `.`→`..`→`…`.
   - **Do NOT anchor on the elapsed-time token `(<N>s`.** It is absent much of the
     time and its format is highly variable. (A 2026-06-18 attempt to anchor on it
     was reverted.)
   - Do NOT match a bare `…` anywhere on the line — that flags ordinary content and
     collapses the overlay.
   - Completed form: `<glyph> <word> for <N>[hms]` (`/^\S\s+\S+\s+for\s+\d+\s*[hms]/`).
   - Glyphs animate through an open-ended set (✻ ✽ ✳ · ✢ …) — match by STRUCTURE,
     never by enumerating glyphs.

2. **The live-tail verb line must be NEAR the prompt.** Completed verb lines persist
   in scrollback (a settled buffer holds several). `findContentEnd` must NOT latch a
   stale verb line far above the viewport — that collapses the cover and blanks the
   whole overlay during active responses. Bound the upward scan to a live-tail window;
   if none is found, fall back to `promptStart`.

3. **Blanking is never acceptable.** Every boundary/geometry change must fail toward
   *covering more* (formatting a few still-settling lines), never toward a 0px cover.

4. **Verify against real captured terminal data before claiming a fix.** Use
   `session_ops.py read-terminal <name>` for a real buffer, and the live `window.__memorex`
   state (DevTools / CDP 9226 / `uai:memorex:state`) to confirm the boundary in a
   running app. Do not ship Memorex changes on reasoning alone.

5. **Column model:** markers sit at **column 0**; assistant content is indented to
   **column 2**. The sticky-cache key trims trailing whitespace only (preserves the
   leading margin) so col-0 vs col-2 lines don't collide.
