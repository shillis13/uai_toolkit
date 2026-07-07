/**
 * TerminalPane — xterm.js terminal attached to a tmux session via node-pty.
 *
 * Uses TerminalSelectionOverlay for text selection, copy, paste, and link handling.
 * The overlay sits on top of xterm.js and owns all mouse interaction.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';
import TerminalSelectionOverlay from './TerminalSelectionOverlay';
import MemorexView from './MemorexView';
import 'xterm/css/xterm.css';

interface TerminalPaneProps {
  sessionId: string;
  terminalSession: string;
  cliSessionId?: string | null;
  displayName: string;
}

export default function TerminalPane({ sessionId, terminalSession, cliSessionId, displayName }: TerminalPaneProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const [memorexEnabled, setMemorexEnabled] = useState(false);
  const [memorexSplit, setMemorexSplit] = useState(70); // percentage for memorex pane
  const bodyRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  // Re-fit terminal when Memorex toggles or split changes
  useEffect(() => {
    if (fitRef.current && termRef.current) {
      setTimeout(() => {
        fitRef.current?.fit();
        if (termRef.current) {
          window.uai.terminal.resize(sessionId, termRef.current.cols, termRef.current.rows);
        }
        termRef.current?.focus();
      }, 100);
    }
  }, [memorexEnabled, memorexSplit, sessionId]);

  // Drag handler for memorex/terminal divider
  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev: MouseEvent) => {
      if (!draggingRef.current || !bodyRef.current) return;
      const rect = bodyRef.current.getBoundingClientRect();
      const pct = ((ev.clientY - rect.top) / rect.height) * 100;
      setMemorexSplit(Math.min(85, Math.max(15, pct)));
    };

    const onMouseUp = () => {
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'SF Mono', 'Menlo', monospace",
      scrollback: 10000,
      allowProposedApi: true,
      macOptionClickForcesSelection: true,
      theme: {
        background: '#0a0c10',
        foreground: '#d0d8f0',
        cursor: '#7aa2f7',
        selectionBackground: 'rgba(122, 162, 247, 0.3)',
        black: '#12151c',
        red: '#f7768e',
        green: '#9ece6a',
        yellow: '#e0af68',
        blue: '#7aa2f7',
        magenta: '#bb9af7',
        cyan: '#7dcfff',
        white: '#d0d8f0',
        brightBlack: '#565f80',
        brightRed: '#f7768e',
        brightGreen: '#9ece6a',
        brightYellow: '#e0af68',
        brightBlue: '#7aa2f7',
        brightMagenta: '#bb9af7',
        brightCyan: '#7dcfff',
        brightWhite: '#d0d8f0',
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());

    // Defer open until container has non-zero dimensions
    const container = containerRef.current;
    const tryOpen = () => {
      if (!container || container.clientWidth === 0 || container.clientHeight === 0) {
        requestAnimationFrame(tryOpen);
        return;
      }
      term.open(container);
      fitAddon.fit();
    };
    tryOpen();

    termRef.current = term;
    fitRef.current = fitAddon;

    // Attach to tmux session via main process
    const cols = term.cols;
    const rows = term.rows;
    window.uai.terminal.attach(sessionId, terminalSession, cols, rows);

    // Shift+Enter → send \n (LF) instead of \r (CR) for newline insertion
    let shiftEnterPending = false;

    term.attachCustomKeyEventHandler((event: KeyboardEvent) => {
      if (event.type === 'keydown' && event.key === 'Enter' && event.shiftKey) {
        shiftEnterPending = true;
      }
      if (event.type === 'keydown' && (event.metaKey || event.ctrlKey)) {
        if (event.key === 'Home') {
          event.preventDefault();
          term.scrollToTop();
          return false;
        }
        if (event.key === 'End') {
          event.preventDefault();
          term.scrollToBottom();
          return false;
        }
      }
      return true;
    });

    // Forward terminal input → main → PTY
    const inputDisposable = term.onData((data: string) => {
      if (shiftEnterPending && data === '\r') {
        shiftEnterPending = false;
        window.uai.terminal.input(sessionId, '\n');
        return;
      }
      shiftEnterPending = false;
      window.uai.terminal.input(sessionId, data);
    });

    // Receive PTY output → terminal
    const unsubData = window.uai.terminal.onData((sid: string, data: string) => {
      if (sid === sessionId) {
        term.write(data);
      }
    });

    // Handle PTY exit
    const unsubExit = window.uai.terminal.onExit((sid: string, exitCode: number) => {
      if (sid === sessionId) {
        term.write(`\r\n\x1b[33m[Session exited with code ${exitCode}]\x1b[0m\r\n`);
      }
    });

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      fitAddon.fit();
      window.uai.terminal.resize(sessionId, term.cols, term.rows);
    });
    resizeObserver.observe(container);

    // Re-fit after layout settles
    requestAnimationFrame(() => {
      fitAddon.fit();
      setTimeout(() => {
        fitAddon.fit();
        if (termRef.current) {
          window.uai.terminal.resize(sessionId, termRef.current.cols, termRef.current.rows);
        }
      }, 150);
    });

    // Focus the terminal
    term.focus();

    // Cleanup
    return () => {
      inputDisposable.dispose();
      unsubData();
      unsubExit();
      resizeObserver.disconnect();
      window.uai.terminal.detach(sessionId);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [sessionId, terminalSession]);

  return (
    <div className="terminal-pane">
      <div className="terminal-pane-header">
        <span className="terminal-pane-name">{displayName}</span>
        <span className="terminal-pane-session">{terminalSession}</span>
        <button
          className={`memorex-toggle ${memorexEnabled ? 'active' : ''}`}
          onClick={() => setMemorexEnabled(v => !v)}
          title={memorexEnabled ? 'Disable Memorex view' : 'Enable Memorex view'}
        >
          {memorexEnabled ? '◉ Memorex' : '○ Memorex'}
        </button>
      </div>
      <div className="terminal-pane-body" ref={bodyRef}>
        {memorexEnabled && (
          <>
            <div className="memorex-pane" style={{ flex: `0 0 ${memorexSplit}%` }}>
              <MemorexView
                zellijSession={terminalSession}
                cliSessionId={cliSessionId || undefined}
                enabled={true}
                hideLiveZone={true}
              />
            </div>
            <div className="memorex-divider-handle" onMouseDown={handleDividerMouseDown}>
              <span className="memorex-divider-label">LIVE</span>
            </div>
          </>
        )}
        <div className="terminal-container" ref={containerRef} style={{ position: 'relative' }}>
          <TerminalSelectionOverlay
            termRef={termRef}
            containerRef={containerRef}
            sessionId={sessionId}
          />
        </div>
      </div>
    </div>
  );
}
