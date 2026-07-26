import { describe, expect, it } from 'vitest';
import {
  currentTerminalRegionStart,
  filterTerminalCandidatesForTurn,
  isActiveVerbLine,
  isCompletedVerbLine,
  provisionalReachedSettlement,
  sectionDefaultCollapsed,
  shouldDrainClosedTerminalProvisionals,
  shouldSeedUpdatedTerminalTail,
  terminalOpeningFingerprint,
  visibleActiveVerbLineIndex,
  visibleTerminalGapLineCount,
} from '@uai/renderer-ui/components/TerminalFormatOverlay';

describe('Memorex unfinished terminal region', () => {
  it('starts after the newest completed verb summary', () => {
    const lines = [
      '⏺ settled answer',
      '✻ Crunched for 2m 10s',
      '❯ next prompt',
      '∴ current thinking',
      '✻ Working carefully… (4s)',
      '────────────────────────────────',
    ];
    expect(currentTerminalRegionStart(lines, 5, true)).toBe(2);
  });

  it('falls back to the newest submitted user marker', () => {
    const lines = [
      '  settled body without a verb marker',
      '❯ next prompt',
      '⏺ current answer',
      '────────────────────────────────',
    ];
    expect(currentTerminalRegionStart(lines, 3, true)).toBe(1);
  });

  it('returns an empty live region for settled history with no safe boundary', () => {
    const lines = [
      '  settled body without a terminal marker',
      '────────────────────────────────',
    ];
    expect(currentTerminalRegionStart(lines, 1, true)).toBe(1);
  });

  it('distinguishes active and completed verb lines', () => {
    expect(isActiveVerbLine('✻ Writing code… (3s)')).toBe(true);
    expect(isCompletedVerbLine('✻ Crunched for 3m 8s')).toBe(true);
    expect(isActiveVerbLine('✻ Crunched for 3m 8s')).toBe(false);
  });

  it('uses the same type collapse default for settled and provisional cards', () => {
    expect(sectionDefaultCollapsed('tool', null)).toBe(true);
    expect(sectionDefaultCollapsed('thinking', null)).toBe(true);
    expect(sectionDefaultCollapsed('assistant', null)).toBe(false);
    expect(sectionDefaultCollapsed('tool', false)).toBe(false);
    expect(sectionDefaultCollapsed('tool', null, 'AskUserQuestion')).toBe(false);
    expect(sectionDefaultCollapsed('tool', true, 'AskUserQuestion')).toBe(true);
  });

  it('keeps repaint fingerprints stable when only a long row suffix reflows', () => {
    const shared = `⏺ ${'same opening '.repeat(10)}`;
    expect(terminalOpeningFingerprint('assistant', `${shared}first suffix`))
      .toBe(terminalOpeningFingerprint('assistant', `${shared}different suffix`));
  });

  it('does not re-seed a settled terminal tail after Transcript advances', () => {
    expect(shouldSeedUpdatedTerminalTail(
      'assistant:completed answer',
      'revision-before-settle',
      'revision-after-settle',
      new Set(),
    )).toBe(false);
    expect(shouldSeedUpdatedTerminalTail(
      'assistant:completed answer',
      'same-revision',
      'same-revision',
      new Set(['assistant:completed answer']),
    )).toBe(false);
    expect(shouldSeedUpdatedTerminalTail(
      'assistant:still streaming',
      'same-revision',
      'same-revision',
      new Set(),
    )).toBe(true);
  });

  it('suppresses consumed tails through turn closure and clears only at the next user marker', () => {
    const consumed = new Set(['assistant:old', 'assistant:repeat']);
    expect(filterTerminalCandidatesForTurn([
      { type: 'assistant', terminalFingerprint: 'assistant:old' },
    ], consumed)).toEqual([]);
    expect(consumed).toEqual(new Set(['assistant:old', 'assistant:repeat']));

    expect(filterTerminalCandidatesForTurn([
      { type: 'assistant', terminalFingerprint: 'assistant:old' },
      { type: 'user', terminalFingerprint: 'user:new turn' },
      { type: 'assistant', terminalFingerprint: 'assistant:repeat' },
    ], consumed)).toEqual([
      { type: 'user', terminalFingerprint: 'user:new turn' },
      { type: 'assistant', terminalFingerprint: 'assistant:repeat' },
    ]);
    expect(consumed.size).toBe(0);
  });

  it('drains closed-turn provisionals after settlement or the bounded grace', () => {
    expect(provisionalReachedSettlement(120, 119)).toBe(false);
    expect(provisionalReachedSettlement(120, 120)).toBe(true);
    expect(provisionalReachedSettlement(undefined, 120)).toBe(false);
    expect(shouldDrainClosedTerminalProvisionals(true, 9999)).toBe(false);
    expect(shouldDrainClosedTerminalProvisionals(true, 10000)).toBe(true);
    expect(shouldDrainClosedTerminalProvisionals(false, 50000)).toBe(false);
  });

  it('exposes only visible terminal rows from the active verb downward', () => {
    const lines = [
      'settled history',
      '✻ Cogitating… (4s)',
      '□ task',
      '────────────────────',
      '❯ prompt',
      'status',
      '',
      '',
      '',
      '',
    ];
    // Four captured trailing blanks but only one is actually visible in xterm.
    // The real gap is verb + task + prompt chrome + one visible blank = 6 rows.
    expect(visibleTerminalGapLineCount(lines, 1, 20, 1)).toBe(6);
    expect(visibleTerminalGapLineCount(lines, null, 20, 1)).toBe(0);
    expect(visibleTerminalGapLineCount(lines, 1, 4, 1)).toBe(4);
  });

  it('ignores an active-looking verb outside the visible terminal rows', () => {
    const lines = [
      '✻ Stale-looking… (90s)',
      ...Array.from({ length: 20 }, (_, i) => `history ${i}`),
      '✻ Cogitating… (4s)',
      '□ task',
      '────────────────────',
      '❯ prompt',
      'status',
      '',
      '',
      '',
    ];
    expect(visibleActiveVerbLineIndex(lines, 0, 26, 8, 1)).toBe(21);
    expect(visibleActiveVerbLineIndex(lines, 0, 21, 8, 1)).toBeNull();
  });
});
