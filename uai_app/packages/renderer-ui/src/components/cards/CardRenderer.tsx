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

  if (isSessionCard(card)) {
    platformColor = PLATFORM_COLORS[card.platform];
    // Green dot reserved for unread responses (future).
    // Running/stopped shown via name dimming (extraClass).
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
