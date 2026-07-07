import type { Meta, StoryObj } from '@storybook/react';
import CardListView from './CardListView';
import type { SessionCard, AnyCard } from '@uai/shared/cards';

const meta: Meta<typeof CardListView> = {
  title: 'Cards/CardListView',
  component: CardListView,
  parameters: { layout: 'padded' },
};
export default meta;
type Story = StoryObj<typeof CardListView>;

function mockSession(overrides: Partial<SessionCard> & { tracking_id: string }): SessionCard {
  return {
    entity_id: `session:${overrides.tracking_id}`,
    entity_type: 'session',
    display_name: overrides.display_name || overrides.tracking_id,
    created_at: overrides.created_at || '2026-05-07T12:00:00Z',
    last_activity: overrides.last_activity || '2026-05-07T14:00:00Z',
    tags: overrides.tags || [],
    tracking_id: overrides.tracking_id,
    platform: overrides.platform || 'claude_cli',
    process_status: overrides.process_status || 'running',
    roles: overrides.roles || ['assistant'],
    context_percent: overrides.context_percent ?? null,
    exchange_count: overrides.exchange_count ?? 0,
    pinned: overrides.pinned ?? false,
  };
}

const sessions: AnyCard[] = [
  mockSession({ tracking_id: '20260507_001_cla', display_name: 'Continuity IIb', platform: 'claude_cli', process_status: 'running', roles: ['architect'], context_percent: 48, tags: ['uai'], pinned: true }),
  mockSession({ tracking_id: '20260507_002_cod', display_name: 'Codex Reviewer', platform: 'codex_cli', process_status: 'stopped', roles: ['peer_reviewer'], context_percent: 23, tags: ['review'] }),
  mockSession({ tracking_id: '20260507_003_gem', display_name: 'Gemini Research', platform: 'gemini_cli', process_status: 'running', roles: ['researcher'] }),
  mockSession({ tracking_id: '20260507_004_cla', display_name: 'Fork 1 — Groups', platform: 'claude_cli', process_status: 'stopped', roles: ['worker'], context_percent: 41 }),
  mockSession({ tracking_id: '20260507_005_cla', display_name: 'Fork 2 — Navigator', platform: 'claude_cli', process_status: 'stopped', roles: ['worker'], context_percent: 38 }),
];

export const Default: Story = { args: { cards: sessions } };
export const WithActiveCard: Story = { args: { cards: sessions, activeCardId: 'session:20260507_001_cla' } };
export const WithSelection: Story = { args: { cards: sessions, selectedIds: new Set(['session:20260507_002_cod', 'session:20260507_004_cla']) } };
export const Empty: Story = { args: { cards: [], emptyMessage: 'No sessions match filters.' } };
export const PinnedFirst: Story = {
  args: {
    cards: [
      mockSession({ tracking_id: 'unpinned_1', display_name: 'Unpinned Session', pinned: false }),
      mockSession({ tracking_id: 'pinned_1', display_name: 'Pinned Session', pinned: true }),
      mockSession({ tracking_id: 'unpinned_2', display_name: 'Another Unpinned', pinned: false }),
    ],
  },
};
