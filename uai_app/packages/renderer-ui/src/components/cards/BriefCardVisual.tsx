/**
 * BriefCardVisual — brief-specific card rendering.
 */

import type { BriefCard } from '@uai/shared/cards';

interface BriefCardVisualProps {
  card: BriefCard;
}

export default function BriefCardVisual({ card }: BriefCardVisualProps): JSX.Element {
  return (
    <div className="card-meta">
      {card.description && <span className="card-description">{card.description}</span>}
      {card.file_size != null && (
        <span className="card-size">{Math.round(card.file_size / 1024)}KB</span>
      )}
      <span className={`card-badge ${card.status}`}>{card.status}</span>
    </div>
  );
}
