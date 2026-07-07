/**
 * Memorex re-render corruption cleanup — pure, DOM-free (unit-testable).
 *
 * When the CLI repaints an overflowing response (a genuine window/panel resize we
 * couldn't fully avoid, or Claude Code's own re-render), it can commit the same
 * block of lines to the scrollback twice in a row — sometimes cleanly, sometimes
 * with extra blank lines interleaved. Memorex scrapes that corrupted scrollback, so
 * we clean it up at the display layer. See todo_0341.
 */

/**
 * Remove a run of lines that duplicates the run immediately before it — matching on
 * the NON-BLANK content sequence, so interleaved blank lines (the double-spacing the
 * re-render also inserts) don't defeat the match. Also handles the "partial-then-
 * fuller" shape (Broken-Clock): the partial copy is a verbatim content-prefix of the
 * fuller copy, so the partial's prefix is dropped and the continuation kept.
 *
 * Conservative on purpose:
 *  - requires >= MIN (3) consecutive NON-BLANK content lines to repeat verbatim.
 *    Legit table borders are single lines with differing content between them (never
 *    a 3-content-line verbatim block repeat), and a command legitimately run twice is
 *    not *consecutive* — both are left untouched.
 *  - removes only the second copy's content span (its first→last content line, with
 *    any blanks between); trailing blanks stay (Memorex collapses blank runs anyway).
 *  - bounded (size + block-length caps) so it can't get pathological on a huge section.
 *
 * Validated against the real Revenant + Broken-Clock captures, an interleaved-blank
 * reproduction, and legit-content counterexamples.
 */
export function dedupConsecutiveBlocks(lines: string[]): string[] {
  const MIN = 3;
  if (lines.length < MIN * 2 || lines.length > 800) return lines;
  let out = lines.slice();
  let changed = true;
  while (changed) {
    changed = false;
    // Indices of the non-blank ("content") lines, in order.
    const ci: number[] = [];
    for (let i = 0; i < out.length; i++) if (out[i].trim() !== '') ci.push(i);

    for (let a = 0; a < ci.length && !changed; a++) {
      const maxK = Math.min((ci.length - a) >> 1, 80);
      for (let k = maxK; k >= MIN; k--) {
        let match = true;
        for (let j = 0; j < k; j++) {
          if (out[ci[a + j]] !== out[ci[a + k + j]]) { match = false; break; }
        }
        if (match) {
          // Drop the second copy's span: its first content line → its last content
          // line (inclusive of any blanks interleaved within that span).
          const startDel = ci[a + k];
          const endDel = ci[a + 2 * k - 1];
          out.splice(startDel, endDel - startDel + 1);
          changed = true;
          break;
        }
      }
    }
  }
  return out;
}
