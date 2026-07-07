import { describe, it, expect } from 'vitest';
import {
  reminderHasContent,
  reminderFires,
  wrapWithReminder,
  applyReminder,
} from '@uai/renderer-ui/components/prompt-reminder';
import type { PromptReminder } from '@uai/shared/types';

const base = (over: Partial<PromptReminder> = {}): PromptReminder => ({
  enabled: true,
  cadence: 'every',
  prepend: 'REMEMBER: commit via Git Guardian.',
  ...over,
});

describe('reminderHasContent', () => {
  it('false when disabled', () => {
    expect(reminderHasContent(base({ enabled: false }))).toBe(false);
  });
  it('false when both sides blank', () => {
    expect(reminderHasContent(base({ prepend: '   ', append: '' }))).toBe(false);
  });
  it('true with a prepend', () => {
    expect(reminderHasContent(base())).toBe(true);
  });
  it('true with only an append', () => {
    expect(reminderHasContent(base({ prepend: '', append: 'end note' }))).toBe(true);
  });
  it('false for undefined/null', () => {
    expect(reminderHasContent(undefined)).toBe(false);
    expect(reminderHasContent(null)).toBe(false);
  });
});

describe('reminderFires — cadence', () => {
  it("'every' fires on every send", () => {
    const r = base({ cadence: 'every' });
    expect([0, 1, 2, 5, 99].map(c => reminderFires(r, c))).toEqual([true, true, true, true, true]);
  });
  it("'once' fires (caller disables after)", () => {
    expect(reminderFires(base({ cadence: 'once' }), 0)).toBe(true);
  });
  it("'nth' fires on send #1 then every N (n=3 → sends 0,3,6)", () => {
    const r = base({ cadence: 'nth', n: 3 });
    expect([0, 1, 2, 3, 4, 5, 6].map(c => reminderFires(r, c))).toEqual([
      true, false, false, true, false, false, true,
    ]);
  });
  it("'nth' clamps n<2 up to 2", () => {
    const r = base({ cadence: 'nth', n: 1 });
    expect([0, 1, 2, 3].map(c => reminderFires(r, c))).toEqual([true, false, true, false]);
  });
  it("'nth' defaults n to 3 when unset", () => {
    const r = base({ cadence: 'nth' });
    expect([0, 3].map(c => reminderFires(r, c))).toEqual([true, true]);
    expect(reminderFires(r, 1)).toBe(false);
  });
  it('never fires when content is empty', () => {
    expect(reminderFires(base({ prepend: '', append: '' }), 0)).toBe(false);
  });
});

describe('wrapWithReminder', () => {
  it('prepend only', () => {
    expect(wrapWithReminder('do X', base({ prepend: 'PRE', append: '' })))
      .toBe('PRE\n\ndo X');
  });
  it('append only', () => {
    expect(wrapWithReminder('do X', base({ prepend: '', append: 'POST' })))
      .toBe('do X\n\nPOST');
  });
  it('both sides', () => {
    expect(wrapWithReminder('do X', base({ prepend: 'PRE', append: 'POST' })))
      .toBe('PRE\n\ndo X\n\nPOST');
  });
  it('trims trailing ws on prepend / leading ws on append but preserves user text', () => {
    expect(wrapWithReminder('  keep me  ', base({ prepend: 'PRE\n\n', append: '\n\nPOST' })))
      .toBe('PRE\n\n  keep me  \n\nPOST');
  });
});

describe('applyReminder — integration', () => {
  it('wraps and reports applied when it fires', () => {
    const out = applyReminder('hi', base({ cadence: 'every', prepend: 'PRE' }), 0);
    expect(out).toEqual({ text: 'PRE\n\nhi', applied: true, disableAfter: false });
  });
  it('passes text through unchanged when it does not fire', () => {
    const out = applyReminder('hi', base({ cadence: 'nth', n: 3 }), 1);
    expect(out).toEqual({ text: 'hi', applied: false, disableAfter: false });
  });
  it("'once' sets disableAfter", () => {
    const out = applyReminder('hi', base({ cadence: 'once', prepend: 'PRE' }), 4);
    expect(out.applied).toBe(true);
    expect(out.disableAfter).toBe(true);
  });
  it('disabled reminder is a no-op', () => {
    const out = applyReminder('hi', base({ enabled: false }), 0);
    expect(out).toEqual({ text: 'hi', applied: false, disableAfter: false });
  });
});
