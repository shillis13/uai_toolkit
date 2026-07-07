/**
 * UAI App — Phase 0B Spike
 *
 * Proves the architecture end-to-end:
 * - Bootstrap from external stores (session_store.py)
 * - Render sessions through shared store
 * - Click session → attach terminal via node-pty + tmux
 * - Store change events refresh UI
 */

import { useState } from 'react';
import SessionList from './components/SessionList';
import TerminalPane from './components/TerminalPane';
import { useSessionStore } from './stores/session-store';

export default function App(): JSX.Element {
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const { getSession } = useSessionStore();

  const activeSession = activeSessionId ? getSession(activeSessionId) : undefined;

  return (
    <div className="app">
      <div className="navigator-panel">
        <SessionList
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
        />
      </div>
      <div className="workspace-panel">
        {activeSession && activeSession.terminal_session ? (
          <TerminalPane
            key={activeSession.tracking_id}
            sessionId={activeSession.tracking_id}
            terminalSession={activeSession.terminal_session}
            cliSessionId={activeSession.cli_session_id}
            displayName={activeSession.display_name || activeSession.tracking_id}
          />
        ) : activeSession && !activeSession.terminal_session ? (
          <div className="workspace-placeholder">
            <h2>{activeSession.display_name || activeSession.tracking_id}</h2>
            <p>No terminal session available for this session.</p>
          </div>
        ) : (
          <div className="workspace-placeholder">
            <h2>UAI</h2>
            <p>Select a session to open it here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
