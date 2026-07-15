/**
 * LogFileViewer — generic live file tail viewer with schema-driven formatting.
 *
 * Tails any file via the logTail IPC service. Renders lines according to
 * an optional schema (JSONL field extraction, level coloring, timestamp parsing).
 * Falls back to raw text display for unknown formats.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface LogFileSchema {
  format: 'jsonl' | 'text';
  timestampField?: string;
  levelField?: string;
  levelColors?: Record<string, string>;
  sessionField?: string;
  displayFields?: string[];  // which fields to show (all if absent)
}

interface LogFileViewerProps {
  filePath: string;
  schema?: LogFileSchema;
  sessionFilter?: string;     // filter JSONL by session field value
  searchFilter?: string;      // text search filter
  maxLines?: number;           // display buffer (default 500)
}

const DEFAULT_LEVEL_COLORS: Record<string, string> = {
  error: 'var(--accent-red, #f7768e)',
  warn: 'var(--accent-yellow, #e0af68)',
  warning: 'var(--accent-yellow, #e0af68)',
  info: 'var(--accent-green, #9ece6a)',
  debug: 'var(--text-muted, #565f89)',
};

function formatJsonlLine(raw: string, schema: LogFileSchema, sessionFilter?: string): JSX.Element | null {
  try {
    const obj = JSON.parse(raw);

    // Session filter
    if (sessionFilter && schema.sessionField && obj[schema.sessionField] !== sessionFilter) return null;

    const ts = schema.timestampField ? obj[schema.timestampField] : null;
    const level = schema.levelField ? obj[schema.levelField] : null;
    const levelColor = level ? (schema.levelColors?.[level] || DEFAULT_LEVEL_COLORS[level] || '') : '';

    // Pick display fields
    const fields = schema.displayFields || Object.keys(obj).filter(k => k !== schema.timestampField);
    const time = ts ? new Date(ts).toLocaleTimeString() : '';

    return (
      <div className={`log-line${level === 'error' ? ' log-line-error' : ''}`}>
        {time && <span className="log-line-time">{time}</span>}
        {level && <span className="log-line-level" style={{ color: levelColor }}>{level}</span>}
        {fields.map(f => {
          if (f === schema.timestampField || f === schema.levelField) return null;
          const val = obj[f];
          if (val === null || val === undefined) return null;
          const display = typeof val === 'object' ? JSON.stringify(val) : String(val);
          return <span key={f} className="log-line-field" title={f}>{display}</span>;
        })}
      </div>
    );
  } catch {
    return <div className="log-line log-line-raw">{raw}</div>;
  }
}

function formatTextLine(raw: string): JSX.Element {
  return <div className="log-line log-line-raw">{raw}</div>;
}

export default function LogFileViewer({ filePath, schema, sessionFilter, searchFilter, maxLines = 500 }: LogFileViewerProps): JSX.Element {
  const [lines, setLines] = useState<string[]>([]);
  const [tailing, setTailing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const tailIdRef = useRef(`tail_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`);
  const userScrolledRef = useRef(false);

  // Start tail on mount
  useEffect(() => {
    const tailId = tailIdRef.current;
    let unsubData: (() => void) | null = null;

    window.uai.logTail.start(tailId, filePath).then(result => {
      if (!result.ok) { setError(result.error || 'Failed to start tail'); return; }
      setLines(result.lines.slice(-maxLines));

      unsubData = window.uai.logTail.onData((id, newLines) => {
        if (id !== tailId) return;
        setLines(prev => [...prev, ...newLines].slice(-maxLines));
      });
    });

    return () => {
      window.uai.logTail.stop(tailId);
      if (unsubData) unsubData();
    };
  }, [filePath, maxLines]);

  // Auto-scroll to bottom unless user scrolled up
  useEffect(() => {
    if (!userScrolledRef.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [lines.length]);

  const handleScroll = useCallback(() => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    const atBottom = scrollHeight - scrollTop - clientHeight < 30;
    userScrolledRef.current = !atBottom;
    setTailing(atBottom);
  }, []);

  const scrollToBottom = useCallback(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
      userScrolledRef.current = false;
      setTailing(true);
    }
  }, []);

  // Apply text search filter
  const filteredLines = searchFilter
    ? lines.filter(l => l.toLowerCase().includes(searchFilter.toLowerCase()))
    : lines;

  if (error) {
    return <div className="log-viewer-error">{error}</div>;
  }

  const isJsonl = schema?.format === 'jsonl' || filePath.endsWith('.jsonl');

  return (
    <div className="log-file-viewer">
      <div className="log-file-viewer-content" ref={listRef} onScroll={handleScroll}>
        {filteredLines.map((line, i) => {
          if (isJsonl && schema) {
            const el = formatJsonlLine(line, schema, sessionFilter);
            if (el === null) return null; // filtered out
            // data-copyrow: copy this row as ONE line (fields space-joined), not one
            // field per line — see copyFlatten.ts.
            return <div key={i} data-copyrow>{el}</div>;
          }
          return <div key={i} data-copyrow>{formatTextLine(line)}</div>;
        })}
      </div>
      {!tailing && (
        <button className="log-viewer-scroll-btn" onClick={scrollToBottom} title="Scroll to bottom">
          {'\u2193'} Live
        </button>
      )}
    </div>
  );
}
