/**
 * MemorexView — Dual-zone terminal display: Memorex (formatted transcript) + Live (xterm).
 *
 * Memorex zone: auto-refreshing JSONL transcript rendered as structured blocks.
 * Live zone: raw xterm terminal for streaming output and interactive prompts.
 *
 * Spike: fixed 70/30 split. Future: dynamic sizing based on live activity.
 *
 * Security: all markdown content sanitized via DOMPurify (same pattern as TranscriptViewer).
 */

import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react';
import DOMPurify from 'dompurify';
import { marked } from 'marked';

marked.setOptions({ breaks: true, gfm: true });

function safeParse(md: string): string {
  try {
    const raw = marked.parse(md);
    const str = typeof raw === 'string' ? raw : String(raw);
    return DOMPurify.sanitize(str);
  } catch {
    return DOMPurify.sanitize(md);
  }
}

// ── Data types ────────────────────────────────────────────────────────────────

type BlockType = 'user' | 'assistant' | 'tool_use' | 'tool_result' | 'thinking';

interface MemorexBlock {
  id: number;
  type: BlockType;
  content: string;
  toolName?: string;
  toolInput?: string;
  timestamp?: string;
}

interface MemorexViewProps {
  children?: ReactNode;
  zellijSession: string;
  cliSessionId?: string;
  enabled: boolean;
  hideLiveZone?: boolean;
}

const POLL_INTERVAL_MS = 5000;

// ── Component ─────────────────────────────────────────────────────────────────

const MemorexView = ({ children, zellijSession, cliSessionId, enabled, hideLiveZone }: MemorexViewProps): JSX.Element => {
  const [blocks, setBlocks] = useState<MemorexBlock[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collapsedBlocks, setCollapsedBlocks] = useState<Set<number>>(new Set());
  const memorexRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const lastBlockCountRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const parseResponse = useCallback((days: any[]): MemorexBlock[] => {
    const result: MemorexBlock[] = [];
    let id = 1;

    for (const day of (days ?? [])) {
      for (const turn of (day.turns ?? [])) {
        for (const msg of (turn.messages ?? [])) {
          const mtype = msg.type as string;
          if (mtype === 'system' || mtype === 'meta') continue;

          const content = typeof msg.content === 'string'
            ? msg.content
            : Array.isArray(msg.content)
              ? msg.content.filter((b: any) => b?.type === 'text').map((b: any) => b.text ?? '').join('\n')
              : String(msg.content ?? '');

          result.push({
            id: id++,
            type: mtype as BlockType,
            content,
            toolName: msg.tool_name,
            toolInput: msg.tool_input
              ? (typeof msg.tool_input === 'string' ? msg.tool_input : JSON.stringify(msg.tool_input, null, 2))
              : undefined,
            timestamp: msg.timestamp,
          });
        }
      }
    }

    return result;
  }, []);

  const fetchTranscript = useCallback(async () => {
    if (!zellijSession && !cliSessionId) return;

    try {
      const result = await window.uai.transcript.read(
        zellijSession,
        cliSessionId,
        'structured'
      );

      if (result.ok && result.days) {
        const newBlocks = parseResponse(result.days);
        setBlocks(newBlocks);
        setError(null);

        if (newBlocks.length > lastBlockCountRef.current && autoScrollRef.current) {
          requestAnimationFrame(() => {
            if (memorexRef.current) {
              memorexRef.current.scrollTop = memorexRef.current.scrollHeight;
            }
          });
        }
        lastBlockCountRef.current = newBlocks.length;
      }
    } catch (e: any) {
      setError(e.message);
    }
  }, [zellijSession, cliSessionId, parseResponse]);

  useEffect(() => {
    if (!enabled) return;
    setLoading(true);
    fetchTranscript().finally(() => setLoading(false));
  }, [enabled, fetchTranscript]);

  useEffect(() => {
    if (!enabled) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      return;
    }

    pollTimerRef.current = setInterval(fetchTranscript, POLL_INTERVAL_MS);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [enabled, fetchTranscript]);

  const handleMemorexScroll = useCallback(() => {
    if (!memorexRef.current) return;
    const el = memorexRef.current;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    autoScrollRef.current = atBottom;
  }, []);

  const toggleCollapse = useCallback((blockId: number) => {
    setCollapsedBlocks(prev => {
      const next = new Set(prev);
      if (next.has(blockId)) next.delete(blockId);
      else next.add(blockId);
      return next;
    });
  }, []);

  if (!enabled) {
    return <>{children}</>;
  }

  const renderBlock = (block: MemorexBlock) => {
    const isCollapsed = collapsedBlocks.has(block.id);
    const isTool = block.type === 'tool_use' || block.type === 'tool_result';
    const isThinking = block.type === 'thinking';
    const isCollapsible = isTool || isThinking;

    const label = block.type === 'user' ? 'YOU'
      : block.type === 'assistant' ? 'CLAUDE'
      : block.type === 'tool_use' ? (block.toolName ?? 'Tool')
      : block.type === 'tool_result' ? 'Result'
      : block.type === 'thinking' ? 'Thinking'
      : block.type;

    const blockEl = document.createElement('div');

    return (
      <div key={block.id} className={`memorex-block memorex-block-${block.type}`}>
        <div
          className="memorex-block-header"
          onClick={isCollapsible ? () => toggleCollapse(block.id) : undefined}
          style={{ cursor: isCollapsible ? 'pointer' : 'default' }}
        >
          <span className="memorex-block-label">{label}</span>
          {isCollapsible && (
            <span className="memorex-block-toggle">
              {isCollapsed ? '\u25B6' : '\u25BC'}
            </span>
          )}
        </div>
        {(!isCollapsible || !isCollapsed) && (
          <div className="memorex-block-content">
            {isTool ? (
              <pre className="memorex-tool-content">
                {block.type === 'tool_use' ? (block.toolInput || block.content || '(no input)') : (block.content || '(empty result)')}
              </pre>
            ) : (
              <MemorexTextContent content={block.content} />
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="memorex-container">
      <div
        ref={memorexRef}
        className="memorex-zone"
        onScroll={handleMemorexScroll}
      >
        <div className="memorex-status" style={{ color: '#e0af68', fontSize: 11 }}>
          Memorex: {blocks.length} blocks | loading={String(loading)} | error={error || 'none'} | uuid={cliSessionId || 'none'} | session={zellijSession || 'none'}
        </div>
        {loading && blocks.length === 0 && (
          <div className="memorex-status">Loading transcript...</div>
        )}
        {error && (
          <div className="memorex-status memorex-error">Error: {error}</div>
        )}
        {blocks.length === 0 && !loading && !error && (
          <div className="memorex-status">No messages yet.</div>
        )}
        {blocks.map(renderBlock)}
      </div>

      {!hideLiveZone && (
        <>
          <div className="memorex-divider">
            <span className="memorex-divider-label">LIVE</span>
            <span className="memorex-block-count">{blocks.length} messages</span>
          </div>
          <div className="memorex-live-zone">
            {children}
          </div>
        </>
      )}
    </div>
  );
};

/** Renders sanitized markdown content using ref-based DOM insertion (no dangerouslySetInnerHTML) */
function MemorexTextContent({ content }: { content: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.innerHTML = safeParse(content);
    }
  }, [content]);

  return <div className="memorex-text-content" ref={ref} />;
}

export default MemorexView;
