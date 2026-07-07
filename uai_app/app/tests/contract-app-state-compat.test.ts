/**
 * Contract Test: app_state tab compatibility
 *
 * Legacy persisted tabs predate the typed Tab model and may still use
 * sessionTrackingId without type/targetId. These should hydrate as session tabs.
 */

import { describe, expect, it } from 'vitest';
import { normalizePersistedAppState } from '../main/command-handlers';

describe('app_state tab compatibility', () => {
  it('normalizes legacy sessionTrackingId tabs into typed session tabs', () => {
    const { state, changed } = normalizePersistedAppState({
      tabs: [
        {
          id: 'tab_legacy_1',
          sessionTrackingId: '20260419_185845_74a2944e_cla',
          label: 'Condenser-claude',
          openedAt: '2026-04-25T02:34:27.985Z',
        },
      ],
      activeTabId: 'tab_legacy_1',
    });

    expect(changed).toBe(true);
    expect(state.activeTabId).toBe('tab_legacy_1');
    expect(state.tabs).toEqual([
      {
        id: 'tab_legacy_1',
        type: 'session',
        targetId: '20260419_185845_74a2944e_cla',
        label: 'Condenser-claude',
        openedAt: '2026-04-25T02:34:27.985Z',
      },
    ]);
  });

  it('preserves modern typed tabs without rewriting them', () => {
    const input = {
      tabs: [
        {
          id: 'tab_modern_1',
          type: 'transcript',
          targetId: '20260419_185845_74a2944e_cla',
          label: 'Transcript',
          openedAt: '2026-05-12T00:00:00.000Z',
        },
      ],
      activeTabId: 'tab_modern_1',
    };

    const { state, changed } = normalizePersistedAppState(input);

    expect(changed).toBe(false);
    expect(state).toBe(input);
  });
});
