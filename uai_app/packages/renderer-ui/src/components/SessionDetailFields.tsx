import { useState, useCallback } from 'react';
import type { Session } from '@uai/shared/types';

export interface SessionDetailFieldsProps {
  session: Session;
  queueCount?: number;
  inboxCount?: { total: number; unread: number };
  onEditInStore?: () => void;
}

const PROCESS_STATUS_COLORS: Record<string, string> = {
  running: 'var(--accent-green)',
  stopped: 'var(--text-muted)',
  exited: 'var(--accent-orange)',
};

const IDENTITY_STATUS_COLORS: Record<string, string> = {
  draft: 'var(--text-muted)',
  pending: 'var(--accent-yellow)',
  confirmed: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  orphaned: 'var(--accent-orange)',
};

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude CLI',
  codex_cli: 'Codex CLI',
  gemini_cli: 'Gemini CLI',
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

function formatDate(value?: string | null): string | null {
  if (!value) return null;
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function statusLabel(status: string): string {
  return status.toUpperCase();
}

function DetailRow({
  label,
  fieldKey,
  value,
  mono,
  copyable,
}: {
  label: string;
  fieldKey: string;
  value?: string | null;
  mono?: boolean;
  copyable?: boolean;
}): JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!copyable || !value) return;
    window.uai.clipboard.write(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }, [copyable, value]);

  return (
    <div className="worker-detail-row right-panel-detail-row">
      <span className="worker-detail-label">{label}</span>
      <span
        className={`worker-detail-value${copyable && value ? ' worker-detail-copyable' : ''}${mono ? ' worker-detail-path' : ''}`}
        onClick={handleCopy}
        title={copyable && value ? 'Click to copy' : undefined}
      >
        {copied ? '✓ Copied' : (value || '—')}
      </span>
    </div>
  );
}

function DetailSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ctx-detail-section">
      <div className="ctx-detail-section-header" onClick={() => setOpen((value) => !value)}>
        <span className="ctx-detail-section-arrow">{open ? '▾' : '▸'}</span>
        <span className="ctx-detail-section-title">{title}</span>
      </div>
      {open && <div className="ctx-detail-section-body worker-detail-info">{children}</div>}
    </div>
  );
}

export default function SessionDetailFields({
  session,
  queueCount = 0,
  inboxCount = { total: 0, unread: 0 },
  onEditInStore,
}: SessionDetailFieldsProps): JSX.Element {
  const displayName = session.display_name || session.tracking_id;
  const roleText = session.roles.length > 0 ? session.roles.join(', ') : null;
  const msgCount = session.message_count != null ? String(session.message_count) : null;
  const contextText = session.context_percent != null ? `${session.context_percent}% used` : null;

  return (
    <>
      <div className="right-panel-detail-summary worker-detail-summary">
        <span className="ctx-status-dot" style={{ backgroundColor: PROCESS_STATUS_COLORS[session.process_status] || 'var(--text-muted)' }} />
        <span className="platform-pill" style={{ color: PLATFORM_COLORS[session.platform] || 'var(--text-sec)' }}>
          {PLATFORM_LABELS[session.platform] || session.platform}
        </span>
        <span className="right-panel-detail-name" title={displayName}>{displayName}</span>
        {onEditInStore && (
          <button className="sess-store-edit-in-store-btn" onClick={onEditInStore} title="Edit in Session Store Manager">Edit</button>
        )}
      </div>

      <div className="worker-detail-info right-panel-session-details">
        <DetailSection title="Identity">
          <div className="worker-detail-row right-panel-detail-row">
            <span className="worker-detail-label">Status</span>
            <span className={`status-pill ${session.process_status}`}>{statusLabel(session.process_status)}</span>
          </div>
          <DetailRow label="ID" fieldKey="tracking_id" value={session.tracking_id} mono copyable />
          <DetailRow label="CLI UUID" fieldKey="cli_uuid" value={session.cli_session_id} mono copyable />
          <DetailRow label="Terminal Session" fieldKey="terminal_session" value={session.terminal_session} mono copyable />
          <DetailRow label="Display Name" fieldKey="display_name" value={session.display_name} />
        </DetailSection>

        <DetailSection title="Classification">
          <DetailRow label="Platform" fieldKey="platform" value={PLATFORM_LABELS[session.platform] || session.platform} />
          <DetailRow label="Runtime" fieldKey="runtime_state" value={session.runtime_state} />
          <DetailRow label="Role" fieldKey="roles" value={roleText} />
          <div className="worker-detail-row right-panel-detail-row">
            <span className="worker-detail-label">Identity</span>
            <span className="ctx-status-pill" style={{ color: IDENTITY_STATUS_COLORS[session.identity_status] || 'var(--text-muted)' }}>
              {session.identity_status}
            </span>
          </div>
          <DetailRow label="Parent" fieldKey="parent_tracking_id" value={session.parent_tracking_id} mono copyable />
        </DetailSection>

        <DetailSection title="Paths">
          <DetailRow label="Project Dir" fieldKey="project_dir" value={session.project_dir} mono copyable />
          <DetailRow label="Session Dir" fieldKey="session_dir" value={session.session_dir} mono copyable />
        </DetailSection>

        <DetailSection title="Metrics">
          <DetailRow label="Turns" fieldKey="turns" value={String(session.exchange_count ?? 0)} />
          <DetailRow label="Msgs" fieldKey="msgs" value={msgCount} />
          <DetailRow label="Context" fieldKey="context" value={contextText} />
          <DetailRow label="Inbox (Prompts)" fieldKey="queued_prompts" value={String(queueCount)} />
          <DetailRow label="Inbox (Messages)" fieldKey="unread_messages" value={String(inboxCount.unread)} />
        </DetailSection>

        <DetailSection title="Timestamps">
          <DetailRow label="Created" fieldKey="created_at" value={formatDate(session.created_at)} />
          <DetailRow label="Last Activity" fieldKey="last_activity" value={formatDate(session.last_activity)} />
        </DetailSection>
      </div>
    </>
  );
}
