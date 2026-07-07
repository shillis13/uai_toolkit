import { describe, it, expect } from 'vitest';
import { dedupConsecutiveBlocks } from '@uai/renderer-ui/components/memorex-dedup';

describe('dedupConsecutiveBlocks — re-render scrollback corruption cleanup', () => {
  it('removes a verbatim consecutive block duplication (Revenant shape)', () => {
    // P, blank, Q — committed twice back-to-back
    const block = [
      '2.3 + 4.1 — prompt area already has text (occupied): one shared policy',
      "clear-watcher). Alternative skip: don't write, report which were busy",
      'hold-vs-skip; I lean hold with a delivered/held/skipped report.',
      '',
      '2.2 — mixing CLI "Prompt Area" vs UAI "Prompt Box": one tool',
      'meaningful: type-only vs type+Enter. A UAI-native surface is the box',
      "your 2.2). submit honored only where meaningful.",
    ];
    expect(dedupConsecutiveBlocks([...block, ...block])).toEqual(block);
  });

  it('handles partial-then-fuller (Broken-Clock shape): drops partial, keeps continuation', () => {
    const input = ['Answer', 'gone', 'reclaim', 'Answer', 'gone', 'reclaim', 'complete', 'TO YOU'];
    expect(dedupConsecutiveBlocks(input)).toEqual(['Answer', 'gone', 'reclaim', 'complete', 'TO YOU']);
  });

  it('leaves legit table borders untouched (single-line repeats with content between)', () => {
    const table = ['| a | b |', '|---+---|', '| c | d |', '|---+---|', '| e | f |', '|---+---|'];
    expect(dedupConsecutiveBlocks(table)).toEqual(table);
  });

  it('leaves a non-consecutive repeat untouched (same command run again later)', () => {
    const input = ['line one', 'line two', 'line three', 'other', 'line one', 'line two', 'line three'];
    expect(dedupConsecutiveBlocks(input)).toEqual(input);
  });

  it('does not collapse a blank-only run (block must contain a non-blank line)', () => {
    const input = ['', '', '', '', '', '', ''];
    expect(dedupConsecutiveBlocks(input)).toEqual(input);
  });

  it('leaves a 2-line consecutive repeat alone (below the k>=3 threshold)', () => {
    const input = ['aa', 'bb', 'aa', 'bb'];
    expect(dedupConsecutiveBlocks(input)).toEqual(input);
  });

  it('is a no-op on short input', () => {
    expect(dedupConsecutiveBlocks(['x', 'y'])).toEqual(['x', 'y']);
  });

  it('collapses two full duplicate copies down to one', () => {
    const one = ['alpha', 'beta', 'gamma', 'delta'];
    expect(dedupConsecutiveBlocks([...one, ...one])).toEqual(one);
  });

  it('dedups despite interleaved blank lines (double-spacing corruption)', () => {
    // A content block with blanks interleaved, committed twice. The match is on the
    // non-blank content sequence, so the blanks don't defeat it; the second copy's
    // span (with its blanks) is dropped, the first copy (with its blanks) kept.
    const copy = ['46. fox', '', '47. fox', '48. fox', '', '49. fox'];
    expect(dedupConsecutiveBlocks([...copy, ...copy])).toEqual(copy);
  });

  it('dedups when the two copies have DIFFERENT interleaved blanks', () => {
    const first = ['46. fox', '', '47. fox', '48. fox', '49. fox'];
    const second = ['46. fox', '47. fox', '', '48. fox', '49. fox']; // same content, blanks moved
    // content sequence matches → second copy's content span removed, first kept
    expect(dedupConsecutiveBlocks([...first, ...second])).toEqual(first);
  });
});
