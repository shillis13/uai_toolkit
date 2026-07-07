/**
 * ProjectCardVisual — project-specific card rendering.
 *
 * Shows working dir, branch, status badge, session count.
 */

import type { ProjectCard } from '@uai/shared/cards';

const STATUS_COLORS: Record<string, string> = {
  clean: 'var(--accent-green)',
  dirty: 'var(--accent-orange, #ff9e64)',
  ahead: 'var(--accent-blue)',
  behind: 'var(--accent-purple)',
  unknown: 'var(--text-muted)',
};

interface ProjectCardVisualProps {
  card: ProjectCard;
}

export default function ProjectCardVisual({ card }: ProjectCardVisualProps): JSX.Element {
  return (
    <div className="card-meta">
      {card.branch && <span className="card-branch">{card.branch}</span>}
      <span className="card-badge" style={{ color: STATUS_COLORS[card.git_status] || STATUS_COLORS.unknown }}>
        {card.git_status}
      </span>
      {card.session_count != null && card.session_count > 0 && (
        <span className="card-count">{card.session_count} sessions</span>
      )}
      {card.availability !== 'available' && (
        <span className="card-badge draft">{card.availability}</span>
      )}
    </div>
  );
}
