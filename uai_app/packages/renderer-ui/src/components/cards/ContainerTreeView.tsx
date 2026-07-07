/**
 * ContainerTreeView — generic collapsible tree with container navigation.
 *
 * Shows sub-containers as collapsible nodes and cards as leaves.
 * Works with any container type (folders, groups).
 */

import { useState, useCallback } from 'react';
import type { AnyCard } from '@uai/shared/cards';
import type { ContainerEntry } from '@uai/shared/cards';
import CardListView from './CardListView';

interface ContainerTreeViewProps {
  container: ContainerEntry;
  allContainers: Record<string, ContainerEntry>;
  getCardsForIds: (cardIds: string[]) => AnyCard[];
  activeCardId?: string;
  selectedIds?: Set<string>;
  onCardClick?: (card: AnyCard) => void;
  onCardSelect?: (card: AnyCard) => void;
  onCardContextMenu?: (card: AnyCard, e: React.MouseEvent) => void;
  onContainerClick?: (containerId: string) => void;
  depth?: number;
}

export default function ContainerTreeView({
  container, allContainers, getCardsForIds,
  activeCardId, selectedIds,
  onCardClick, onCardSelect, onCardContextMenu,
  onContainerClick, depth = 0,
}: ContainerTreeViewProps): JSX.Element {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleCollapse = useCallback((id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const cards = getCardsForIds(container.cards);

  return (
    <div className="container-tree-view" style={{ paddingLeft: depth > 0 ? 12 : 0 }}>
      {container.sub_containers.map(childId => {
        const child = allContainers[childId];
        if (!child) return null;
        const isCollapsed = collapsed.has(childId);

        return (
          <div key={childId} className="tree-node">
            <div
              className="tree-node-label"
              onClick={() => {
                if (onContainerClick) {
                  onContainerClick(childId);
                } else {
                  toggleCollapse(childId);
                }
              }}
            >
              <span className="tree-toggle">{isCollapsed ? '\u25B6' : '\u25BC'}</span>
              <span className="tree-name">{child.name}</span>
              <span className="tree-count">({child.cards.length})</span>
            </div>
            {!isCollapsed && (
              <ContainerTreeView
                container={child}
                allContainers={allContainers}
                getCardsForIds={getCardsForIds}
                activeCardId={activeCardId}
                selectedIds={selectedIds}
                onCardClick={onCardClick}
                onCardSelect={onCardSelect}
                onCardContextMenu={onCardContextMenu}
                onContainerClick={onContainerClick}
                depth={depth + 1}
              />
            )}
          </div>
        );
      })}

      <CardListView
        cards={cards}
        activeCardId={activeCardId}
        selectedIds={selectedIds}
        onCardClick={onCardClick}
        onCardSelect={onCardSelect}
        onCardContextMenu={onCardContextMenu}
      />
    </div>
  );
}
