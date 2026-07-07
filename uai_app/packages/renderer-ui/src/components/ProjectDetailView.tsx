/**
 * ProjectDetailView — detail fields for a selected project.
 *
 * Used in ContextPanel (right panel Details tab) and as TabContentPane content.
 * Shows identity, goal, git state, sessions, tags, and notes.
 */

import { useState, useCallback } from 'react';
import type { ProjectCard, SessionCard } from '@uai/shared/cards';
import { useToast } from './Toast';
import { TagList } from './tags/TagBadge';
import { TagPicker } from './tags/TagPicker';
import { executeCommand } from '../utils/execute-command';

const LIFECYCLE_COLORS: Record<string, string> = {
  active: 'var(--accent-green)',
  paused: 'var(--accent-yellow)',
  complete: 'var(--accent-blue)',
  archived: 'var(--text-muted)',
};

const GIT_STATUS_COLORS: Record<string, string> = {
  clean: 'var(--accent-green)',
  dirty: 'var(--accent-orange)',
  ahead: 'var(--accent-blue)',
  behind: 'var(--accent-purple)',
  unknown: 'var(--text-muted)',
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

interface ProjectDetailViewProps {
  project: ProjectCard;
  sessions?: SessionCard[];
  compact?: boolean;  // true for ContextPanel, false for tab view
}

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

export default function ProjectDetailView({ project, sessions = [], compact }: ProjectDetailViewProps): JSX.Element {
  const { showToast } = useToast();
  const [showTagPicker, setShowTagPicker] = useState(false);

  const handleTagToggle = useCallback(async (_cardId: string, tagName: string) => {
    const hasTag = project.tags.includes(tagName);
    await executeCommand(hasTag ? 'tag.remove' : 'tag.add', {
      cardId: project.entity_id, tag: tagName,
    }, { onFailure: 'toast', toastFn: showToast });
  }, [project, showToast]);

  return (
    <div className={`project-detail-view${compact ? ' compact' : ''}`}>
      <div className="project-hero">
        <div className="project-hero-icon" aria-hidden="true">{'📁'}</div>
        <div className="project-hero-text">
          <h3 className="detail-view-title project-hero-title">{project.display_name}</h3>
          {project.goal && <p className="detail-view-subtitle project-hero-subtitle">{project.goal}</p>}
        </div>
        <div className="project-hero-badges">
          {project.lifecycle_status && (
            <span className="project-status-badge" style={{ color: LIFECYCLE_COLORS[project.lifecycle_status] || 'var(--text)' }}>
              {project.lifecycle_status}
            </span>
          )}
          <span className="project-status-badge project-git-badge" style={{ color: GIT_STATUS_COLORS[project.git_status] || 'var(--text)' }}>
            {project.git_status}
          </span>
        </div>
      </div>

      <div className="detail-view-section">
        <DetailRow label="Project ID" value={project.project_id} copyable />
        {project.lifecycle_status && <DetailRow label="Lifecycle" value={project.lifecycle_status} />}
        {project.goal && compact && <DetailRow label="Goal" value={project.goal} />}
      </div>

      <div className="detail-view-section">
        <div className="ctx-detail-row">
          <span className="ctx-detail-label">Git Status</span>
          <span className="ctx-detail-value" style={{ color: GIT_STATUS_COLORS[project.git_status] || 'var(--text)' }}>
            {project.git_status}
          </span>
        </div>
        {project.branch && <DetailRow label="Branch" value={project.branch} copyable />}
        <DetailRow label="Working Dir" value={project.working_dir} copyable />
      </div>

      <div className="detail-view-section">
        {project.session_count != null && <DetailRow label="Sessions" value={`${project.session_count}`} />}
        <DetailRow label="Source" value={project.source_path} copyable />
        {project.availability !== 'available' && (
          <DetailRow label="Availability" value={project.availability} />
        )}
      </div>

      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Files</span>
        </div>
        <div className="project-files-note">
          <div className="project-files-path copyable" onClick={() => window.uai.clipboard.write(project.working_dir)} title="Click to copy working directory">
            {project.working_dir}
          </div>
          <div className="project-files-help">
            Directory tree browsing is not wired yet in UAI. This section points to the canonical project root for now.
          </div>
        </div>
      </div>

      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Docs</span>
        </div>
        <div className="project-doc-links">
          <div className="project-doc-item">
            <span className="project-doc-label">Metadata</span>
            <span className="project-doc-value copyable" onClick={() => window.uai.clipboard.write(project.source_path)} title="Click to copy source path">
              {project.source_path}
            </span>
          </div>
        </div>
      </div>

      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Project Sessions ({sessions.length})</span>
        </div>
        {sessions.length > 0 ? (
          <div className="project-session-list">
            {sessions.map((sessionCard) => (
              <div key={sessionCard.entity_id} className="project-session-row">
                <span className="project-session-platform-dot" style={{ backgroundColor: PLATFORM_COLORS[sessionCard.platform] || 'var(--text-muted)' }} />
                <div className="project-session-main">
                  <div className="project-session-name">{sessionCard.display_name}</div>
                  <div className="project-session-meta">
                    <span>{PLATFORM_LABELS[sessionCard.platform] || sessionCard.platform}</span>
                    {sessionCard.roles && sessionCard.roles.length > 0 && (
                      <>
                        <span>·</span>
                        <span>{sessionCard.roles.join(', ')}</span>
                      </>
                    )}
                  </div>
                </div>
                <span className="project-session-status">{sessionCard.process_status}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="ctx-notes-empty">No sessions currently associated with this project.</div>
        )}
      </div>

      <div className="detail-view-section">
        <div className="ctx-section-header">
          <span>Tags</span>
          <span className="ctx-edit-btn" onClick={() => setShowTagPicker(!showTagPicker)}>
            {showTagPicker ? 'Done' : 'Edit'}
          </span>
        </div>
        {project.tags.length > 0 && <TagList tags={project.tags} />}
        {project.tags.length === 0 && !showTagPicker && (
          <div className="ctx-notes-empty">No tags.</div>
        )}
        {showTagPicker && (
          <TagPicker
            cardId={project.entity_id}
            currentTags={project.tags}
            entityType="project"
            onTagToggle={handleTagToggle}
            onCreateTag={async (name) => {
              await executeCommand('tag.add', {
                cardId: project.entity_id, tag: name,
              }, { onFailure: 'toast', toastFn: showToast });
            }}
          />
        )}
      </div>
    </div>
  );
}
