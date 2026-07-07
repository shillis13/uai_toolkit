/**
 * TagBadge — displays a tag as a colored pill/badge.
 *
 * Workstream 1C: Organization Entities
 *
 * Used in session cards, context panel, and detail views.
 * Optionally dismissible (shows x button for removal).
 */

import React from 'react';
import type { Tag } from '@uai/shared/types';

// ─── Props ───────────────────────────────────────────────────────────────

interface TagBadgeProps {
  tag: Tag | string;  // Tag object or just a tag name string
  color?: string;     // Override color (used when tag is a string)
  onRemove?: () => void;
  onClick?: () => void;
}

// ─── Component ───────────────────────────────────────────────────────────

export function TagBadge({ tag, color, onRemove, onClick }: TagBadgeProps): React.ReactElement {
  const name = typeof tag === 'string' ? tag : tag.name;
  const badgeColor = color || (typeof tag === 'object' ? tag.color : null) || '#666';

  return (
    <span
      className={`tag-badge ${onClick ? 'tag-badge--clickable' : ''}`}
      style={{
        backgroundColor: `${badgeColor}22`,
        borderColor: `${badgeColor}44`,
        color: badgeColor,
      }}
      onClick={onClick}
      title={name}
    >
      <span className="tag-badge-name">{name}</span>
      {onRemove && (
        <button
          className="tag-badge-remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          title={`Remove tag: ${name}`}
          aria-label={`Remove tag: ${name}`}
        >
          &times;
        </button>
      )}
    </span>
  );
}

// ─── TagList — renders a list of tag badges ──────────────────────────────

interface TagListProps {
  tags: (Tag | string)[];
  onRemove?: (tagName: string) => void;
  onClick?: (tagName: string) => void;
}

export function TagList({ tags, onRemove, onClick }: TagListProps): React.ReactElement {
  return (
    <div className="tag-list">
      {tags.map((tag) => {
        const name = typeof tag === 'string' ? tag : tag.name;
        return (
          <TagBadge
            key={name}
            tag={tag}
            onRemove={onRemove ? () => onRemove(name) : undefined}
            onClick={onClick ? () => onClick(name) : undefined}
          />
        );
      })}
    </div>
  );
}
