/**
 * BaseCardView — renders any card with platform bar, name, status dot, metadata.
 *
 * This is the universal card chrome. Type-specific content is passed as children.
 * Hover triggers a rich tooltip after 200ms delay, rendered via portal.
 */

import { useState, useRef, useCallback } from 'react';
import type { BaseCard } from '@uai/shared/cards';
import { isSessionCard } from '@uai/shared/cards';
import CardRichTooltip from './CardRichTooltip';
import type { TooltipPosition } from './CardRichTooltip';

interface BaseCardViewProps {
  card: BaseCard;
  active?: boolean;
  selected?: boolean;
  hasTab?: boolean;
  onClick?: (e?: React.MouseEvent) => void;
  onDoubleClick?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  platformColor?: string;
  statusColor?: string;
  vendorBadge?: { label: string; title: string; color: string };
  extraClass?: string;
  tooltipPosition?: TooltipPosition;
  children?: React.ReactNode;
}

export default function BaseCardView({
  card, active, selected, hasTab, onClick, onDoubleClick, onContextMenu,
  platformColor, statusColor, vendorBadge, extraClass, tooltipPosition, children,
}: BaseCardViewProps): JSX.Element {
  const pinned = isSessionCard(card) && card.pinned;
  const [hovered, setHovered] = useState(false);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const handleMouseEnter = useCallback(() => {
    hoverTimerRef.current = setTimeout(() => setHovered(true), 200);
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (hoverTimerRef.current) { clearTimeout(hoverTimerRef.current); hoverTimerRef.current = null; }
    setHovered(false);
  }, []);

  const handleTooltipEnter = useCallback(() => {
    if (hoverTimerRef.current) { clearTimeout(hoverTimerRef.current); hoverTimerRef.current = null; }
  }, []);

  const handleTooltipLeave = useCallback(() => {
    setHovered(false);
  }, []);

  const cardRect = hovered && cardRef.current ? cardRef.current.getBoundingClientRect() : null;

  return (
    <div
      ref={cardRef}
      className={`session-card${active ? ' active' : ''}${selected ? ' selected' : ''}${pinned ? ' pinned' : ''}${extraClass ? ` ${extraClass}` : ''}`}
      onClick={(e) => onClick?.(e)}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {platformColor && <div className="card-platform-bar" style={{ backgroundColor: platformColor }} />}
      {hasTab && <div className="card-tab-indicator" />}
      <div className="card-content">
        <div className="card-header">
          {vendorBadge && (
            <span
              className="card-vendor-badge"
              style={{ color: vendorBadge.color, borderColor: vendorBadge.color }}
              title={vendorBadge.title}
            >{vendorBadge.label}</span>
          )}
          <span className="card-name">{card.display_name}</span>
          {pinned && <span className="card-pin-icon" title="Pinned">{'\uD83D\uDCCC'}</span>}
          {statusColor && <span className="card-status-dot" style={{ backgroundColor: statusColor }} />}
        </div>
        {children}
      </div>
      {cardRect && (
        <CardRichTooltip
          card={card}
          cardRect={cardRect}
          onMouseEnter={handleTooltipEnter}
          onMouseLeave={handleTooltipLeave}
          position={tooltipPosition}
        />
      )}
    </div>
  );
}
