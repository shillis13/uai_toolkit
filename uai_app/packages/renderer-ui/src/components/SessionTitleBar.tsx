/**
 * SessionTitleBar — two-row title bar matching UCI's CardDetailView toolbar.
 *
 * Row 1: ← ↑ → nav arrows | Session name | platform badge | folder | ... | UUID/Terminal stacked | Stop | RUNNING | Transcript | Memorex
 * Row 2 (when Memorex active): filter pills
 *
 * Spans full width of workspace, above both content and right panel.
 */

import { useState, useCallback } from 'react';
import { useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import { useFeature } from '../stores/features';
import type { Tab, Session } from '@uai/shared/types';

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: '#e07a4a',
  codex_cli: '#8b5cf6',
  gemini_cli: '#4285f4',
};

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'claude',
  codex_cli: 'codex',
  gemini_cli: 'gemini',
};

interface SessionTitleBarProps {
  tab: Tab;
  subtab?: 'chat' | 'work';
  onSetSubtab?: (v: 'chat' | 'work') => void;
  onToggleMemorex?: () => void;
  memorexEnabled?: boolean;
  onToggleTranscript?: () => void;
  transcriptOpen?: boolean;
  onToggleRightPanel?: () => void;
  canGoBack?: boolean;
  canGoForward?: boolean;
  onNavigateBack?: () => void;
  onNavigateForward?: () => void;
  onNavigateUp?: () => void;
  canGoUp?: boolean;
}

export default function SessionTitleBar({ tab, subtab = 'chat', onSetSubtab, onToggleMemorex, memorexEnabled, onToggleTranscript, transcriptOpen, onToggleRightPanel, canGoBack, canGoForward, onNavigateBack, onNavigateForward, onNavigateUp, canGoUp }: SessionTitleBarProps): JSX.Element {
  const { getSession } = useSessionStore();
  const { showToast } = useToast();
  const showWorkSubtab = useFeature('session.workSubtab');
  const session = getSession(tab.targetId);
  const isRunning = session?.process_status === 'running';

  const handleStop = useCallback(() => {
    if (!session) return;
    executeCommand('session.stop', { trackingId: session.tracking_id }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [session, showToast]);

  const handleResume = useCallback(() => {
    if (!session) return;
    executeCommand('session.resume', { trackingId: session.tracking_id }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [session, showToast]);

  const handleTranscript = useCallback(() => {
    onToggleTranscript?.();
  }, [onToggleTranscript]);

  const handleCopyUri = useCallback(() => {
    if (session?.tracking_id) {
      window.uai.clipboard.write(`uai://session/${session.tracking_id}`);
      showToast('Copied URI', 'info');
    }
  }, [session, showToast]);

  const handleCopyUuid = useCallback(() => {
    if (session?.cli_session_id) {
      window.uai.clipboard.write(session.cli_session_id);
      showToast('Copied UUID', 'info');
    }
  }, [session, showToast]);

  return (
    <div className="session-title-bar">
      {/* Row 1 */}
      <div className="stb-row">
        <div className="stb-left">
          <div className="stb-nav-arrows">
            <button className="stb-nav-btn" title="Back" disabled={!canGoBack} onClick={onNavigateBack}>{'\u2190'}</button>
            <button className="stb-nav-btn" title="Up to folder" disabled={!canGoUp} onClick={onNavigateUp}>{'\u2191'}</button>
            <button className="stb-nav-btn" title="Forward" disabled={!canGoForward} onClick={onNavigateForward}>{'\u2192'}</button>
          </div>
          <span className="stb-name">{session?.display_name || tab.label}</span>
          {session?.platform && (
            <span className="stb-badge" style={{ color: PLATFORM_COLORS[session.platform] || 'var(--text-muted)' }}>
              {PLATFORM_LABELS[session.platform] || session.platform}
            </span>
          )}
          {/* The Chat/Work toggle only appears when the Work subtab feature is on;
              hidden, a session is chat-only so the toggle is pointless. */}
          {onSetSubtab && showWorkSubtab && (
            <div className="stb-subtabs" role="tablist" aria-label="Chat or Work view">
              <button className={`stb-subtab chat${subtab === 'chat' ? ' on' : ''}`} onClick={() => onSetSubtab('chat')} title="Chat — live terminal / transcript">💬 Chat</button>
              <button className={`stb-subtab work${subtab === 'work' ? ' on' : ''}`} onClick={() => onSetSubtab('work')} title="Work — this session's worker page">🗂 Work</button>
            </div>
          )}
        </div>
        <div className="stb-right">
          {session?.tracking_id && (
            <div className="stb-ids">
              <span className="stb-id" onClick={handleCopyUri} title={`URI: uai://session/${session.tracking_id}`}>
                URI: uai://session/{session.tracking_id}
              </span>
              {session.cli_session_id && (
                <span className="stb-id stb-id-secondary" onClick={handleCopyUuid} title={`UUID: ${session.cli_session_id}`}>
                  UUID: {session.cli_session_id}
                </span>
              )}
            </div>
          )}
          {isRunning ? (
            <button className="stb-stop-btn" onClick={handleStop} title="Stop session">Stop</button>
          ) : (
            <button className="stb-resume-btn" onClick={handleResume} title="Resume session">Resume</button>
          )}
          <span className={`stb-status ${isRunning ? 'running' : 'stopped'}`}>
            {isRunning ? 'RUNNING' : 'STOPPED'}
          </span>
          <button className={`stb-action-btn${transcriptOpen ? ' stb-btn-active-transcript' : ''}`} onClick={handleTranscript} title={transcriptOpen ? 'Close transcript' : 'View transcript'}>
            Transcript
          </button>
          <button
            className={`stb-action-btn${memorexEnabled ? ' stb-btn-active-memorex' : ''}`}
            onClick={onToggleMemorex}
            title="Toggle Memorex view"
          >
            Memorex
          </button>
          {onToggleRightPanel && (
            <button className="stb-action-btn stb-panel-toggle" onClick={onToggleRightPanel} title="Toggle right panel">
              {'\u2759\u2759'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
