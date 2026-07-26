/**
 * CardRenderer — discriminated union dispatch to type-specific visuals.
 *
 * Given any BaseCard, selects the right visual component based on entity_type.
 */

import type { AnyCard } from '@uai/shared/cards';
import { isSessionCard, isBriefCard, isFolderCard, isProjectCard } from '@uai/shared/cards';
import BaseCardView from './BaseCardView';
import type { TooltipPosition } from './CardRichTooltip';
import SessionCardVisual from './SessionCardVisual';
import BriefCardVisual from './BriefCardVisual';
import FolderCardVisual from './FolderCardVisual';
import ProjectCardVisual from './ProjectCardVisual';

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange, #ff9e64)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

// AI-vendor badge shown next to a session's name — replaces the full-height
// platform color bar, whose coloring collided with folder accent bars (PianoMan
// 2026-07-20). Monogram + vendor color, localized so it no longer reads as a
// folder-style color stripe.
const PLATFORM_BADGE: Record<string, { label: string; title: string }> = {
  claude_cli: { label: 'CL', title: 'Claude' },
  codex_cli: { label: 'CX', title: 'Codex' },
  gemini_cli: { label: 'GM', title: 'Gemini' },
};

const STATUS_COLORS: Record<string, string> = {
  running: 'var(--accent-green)',
  stopped: 'var(--text-muted)',
  exited: 'var(--text-muted)',
};

interface CardRendererProps {
  card: AnyCard;
  active?: boolean;
  selected?: boolean;
  hasTab?: boolean;
  onClick?: (e?: React.MouseEvent) => void;
  onDoubleClick?: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  tooltipPosition?: TooltipPosition;
}

export default function CardRenderer({
  card, active, selected, hasTab, onClick, onDoubleClick, onContextMenu, tooltipPosition,
}: CardRendererProps): JSX.Element {
  let platformColor: string | undefined;
  let statusColor: string | undefined;
  let extraClass: string | undefined;
  let vendorBadge: { label: string; title: string; color: string } | undefined;

  if (isSessionCard(card)) {
    // Vendor badge instead of the platform color bar (bar coloring collided with
    // folder accents). Running/stopped shown via name dimming (extraClass).
    const pb = PLATFORM_BADGE[card.platform];
    if (pb) vendorBadge = { ...pb, color: PLATFORM_COLORS[card.platform] || 'var(--text-muted)' };
    statusColor = undefined;
    if (card.process_status !== 'running') extraClass = 'stopped';
  }

  return (
    <BaseCardView
      card={card}
      active={active}
      selected={selected}
      hasTab={hasTab}
      onClick={onClick}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
      platformColor={platformColor}
      statusColor={statusColor}
      vendorBadge={vendorBadge}
      extraClass={extraClass}
      tooltipPosition={tooltipPosition}
    >
      {isSessionCard(card) && <SessionCardVisual card={card} hasTab={hasTab} />}
      {isBriefCard(card) && <BriefCardVisual card={card} />}
      {isFolderCard(card) && <FolderCardVisual card={card} />}
      {isProjectCard(card) && <ProjectCardVisual card={card} />}
    </BaseCardView>
  );
}
