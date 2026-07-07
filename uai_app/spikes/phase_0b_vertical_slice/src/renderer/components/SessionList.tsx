/**
 * SessionList — Phase 0B Spike component.
 *
 * Renders sessions from the shared SessionStore.
 * Proves: bootstrap → store → component rendering → command → change event refresh.
 */

import { useState, useRef, useEffect } from 'react';
import { useSessionStore } from '../stores/session-store';
import type { Session } from '../../shared/types';

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: '#ff9e64',
  codex_cli: '#bb9af7',
  gemini_cli: '#7aa2f7',
};

const STATUS_COLORS: Record<string, string> = {
  running: '#9ece6a',
  stopped: '#565f89',
  exited: '#565f89',
};

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return '';
  }
}

function getDisplayName(session: Session): string {
  if (session.display_name) {
    return session.display_name
      .replace(/^(claude|codex|gemini)_cli_/, '')
      .replace(/_\d{8}T\d{6}$/, '')
      .replace(/_/g, ' ');
  }
  return session.roles.length > 0 ? session.roles[0] : session.tracking_id;
}

// ─── Context Menu ──────────────────────────────────────────────────────────

interface ContextMenuState {
  x: number;
  y: number;
  sessionId: string;
}

function ContextMenu({ x, y, session, onClose, onRename }: {
  x: number;
  y: number;
  session: Session;
  onClose: () => void;
  onRename: () => void;
}): JSX.Element {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div ref={menuRef} className="context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
      <button className="context-menu-item" onClick={() => { onRename(); onClose(); }}>Rename</button>
      <button className="context-menu-item" onClick={() => {
        window.uai.clipboard.write(session.tracking_id);
        onClose();
      }}>Copy Tracking ID</button>
      {session.cli_session_id && (
        <button className="context-menu-item" onClick={() => {
          window.uai.clipboard.write(session.cli_session_id!);
          onClose();
        }}>Copy CLI UUID</button>
      )}
    </div>
  );
}

// ─── Session Card ──────────────────────────────────────────────────────────

function SessionCard({ session, active, onClick, onContextMenu, renaming, renameValue, onRenameChange, onRenameSubmit, onRenameCancel }: {
  session: Session;
  active: boolean;
  onClick: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
  renaming: boolean;
  renameValue: string;
  onRenameChange: (v: string) => void;
  onRenameSubmit: () => void;
  onRenameCancel: () => void;
}): JSX.Element {
  const platformColor = PLATFORM_COLORS[session.platform] || '#565f89';
  const statusColor = STATUS_COLORS[session.process_status] || '#565f89';
  const name = getDisplayName(session);
  const isActive = session.process_status === 'running';

  return (
    <div
      className={`session-card ${isActive ? '' : 'stopped'} ${active ? 'active' : ''}`}
      onClick={onClick}
      onContextMenu={onContextMenu}
    >
      <div className="card-platform-bar" style={{ backgroundColor: platformColor }} />
      <div className="card-content">
        <div className="card-header">
          {renaming ? (
            <input
              className="card-rename-input"
              value={renameValue}
              onChange={(e) => onRenameChange(e.target.value)}
              onBlur={onRenameSubmit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onRenameSubmit();
                if (e.key === 'Escape') onRenameCancel();
              }}
              onClick={(e) => e.stopPropagation()}
              autoFocus
            />
          ) : (
            <span className="card-name">{name}</span>
          )}
          <span className="card-time">{formatTime(session.last_activity || session.created_at)}</span>
          <span className="card-status-dot" style={{ backgroundColor: statusColor }} />
        </div>
        <div className="card-meta">
          {session.roles.length > 0 && <span className="card-role">{session.roles[0]}</span>}
          {session.context_percent != null && session.context_percent > 0 && (
            <span className="card-ctx">ctx:{session.context_percent}%</span>
          )}
          {session.identity_status !== 'confirmed' && (
            <span className="card-badge draft">{session.identity_status}</span>
          )}
          {session.notes && <span className="card-notes-hint" title={session.notes}>notes</span>}
        </div>
      </div>
    </div>
  );
}

