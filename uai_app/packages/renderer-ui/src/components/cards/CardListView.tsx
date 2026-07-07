/**
 * CardListView — generic sortable, filterable, multi-selectable card list.
 *
 * Works with BaseCard. Does NOT know about sessions or briefs.
 * Type-specific rendering is handled by CardRenderer.
 * Supports list and grid view modes.
 */

import type { AnyCard } from '@uai/shared/cards';
import { isSessionCard } from '@uai/shared/cards';
import CardRenderer from './CardRenderer';
import type { TooltipPosition } from './CardRichTooltip';

type ViewMode = 'list' | 'grid';

interface CardListViewProps {
  cards: AnyCard[];
  activeCardId?: string;
  selectedIds?: Set<string>;
  viewMode?: ViewMode;
  openTabTargetIds?: Set<string>;
  onCardClick?: (card: AnyCard, e?: React.MouseEvent) => void;
  onCardDoubleClick?: (card: AnyCard) => void;
  onCardSelect?: (card: AnyCard) => void;
  onCardContextMenu?: (card: AnyCard, e: React.MouseEvent) => void;
  emptyMessage?: string;
  tooltipPosition?: TooltipPosition;
}

export default function CardListView({
  cards, activeCardId, selectedIds, viewMode = 'list', openTabTargetIds, onCardClick, onCardDoubleClick, onCardSelect,
  onCardContextMenu, emptyMessage = 'No items found.', tooltipPosition,
}: CardListViewProps): JSX.Element {
  if (cards.length === 0) {
    return <div className="session-list-empty">{emptyMessage}</div>;
  }

  // Pinned items sort to top regardless of other sort order
  const sorted = [...cards].sort((a, b) => {
    const ap = isSessionCard(a) && a.pinned ? 1 : 0;
    const bp = isSessionCard(b) && b.pinned ? 1 : 0;
    return bp - ap;
  });

  return (
    <div className={`card-list-view${viewMode === 'grid' ? ' card-grid-view' : ''}`}>
      {sorted.map(card => (
        <CardRenderer
          key={card.entity_id}
          card={card}
          active={card.entity_id === activeCardId}
          selected={selectedIds?.has(card.entity_id)}
          hasTab={openTabTargetIds ? (isSessionCard(card) ? openTabTargetIds.has(card.tracking_id) : false) : undefined}
          onClick={(e?: React.MouseEvent) => {
            if (e && (e.metaKey || e.ctrlKey)) {
              onCardSelect?.(card);
            } else {
              onCardClick?.(card, e);
            }
          }}
          onDoubleClick={() => onCardDoubleClick?.(card)}
          onContextMenu={(e) => onCardContextMenu?.(card, e)}
          tooltipPosition={tooltipPosition}
        />
      ))}
    </div>
  );
}
