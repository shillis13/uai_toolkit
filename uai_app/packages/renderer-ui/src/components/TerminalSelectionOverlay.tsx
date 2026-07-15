/**
 * TerminalSelectionOverlay — Transparent overlay for text selection in the terminal.
 *
 * Ported from spike (phase_0b_vertical_slice). Sits on top of xterm.js and owns
 * all selection behavior. Supports: click, shift+click, drag, Cmd+C, link handling.
 *
 * No shell commands or exec calls — this is a pure React UI component.
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import type { Terminal } from 'xterm';

interface GridPos {
  row: number;
  col: number;
}

interface TerminalSelectionOverlayProps {
  termRef: React.RefObject<Terminal | null>;
  containerRef: React.RefObject<HTMLDivElement | null>;
  sessionId: string;
  onSelectionChange?: (text: string | null) => void;
}

const URL_RE = /https?:\/\/[^\s<>"')\]]+/g;

const TerminalSelectionOverlay = ({
  termRef,
  containerRef,
  sessionId,
  onSelectionChange,
}: TerminalSelectionOverlayProps): JSX.Element => {
  const overlayRef = useRef<HTMLDivElement>(null);

  const [anchor, setAnchor] = useState<GridPos | null>(null);
  const [cursor, setCursor] = useState<GridPos | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const selectedTextRef = useRef<string | null>(null);

  const metricsRef = useRef({ cellWidth: 0, cellHeight: 0, xOffset: 0, yOffset: 0, renderXOffset: 0, renderYOffset: 0 });

  const updateMetrics = useCallback(() => {
    const screen = containerRef.current?.querySelector('.xterm-screen');
    const container = containerRef.current;
    const term = termRef.current;
    if (!screen || !container || !term) return;
    const screenRect = screen.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    metricsRef.current = {
      cellWidth: screenRect.width / term.cols,
      cellHeight: screenRect.height / term.rows,
      xOffset: screenRect.left,
      yOffset: screenRect.top,
      renderXOffset: screenRect.left - containerRect.left,
      renderYOffset: screenRect.top - containerRect.top,
    };
  }, [containerRef, termRef]);

  useEffect(() => {
    updateMetrics();
    const observer = new ResizeObserver(() => updateMetrics());
    const el = containerRef.current;
    if (el) observer.observe(el);
    return () => observer.disconnect();
  }, [containerRef, updateMetrics]);

  const pixelToGrid = useCallback((clientX: number, clientY: number): GridPos => {
    const term = termRef.current;
    const { cellWidth, cellHeight, xOffset, yOffset } = metricsRef.current;
    if (!term || cellWidth === 0) return { row: 0, col: 0 };

    const col = Math.floor((clientX - xOffset) / cellWidth);
    const viewportRow = Math.floor((clientY - yOffset) / cellHeight);
    const bufferRow = viewportRow + term.buffer.active.viewportY;

    return {
      col: Math.max(0, Math.min(col, term.cols - 1)),
      row: Math.max(0, bufferRow),
    };
  }, [termRef]);

  const normalizeRange = useCallback((a: GridPos, b: GridPos): [GridPos, GridPos] => {
    if (a.row < b.row || (a.row === b.row && a.col <= b.col)) return [a, b];
    return [b, a];
  }, []);

  const getTextInRange = useCallback((startRow: number, startCol: number, endRow: number, endCol: number): string => {
    const term = termRef.current;
    if (!term) return '';
    const buffer = term.buffer.active;
    const lines: string[] = [];

    for (let y = startRow; y <= endRow; y++) {
      const line = buffer.getLine(y);
      if (!line) continue;
      const colStart = y === startRow ? startCol : 0;
      const colEnd = y === endRow ? endCol + 1 : term.cols;
      let text = '';
      for (let x = colStart; x < colEnd; x++) {
        const cell = line.getCell(x);
        if (cell) {
          const chars = cell.getChars();
          text += chars || ' ';
        }
      }
      if (!line.isWrapped || y === endRow) {
        text = text.replace(/\s+$/, '');
      }
      lines.push(text);
    }
    return lines.join('\n');
  }, [termRef]);

  const updateSelection = useCallback((a: GridPos | null, b: GridPos | null) => {
    if (!a || !b) {
      selectedTextRef.current = null;
      onSelectionChange?.(null);
      return;
    }
    const [start, end] = a.row < b.row || (a.row === b.row && a.col <= b.col) ? [a, b] : [b, a];
    const text = getTextInRange(start.row, start.col, end.row, end.col);
    selectedTextRef.current = text;
    onSelectionChange?.(text);
  }, [getTextInRange, onSelectionChange]);

  const getUrlAtPosition = useCallback((pos: GridPos): string | null => {
    const term = termRef.current;
    if (!term) return null;
    const line = term.buffer.active.getLine(pos.row);
    if (!line) return null;

    let lineText = '';
    for (let x = 0; x < term.cols; x++) {
      const cell = line.getCell(x);
      lineText += cell?.getChars() || ' ';
    }

    let match: RegExpExecArray | null;
    URL_RE.lastIndex = 0;
    while ((match = URL_RE.exec(lineText)) !== null) {
      const matchStart = match.index;
      const matchEnd = matchStart + match[0].length;
      if (pos.col >= matchStart && pos.col < matchEnd) {
        return match[0];
      }
    }
    return null;
  }, [termRef]);

  const clearSelection = useCallback(() => {
    setAnchor(null);
    setCursor(null);
    selectedTextRef.current = null;
    onSelectionChange?.(null);
    termRef.current?.clearSelection();
  }, [onSelectionChange, termRef]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;

    updateMetrics();
    const pos = pixelToGrid(e.clientX, e.clientY);

    if (e.shiftKey) {
      const url = getUrlAtPosition(pos);
      if (url) {
        e.preventDefault();
        window.uai.openUrl(url);
        return;
      }
    }

    if (e.ctrlKey || e.metaKey) {
      const url = getUrlAtPosition(pos);
      if (url) {
        e.preventDefault();
        navigator.clipboard.writeText(url);
        return;
      }
      return;
    }

    if (e.shiftKey && anchor) {
      e.preventDefault();
      setCursor(pos);
      updateSelection(anchor, pos);
      return;
    }

    e.preventDefault();
    setAnchor(pos);
    setCursor(null);
    setIsDragging(true);
    selectedTextRef.current = null;
    onSelectionChange?.(null);

    termRef.current?.focus();
  }, [anchor, pixelToGrid, getUrlAtPosition, updateMetrics, updateSelection, onSelectionChange, termRef]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !anchor) return;
    const pos = pixelToGrid(e.clientX, e.clientY);
    setCursor(prev => {
      if (prev && prev.row === pos.row && prev.col === pos.col) return prev;
      return pos;
    });
  }, [isDragging, anchor, pixelToGrid]);

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    if (!isDragging) return;
    setIsDragging(false);

    if (!anchor) return;
    const pos = pixelToGrid(e.clientX, e.clientY);

    if (pos.row === anchor.row && pos.col === anchor.col) {
      setCursor(null);
      selectedTextRef.current = null;
      onSelectionChange?.(null);
      return;
    }

    setCursor(pos);
    updateSelection(anchor, pos);
  }, [isDragging, anchor, pixelToGrid, updateSelection, onSelectionChange]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    clearSelection();
    const viewport = containerRef.current?.querySelector('.xterm-viewport');
    if (viewport) {
      viewport.dispatchEvent(new WheelEvent('wheel', {
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        deltaMode: e.deltaMode,
        clientX: e.clientX,
        clientY: e.clientY,
        bubbles: true,
        cancelable: true,
      }));
    }
  }, [containerRef, clearSelection]);

  const renderHighlights = () => {
    if (!anchor || !cursor) return null;
    const term = termRef.current;
    if (!term) return null;

    const { cellWidth, cellHeight, renderXOffset, renderYOffset } = metricsRef.current;
    if (cellWidth === 0) return null;

    const [start, end] = normalizeRange(anchor, cursor);
    const viewportY = term.buffer.active.viewportY;
    const highlights: JSX.Element[] = [];

    for (let row = start.row; row <= end.row; row++) {
      const viewRow = row - viewportY;
      if (viewRow < 0 || viewRow >= term.rows) continue;

      const colStart = row === start.row ? start.col : 0;
      const colEnd = row === end.row ? end.col : term.cols - 1;

      highlights.push(
        <div
          key={row}
          style={{
            position: 'absolute',
            left: `${renderXOffset + colStart * cellWidth}px`,
            top: `${renderYOffset + viewRow * cellHeight}px`,
            width: `${(colEnd - colStart + 1) * cellWidth}px`,
            height: `${cellHeight}px`,
            backgroundColor: 'rgba(122, 162, 247, 0.3)',
            pointerEvents: 'none',
            borderRadius: '1px',
          }}
        />
      );
    }

    return highlights;
  };

  // Handle Cmd+C via copy event
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleCopy = (e: ClipboardEvent) => {
      const text = selectedTextRef.current;
      if (text) {
        e.preventDefault();
        e.clipboardData?.setData('text/plain', text);
      }
    };

    container.addEventListener('copy', handleCopy, true);
    return () => container.removeEventListener('copy', handleCopy, true);
  }, [containerRef]);

  // Handle paste: intercept and route through terminal input
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;

    const handlePaste = (e: ClipboardEvent) => {
      const text = e.clipboardData?.getData('text/plain');
      if (!text) return;
      e.preventDefault();
      e.stopPropagation();
      termRef.current?.focus();
      window.uai.terminal.input(sessionId, text);
    };

    overlay.addEventListener('paste', handlePaste, true);
    return () => overlay.removeEventListener('paste', handlePaste, true);
  }, [sessionId, termRef]);

  return (
    <div
      ref={overlayRef}
      className="terminal-selection-overlay"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onWheel={handleWheel}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 5,
        cursor: 'text',
      }}
    >
      {renderHighlights()}
    </div>
  );
};

export default TerminalSelectionOverlay;
