/**
 * Contract Test: Tab Normalization
 *
 * Validates that normalizePersistedAppState correctly handles legacy,
 * malformed, and valid tab data from persisted app_state.json.
 *
 * normalizePersistedTab is module-private, so all tests go through
 * the public normalizePersistedAppState entry point.
 */

import { describe, it, expect } from 'vitest';
import { normalizePersistedAppState } from '../main/command-handlers';

// Helper: build a fully valid modern tab
function validTab(overrides: Record<string, unknown> = {}) {
  return {
    id: 'tab_valid_1',
    type: 'session',
    targetId: '20260501_120000_abc12345_cla',
    label: 'My Session',
    openedAt: '2026-05-01T12:00:00.000Z',
    ...overrides,
  };
}

describe('Tab normalization — normalizePersistedAppState', () => {

  // ── 1. Valid tab passes through unchanged ──────────────────────────────

  it('valid tab with all fields passes through unchanged', () => {
    const tab = validTab();
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(false);
    expect(state).toBe(input); // identity — no rewrite
    expect(state.tabs).toEqual([tab]);
  });

  // ── 2. Tab missing `type` defaults to 'session' ──────────────────────

  it('tab missing type defaults to session', () => {
    const tab = validTab();
    delete (tab as Record<string, unknown>).type;
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].type).toBe('session');
  });

  // ── 3. Tab with invalid type defaults to 'session' ───────────────────

  it('tab with invalid type defaults to session', () => {
    const tab = validTab({ type: 'bogus' });
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].type).toBe('session');
  });

  // ── 4. Legacy sessionTrackingId migrates to targetId ──────────────────

  it('tab with legacy sessionTrackingId migrates to targetId', () => {
    const legacyTab = {
      id: 'tab_legacy_1',
      sessionTrackingId: '20260501_120000_abc12345_cla',
      label: 'Legacy Tab',
      openedAt: '2026-05-01T12:00:00.000Z',
    };
    const input = { tabs: [legacyTab], activeTabId: 'tab_legacy_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].targetId).toBe('20260501_120000_abc12345_cla');
    expect(tabs[0]).not.toHaveProperty('sessionTrackingId');
    expect(tabs[0].type).toBe('session');
  });

  // ── 5. Tab with no targetId and no sessionTrackingId is dropped ───────

  it('tab with no targetId and no sessionTrackingId is dropped', () => {
    const emptyTab = {
      id: 'tab_empty_1',
      type: 'session',
      label: 'Orphan',
      openedAt: '2026-05-01T12:00:00.000Z',
    };
    const input = { tabs: [emptyTab], activeTabId: 'tab_empty_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(0);
  });

  // ── 6. Tab missing `id` gets a generated one ─────────────────────────

  it('tab missing id gets a generated id', () => {
    const tab = validTab();
    delete (tab as Record<string, unknown>).id;
    const input = { tabs: [tab], activeTabId: '' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].id).toBeTypeOf('string');
    expect((tabs[0].id as string).length).toBeGreaterThan(0);
    expect((tabs[0].id as string)).toMatch(/^tab_legacy_/);
  });

  // ── 7. Tab missing `label` uses targetId as label ─────────────────────

  it('tab missing label uses targetId as label', () => {
    const tab = validTab();
    delete (tab as Record<string, unknown>).label;
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].label).toBe('20260501_120000_abc12345_cla');
  });

  // ── 8. Mixed valid/invalid tabs filters correctly ─────────────────────

  it('mixed valid and invalid tabs filters correctly', () => {
    const goodTab = validTab({ id: 'tab_good' });
    const badTab = { id: 'tab_bad', type: 'session', label: 'No Target' }; // no targetId
    const legacyTab = {
      id: 'tab_legacy_2',
      sessionTrackingId: '20260502_130000_def67890_cla',
      label: 'Legacy',
      openedAt: '2026-05-02T13:00:00.000Z',
    };
    const input = {
      tabs: [goodTab, badTab, legacyTab],
      activeTabId: 'tab_good',
    };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    // goodTab preserved, badTab dropped, legacyTab migrated
    expect(tabs).toHaveLength(2);
    expect(tabs[0].id).toBe('tab_good');
    expect(tabs[1].id).toBe('tab_legacy_2');
    expect(tabs[1].targetId).toBe('20260502_130000_def67890_cla');
  });

  // ── 9. changed: true when normalization occurs ─────────────────────────

  it('reports changed: true when normalization modifies tabs', () => {
    const tab = validTab({ type: 'bogus' });
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
  });

  // ── 10. changed: false when tabs are already clean ─────────────────────

  it('reports changed: false when all tabs are already clean', () => {
    const tab = validTab();
    const input = { tabs: [tab], activeTabId: 'tab_valid_1' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(false);
    // State should be the same object reference — no rewrite occurred
    expect(state).toBe(input);
  });

  // ── 11. activeTabId pointing to removed tab gets reassigned ────────────

  it('activeTabId pointing to a removed tab gets reassigned', () => {
    const goodTab = validTab({ id: 'tab_survivor' });
    const badTab = { id: 'tab_doomed', type: 'session', label: 'No Target' }; // dropped
    const input = {
      tabs: [goodTab, badTab],
      activeTabId: 'tab_doomed',
    };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    // activeTabId should be reassigned to the last surviving tab
    expect(state.activeTabId).toBe('tab_survivor');
  });

  // ── Edge cases ─────────────────────────────────────────────────────────

  it('activeTabId set to null when all tabs are dropped', () => {
    const badTab = { id: 'tab_only', type: 'session', label: 'No Target' };
    const input = {
      tabs: [badTab],
      activeTabId: 'tab_only',
    };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    expect((state.tabs as unknown[]).length).toBe(0);
    expect(state.activeTabId).toBeNull();
  });

  it('handles missing tabs property (not an array) gracefully', () => {
    const input = { activeTabId: 'tab_gone' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    expect(state.tabs).toEqual([]);
    expect(state.activeTabId).toBeNull();
  });

  it('non-object tab entries are dropped', () => {
    const input = {
      tabs: ['not-an-object', 42, null, validTab()],
      activeTabId: 'tab_valid_1',
    };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(true);
    const tabs = state.tabs as Array<Record<string, unknown>>;
    expect(tabs).toHaveLength(1);
    expect(tabs[0].id).toBe('tab_valid_1');
  });

  it('all valid TabType values are accepted', () => {
    const validTypes = ['session', 'folder', 'group', 'terminal', 'brief', 'transcript', 'search'];
    const tabs = validTypes.map((type, i) => validTab({
      id: `tab_type_${i}`,
      type,
      targetId: `target_${i}`,
    }));
    const input = { tabs, activeTabId: 'tab_type_0' };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(false);
    expect((state.tabs as unknown[]).length).toBe(validTypes.length);
  });
});
