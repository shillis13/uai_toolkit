/**
 * FolderContextMenu — right-click context menu for folders in the navigator.
 *
 * Actions:
 * - New Folder (creates a child folder)
 * - Rename Folder (inline rename input)
 * - Delete Folder (with confirmation)
 * - Add Session (mini-picker showing unfiled sessions)
 * - Remove Session (submenu of sessions in this folder)
 *
 * Uses executeCommand for all operations. Follows the same pattern as
 * the session ContextMenu and GroupContextMenu in Navigator.tsx.
 */

import React, { useState, useRef, useCallback } from 'react';
import { executeCommand } from '../../utils/execute-command';
import { useFolderStore } from '../../stores/folder-store';
import { useCardStore } from '../../stores/card-store';
import { useContextMenuDismiss } from '../../hooks/use-context-menu-dismiss';
import type { SessionCard, ProjectCard } from '@uai/shared/cards';

// ─── Props ───────────────────────────────────────────────────────────────

export interface FolderContextMenuProps {
  x: number;
  y: number;
  folderId: string;
  onClose: () => void;
  toastFn: (message: string, type?: 'error' | 'info' | 'warning') => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────

function getCardDisplayName(card: SessionCard): string {
  if (card.display_name) {
    return card.display_name
      .replace(/^(claude|codex|gemini)_cli_/, '')
      .replace(/_\d{8}T\d{6}$/, '')
      .replace(/_/g, ' ');
  }
  return card.roles && card.roles.length > 0 ? card.roles[0] : card.tracking_id;
}

function getProjectDisplayName(card: ProjectCard): string {
  if (card.display_name) return card.display_name;
  return card.project_id || card.entity_id;
}

// ─── Component ───────────────────────────────────────────────────────────

export function FolderContextMenu({
  x,
  y,
  folderId,
  onClose,
  toastFn,
}: FolderContextMenuProps): React.ReactElement | null {
  const menuRef = useRef<HTMLDivElement>(null);
  const { getFolder, parentFolder, storeData } = useFolderStore();
  const cardStore = useCardStore();

  const [mode, setMode] = useState<'menu' | 'rename' | 'new-folder' | 'add-session' | 'add-project' | 'confirm-delete'>('menu');
  const [nameValue, setNameValue] = useState('');
  const [sessionSearch, setSessionSearch] = useState('');
  const [projectSearch, setProjectSearch] = useState('');

  const folder = getFolder(folderId);

  useContextMenuDismiss(menuRef, onClose);

  // ── Computed: sibling info for Move Up/Down (must be before early returns) ──
  const parentId = folder ? parentFolder(folderId) : undefined;
  const parentFolderObj = parentId ? getFolder(parentId) : undefined;
  const siblings = parentFolderObj?.subfolders || [];
  const siblingIndex = siblings.indexOf(folderId);

  const handleMoveUp = useCallback(() => {
    if (!parentId || siblingIndex <= 0) return;
    const newOrder = [...siblings];
    [newOrder[siblingIndex - 1], newOrder[siblingIndex]] = [newOrder[siblingIndex], newOrder[siblingIndex - 1]];
    executeCommand('folder.reorderSubfolders', { parentId, orderedIds: newOrder }, { onFailure: 'toast', toastFn });
    onClose();
  }, [parentId, siblings, siblingIndex, toastFn, onClose]);

  const handleMoveDown = useCallback(() => {
    if (!parentId || siblingIndex < 0 || siblingIndex >= siblings.length - 1) return;
    const newOrder = [...siblings];
    [newOrder[siblingIndex], newOrder[siblingIndex + 1]] = [newOrder[siblingIndex + 1], newOrder[siblingIndex]];
    executeCommand('folder.reorderSubfolders', { parentId, orderedIds: newOrder }, { onFailure: 'toast', toastFn });
    onClose();
  }, [parentId, siblings, siblingIndex, toastFn, onClose]);

  const handleMoveTo = useCallback((targetParentId: string) => {
    executeCommand('folder.moveFolder', { folderId, targetParentId }, { onFailure: 'toast', toastFn });
    onClose();
  }, [folderId, toastFn, onClose]);

  if (!folder) return null;

  // ── Action: New Folder ──────────────────────────────────────────────────

  const handleNewFolder = useCallback(() => {
    setNameValue('');
    setMode('new-folder');
  }, []);

  const submitNewFolder = useCallback(async () => {
    const name = nameValue.trim();
    if (!name) {
      onClose();
      return;
    }
    // Close menu first to avoid unmount-during-rerender crash
    onClose();
    await executeCommand('folder.create', {
      parentId: folderId,
      name,
    }, { onFailure: 'toast', toastFn });
  }, [nameValue, folderId, toastFn, onClose]);

  // ── Action: Rename ──────────────────────────────────────────────────────

  const handleRename = useCallback(() => {
    setNameValue(folder.name);
    setMode('rename');
  }, [folder.name]);

  const submitRename = useCallback(async () => {
    const name = nameValue.trim();
    if (!name || name === folder.name) {
      onClose();
      return;
    }
    onClose();
    await executeCommand('folder.rename', {
      folderId,
      name,
    }, { onFailure: 'toast', toastFn });
  }, [nameValue, folder.name, folderId, toastFn, onClose]);

  // ── Action: Delete ──────────────────────────────────────────────────────

  const handleDelete = useCallback(() => {
    setMode('confirm-delete');
  }, []);

  const confirmDelete = useCallback(async () => {
    onClose();
    await executeCommand('folder.delete', {
      folderId,
      policy: 'reparent',
    }, { onFailure: 'toast', toastFn });
  }, [folderId, toastFn, onClose]);

  // ── Action: Add Session ─────────────────────────────────────────────────

  const handleAddSession = useCallback(() => {
    setSessionSearch('');
    setMode('add-session');
  }, []);

  const addSessionToFolder = useCallback((cardId: string) => {
    executeCommand('folder.moveCard', {
      cardId,
      targetFolderId: folderId,
    }, { onFailure: 'toast', toastFn });
    onClose();
  }, [folderId, toastFn, onClose]);

  // ── Action: Remove Session ──────────────────────────────────────────────

  const removeSessionFromFolder = useCallback((cardId: string) => {
    executeCommand('folder.unfileCard', {
      cardId,
    }, { onFailure: 'toast', toastFn });
    onClose();
  }, [toastFn, onClose]);

  // ── Action: Add Project ─────────────────────────────────────────────────

  const handleAddProject = useCallback(() => {
    setProjectSearch('');
    setMode('add-project');
  }, []);

  const addProjectToFolder = useCallback((cardId: string) => {
    executeCommand('folder.moveCard', {
      cardId,
      targetFolderId: folderId,
    }, { onFailure: 'toast', toastFn });
    onClose();
  }, [folderId, toastFn, onClose]);

  // ── Action: Remove Project ──────────────────────────────────────────────

  const removeProjectFromFolder = useCallback((cardId: string) => {
    executeCommand('folder.unfileCard', {
      cardId,
    }, { onFailure: 'toast', toastFn });
    onClose();
  }, [toastFn, onClose]);

  // ── Computed: Sessions in this folder ───────────────────────────────────

  const folderCards: SessionCard[] = folder.cards
    .map(cardId => cardStore.sessions.find(s => s.entity_id === cardId))
    .filter((s): s is SessionCard => s != null);

  // ── Computed: Sessions available to add (not already in this folder) ────

  const folderCardIds = new Set(folder.cards);
  const availableSessions: SessionCard[] = cardStore.sessions
    .filter(s => !folderCardIds.has(s.entity_id as any))
    .filter(s => {
      if (!sessionSearch) return true;
      const q = sessionSearch.toLowerCase();
      const name = getCardDisplayName(s).toLowerCase();
      const tid = s.tracking_id.toLowerCase();
      return name.includes(q) || tid.includes(q);
    });

  // ── Computed: Projects in this folder ───────────────────────────────────

  const folderProjects: ProjectCard[] = folder.cards
    .map(cardId => cardStore.projects.find(p => p.entity_id === cardId))
    .filter((p): p is ProjectCard => p != null);

  // ── Computed: Projects available to add (not already in this folder) ────

  const availableProjects: ProjectCard[] = cardStore.projects
    .filter(p => !folderCardIds.has(p.entity_id as any))
    .filter(p => {
      if (!projectSearch) return true;
      const q = projectSearch.toLowerCase();
      const name = getProjectDisplayName(p).toLowerCase();
      return name.includes(q);
    });

  // ── Render: Rename mode ─────────────────────────────────────────────────

  if (mode === 'rename') {
    return (
      <div ref={menuRef} className="context-menu folder-context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
        <div className="folder-ctx-input-row">
          <input
            className="folder-ctx-input"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitRename();
              if (e.key === 'Escape') onClose();
            }}
            placeholder="Folder name"
            autoFocus
          />
          <button className="folder-ctx-input-btn" onClick={submitRename}>Save</button>
        </div>
      </div>
    );
  }

  // ── Render: New Folder mode ─────────────────────────────────────────────

  if (mode === 'new-folder') {
    return (
      <div ref={menuRef} className="context-menu folder-context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
        <div className="folder-ctx-input-row">
          <input
            className="folder-ctx-input"
            value={nameValue}
            onChange={(e) => setNameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitNewFolder();
              if (e.key === 'Escape') onClose();
            }}
            placeholder="New folder name"
            autoFocus
          />
          <button className="folder-ctx-input-btn" onClick={submitNewFolder}>Create</button>
        </div>
      </div>
    );
  }

  // ── Render: Confirm Delete mode ─────────────────────────────────────────

  if (mode === 'confirm-delete') {
    const childCount = folder.subfolders.length;
    const cardCount = folder.cards.length;
    return (
      <div ref={menuRef} className="context-menu folder-context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
        <div className="folder-ctx-confirm">
          <div className="folder-ctx-confirm-msg">
            Delete "{folder.name}"?
            {(childCount > 0 || cardCount > 0) && (
              <span className="folder-ctx-confirm-detail">
                {childCount > 0 && ` ${childCount} subfolder${childCount > 1 ? 's' : ''}`}
                {childCount > 0 && cardCount > 0 && ','}
                {cardCount > 0 && ` ${cardCount} session${cardCount > 1 ? 's' : ''}`}
                {' '}will be moved to parent.
              </span>
            )}
          </div>
          <div className="folder-ctx-confirm-actions">
            <button className="folder-ctx-input-btn" onClick={() => setMode('menu')}>Cancel</button>
            <button className="folder-ctx-input-btn folder-ctx-input-btn--danger" onClick={confirmDelete}>Delete</button>
          </div>
        </div>
      </div>
    );
  }

  // ── Render: Add Session picker mode ─────────────────────────────────────

  if (mode === 'add-session') {
    return (
      <div ref={menuRef} className="context-menu folder-context-menu folder-ctx-picker" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
        <div className="folder-ctx-picker-header">Add session to "{folder.name}"</div>
        <div className="folder-ctx-input-row">
          <input
            className="folder-ctx-input"
            value={sessionSearch}
            onChange={(e) => setSessionSearch(e.target.value)}
            placeholder="Search sessions..."
            autoFocus
          />
        </div>
        <div className="folder-ctx-picker-list">
          {availableSessions.length > 0 ? (
            availableSessions.slice(0, 15).map(s => (
              <button
                key={s.entity_id}
                className="context-menu-item folder-ctx-picker-item"
                onClick={() => addSessionToFolder(s.entity_id)}
              >
                <span className="folder-ctx-picker-status" style={{
                  color: s.process_status === 'running' ? 'var(--accent-green)' : 'var(--text-muted)',
                }}>
                  {s.process_status === 'running' ? '\u25CF' : '\u25CB'}
                </span>
                <span className="folder-ctx-picker-name">{getCardDisplayName(s)}</span>
              </button>
            ))
          ) : (
            <div className="folder-ctx-picker-empty">
              {sessionSearch ? 'No matching sessions.' : 'All sessions already in this folder.'}
            </div>
          )}
          {availableSessions.length > 15 && (
            <div className="folder-ctx-picker-overflow">
              +{availableSessions.length - 15} more — type to filter
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Render: Add Project picker mode ─────────────────────────────────────

  if (mode === 'add-project') {
    return (
      <div ref={menuRef} className="context-menu folder-context-menu folder-ctx-picker" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
        <div className="folder-ctx-picker-header">Add project to "{folder.name}"</div>
        <div className="folder-ctx-input-row">
          <input
            className="folder-ctx-input"
            value={projectSearch}
            onChange={(e) => setProjectSearch(e.target.value)}
            placeholder="Search projects..."
            autoFocus
          />
        </div>
        <div className="folder-ctx-picker-list">
          {availableProjects.length > 0 ? (
            availableProjects.slice(0, 15).map(p => (
              <button
                key={p.entity_id}
                className="context-menu-item folder-ctx-picker-item"
                onClick={() => addProjectToFolder(p.entity_id)}
              >
                <span className="folder-ctx-picker-name">{getProjectDisplayName(p)}</span>
              </button>
            ))
          ) : (
            <div className="folder-ctx-picker-empty">
              {projectSearch ? 'No matching projects.' : 'All projects already in this folder.'}
            </div>
          )}
          {availableProjects.length > 15 && (
            <div className="folder-ctx-picker-overflow">
              +{availableProjects.length - 15} more — type to filter
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Render: Main menu ───────────────────────────────────────────────────

  const isBuiltin = folder.builtin;

  const canMoveUp = !isBuiltin && parentId != null && siblingIndex > 0;
  const canMoveDown = !isBuiltin && parentId != null && siblingIndex >= 0 && siblingIndex < siblings.length - 1;

  // ── Computed: potential parent folders for "Move to..." ────────────────
  const allFolderIds = Object.keys(storeData.folders);
  const selfDescendants = new Set<string>();
  const collectDescendants = (id: string) => {
    selfDescendants.add(id);
    const f = getFolder(id);
    if (f) { for (const child of f.subfolders) collectDescendants(child); }
  };
  collectDescendants(folderId);
  // Exclude briefs tree and self/descendants/parent
  const briefsDescendants = new Set<string>();
  const collectBriefs = (id: string) => {
    briefsDescendants.add(id);
    const f = getFolder(id);
    if (f) { for (const child of f.subfolders) collectBriefs(child); }
  };
  collectBriefs('all_briefs');
  const moveTargets = isBuiltin ? [] : allFolderIds
    .filter(id => !selfDescendants.has(id) && id !== parentId && !briefsDescendants.has(id))
    .map(id => getFolder(id))
    .filter((f): f is NonNullable<typeof f> => f != null);

  return (
    <div ref={menuRef} className="context-menu folder-context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
      <button className="context-menu-item" onClick={handleNewFolder}>
        New Folder
      </button>
      {!isBuiltin && (
        <button className="context-menu-item" onClick={handleRename}>
          Rename Folder
        </button>
      )}
      <div className="context-menu-separator" />
      <button className="context-menu-item" onClick={handleAddSession}>
        Add Session
      </button>
      {folderCards.length > 0 && (
        <div className="context-menu-item submenu-trigger folder-ctx-remove-trigger">
          Remove Session {'\u25B6'}
          <div className="context-submenu folder-ctx-remove-submenu">
            {folderCards.map(s => (
              <button
                key={s.entity_id}
                className="context-menu-item"
                onClick={() => removeSessionFromFolder(s.entity_id)}
              >
                {getCardDisplayName(s)}
              </button>
            ))}
          </div>
        </div>
      )}
      <button className="context-menu-item" onClick={handleAddProject}>
        Add Project
      </button>
      {folderProjects.length > 0 && (
        <div className="context-menu-item submenu-trigger folder-ctx-remove-trigger">
          Remove Project {'\u25B6'}
          <div className="context-submenu folder-ctx-remove-submenu">
            {folderProjects.map(p => (
              <button
                key={p.entity_id}
                className="context-menu-item"
                onClick={() => removeProjectFromFolder(p.entity_id)}
              >
                {getProjectDisplayName(p)}
              </button>
            ))}
          </div>
        </div>
      )}
      {!isBuiltin && (canMoveUp || canMoveDown || moveTargets.length > 0) && (
        <>
          <div className="context-menu-separator" />
          {canMoveUp && (
            <button className="context-menu-item" onClick={handleMoveUp}>
              Move Up
            </button>
          )}
          {canMoveDown && (
            <button className="context-menu-item" onClick={handleMoveDown}>
              Move Down
            </button>
          )}
          {moveTargets.length > 0 && (
            <div className="context-menu-item submenu-trigger">
              Move to... {'\u25B6'}
              <div className="context-submenu">
                {moveTargets.map(f => (
                  <button
                    key={f.id}
                    className="context-menu-item"
                    onClick={() => handleMoveTo(f.id)}
                  >{f.name}</button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      {!isBuiltin && (
        <>
          <div className="context-menu-separator" />
          <button className="context-menu-item danger" onClick={handleDelete}>
            Delete Folder
          </button>
        </>
      )}
    </div>
  );
}
