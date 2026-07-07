/**
 * StandaloneTerminal — raw shell terminal (no AI session).
 *
 * Renders a full-width xterm.js terminal connected to a plain shell ($SHELL).
 * No session association, no PromptBox, no transcript, no Memorex — just a PTY.
 * Used by the 'terminal' tab type in TabContentPane.
 */

import { useEffect, useRef, useCallback } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';
import { WebLinksAddon } from 'xterm-addon-web-links';
import 'xterm/css/xterm.css';

interface StandaloneTerminalProps {
  tabId: string;
  cwd?: string;
}

const THEME = {
  background: '#0a0c10',
  foreground: '#d0d8f0',
  cursor: '#d0d8f0',
  cursorAccent: '#0a0c10',
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
  brightWhite: '#c0caf5',
};

export default function StandaloneTerminal({ tabId, cwd }: StandaloneTerminalProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const initializedRef = useRef(false);
  const cleanupFnsRef = useRef<Array<() => void>>([]);

  const doFit = useCallback(() => {
    if (fitRef.current && termRef.current && containerRef.current) {
      if (containerRef.current.clientWidth > 0 && containerRef.current.clientHeight > 0) {
        fitRef.current.fit();
        const { cols, rows } = termRef.current;
        window.uai.standaloneTerminal.resize(tabId, cols, rows);
      }
    }
  }, [tabId]);

  useEffect(() => {
    if (initializedRef.current || !containerRef.current) return;
    initializedRef.current = true;

    const term = new Terminal({
      theme: THEME,
      fontFamily: "'SF Mono', 'Menlo', monospace",
      fontSize: 13,
      cursorBlink: true,
      scrollback: 10000,
      allowProposedApi: true,
      macOptionClickForcesSelection: true,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());

    const container = containerRef.current;

    const tryOpen = () => {
      if (!container || container.clientWidth === 0 || container.clientHeight === 0) {
        requestAnimationFrame(tryOpen);
        return;
      }
      term.open(container);
      fitAddon.fit();

      // Wire output: PTY -> xterm. This MUST be registered before create() so
      // that a re-attach replay (the PTY's scrollback, sent on the data channel
      // during the create handler) isn't missed on tab-switch remount.
      const removeDataListener = window.uai.standaloneTerminal.onData((id: string, data: string) => {
        if (id === tabId) {
          term.write(data);
        }
      });
      cleanupFnsRef.current.push(removeDataListener);

      // Handle PTY exit
      const removeExitListener = window.uai.standaloneTerminal.onExit((id: string, exitCode: number) => {
        if (id === tabId) {
          term.write(`\r\n\x1b[90m[Process exited with code ${exitCode}]\x1b[0m\r\n`);
        }
      });
      cleanupFnsRef.current.push(removeExitListener);

      // Create (or re-attach to) the standalone PTY after the terminal is open
      // and has dimensions.
      const { cols, rows } = term;
      window.uai.standaloneTerminal.create(tabId, cols, rows, cwd).then(() => {
        // Wire input: xterm -> PTY
        const dataDisposable = term.onData((data: string) => {
          window.uai.standaloneTerminal.input(tabId, data);
        });
        cleanupFnsRef.current.push(() => dataDisposable.dispose());
      });
    };
    tryOpen();

    termRef.current = term;
    fitRef.current = fitAddon;

    // Re-fit after layout settles
    requestAnimationFrame(() => {
      fitAddon.fit();
      setTimeout(() => {
        fitAddon.fit();
        if (termRef.current) {
          const { cols, rows } = termRef.current;
          window.uai.standaloneTerminal.resize(tabId, cols, rows);
        }
      }, 150);
    });

    // ResizeObserver for container dimension changes
    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    const resizeObserver = new ResizeObserver(() => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (fitRef.current && termRef.current) {
          fitRef.current.fit();
          window.uai.standaloneTerminal.resize(tabId, termRef.current.cols, termRef.current.rows);
        }
      }, 50);
    });
    resizeObserver.observe(container);
    cleanupFnsRef.current.push(() => resizeObserver.disconnect());

    term.focus();

    // Cleanup on unmount. NOTE: we deliberately do NOT close the PTY here.
    // The component unmounts on every tab switch (only the active tab is
    // mounted), and killing the shell would reset the terminal. The PTY is
    // kept alive in the main process and re-attached on remount; it is only
    // torn down on a real tab close (workspace.tabs.close → closeStandaloneTerminal).
    return () => {
      for (const fn of cleanupFnsRef.current) fn();
      cleanupFnsRef.current = [];
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      initializedRef.current = false;
    };
  }, [tabId, cwd]);

  return (
    <div
      ref={containerRef}
      className="standalone-terminal-container"
      style={{
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        background: 'var(--bg-deep)',
      }}
      data-testid={`standalone-terminal-${tabId}`}
    />
  );
}
