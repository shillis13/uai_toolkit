/**
 * TeamDetailView — detail fields for a selected team.
 *
 * Used in ContextPanel (right panel Details tab) and as TabContentPane content.
 * Shows identity, slots with occupancy, comms plan, assigned projects, tags.
 */

import { useState, useCallback } from 'react';
import type { TeamCard } from '@uai/shared/cards';
import { useToast } from './Toast';
import { TagList } from './tags/TagBadge';
import { TagPicker } from './tags/TagPicker';
import { executeCommand } from '../utils/execute-command';

const STATUS_COLORS: Record<string, string> = {
  active: 'var(--accent-green)',
  paused: 'var(--accent-yellow)',
  disbanded: 'var(--text-muted)',
};

function DetailRow({ label, value, copyable }: { label: string; value: string | null; copyable?: boolean }): JSX.Element {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    if (!value) return;
    window.uai.clipboard.write(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [value]);

  return (
    <div className="ctx-detail-row">
      <span className="ctx-detail-label">{label}</span>
      <span
        className={`ctx-detail-value${copyable ? ' copyable' : ''}`}
        onClick={copyable ? handleCopy : undefined}
        title={copyable ? 'Click to copy' : undefined}
      >
        {value || '\u2014'}
        {copied && <span className="ctx-copied-badge">Copied</span>}
      </span>
    </div>
  );
}

interface TeamDetailViewProps {
  team: TeamCard;
  compact?: boolean;
}

export default function TeamDetailView({ team, compact }: TeamDetailViewProps): JSX.Element {
  const { showToast } = useToast();
  const [showTagPicker, setShowTagPicker] = useState(false);

  const handleTagToggle = useCallback(async (_cardId: string, tagName: string) => {
    const hasTag = team.tags.includes(tagName);
    await executeCommand(hasTag ? 'tag.remove' : 'tag.add', {
      cardId: team.entity_id, tag: tagName,
    }, { onFailure: 'toast', toastFn: showToast });
  }, [team, showToast]);

  return (
    <div className={`team-detail-view${compact ? ' compact' : ''}`}>
      {!compact && (
        <div className="detail-view-header">
          <h3 className="detail-view-title">{team.display_name}</h3>
          {team.description && <p className="detail-view-subtitle">{team.description}</p>}
        </div>
      )}

      <div className="detail-view-section">
        <DetailRow label="Team ID" value={team.entity_id.split(':')[1]} copyable />
        <div className="ctx-detail-row">
          <span className="ctx-detail-label">Status</span>
          <span className="ctx-detail-value" style={{ color: STATUS_COLORS[team.status] || 'var(--text)' }}>
            {team.status}
          </span>
        </div>
        {compact && team.description && <DetailRow label="Description" value={team.description} />}
      </div>

      {/* Slots */}
      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Slots</span>
          <span className="ctx-detail-value" style={{ fontSize: '11px' }}>
            {team.filled_count}/{team.slot_count} filled
          </span>
        </div>
        <div className="team-slots-bar">
          {Array.from({ length: team.slot_count }, (_, i) => (
            <div
              key={i}
              className={`team-slot-indicator ${i < team.filled_count ? 'filled' : 'empty'}`}
              title={i < team.filled_count ? 'Filled' : 'Available'}
            />
          ))}
        </div>
      </div>

      {/* Assigned Projects */}
      {team.project_ids.length > 0 && (
        <div className="detail-view-section">
          <div className="ctx-section-header"><span>Projects</span></div>
          {team.project_ids.map(pid => (
            <div key={pid} className="team-project-link" onClick={() => {
              executeCommand('workspace.tabs.open', {
                type: 'project', targetId: pid, label: pid,
              });
            }}>
              {pid}
            </div>
          ))}
        </div>
      )}

      <div className="detail-view-section">
        <DetailRow label="Source" value={team.source_path} copyable />
        {team.availability !== 'available' && (
          <DetailRow label="Availability" value={team.availability} />
        )}
      </div>

      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Tags</span>
          <span className="ctx-edit-btn" onClick={() => setShowTagPicker(!showTagPicker)}>
            {showTagPicker ? 'Done' : 'Edit'}
          </span>
        </div>
        {team.tags.length > 0 && <TagList tags={team.tags} />}
        {team.tags.length === 0 && !showTagPicker && (
          <div className="ctx-notes-empty">No tags.</div>
        )}
        {showTagPicker && (
          <TagPicker
            cardId={team.entity_id}
            currentTags={team.tags}
            entityType="team"
            onTagToggle={handleTagToggle}
            onCreateTag={async (name) => {
              await executeCommand('tag.add', {
                cardId: team.entity_id, tag: name,
              }, { onFailure: 'toast', toastFn: showToast });
            }}
          />
        )}
      </div>
    </div>
  );
}