// ─── Session List ──────────────────────────────────────────────────────────

interface SessionListProps {
  activeSessionId: string | null;
  onSelectSession: (trackingId: string) => void;
}

export default function SessionList({ activeSessionId, onSelectSession }: SessionListProps): JSX.Element {
  const { sessions, initialized, refresh, aiRoot } = useSessionStore();
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const handleContextMenu = (e: React.MouseEvent, sessionId: string) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, sessionId });
  };

  const startRename = (session: Session) => {
    setRenamingId(session.tracking_id);
    setRenameValue(session.display_name || '');
  };

  const submitRename = async () => {
    if (!renamingId || !renameValue.trim()) {
      setRenamingId(null);
      return;
    }
    // Path 1: dispatch command → main → session_store.py → SQLite
    const result = await window.uai.sessions.update(renamingId, { display_name: renameValue.trim() });
    if (!result.ok) {
      console.error('Rename failed:', result.error);
    }
    // Path 2 will handle the refresh via onStoreChanged
    setRenamingId(null);
  };

  const cancelRename = () => {
    setRenamingId(null);
  };

  const createSession = async (platform: string) => {
    const platformLabels: Record<string, string> = {
      claude_cli: 'Claude',
      codex_cli: 'Codex',
      gemini_cli: 'Gemini',
    };
    const result = await window.uai.sessions.create({
      platform,
      displayName: `${platformLabels[platform] || 'AI'} — app launched`,
      roles: ['assistant'],
      projectDir: aiRoot || undefined,
    });
    if (!result.ok) {
      console.error('Create session failed:', result.error);
    }
  };

  if (!initialized) {
    return <div className="session-list-loading">Loading sessions...</div>;
  }

  const active = sessions.filter(s => s.process_status === 'running');
  const stopped = sessions.filter(s => s.process_status !== 'running' && !s.archived);
  const ctxSession = contextMenu ? sessions.find(s => s.tracking_id === contextMenu.sessionId) : null;

  const renderCard = (s: Session) => (
    <SessionCard
      key={s.tracking_id}
      session={s}
      active={s.tracking_id === activeSessionId}
      onClick={() => onSelectSession(s.tracking_id)}
      onContextMenu={(e) => handleContextMenu(e, s.tracking_id)}
      renaming={renamingId === s.tracking_id}
      renameValue={renameValue}
      onRenameChange={setRenameValue}
      onRenameSubmit={submitRename}
      onRenameCancel={cancelRename}
    />
  );

  return (
    <div className="session-list">
      <div className="session-list-header">
        <span className="session-list-title">Sessions ({sessions.length})</span>
        <button className="refresh-btn" onClick={refresh} title="Refresh">↻</button>
      </div>
      <div className="new-session-bar">
        <button className="new-session-btn claude" onClick={() => createSession('claude_cli')}>+ Claude</button>
        <button className="new-session-btn codex" onClick={() => createSession('codex_cli')}>+ Codex</button>
        <button className="new-session-btn gemini" onClick={() => createSession('gemini_cli')}>+ Gemini</button>
      </div>
      {active.length > 0 && (
        <div className="session-section">
          <div className="session-section-label">Active ({active.length})</div>
          {active.map(renderCard)}
        </div>
      )}
      {stopped.length > 0 && (
        <div className="session-section">
          <div className="session-section-label">Stopped ({stopped.length})</div>
          {stopped.map(renderCard)}
        </div>
      )}
      {sessions.length === 0 && (
        <div className="session-list-empty">No sessions found.</div>
      )}

      {/* Context Menu */}
      {contextMenu && ctxSession && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          session={ctxSession}
          onClose={() => setContextMenu(null)}
          onRename={() => startRename(ctxSession)}
        />
      )}
    </div>
  );
}
