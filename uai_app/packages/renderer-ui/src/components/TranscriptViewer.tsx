/**
 * TranscriptViewer: Slide-in panel reading structured Claude Code or Codex JSONL.
 * Opens via Cmd+Shift+C or the toolbar and follows the shared transcript cache.
 *
 * Overlay mode: side panel (right ~50%) — terminal remains accessible on left.
 * Features: search with navigation, multi-select with copy, resizable width,
 *           collapsible messages by type, day grouping, message numbering.
 *
 * Security: all markdown content is sanitized via DOMPurify before rendering.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import ClearableInput from './ClearableInput';

// Configure marked — no mangling of html, sync rendering
marked.setOptions({ breaks: true, gfm: true });

// Per-session view-state persistence (type filters + panel width). A pinned
// transcript can remount when tabs switch; without this its filters snap back to
// defaults. Keyed by the session's CLI uuid (falls back to terminal session).
interface TvView {
  showUser: boolean; showAssistant: boolean; showTools: boolean;
  showThinking: boolean; showSystem: boolean; showInjected: boolean;
  panelWidth: number;
}
const TV_VIEW_KEY = (k: string) => `uai:tv:view:${k}`;
function loadTvView(k: string): Partial<TvView> {
  if (!k) return {};
  try { return JSON.parse(localStorage.getItem(TV_VIEW_KEY(k)) || '{}') || {}; }
  catch { return {}; }
}
function saveTvView(k: string, v: TvView): void {
  if (!k) return;
  try { localStorage.setItem(TV_VIEW_KEY(k), JSON.stringify(v)); } catch { /* ignore */ }
}

/** Parse markdown and sanitize via DOMPurify to prevent XSS */
function safeParse(md: string): string {
  // Protect literal <<<…>>> markers (e.g. <<<SESSION RESUMED>>>) — their inner
  // `<SESSION RESUMED>` reads as an HTML tag and gets stripped by marked/
  // DOMPurify, mangling the marker to `<<>>`. Escape the angle brackets inside
  // any <<<…>>> run so it renders as literal text (verified: marked preserves
  // the &lt;/&gt; entities without double-escaping).
  const guarded = md.replace(/<<<[\s\S]*?>>>/g,
    (m) => m.replace(/</g, '&lt;').replace(/>/g, '&gt;'));
  try {
    const result = marked.parse(guarded);
    if (typeof result !== 'string') return DOMPurify.sanitize(String(result));
    return DOMPurify.sanitize(result);
  } catch (e) {
    console.error('[TranscriptViewer] marked.parse failed:', e);
    return DOMPurify.sanitize(md);
  }
}

// ── Data model ──────────────────────────────────────────────────────────────

type MsgType = 'user' | 'response' | 'tool_use' | 'tool_result' | 'thinking' | 'system' | 'meta' | 'skill' | 'agent_result' | 'injected';

/** Non-human messages that arrive as role="user" in JSONL but are NOT human input */
const SYSTEM_INJECTED_TYPES: Set<string> = new Set(['skill', 'agent_result', 'injected']);

interface Message {
  id: number;             // sequential message number (1-indexed)
  lineStart: number;      // JSONL line number (1-indexed)
  type: MsgType;
  role: string;           // user, assistant, system
  timestamp: string;      // ISO string or empty
  content: string;        // text content (markdown for user/assistant)
  html: string;           // sanitized markdown, reused across incremental refreshes
  toolName?: string;      // for tool messages: the tool name
  toolInput?: string;     // for tool messages: input JSON
}

interface Turn {
  number: number;
  timestamp: string;
  messages: Message[];
}

interface DayGroup {
  dateLabel: string;      // "Today — Saturday" or "2026-04-10 — Thursday"
  dateKey: string;        // YYYY-MM-DD for sorting/keying
  turns: Turn[];
}

// ── Map structured backend response to component model ─────────────────────

function mapStructuredResponse(
  days: any[],
  previous: ReadonlyMap<number, Message> = new Map(),
): { dayGroups: DayGroup[]; allMessages: Message[] } {
  const allMessages: Message[] = [];
  let msgId = 1;

  const dayGroups: DayGroup[] = days.map((day: any) => ({
    dateLabel: day.label ?? day.date ?? 'Unknown',
    dateKey: day.date ?? 'Unknown',
    turns: (day.turns ?? []).map((turn: any) => {
      const turnMessages: Message[] = (turn.messages ?? []).map((m: any) => {
        const id = msgId++;
        const type = m.type ?? 'response';
        const content = typeof m.content === 'string' ? m.content : (Array.isArray(m.content) ? m.content.filter((b: any) => b?.type === 'text').map((b: any) => b.text ?? '').join('\n') || `(${m.content.map((b: any) => b?.type).join(', ')})` : String(m.content ?? ''));
        const toolInput = m.tool_input ? (typeof m.tool_input === 'string' ? m.tool_input : JSON.stringify(m.tool_input, null, 2)) : undefined;
        const prior = previous.get(id);
        const unchanged = prior
          && prior.lineStart === (m.line_number ?? 0)
          && prior.type === type
          && prior.role === (m.role ?? 'assistant')
          && prior.timestamp === (m.timestamp ?? '')
          && prior.content === content
          && prior.toolName === m.tool_name
          && prior.toolInput === toolInput;
        const msg: Message = unchanged ? prior : {
          id,
          lineStart: m.line_number ?? 0,
          type,
          role: m.role ?? 'assistant',
          timestamp: m.timestamp ?? '',
          content,
          html: type === 'tool_use' || type === 'tool_result' ? '' : safeParse(content),
          toolName: m.tool_name,
          toolInput,
        };
        allMessages.push(msg);
        return msg;
      });
      return { number: turn.number, timestamp: turn.timestamp ?? '', messages: turnMessages } as Turn;
    }),
  }));

  return { dayGroups, allMessages };
}

