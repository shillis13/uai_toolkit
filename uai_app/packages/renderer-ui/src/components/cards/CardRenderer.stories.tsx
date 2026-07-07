import type { Meta, StoryObj } from '@storybook/react';
import CardRenderer from './CardRenderer';
import type { SessionCard, BriefCard, FolderCard, GroupCard, ProjectCard } from '@uai/shared/cards';

const meta: Meta<typeof CardRenderer> = {
  title: 'Cards/CardRenderer',
  component: CardRenderer,
  parameters: { layout: 'padded' },
};
export default meta;
type Story = StoryObj<typeof CardRenderer>;

const mockSession: SessionCard = {
  entity_id: 'session:20260507_120000_abcd1234_cla',
  entity_type: 'session',
  display_name: 'Continuity IIb',
  created_at: '2026-05-07T12:00:00Z',
  last_activity: '2026-05-07T14:30:00Z',
  tags: ['uai', 'phase-2'],
  tracking_id: '20260507_120000_abcd1234_cla',
  platform: 'claude_cli',
  process_status: 'running',
  roles: ['architect'],
  context_percent: 48,
  exchange_count: 136,
  pinned: true,
};

const mockSessionStopped: SessionCard = {
  entity_id: 'session:20260506_090000_efgh5678_cod',
  entity_type: 'session',
  display_name: 'Codex Reviewer',
  created_at: '2026-05-06T09:00:00Z',
  last_activity: '2026-05-06T11:45:00Z',
  tags: ['review'],
  tracking_id: '20260506_090000_efgh5678_cod',
  platform: 'codex_cli',
  process_status: 'stopped',
  roles: ['peer_reviewer'],
  context_percent: 23,
  exchange_count: 42,
};

const mockBrief: BriefCard = {
  entity_id: 'brief:Continuity_IIb',
  entity_type: 'brief',
  display_name: 'Continuity IIb -- UAI Resurrection',
  created_at: '2026-04-25T00:00:00Z',
  last_activity: '2026-04-25T03:23:07Z',
  tags: [],
  name: 'Continuity_IIb',
  description: 'Session brief covering UAI architecture design, spike, Phase 1 build, and Phase 2 start',
  status: 'active',
  brief_path: '/mock/path/Continuity_IIb.yml',
  file_size: 28672,
};

const mockFolder: FolderCard = {
  entity_id: 'folder:all_sessions',
  entity_type: 'folder',
  display_name: 'All Sessions',
  created_at: '',
  last_activity: '',
  tags: [],
  builtin: true,
  container: { children: [], sub_containers: [], placement_rule: 'exclusive' },
};

const mockGroup: GroupCard = {
  entity_id: 'group:uai_team',
  entity_type: 'group',
  display_name: 'UAI Team',
  created_at: '2026-05-01T00:00:00Z',
  last_activity: '2026-05-07T14:00:00Z',
  tags: [],
  container: {
    children: ['session:abc', 'session:def', 'session:ghi'],
    sub_containers: [],
    placement_rule: 'non-exclusive',
  },
};

const mockProject: ProjectCard = {
  entity_id: 'project:uai-resurrection',
  entity_type: 'project',
  display_name: 'uai-resurrection',
  created_at: '2026-04-21T00:00:00Z',
  last_activity: '2026-05-07T00:00:00Z',
  tags: ['devtree'],
  project_id: 'uai-resurrection',
  working_dir: '/Users/test/devTrees/AI_ROOT_uai-resurrection',
  branch: 'dev/uai-resurrection',
  status: 'dirty',
  assigned_ais: [],
  source_path: '/Users/test/devTrees/AI_ROOT_uai-resurrection/ai_general',
  availability: 'available',
  session_count: 12,
};

export const RunningSession: Story = { args: { card: mockSession } };
export const StoppedSession: Story = { args: { card: mockSessionStopped } };
export const ActiveBrief: Story = { args: { card: mockBrief } };
export const BuiltinFolder: Story = { args: { card: mockFolder } };
export const GroupWithMembers: Story = { args: { card: mockGroup } };
export const DirtyProject: Story = { args: { card: mockProject } };
export const ActiveCard: Story = { args: { card: mockSession, active: true } };
export const SelectedCard: Story = { args: { card: mockSession, selected: true } };
