/**
 * Contract Test: Container Manager
 *
 * Tests generic container operations with exclusive placement rules.
 * Validates that folder behavior is preserved.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// Set AI_ROOT to a temp directory before importing
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uai-container-test-'));
const dataDir = path.join(tmpDir, 'ai_general', 'data');
fs.mkdirSync(dataDir, { recursive: true });
process.env.AI_ROOT = tmpDir;

import {
  loadContainers, createContainer, addCardToContainer,
  removeCardFromContainer, moveCard, deleteContainer,
  renameContainer, listCards, validateContainerTree,
  getContainerSnapshot,
} from '../main/container-manager';

function cleanupContainers(): void {
  const containersPath = path.join(dataDir, 'containers.json');
  if (fs.existsSync(containersPath)) {
    fs.unlinkSync(containersPath);
  }
}

describe('ContainerManager — exclusive placement (folders)', () => {
  beforeEach(cleanupContainers);

  it('creates a container under a root', () => {
    const { containerId } = createContainer('folder', 'My Folder', 'all_sessions');
    expect(containerId).toBeTruthy();

    const store = getContainerSnapshot();
    expect(store.containers[containerId]).toBeDefined();
    expect(store.containers[containerId].name).toBe('My Folder');
    expect(store.containers[containerId].placement_rule).toBe('exclusive');
  });

  it('adds a card to a container', () => {
    const { containerId } = createContainer('folder', 'Folder A', 'all_sessions');
    addCardToContainer(containerId, 'session:test_1');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].cards).toContain('session:test_1');
  });

  it('moveCard with exclusive placement removes from old container', () => {
    const { containerId: folderA } = createContainer('folder', 'Folder A', 'all_sessions');
    const { containerId: folderB } = createContainer('folder', 'Folder B', 'all_sessions');

    addCardToContainer(folderA, 'session:test_1');
    moveCard('session:test_1', folderA, folderB);

    const store = getContainerSnapshot();
    expect(store.containers[folderA].cards).not.toContain('session:test_1');
    expect(store.containers[folderB].cards).toContain('session:test_1');
  });

  it('removeCardFromContainer moves card to root for exclusive placement', () => {
    const { containerId } = createContainer('folder', 'Folder A', 'all_sessions');
    addCardToContainer(containerId, 'session:test_1');
    removeCardFromContainer(containerId, 'session:test_1');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].cards).not.toContain('session:test_1');
    expect(store.containers['all_sessions'].cards).toContain('session:test_1');
  });

  it('deleteContainer reparents children to parent', () => {
    const { containerId } = createContainer('folder', 'Doomed', 'all_sessions');
    addCardToContainer(containerId, 'session:orphan_1');
    deleteContainer(containerId);

    const store = getContainerSnapshot();
    expect(store.containers[containerId]).toBeUndefined();
    expect(store.containers['all_sessions'].cards).toContain('session:orphan_1');
  });

  it('renameContainer changes the name', () => {
    const { containerId } = createContainer('folder', 'Old Name', 'all_sessions');
    renameContainer(containerId, 'New Name');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].name).toBe('New Name');
  });

  it('validates tree catches orphaned containers', () => {
    const store = getContainerSnapshot();
    // Manually create an orphan for test
    store.containers['orphan_test'] = {
      id: 'orphan_test', name: 'Orphan', container_type: 'folder',
      icon: null, color: null, builtin: false, placement_rule: 'exclusive',
      sub_containers: [], cards: [],
    };
    const errors = validateContainerTree(store);
    expect(errors.some(e => e.includes('orphan'))).toBe(true);
  });

  it('listCards returns cards in a container', () => {
    const { containerId } = createContainer('folder', 'List Test', 'all_sessions');
    addCardToContainer(containerId, 'session:list_1');
    addCardToContainer(containerId, 'session:list_2');

    const cards = listCards(containerId);
    expect(cards).toContain('session:list_1');
    expect(cards).toContain('session:list_2');
  });

  it('rejects session card placed under briefs root tree', () => {
    const { containerId } = createContainer('folder', 'Brief Folder', 'all_briefs');
    expect(() => addCardToContainer(containerId, 'session:wrong_root')).toThrow(
      /session cards can only be in the sessions container tree/i
    );
  });

  it('listCards with descendants includes nested containers', () => {
    const { containerId: parent } = createContainer('folder', 'Parent', 'all_sessions');
    const { containerId: child } = createContainer('folder', 'Child', parent);
    addCardToContainer(parent, 'session:p1');
    addCardToContainer(child, 'session:c1');

    const cards = listCards(parent, { descendants: true });
    expect(cards).toContain('session:p1');
    expect(cards).toContain('session:c1');
  });
});


afterEach(() => {
  // Cleanup temp directory
});