// ── Search helpers ──────────────────────────────────────────────────────────

interface MatchLocation { msgId: number; index: number; }

function findAllMatches(messages: Message[], query: string): MatchLocation[] {
  if (!query) return [];
  const q = query.toLowerCase();
  const matches: MatchLocation[] = [];
  for (const msg of messages) {
    let idx = 0;
    const text = msg.content.toLowerCase();
    while ((idx = text.indexOf(q, idx)) !== -1) {
      matches.push({ msgId: msg.id, index: idx });
      idx += q.length;
    }
  }
  return matches;
}

// ── Timestamp formatting ────────────────────────────────────────────────────

function formatTime(ts: string): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    const date = d.toLocaleDateString('en-CA'); // YYYY-MM-DD
    const time = d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    return `${date} ${time}`;
  } catch { return ''; }
}

function formatDateTime(ts: string): string {
  if (!ts) return '';
  try { return new Date(ts).toISOString().replace('T', ' ').slice(0, 19); } catch { return ''; }
}

// ── Component ───────────────────────────────────────────────────────────────

type AiPlatform = 'claude_cli' | 'codex_cli' | 'gemini_cli';

const PLATFORM_LABELS: Record<AiPlatform, string> = {
  claude_cli: 'CLAUDE',
  codex_cli: 'CODEX',
  gemini_cli: 'GEMINI',
};

const PLATFORM_CSS: Record<AiPlatform, string> = {
  claude_cli: 'tv-platform-claude',
  codex_cli: 'tv-platform-codex',
  gemini_cli: 'tv-platform-gemini',
};

interface Props {
  open: boolean;
  zellijSession: string;
  cliSessionId?: string;
  sessionName?: string;
  platform?: AiPlatform;
  onClose: () => void;
  inline?: boolean;
  resumable?: boolean;
  onResume?: () => void;
  scrollToLine?: number;
  /** When provided, renders a pin toggle in the header (overlay mode only). */
  pinned?: boolean;
  onTogglePin?: () => void;
}

