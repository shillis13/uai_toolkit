/**
 * FolderTree — renders the folder hierarchy in the navigator.
 *
 * Workstream 1C: Organization Entities
 *
 * Displays folders as a collapsible tree. Supports:
 * - Expand/collapse subfolders
 * - Click to navigate into folder
 * - Context menu integration (1B will wire this)
 * - Card count badges with entity-type tooltips
 *
 * This component is designed for 1B to import into the Navigator.
 * Only the top-level FolderTree calls useFolderStore; FolderNode
 * receives store accessors as props to avoid per-node subscriptions.
 */

import React, { useState, useCallback } from 'react';
import { useFolderStore } from '../../stores/folder-store';
import { useCardStore } from '../../stores/card-store';
import type { Folder } from '@uai/shared/types';
import { folderAccent } from './folderAccent';

// ─── Props ───────────────────────────────────────────────────────────────

interface FolderTreeProps {
  rootId: string;
  selectedFolderId?: string;
  onSelectFolder: (folderId: string) => void;
  onContextMenu?: (folderId: string, event: React.MouseEvent) => void;
  collapsedFolders?: Set<string>;
  onToggleCollapse?: (folderId: string) => void;
}

interface EntityCounts { sessionCount: number; projectCount: number; total: number }

interface FolderNodeProps {
  folderId: string;
  depth: number;
  selectedFolderId?: string;
  collapsedFolders: Set<string>;
  onSelectFolder: (folderId: string) => void;
  onContextMenu?: (folderId: string, event: React.MouseEvent) => void;
  onToggleCollapse: (folderId: string) => void;
  getFolder: (id: string) => Folder | undefined;
  getDescendantCards: (id: string) => string[];
  getEntityCounts: (cardIds: string[]) => EntityCounts;
}

// ─── FolderNode ──────────────────────────────────────────────────────────

function FolderNode({
  folderId,
  depth,
  selectedFolderId,
  collapsedFolders,
  onSelectFolder,
  onContextMenu,
  onToggleCollapse,
  getFolder,
  getDescendantCards,
  getEntityCounts,
}: FolderNodeProps): React.ReactElement | null {
  const folder = getFolder(folderId);
  if (!folder) return null;

  const isCollapsed = collapsedFolders.has(folderId);
  const isSelected = folderId === selectedFolderId;
  const hasChildren = folder.subfolders.length > 0;
  const cardIds = getDescendantCards(folderId);
  const counts = getEntityCounts(cardIds);
  const fc = folderAccent(folder);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onSelectFolder(folderId);
  };

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleCollapse(folderId);
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onContextMenu?.(folderId, e);
  };

  return (
    <div className="folder-tree-node">
      <div
        className={`folder-tree-row ${isSelected ? 'folder-tree-row--selected' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px`, ['--fc' as string]: fc } as React.CSSProperties}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
        data-folder-id={folderId}
      >
        {/* Expand/collapse toggle */}
        <span
          className={`folder-tree-toggle ${hasChildren ? '' : 'folder-tree-toggle--hidden'}`}
          onClick={handleToggle}
        >
          {hasChildren ? (isCollapsed ? '\u25B6' : '\u25BC') : ''}
        </span>

        {/* Folder icon \u2014 a custom icon shows as-is; the default folder glyph is a
            saturated color swatch so every row carries its accent. */}
        <span className="folder-tree-icon">
          {folder.icon
            ? folder.icon
            : <span className="folder-tree-swatch" aria-hidden="true" />}
        </span>

        {/* Folder name */}
        <span className="folder-tree-name">{folder.name}</span>

        {/* Card count badge: total with type breakdown tooltip */}
        {counts.total > 0 && (
          <span
            className="folder-count"
            title={[
              counts.sessionCount > 0 ? `Sessions: ${counts.sessionCount}` : '',
              counts.projectCount > 0 ? `Projects: ${counts.projectCount}` : '',
            ].filter(Boolean).join(', ')}
          >
            {counts.total}
          </span>
        )}
      </div>

      {/* Children */}
      {!isCollapsed && hasChildren && (
        <div className="folder-tree-children">
          {folder.subfolders.map(childId => (
            <FolderNode
              key={childId}
              folderId={childId}
              depth={depth + 1}
              selectedFolderId={selectedFolderId}
              collapsedFolders={collapsedFolders}
              onSelectFolder={onSelectFolder}
              onContextMenu={onContextMenu}
              onToggleCollapse={onToggleCollapse}
              getFolder={getFolder}
              getDescendantCards={getDescendantCards}
              getEntityCounts={getEntityCounts}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── FolderTree ──────────────────────────────────────────────────────────

export function FolderTree({
  rootId,
  selectedFolderId,
  onSelectFolder,
  onContextMenu,
  collapsedFolders: externalCollapsed,
  onToggleCollapse: externalToggle,
}: FolderTreeProps): React.ReactElement {
  // Single store subscription at the tree level — not per node
  const { getFolder, descendantCards } = useFolderStore();
  // Subscribe to the card store so counts stay fresh as sessions load, and so we
  // can resolve refs the same way the folder Tab view does.
  const { getCard } = useCardStore();

  const getEntityCounts = useCallback((cardIds: string[]): EntityCounts => {
    // Count only refs that RESOLVE to a real card. A folder can hold dangling refs
    // (e.g. `session:list_1` pointing at a session that no longer exists). The
    // folder's Tab view drops unresolved refs (card-store getCardsInContainer
    // filters them out), so the Navigator count must too — otherwise the Navigator
    // shows N sessions the Tab can't display (the count↔tab mismatch bug).
    const resolved = cardIds.filter(id => getCard(id) !== undefined);
    const sessionCount = resolved.filter(id => id.startsWith('session:')).length;
    const projectCount = resolved.filter(id => id.startsWith('project:')).length;
    return { sessionCount, projectCount, total: resolved.length };
  }, [getCard]);

  const [internalCollapsed, setInternalCollapsed] = useState<Set<string>>(new Set());

  const internalToggle = useCallback((folderId: string) => {
    setInternalCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(folderId)) {
        next.delete(folderId);
      } else {
        next.add(folderId);
      }
      return next;
    });
  }, []);

  const collapsedFolders = externalCollapsed ?? internalCollapsed;
  const onToggleCollapse = externalToggle ?? internalToggle;

  return (
    <div className="folder-tree" role="tree">
      <FolderNode
        folderId={rootId}
        depth={0}
        selectedFolderId={selectedFolderId}
        collapsedFolders={collapsedFolders}
        onSelectFolder={onSelectFolder}
        onContextMenu={onContextMenu}
        onToggleCollapse={onToggleCollapse}
        getFolder={getFolder}
        getDescendantCards={descendantCards}
        getEntityCounts={getEntityCounts}
      />
    </div>
  );
}
