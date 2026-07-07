import type { Meta, StoryObj } from '@storybook/react';
import ComposeMessage from './ComposeMessage';
import { ToastProvider } from './Toast';

const meta: Meta<typeof ComposeMessage> = {
  title: 'Comms/ComposeMessage',
  component: ComposeMessage,
  parameters: { layout: 'padded' },
  decorators: [
    (Story) => {
      // Mock sessions for recipient dropdown
      (window as any).uai.sessions = {
        list: () => Promise.resolve([
          { tracking_id: '20260507_001_cla', display_name: 'Continuity IIb', process_status: 'running', platform: 'claude_cli', roles: ['architect'], created_at: '', last_activity: '', tags: [], runtime_state: 'unknown', activity_state: 'unknown', context_percent: 48, exchange_count: 0, pinned: false, lastViewedAt: null, notes: null, archived: false, identity_status: 'confirmed', cli_session_id: null, terminal_session: null, session_dir: '', project_dir: '', model: null, parent_tracking_id: null },
          { tracking_id: '20260507_002_cod', display_name: 'Codex Reviewer', process_status: 'running', platform: 'codex_cli', roles: ['reviewer'], created_at: '', last_activity: '', tags: [], runtime_state: 'unknown', activity_state: 'unknown', context_percent: 23, exchange_count: 0, pinned: false, lastViewedAt: null, notes: null, archived: false, identity_status: 'confirmed', cli_session_id: null, terminal_session: null, session_dir: '', project_dir: '', model: null, parent_tracking_id: null },
        ]),
        get: () => Promise.resolve(null),
        update: () => Promise.resolve({ ok: true }),
        create: () => Promise.resolve({ ok: true, command_id: 'mock', data: { trackingId: 'mock' } }),
      };
      (window as any).uai.comms.send = () => Promise.resolve({ ok: true, messageId: 'msg_mock' });
      return <ToastProvider><Story /></ToastProvider>;
    },
  ],
};
export default meta;
type Story = StoryObj<typeof ComposeMessage>;

export const Default: Story = { args: {} };
export const WithRecipient: Story = { args: { defaultTo: '20260507_001_cla' } };
export const AsReply: Story = { args: { defaultTo: '20260507_002_cod', defaultReplyTo: 'msg_original_123' } };