export function TranscriptViewer({ open, zellijSession, cliSessionId, sessionName, platform: platformProp, onClose, inline = false, resumable = false, onResume, scrollToLine, pinned = false, onTogglePin }: Props) {
  const [dayGroups, setDayGroups] = useState<DayGroup[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uuid, setUuid] = useState<string | null>(null);
  const [jsonlPath, setJsonlPath] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('');
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentMatchIdx, setCurrentMatchIdx] = useState(0);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<Message[]>([]);
  const lastRevisionRef = useRef('');
  const loadGenerationRef = useRef(0);

  // Resolve platform — prefer prop, fall back to session lookup
  const [resolvedPlatform, setResolvedPlatform] = useState<AiPlatform | null>(platformProp ?? null);
  useEffect(() => {
    if (platformProp) { setResolvedPlatform(platformProp); return; }
    if (!zellijSession) return;
    window.uai.sessions.get(zellijSession).then(s => {
      if (s?.platform) setResolvedPlatform(s.platform);
    }).catch(() => { /* ignore — platform stays null, falls back to generic label */ });
  }, [platformProp, zellijSession]);

  const assistantLabel = resolvedPlatform ? PLATFORM_LABELS[resolvedPlatform] : 'Assistant';
  const platformCssClass = resolvedPlatform ? PLATFORM_CSS[resolvedPlatform] : '';

  // Collapse state
  const [collapsedMessages, setCollapsedMessages] = useState<Set<number>>(new Set());
  const [collapsedTurns, setCollapsedTurns] = useState<Set<number>>(new Set());
  const [collapsedDays, setCollapsedDays] = useState<Set<string>>(new Set());

  // Persisted view state key (survives a pinned transcript's remount on tab switch).
  const sessKey = cliSessionId || zellijSession || '';
  const savedView = useMemo(() => loadTvView(sessKey), [sessKey]);

  useEffect(() => {
    loadGenerationRef.current++;
    lastRevisionRef.current = '';
    messagesRef.current = [];
  }, [sessKey]);

  // Type visibility filters (Tools, Thinking, Injected default to off) — restored
  // from the persisted view so switching tabs doesn't reset them.
  const [showUser, setShowUser] = useState(() => savedView.showUser ?? true);
  const [showAssistant, setShowAssistant] = useState(() => savedView.showAssistant ?? true);
  const [showTools, setShowTools] = useState(() => savedView.showTools ?? false);
  const [showThinking, setShowThinking] = useState(() => savedView.showThinking ?? false);
  const [showSystem, setShowSystem] = useState(() => savedView.showSystem ?? true);
  const [showInjected, setShowInjected] = useState(() => savedView.showInjected ?? false);

  // Select mode state
  const [selectMode, setSelectMode] = useState(false);
  const [selectedMessages, setSelectedMessages] = useState<Set<number>>(new Set());

  // Resize state (overlay panel width)
  const [panelWidth, setPanelWidth] = useState(() => savedView.panelWidth ?? 50);

  // Write-through: persist the filters + panel width so a remount restores them.
  useEffect(() => {
    saveTvView(sessKey, { showUser, showAssistant, showTools, showThinking, showSystem, showInjected, panelWidth });
  }, [sessKey, showUser, showAssistant, showTools, showThinking, showSystem, showInjected, panelWidth]);
  const resizeDrag = useRef<{ startX: number; startW: number } | null>(null);

  const loadTranscript = useCallback(async () => {
    if (!zellijSession && !cliSessionId) {
      setUuid(null);
      return;
    }
    const generation = ++loadGenerationRef.current;
    if (messagesRef.current.length === 0) setLoading(true);
    setError(null);
    // NOTE: don't blank uuid/content here — keeping the prior transcript visible
    // during a reload avoids the "clear" flash when a pinned transcript refreshes.
    try {
      const ref = cliSessionId || zellijSession;
      let result: {
        ok: boolean;
        days?: unknown[];
        error?: string;
        uuid?: string;
        path?: string;
        revision?: string;
      } = await window.uai.transcript.getCached(ref);
      if (!result.ok || !result.days) {
        result = await window.uai.transcript.read(zellijSession, cliSessionId, 'structured');
      }
      if (generation !== loadGenerationRef.current) return;
      if (!result.ok) {
        setError(result.error ?? 'Unknown error');
        setDayGroups([]);
        setMessages([]);
        messagesRef.current = [];
      } else {
        const days = (result.days ?? []) as any[];
        // The normal cached path always supplies a stable file revision. If the
        // cache failed and direct read was needed, favor correctness over skipping.
        const revision = result.revision || `direct:${Date.now()}`;
        if (revision === lastRevisionRef.current) return;
        lastRevisionRef.current = revision;

        setUuid(result.uuid ?? cliSessionId ?? null);
        setJsonlPath(result.path ?? null);
        const prior = new Map(messagesRef.current.map((message) => [message.id, message]));
        const { dayGroups: dg, allMessages } = mapStructuredResponse(days, prior);
        messagesRef.current = allMessages;
        setDayGroups(dg);
        setMessages(allMessages);
      }
    } catch (e: any) {
      if (generation === loadGenerationRef.current) setError(e.message);
    } finally {
      if (generation === loadGenerationRef.current) setLoading(false);
    }
  }, [zellijSession, cliSessionId]);

  useEffect(() => { if (open || inline) loadTranscript(); }, [open, inline, loadTranscript]);

  useEffect(() => {
    if (!open && !inline) return;
    const ref = cliSessionId || zellijSession;
    if (!ref || !window.uai.transcript.onUpdated) return;
    return window.uai.transcript.onUpdated((updatedRef) => {
      if (updatedRef === ref) void loadTranscript();
    });
  }, [open, inline, cliSessionId, zellijSession, loadTranscript]);

  useEffect(() => {
    if (inline && !resumable) setStatus('stopped');
    else if (inline && resumable) setStatus('resumable');
    else setStatus('active');
  }, [inline, resumable]);

  useEffect(() => {
    if (messages.length > 0 && bodyRef.current && !scrollToLine) {
      requestAnimationFrame(() => { bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight }); });
    }
  }, [messages, scrollToLine]);

  useEffect(() => {
    if (!scrollToLine || messages.length === 0 || !bodyRef.current) return;
    requestAnimationFrame(() => {
      const el = bodyRef.current?.querySelector(`[data-line-start="${scrollToLine}"]`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('tv-msg-highlight');
        setTimeout(() => el?.classList.remove('tv-msg-highlight'), 2000);
      }
    });
  }, [scrollToLine, messages]);

  // Filtered messages
  const query = searchQuery.toLowerCase().trim();
  const visibleMessages = useMemo(() => {
    let msgs = messages.filter(m => {
      if (m.type === 'user' && !showUser) return false;
      if (m.type === 'response' && !showAssistant) return false;
      if ((m.type === 'tool_use' || m.type === 'tool_result') && !showTools) return false;
      if (m.type === 'thinking' && !showThinking) return false;
      if (m.type === 'system' && !showSystem) return false;
      if (SYSTEM_INJECTED_TYPES.has(m.type) && !showInjected) return false;
      return true;
    });
    if (query) msgs = msgs.filter(m => m.content.toLowerCase().includes(query));
    return msgs;
  }, [messages, showUser, showAssistant, showTools, showThinking, showSystem, showInjected, query]);

  const visibleDayGroups = useMemo(() => {
    const vSet = new Set(visibleMessages.map(m => m.id));
    return dayGroups
      .map(dg => ({
        ...dg,
        turns: dg.turns
          .map(t => ({ ...t, messages: t.messages.filter(m => vSet.has(m.id)) }))
          .filter(t => t.messages.length > 0),
      }))
      .filter(dg => dg.turns.length > 0);
  }, [dayGroups, visibleMessages]);

  // Search
  const allMatches = useMemo(() => findAllMatches(visibleMessages, query), [visibleMessages, query]);
  const totalMatches = allMatches.length;

  useEffect(() => { setCurrentMatchIdx(0); }, [searchQuery]);
  useEffect(() => {
    if (!query || allMatches.length === 0 || !bodyRef.current) return;
    const match = allMatches[currentMatchIdx];
    if (!match) return;
    requestAnimationFrame(() => {
      const el = bodyRef.current?.querySelector('#tv-search-current-match');
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } else {
        bodyRef.current?.querySelector(`[data-msg-id="${match.msgId}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
  }, [currentMatchIdx, query, allMatches]);

  const searchNext = useCallback(() => { if (totalMatches > 0) setCurrentMatchIdx(p => (p + 1) % totalMatches); }, [totalMatches]);
  const searchPrev = useCallback(() => { if (totalMatches > 0) setCurrentMatchIdx(p => (p - 1 + totalMatches) % totalMatches); }, [totalMatches]);

  // Keyboard
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose();
      if ((e.metaKey || e.ctrlKey) && e.key === 'f' && (open || inline)) {
        e.preventDefault();
        setTimeout(() => searchInputRef.current?.focus(), 50);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, inline, onClose]);

  // Resize
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeDrag.current = { startX: e.clientX, startW: panelWidth };

    // Full-window drag overlay — prevents xterm/terminal from capturing mouse events
    const dragOverlay = document.createElement('div');
    dragOverlay.style.cssText = 'position:fixed;inset:0;z-index:999999;cursor:col-resize;';
    document.body.appendChild(dragOverlay);

    const panel = document.querySelector('.tv-panel') as HTMLElement | null;

    const onMouseMove = (ev: MouseEvent) => {
      if (!resizeDrag.current) return;
      ev.preventDefault();
      const dx = resizeDrag.current.startX - ev.clientX;
      const dPct = (dx / window.innerWidth) * 100;
      const newWidth = Math.min(85, Math.max(20, resizeDrag.current.startW + dPct));
      if (panel) panel.style.width = `${newWidth}%`;
      (resizeDrag.current as any)._lastWidth = newWidth;
    };

    const onMouseUp = () => {
      const lastWidth = (resizeDrag.current as any)?._lastWidth;
      resizeDrag.current = null;
      dragOverlay.remove();
      if (lastWidth !== undefined) setPanelWidth(lastWidth);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [panelWidth]);

  // Collapse helpers
  const toggleMsgCollapse = (msgId: number) => {
    setCollapsedMessages(prev => { const n = new Set(prev); n.has(msgId) ? n.delete(msgId) : n.add(msgId); return n; });
  };
  const toggleDayCollapse = (dateKey: string) => {
    setCollapsedDays(prev => { const n = new Set(prev); n.has(dateKey) ? n.delete(dateKey) : n.add(dateKey); return n; });
  };
  const collapseAllOfType = (type: MsgType) => {
    setCollapsedMessages(prev => { const n = new Set(prev); messages.forEach(m => { if (m.type === type) n.add(m.id); }); return n; });
  };
  const expandAllOfType = (type: MsgType) => {
    setCollapsedMessages(prev => { const n = new Set(prev); messages.forEach(m => { if (m.type === type) n.delete(m.id); }); return n; });
  };

  const collapseAllDays = () => {
    setCollapsedDays(new Set(dayGroups.map(dg => dg.dateKey)));
  };
  const expandAllDays = () => {
    setCollapsedDays(new Set());
  };

  // Select helpers
  const toggleSelectMsg = (msgId: number) => {
    setSelectedMessages(prev => { const n = new Set(prev); n.has(msgId) ? n.delete(msgId) : n.add(msgId); return n; });
  };
  const toggleSelectAll = () => {
    setSelectedMessages(selectedMessages.size === visibleMessages.length ? new Set() : new Set(visibleMessages.map(m => m.id)));
  };
  const deselectAll = () => { setSelectedMessages(new Set()); setSelectMode(false); };

  const copyText = (text: string, feedbackId: string) => {
    window.uai.clipboard.write(text);
    setCopyFeedback(feedbackId);
    setTimeout(() => setCopyFeedback(null), 1500);
  };

  const msgCopyLabel = (m: Message) => {
    if (m.type === 'user') return 'You';
    if (m.type === 'response') return assistantLabel;
    if (m.type === 'skill') return 'Skill';
    if (m.type === 'agent_result') return 'Agent';
    if (m.type === 'injected') return 'Injected';
    return `Tool: ${m.toolName}`;
  };

  const copySelected = () => {
    const selected = messages.filter(m => selectedMessages.has(m.id));
    const text = selected.map(m => `[${msgCopyLabel(m)}]\n${m.content}`).join('\n\n---\n\n');
    copyText(text, 'copy-selected');
  };

  const copyAll = () => {
    const text = messages.map(m => `[${msgCopyLabel(m)}]\n${m.content}`).join('\n\n---\n\n');
    copyText(text, 'copy-all');
  };

  /** Highlight search matches — runs AFTER markdown parsing to avoid marker corruption.
   *  Tracks global match index to mark the current match with a special class. */
  const highlightCounterRef = useRef(0);
  function highlightText(msg: Message, resetCounter?: boolean): string {
    if (resetCounter) highlightCounterRef.current = 0;
    if (!msg.content) return '';
    let html = msg.html;
    if (!query) return html;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(escaped, 'gi');
    const curMatch = currentMatchIdx;
    html = html.replace(/(<[^>]*>)|([^<]+)/g, (match, tag, text) => {
      if (tag) return tag;
      return text.replace(re, (m: string) => {
        const idx = highlightCounterRef.current++;
        const isCurrent = idx === curMatch;
        return `<mark class="tv-search-highlight${isCurrent ? ' tv-search-current' : ''}" ${isCurrent ? 'id="tv-search-current-match"' : ''}>${m}</mark>`;
      });
    });
    return html;
  }

  // Generic context menu helper
  const showContextMenu = (e: React.MouseEvent, items: { label: string; action: () => void }[]) => {
    e.preventDefault();
    e.stopPropagation();
    const menu = document.createElement('div');
    menu.className = 'tv-context-menu';
    menu.style.left = `${e.clientX}px`;
    menu.style.top = `${e.clientY}px`;
    items.forEach((item, i) => {
      const el = document.createElement('div');
      el.className = 'tv-context-item';
      el.textContent = item.label;
      el.addEventListener('click', () => { item.action(); cleanup(); });
      menu.appendChild(el);
    });
    document.body.appendChild(menu);
    const cleanup = (ev?: Event) => {
      menu.remove();
      document.removeEventListener('mousedown', cleanup);
      document.removeEventListener('keydown', escHandler);
      window.removeEventListener('contextmenu', cleanupAndBlock, true);
    };
    // Capture phase: block right-click from reopening another menu
    const cleanupAndBlock = (ev: Event) => {
      if (menu.contains(ev.target as Node)) return;
      ev.preventDefault();
      ev.stopPropagation();
      cleanup();
    };
    const escHandler = (ev: KeyboardEvent) => { if (ev.key === 'Escape') cleanup(); };
    // Close on any click/right-click outside, or Escape
    setTimeout(() => {
      document.addEventListener('mousedown', cleanup);
      document.addEventListener('keydown', escHandler);
      window.addEventListener('contextmenu', cleanupAndBlock, true);
    }, 0);
  };

  // Context menu for message chevrons — collapse/expand siblings of same type
  const handleMsgChevronContext = (e: React.MouseEvent, type: MsgType) => {
    const typeLabel = type === 'user' ? 'User' : type === 'response' ? assistantLabel : SYSTEM_INJECTED_TYPES.has(type) ? 'Injected' : 'Tools';
    showContextMenu(e, [
      { label: `Collapse all ${typeLabel} messages`, action: () => collapseAllOfType(type) },
      { label: `Expand all ${typeLabel} messages`, action: () => expandAllOfType(type) },
    ]);
  };

  // Context menu for day headers — collapse/expand all days
  const handleDayChevronContext = (e: React.MouseEvent) => {
    showContextMenu(e, [
      { label: 'Collapse all days', action: collapseAllDays },
      { label: 'Expand all days', action: expandAllDays },
    ]);
  };

  if (!open && !inline) return null;

  // Reset highlight counter for each render pass
  highlightCounterRef.current = 0;

  // ── Message renderer ──────────────────────────────────────────────────────

  const renderMessage = (msg: Message) => {
    const isCollapsed = collapsedMessages.has(msg.id);
    const labelMap: Record<string, string> = {
      user: 'You', response: assistantLabel, tool_use: msg.toolName ?? 'Tool',
      tool_result: 'Result', thinking: 'Thinking', system: 'System', meta: 'Meta',
      skill: 'Skill', agent_result: 'Agent', injected: 'Injected',
    };
    const label = labelMap[msg.type] ?? msg.role;

    return (
      <div
        key={msg.id}
        className={`tv-msg tv-msg-${msg.type}${msg.type === 'response' && platformCssClass ? ` ${platformCssClass}` : ''}${selectedMessages.has(msg.id) ? ' tv-msg-selected' : ''}${isCollapsed ? ' tv-msg-collapsed' : ''}`}
        data-msg-id={msg.id}
        data-line-start={msg.lineStart}
      >
        <div className="tv-msg-header">
          <span className="tv-msg-chevron" onClick={() => toggleMsgCollapse(msg.id)} onContextMenu={(e) => handleMsgChevronContext(e, msg.type)} title="Click to collapse/expand. Right-click for bulk actions.">{isCollapsed ? '\u25B7' : '\u25BD'}</span>
          {selectMode && <input type="checkbox" className="tv-select-checkbox" checked={selectedMessages.has(msg.id)} onChange={() => toggleSelectMsg(msg.id)} />}
          <span className="tv-msg-label">{label}</span>
          <span className="tv-msg-number">#{msg.id}</span>
          {msg.timestamp && <span className="tv-msg-timestamp" title={formatDateTime(msg.timestamp)}>{formatTime(msg.timestamp)}</span>}
          <button className="tv-copy-btn" onClick={() => copyText(msg.type === 'tool_use' ? (msg.toolInput || msg.content) : msg.content, `msg-${msg.id}`)}>{copyFeedback === `msg-${msg.id}` ? '\u2713' : '\u2398'}</button>
        </div>
        {!isCollapsed && (
          <div className="tv-msg-body">
            {msg.type === 'tool_use' ? (
              <pre className="tv-tool-content">{msg.toolInput || msg.content || `(${msg.toolName ?? 'tool'} — no input data)`}</pre>
            ) : msg.type === 'tool_result' ? (
              <pre className="tv-tool-content">{msg.content || '(empty result)'}</pre>
            ) : (
              /* All markdown content is sanitized via DOMPurify in safeParse, called by highlightText */
              <div className="tv-msg-text" dangerouslySetInnerHTML={{ __html: highlightText(msg) }} />
            )}
          </div>
        )}
      </div>
    );
  };

  // ── Turn renderer ─────────────────────────────────────────────────────────

  const toggleTurnCollapse = (turnNum: number) => setCollapsedTurns(prev => {
    const next = new Set(prev);
    if (next.has(turnNum)) next.delete(turnNum); else next.add(turnNum);
    return next;
  });

  const renderTurn = (turn: Turn) => {
    const isTurnCollapsed = collapsedTurns.has(turn.number);
    const userMsg = turn.messages.find(m => m.type === 'user');
    const preview = userMsg ? userMsg.content.slice(0, 80) + (userMsg.content.length > 80 ? '...' : '') : '';
    const visibleTurnMsgs = turn.messages.filter(m => visibleMessages.some(vm => vm.id === m.id));

    return (
      <div key={`turn-${turn.number}`} className="tv-turn">
        <div className="tv-turn-header" onClick={() => toggleTurnCollapse(turn.number)}>
          <span className="tv-turn-chevron">{isTurnCollapsed ? '\u25B7' : '\u25BD'}</span>
          {selectMode && <input type="checkbox" className="tv-select-checkbox tv-select-checkbox-sm" onClick={(e) => e.stopPropagation()} onChange={() => selectTurnMessages(turn)} />}
          <span className="tv-turn-label">Turn {turn.number}</span>
          <span className="tv-turn-count">{turn.messages.length} msgs</span>
          {isTurnCollapsed && preview && <span className="tv-turn-preview">{preview}</span>}
          <button className="tv-btn tv-copy-btn-header" onClick={(e) => { e.stopPropagation(); copyTurnMessages(turn); }}>{copyFeedback === `turn-${turn.number}` ? '\u2713 Copied!' : 'Copy Turn'}</button>
        </div>
        {!isTurnCollapsed && <div className="tv-turn-messages">{visibleTurnMsgs.map(renderMessage)}</div>}
      </div>
    );
  };

  // ── Day group renderer ────────────────────────────────────────────────────

  const copyDayMessages = (dg: DayGroup) => {
    const allMsgs = dg.turns.flatMap(t => t.messages);
    const text = allMsgs.map(m => `[${msgCopyLabel(m)}]\n${m.content}`).join('\n\n---\n\n');
    copyText(text, `day-${dg.dateKey}`);
  };

  const selectDayMessages = (dg: DayGroup) => {
    const ids = dg.turns.flatMap(t => t.messages).map(m => m.id);
    setSelectedMessages(prev => { const n = new Set(prev); ids.forEach(id => n.add(id)); return n; });
    if (!selectMode) setSelectMode(true);
  };

  const copyTurnMessages = (turn: Turn) => {
    const text = turn.messages.map(m => `[${msgCopyLabel(m)}]\n${m.content}`).join('\n\n---\n\n');
    copyText(text, `turn-${turn.number}`);
  };

  const selectTurnMessages = (turn: Turn) => {
    const ids = turn.messages.map(m => m.id);
    setSelectedMessages(prev => { const n = new Set(prev); ids.forEach(id => n.add(id)); return n; });
    if (!selectMode) setSelectMode(true);
  };

  const renderDayGroup = (dg: DayGroup) => {
    const isDayCollapsed = collapsedDays.has(dg.dateKey);
    const totalMsgs = dg.turns.reduce((sum, t) => sum + t.messages.length, 0);
    return (
      <div key={dg.dateKey} className="tv-day-group">
        <div className="tv-day-header" onClick={() => toggleDayCollapse(dg.dateKey)}>
          <span className="tv-day-chevron" onContextMenu={handleDayChevronContext}>{isDayCollapsed ? '\u25B7' : '\u25BD'}</span>
          {selectMode && <input type="checkbox" className="tv-select-checkbox" onClick={(e) => e.stopPropagation()} onChange={() => selectDayMessages(dg)} />}
          <span className="tv-day-label">{dg.dateLabel}</span>
          <span className="tv-day-count">{dg.turns.length} turns, {totalMsgs} msgs</span>
          <button className="tv-btn tv-copy-btn-header" onClick={(e) => { e.stopPropagation(); copyDayMessages(dg); }}>{copyFeedback === `day-${dg.dateKey}` ? '\u2713 Copied!' : 'Copy Day'}</button>
        </div>
        {!isDayCollapsed && <div className="tv-day-turns">{dg.turns.map(renderTurn)}</div>}
      </div>
    );
  };

  // ── Header ────────────────────────────────────────────────────────────────

  const allSelected = visibleMessages.length > 0 && selectedMessages.size === visibleMessages.length;

  const header = (
    <div className="tv-panel-header">
      {/* Identity row — only in overlay mode; inline mode uses SessionTitleBar */}
      {!inline && (
        <div className="tv-header-row1">
          <div className="tv-header-identity">
            {sessionName && <span className="tv-session-name tv-id-copyable" onClick={() => copyText(sessionName, 'id-name')} title="Click to copy">{copyFeedback === 'id-name' ? '\u2713' : sessionName}</span>}
            {!sessionName && 'Transcript'}
            {uuid && <span className="tv-uuid-badge tv-id-copyable" onClick={() => copyText(uuid, 'id-uuid')} title="Click to copy">{copyFeedback === 'id-uuid' ? '\u2713 Copied' : uuid}</span>}
            {zellijSession && <span className="tv-session-badge tv-id-copyable" onClick={() => copyText(zellijSession, 'id-zellij')} title="Click to copy">{copyFeedback === 'id-zellij' ? '\u2713 Copied' : zellijSession}</span>}
            {status && <span className={`tv-status-badge tv-status-${status}`}>{status}</span>}
          </div>
          <div className="tv-header-actions">
            {onTogglePin && (
              <button
                className={`tv-btn tv-btn-pin${pinned ? ' tv-btn-active' : ''}`}
                onClick={onTogglePin}
                title={pinned ? 'Pinned — transcript stays on this session across tabs. Click to unpin.' : 'Pin transcript to this session (stays open across tabs)'}
              >
                <svg className="ctx-pin-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M16 9V4l1 0c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1l1 0v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/>
                </svg>
              </button>
            )}
            <button className="tv-btn" onClick={loadTranscript} title="Refresh">&#8635;</button>
            <button className="tv-btn tv-btn-close" onClick={onClose} title="Close">&#10005;</button>
            {resumable && onResume && <button className="tv-btn tv-btn-resume" onClick={onResume}>&#9654; Resume</button>}
          </div>
        </div>
      )}
      {jsonlPath && (
        <div
          className="tv-header-path tv-id-copyable"
          title={`${jsonlPath}\n⌘/Ctrl+click: open in OS · click: copy path`}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey) { window.uai.openPath(jsonlPath); }
            else { copyText(jsonlPath, 'id-path'); }
          }}
        >
          {copyFeedback === 'id-path' ? '✓ Copied path' : jsonlPath}
        </div>
      )}
      <div className="tv-header-row2">
        <div className="tv-header-controls">
          <button className={`tv-btn tv-btn-select${selectMode ? ' tv-btn-active' : ''}`} onClick={() => { setSelectMode(v => !v); if (selectMode) setSelectedMessages(new Set()); }}>{selectMode ? 'Cancel' : 'Select'}</button>
          {selectMode && <input type="checkbox" className="tv-select-all-checkbox" checked={allSelected} onChange={toggleSelectAll} title={allSelected ? 'Deselect all' : 'Select all'} />}
          <button className="tv-btn tv-btn-select" onClick={selectMode ? copySelected : copyAll}>{copyFeedback === (selectMode ? 'copy-selected' : 'copy-all') ? '\u2713 Copied!' : (selectMode ? 'Copy Selected' : 'Copy All')}</button>
          <div className="tv-filter-group">
            <label className="tv-type-filter"><input type="checkbox" checked={showUser} onChange={() => setShowUser(v => !v)} /><span className="tv-filter-label tv-filter-user">You</span></label>
            <label className="tv-type-filter"><input type="checkbox" checked={showAssistant} onChange={() => setShowAssistant(v => !v)} /><span className={`tv-filter-label tv-filter-response${platformCssClass ? ` ${platformCssClass}` : ''}`}>{assistantLabel}</span></label>
            <label className="tv-type-filter"><input type="checkbox" checked={showTools} onChange={() => setShowTools(v => !v)} /><span className="tv-filter-label tv-filter-tool">Tools</span></label>
            <label className="tv-type-filter"><input type="checkbox" checked={showThinking} onChange={() => setShowThinking(v => !v)} /><span className="tv-filter-label tv-filter-thinking">Thinking</span></label>
            <label className="tv-type-filter"><input type="checkbox" checked={showSystem} onChange={() => setShowSystem(v => !v)} /><span className="tv-filter-label tv-filter-system">System</span></label>
            <label className="tv-type-filter"><input type="checkbox" checked={showInjected} onChange={() => setShowInjected(v => !v)} /><span className="tv-filter-label tv-filter-injected">Injected</span></label>
          </div>
        </div>
        <div className="tv-header-search">
          <ClearableInput ref={searchInputRef} className="tv-search-input tv-search-input-compact" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onClear={() => setSearchQuery('')} onKeyDown={(e) => { if (e.key === 'Escape') { setSearchQuery(''); (e.target as HTMLInputElement).blur(); } if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); searchNext(); } if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); searchPrev(); } }} placeholder="Search..." />
          {query && <><span className="tv-search-count">{totalMatches > 0 ? `${currentMatchIdx + 1}/${totalMatches}` : '0/0'}</span><button className="tv-btn tv-search-nav-btn" onClick={searchPrev} title="Previous">&#9650;</button><button className="tv-btn tv-search-nav-btn" onClick={searchNext} title="Next">&#9660;</button></>}
        </div>
        <div className="tv-jump-btns">
          <button className="tv-btn tv-jump-btn" onClick={() => bodyRef.current?.scrollTo({ top: 0, behavior: 'smooth' })} title="Jump to top">⤒</button>
          <button className="tv-btn tv-jump-btn" onClick={() => bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })} title="Jump to bottom">⤓</button>
        </div>
      </div>
    </div>
  );

  // Selection bar
  const selectionBar = selectedMessages.size > 0 && (
    <div className="tv-selection-bar">
      <span className="tv-selection-count">{selectedMessages.size} selected</span>
      <button className="tv-btn tv-btn-accent" onClick={copySelected}>{copyFeedback === 'copy-selected' ? '\u2713 Copied!' : 'Copy Selected'}</button>
      <button className="tv-btn" onClick={deselectAll}>Deselect All</button>
      <button className="tv-btn" onClick={copyAll}>{copyFeedback === 'copy-all' ? '\u2713 Copied!' : '\u2398 Copy All'}</button>
    </div>
  );

  const bodyContent = (
    <>
      {loading && <div className="tv-state">Loading...</div>}
      {error && <div className="tv-state tv-error">Error: {error}</div>}
      {!loading && !error && messages.length === 0 && <div className="tv-state">No messages found.</div>}
      {visibleDayGroups.map(renderDayGroup)}
    </>
  );

  // Inline mode
  if (inline) {
    return (
      <div className={`tv-inline${platformCssClass ? ` ${platformCssClass}` : ''}`}>
        {header}
        <div className="tv-inline-body" ref={bodyRef}>{bodyContent}</div>
        {selectionBar}
      </div>
    );
  }

  // Overlay mode
  return createPortal(
    <div className={`tv-overlay tv-overlay-side${platformCssClass ? ` ${platformCssClass}` : ''}`} ref={overlayRef}>
      <div className="tv-resize-handle" style={{ right: `${panelWidth}%`, transform: 'translateX(50%)' }} onMouseDown={handleResizeMouseDown} />
      <div className="tv-panel tv-panel-side" style={{ width: `${panelWidth}%` }}>
        {header}
        <div className="tv-panel-body" ref={bodyRef}>{bodyContent}</div>
        {selectionBar}
      </div>
    </div>,
    document.body
  );
}

export default TranscriptViewer;
