import { describe, it, expect } from 'vitest';
import type {
  BaseCard, ContainerCapability, SessionCard, BriefCard,
  FolderCard, ProjectCard, AnyCard, PlacementRule, ContainerType,
} from '../../architecture/contracts';
import { makeEntityId, parseEntityId } from '../../architecture/contracts';

describe('Card type system contracts', () => {
  it('BaseCard has required fields', () => {
    const card: BaseCard = {
      entity_id: 'session:test_123',
      entity_type: 'session',
      display_name: 'Test Session',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T01:00:00Z',
      tags: ['dev'],
    };
    expect(card.entity_id).toBe('session:test_123');
    expect(card.entity_type).toBe('session');
    expect(card.container).toBeUndefined();
  });

  it('ContainerCapability defines children and placement rule', () => {
    const cap: ContainerCapability = {
      children: ['session:a', 'session:b'],
      sub_containers: ['folder:child1'],
      placement_rule: 'exclusive',
    };
    expect(cap.placement_rule).toBe('exclusive');
    expect(cap.children).toHaveLength(2);
  });

  it('FolderCard has container capability with exclusive placement', () => {
    const folder: FolderCard = {
      entity_id: 'folder:test_folder',
      entity_type: 'folder',
      display_name: 'My Folder',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T00:00:00Z',
      tags: [],
      builtin: false,
      container: {
        children: [],
        sub_containers: [],
        placement_rule: 'exclusive',
      },
    };
    expect(folder.container.placement_rule).toBe('exclusive');
  });

  it('SessionCard is a leaf card (no container)', () => {
    const session: SessionCard = {
      entity_id: 'session:20260424_000000_abcdef01_cla',
      entity_type: 'session',
      display_name: 'Test',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T00:00:00Z',
      tags: [],
      tracking_id: '20260424_000000_abcdef01_cla',
      platform: 'claude_cli',
      process_status: 'running',
    };
    expect(session.container).toBeUndefined();
    expect(session.tracking_id).toBeTruthy();
  });

  it('AnyCard union accepts all card types', () => {
    const cards: AnyCard[] = [
      {
        entity_id: 'session:test', entity_type: 'session', display_name: 'S',
        created_at: '', last_activity: '', tags: [],
        tracking_id: 'test', platform: 'claude_cli', process_status: 'running',
      },
      {
        entity_id: 'folder:test', entity_type: 'folder', display_name: 'F',
        created_at: '', last_activity: '', tags: [], builtin: false,
        container: { children: [], sub_containers: [], placement_rule: 'exclusive' },
      },
    ];
    expect(cards).toHaveLength(2);
  });

  it('ProjectCard is a leaf card with project-specific fields', () => {
    const project: ProjectCard = {
      entity_id: 'project:devtree_uai-resurrection',
      entity_type: 'project',
      display_name: 'uai-resurrection',
      created_at: '',
      last_activity: '',
      tags: ['devtree'],
      project_id: 'devtree_uai-resurrection',
      working_dir: '/Users/test/devTrees/AI_ROOT_uai-resurrection',
      branch: 'dev/uai-resurrection',
      git_status: 'dirty',
      lifecycle_status: 'active',
      goal: 'Rebuild UAI',
      assigned_ais: [],
      source_path: '/Users/test/devTrees/AI_ROOT_uai-resurrection/ai_general',
      availability: 'available',
      session_count: 5,
      category: null,
    };
    expect(project.container).toBeUndefined();
    expect(project.entity_type).toBe('project');
    expect(project.branch).toBe('dev/uai-resurrection');
    expect(project.git_status).toBe('dirty');
    expect(project.lifecycle_status).toBe('active');
    expect(project.session_count).toBe(5);
  });

  it('AnyCard union accepts ProjectCard', () => {
    const cards: AnyCard[] = [
      {
        entity_id: 'project:test', entity_type: 'project', display_name: 'P',
        created_at: '', last_activity: '', tags: [],
        project_id: 'test', working_dir: '/tmp', branch: null,
        git_status: 'unknown', lifecycle_status: null, goal: null,
        assigned_ais: [], source_path: '/tmp',
        availability: 'available', category: null,
      },
    ];
    expect(cards).toHaveLength(1);
    expect(cards[0].entity_type).toBe('project');
  });

  it('EntityType includes project', () => {
    const ref = makeEntityId('project', 'my_project');
    const parsed = parseEntityId(ref);
    expect(parsed.type).toBe('project');
  });
});
