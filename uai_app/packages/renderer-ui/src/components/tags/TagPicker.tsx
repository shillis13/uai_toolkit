/**
 * TagPicker — tag selection/management for context menus and panels.
 *
 * Workstream 1C: Organization Entities
 *
 * Shows available tags with checkmarks for currently applied tags.
 * Supports creating new tags inline. Used in context menus and the
 * context panel's tag section.
 */

import React, { useState } from 'react';
import { useTagStore } from '../../stores/tag-store';
import type { Tag, EntityType } from '@uai/shared/types';

// ─── Props ───────────────────────────────────────────────────────────────

interface TagPickerProps {
  cardId: string;
  currentTags: string[];
  entityType?: EntityType;  // Filter tags by entity type
  onTagToggle: (cardId: string, tagName: string) => void;
  onCreateTag?: (name: string, color: string) => void;
}

// ─── Default Colors ──────────────────────────────────────────────────────

const TAG_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899',
];

// ─── Component ───────────────────────────────────────────────────────────

export function TagPicker({
  cardId,
  currentTags,
  entityType = 'session',
  onTagToggle,
  onCreateTag,
}: TagPickerProps): React.ReactElement {
  const { tags, tagsForEntityType } = useTagStore();
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState(TAG_COLORS[0]);

  const availableTags = tagsForEntityType(entityType);

  const handleToggle = (tagName: string) => {
    onTagToggle(cardId, tagName);
  };

  const handleCreate = () => {
    if (!newName.trim()) return;
    onCreateTag?.(newName.trim(), newColor);
    setNewName('');
    setShowCreate(false);
  };

  return (
    <div className="tag-picker">
      <div className="tag-picker-header">Tags</div>

      {/* Existing tags with toggles */}
      <div className="tag-picker-list">
        {availableTags.map((tag) => {
          const isApplied = currentTags.includes(tag.name);
          return (
            <button
              key={tag.name}
              className={`tag-picker-item ${isApplied ? 'tag-picker-item--active' : ''}`}
              onClick={() => handleToggle(tag.name)}
            >
              <span
                className="tag-picker-color"
                style={{ backgroundColor: tag.color || '#666' }}
              />
              <span className="tag-picker-name">{tag.name}</span>
              {isApplied && <span className="tag-picker-check">{'\u2713'}</span>}
            </button>
          );
        })}
        {availableTags.length === 0 && !showCreate && (
          <div className="tag-picker-empty">No tags defined</div>
        )}
      </div>

      {/* Create new tag */}
      {showCreate ? (
        <div className="tag-picker-create">
          <input
            className="tag-picker-input"
            type="text"
            placeholder="Tag name..."
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate();
              if (e.key === 'Escape') setShowCreate(false);
            }}
            autoFocus
          />
          <div className="tag-picker-colors">
            {TAG_COLORS.map((c) => (
              <button
                key={c}
                className={`tag-picker-color-swatch ${c === newColor ? 'tag-picker-color-swatch--selected' : ''}`}
                style={{ backgroundColor: c }}
                onClick={() => setNewColor(c)}
                title={c}
              />
            ))}
          </div>
          <div className="tag-picker-actions">
            <button className="tag-picker-btn" onClick={handleCreate}>Create</button>
            <button className="tag-picker-btn tag-picker-btn--cancel" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        onCreateTag && (
          <button className="tag-picker-add" onClick={() => setShowCreate(true)}>
            + New tag
          </button>
        )
      )}
    </div>
  );
}
