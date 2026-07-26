/**
 * TerminalPane — xterm.js terminal attached to a tmux session via node-pty.
 *
 * Ported from spike (phase_0b_vertical_slice). Uses TerminalSelectionOverlay
 * for text selection, copy, paste, and link handling. Memorex format overlay
 * ported from production UCI.
 */

import { useEffect, useRef } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';
import TerminalSelectionOverlay from './TerminalSelectionOverlay';
import TerminalFormatOverlay from './TerminalFormatOverlay';
import { useViewport } from '../viewport';
import { touchSessionActivity } from '../stores/session-activity';
import { scanSessionPromptArea } from '../stores/prompt-area-state';
import { requestPromptBoxFocus } from '../stores/promptbox-focus';
import 'xterm/css/xterm.css';

interface TerminalPaneProps {
  sessionId: string;
  terminalSession: string;
  cliSessionId?: string | null;
  displayName: string;
  memorexEnabled?: boolean;
  active?: boolean;
}

export default function TerminalPane({ sessionId, terminalSession, cliSessionId, displayName, memorexEnabled: externalMemorex, active = true }: TerminalPaneProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const memorexEnabled = externalMemorex ?? false;

  useViewport('terminal_pane', () => ({
    visible: active,
    children: memorexEnabled ? ['memorex_view'] : [],
    state: { attached: true },
  }), active);

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

    const container = containerRef.current;
    termRef.current = term;
    fitRef.current = fitAddon;

    // Shift+Enter → LF instead of CR
    let shiftEnterPending = false;

    term.attachCustomKeyEventHandler((event: KeyboardEvent) => {
      // A real keydown while this terminal is focused is a genuine Center-Pane
      // action — this is the ONLY keyboard-derived recency signal. We deliberately
      // do NOT use term.onData for recency: xterm emits through onData not only for
      // user typing but also when the terminal AUTO-REPLIES to the CLI's terminal
      // queries (cursor-position / Device-Attributes / focus reports). Those
      // auto-replies fire inside the tmux attach-redraw burst on every tab open,
      // so counting onData would (and did) re-order Recent Sessions just from
      // VIEWING a session. A DOM keydown only happens when the user actually
      // presses a key here.
      if (event.type === 'keydown') {
        touchSessionActivity(sessionId);
      }
      if (event.type === 'keydown' && event.key === 'Enter' && event.shiftKey) {
        shiftEnterPending = true;
      }
      if (event.type === 'keydown' && (event.metaKey || event.ctrlKey)) {
        if (event.key === 'Home' || event.key === 'ArrowUp') {
          event.preventDefault();
          term.scrollToTop();
          return false;
        }
        if (event.key === 'End' || event.key === 'ArrowDown') {
          event.preventDefault();
          term.scrollToBottom();
          return false;
        }
      }
      return true;
    });

    // Forward terminal input → main → PTY. NOTE: recency is NOT bumped here — see
    // the keydown handler above. onData fires for terminal auto-replies during the
    // attach-redraw too, which would falsely re-order Recent Sessions on tab open.
    const inputDisposable = term.onData((data: string) => {
      // Typing into the CLI prompt area → re-scan this session's prompt-area state
      // (debounced). Catches both adding text and submitting/clearing it.
      scanSessionPromptArea(sessionId, 700);
      const active = document.activeElement;
      if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT')
          && !active.classList.contains('xterm-helper-textarea')) {
        return;
      }
      if (shiftEnterPending && data === '\r') {
        shiftEnterPending = false;
        window.uai.terminal.input(sessionId, '\n');
        return;
      }
      shiftEnterPending = false;
      window.uai.terminal.input(sessionId, data);
      // After submitting in the raw CLI prompt area (Enter), pull the cursor back
      // to the Prompt Box so the box — not the terminal — is the default surface.
      if (data === '\r') requestPromptBoxFocus(sessionId);
    });

    // Mouse interaction in the terminal (click, drag-select, scroll) is genuine
    // user activity in the Center Pane — count it for recency, exactly like
    // typing. Tab switches don't fire these, and PTY redraw bursts aren't mouse
    // events, so this can't reorder Recent Sessions just from viewing a tab.
    const mouseTarget = containerRef.current;
    const onUserMouse = () => touchSessionActivity(sessionId);
    mouseTarget?.addEventListener('mousedown', onUserMouse);
    mouseTarget?.addEventListener('wheel', onUserMouse, { passive: true });

    // Receive PTY output → terminal — register BEFORE attach so initial
    // screen data from tmux isn't dropped
    const unsubData = window.uai.terminal.onData((sid: string, data: string) => {
      if (sid === sessionId) {
        // NOTE: do NOT count PTY output as session activity. Output includes the
        // tmux attach-redraw burst that fires on every tab switch, which would
        // re-order Recent Sessions just from viewing a tab. Recency is driven
        // only by the user typing (term.onData above + prompt submit).
        term.write(data);
      }
    });

    // Only resize the pty when the CHARACTER GRID actually changes. A resize sends
    // ioctl(TIOCSWINSZ) → SIGWINCH → the CLI repaints, and repainting an overflowing
    // response is exactly what corrupts the scrollback (interleaved blanks, duplicated
    // blocks, dropped ⏺ marker). fit() runs on every container size change — including
    // sub-cell ones (a panel toggling, the Prompt Box drag, minor layout shifts) that
    // leave cols/rows identical. Sending a same-size resize on those is pure waste and
    // a needless repaint trigger, so guard against it.
    let lastSentCols = -1;
    let lastSentRows = -1;
    const sendResizeIfChanged = () => {
      const t = termRef.current;
      if (!t) return;
      if (t.cols === lastSentCols && t.rows === lastSentRows) return;
      lastSentCols = t.cols;
      lastSentRows = t.rows;
      window.uai.terminal.resize(sessionId, t.cols, t.rows);
    };

    // Open xterm into container, then attach to tmux session
    const tryOpen = () => {
      if (!container || container.clientWidth === 0 || container.clientHeight === 0) {
        requestAnimationFrame(tryOpen);
        return;
      }
      term.open(container);
      fitAddon.fit();
      window.uai.terminal.attach(sessionId, terminalSession, term.cols, term.rows);
      lastSentCols = term.cols;  // attach already delivered this size
      lastSentRows = term.rows;
    };
    tryOpen();

    // Handle PTY exit
    const unsubExit = window.uai.terminal.onExit((sid: string, exitCode: number) => {
      if (sid === sessionId) {
        term.write(`\r\n\x1b[33m[Session exited with code ${exitCode}]\x1b[0m\r\n`);
      }
    });

    // Handle resize (debounced to avoid infinite loop from fit() triggering ResizeObserver)
    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    const resizeObserver = new ResizeObserver(() => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        fitAddon.fit();
        sendResizeIfChanged();
      }, 50);
    });
    resizeObserver.observe(container);

    // Re-fit after layout settles so the pty matches the on-screen xterm size.
    //
    // NOTE: do NOT force a redraw here (e.g. a resize "jiggle"). Forcing the CLI to
    // repaint is exactly what drops the ⏺ response marker on a response taller than
    // the viewport (Claude re-renders the visible tail without the off-screen marker),
    // which then gets folded into the preceding tool section in Memorex. Blank space
    // below the statusline is handled at the overlay layer instead — never by making
    // the CLI redraw. A plain fit+resize only sends SIGWINCH when the size actually
    // changed, so it doesn't gratuitously repaint.
    requestAnimationFrame(() => {
      fitAddon.fit();
      setTimeout(() => {
        fitAddon.fit();
        sendResizeIfChanged();
      }, 150);
    });

    if (active) term.focus();

    return () => {
      inputDisposable.dispose();
      mouseTarget?.removeEventListener('mousedown', onUserMouse);
      mouseTarget?.removeEventListener('wheel', onUserMouse);
      unsubData();
      unsubExit();
      resizeObserver.disconnect();
      window.uai.terminal.detach(sessionId);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [sessionId, terminalSession]);

  useEffect(() => {
    if (active) termRef.current?.focus();
  }, [active]);

  return (
    <div className="terminal-pane">
      <div className="terminal-pane-body">
        <div className="terminal-container" ref={containerRef} style={{ position: 'relative' }}>
          <TerminalSelectionOverlay
            termRef={termRef}
            containerRef={containerRef}
            sessionId={sessionId}
          />
          <TerminalFormatOverlay
            termRef={termRef}
            containerRef={containerRef}
            sessionName={terminalSession}
            sessionId={sessionId}
            enabled={memorexEnabled}
            active={active}
          />
        </div>
      </div>
    </div>
  );
}
