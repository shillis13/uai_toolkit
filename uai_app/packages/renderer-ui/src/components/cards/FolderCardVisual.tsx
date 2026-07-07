/**
 * FolderCardVisual — folder-specific card rendering.
 */

import type { FolderCard } from '@uai/shared/cards';

interface FolderCardVisualProps {
  card: FolderCard;
}

export default function FolderCardVisual({ card }: FolderCardVisualProps): JSX.Element {
  const itemCount = card.container.children.length;
  const subCount = card.container.sub_containers.length;

  return (
    <div className="card-meta">
      <span className="card-count">{itemCount} items</span>
      {subCount > 0 && <span className="card-count">{subCount} sub</span>}
    </div>
  );
}
