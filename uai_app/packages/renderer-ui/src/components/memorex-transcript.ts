/**
 * Transcript-authoritative Memorex reconciliation.
 *
 * The transcript owns settled message boundaries and settled prose. The terminal
 * owns only the still-live tail and the compact/folded presentation of tool calls.
 * Settled Transcript cards and provisional terminal cards form one persistent
 * chain. Each newly appended Transcript card replaces the first provisional card
 * by position; no Transcript content is matched to terminal content.
 */

export type MemorexTranscriptSection = 'user' | 'inject' | 'assistant' | 'thinking' | 'tool';

export interface TranscriptRecord {
  msgId: number;
  turnNum: number;
  type: string;
  section: MemorexTranscriptSection;
  timestamp: string;
  content: string;
  toolName?: string;
  toolInput?: string;
  toolCallId?: string;
}

export interface SettledTranscriptBlock {
  key: string;
  firstMsgId: number;
  lastMsgId: number;
  turnNum: number;
  section: MemorexTranscriptSection;
  timestamp: string;
  label: string;
  content: string;
  lines: string[];
  toolName?: string;
  toolCallId?: string;
  version: string;
}

/** Preserve a reader's distance from the bottom across a DOM rebuild. */
export function restoredScrollTop(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  nextScrollHeight: number,
  stickToBottom: boolean,
): number {
  const nextMax = Math.max(0, nextScrollHeight - clientHeight);
  if (stickToBottom) return nextMax;
  const priorMax = Math.max(0, scrollHeight - clientHeight);
  const distanceFromBottom = Math.max(0, priorMax - scrollTop);
  return Math.max(0, nextMax - distanceFromBottom);
}

export interface VirtualWindowRange {
  /** First rendered item, inclusive. */
  start: number;
  /** Last rendered item, exclusive. */
  end: number;
  /** Spacer height before the rendered items. */
  beforePx: number;
  /** Spacer height after the rendered items. */
  afterPx: number;
  /** Estimated height of every item. */
  totalPx: number;
}

/** Calculate the small item window that intersects the viewport plus overscan.
 *  Heights come from prior DOM measurements when available and estimates otherwise. */
export function calculateVirtualWindow(
  itemHeights: number[],
  scrollTop: number,
  clientHeight: number,
  overscanPx: number,
): VirtualWindowRange {
  const heights = itemHeights.map((height) => Math.max(1, Number.isFinite(height) ? height : 1));
  const totalPx = heights.reduce((sum, height) => sum + height, 0);
  if (heights.length === 0) {
    return { start: 0, end: 0, beforePx: 0, afterPx: 0, totalPx: 0 };
  }

  const wantedTop = Math.max(0, scrollTop - Math.max(0, overscanPx));
  const wantedBottom = Math.min(
    totalPx,
    Math.max(wantedTop, scrollTop + Math.max(0, clientHeight) + Math.max(0, overscanPx)),
  );

  let start = 0;
  let beforePx = 0;
  while (start < heights.length && beforePx + heights[start] < wantedTop) {
    beforePx += heights[start];
    start++;
  }

  let end = start;
  let renderedEndPx = beforePx;
  while (end < heights.length && renderedEndPx < wantedBottom) {
    renderedEndPx += heights[end];
    end++;
  }
  if (end === start && end < heights.length) {
    renderedEndPx += heights[end];
    end++;
  }

  return {
    start,
    end,
    beforePx,
    afterPx: Math.max(0, totalPx - renderedEndPx),
    totalPx,
  };
}

/** Each new settled card replaces one provisional from the head of the FIFO. */
export function settleProvisionalCards<T>(
  provisionalCards: T[],
  appendedSettledCards: number,
): T[] {
  const count = Number.isFinite(appendedSettledCards)
    ? Math.max(0, Math.floor(appendedSettledCards))
    : 0;
  return provisionalCards.slice(count);
}

/** Append terminal cards without allowing a repaint of an existing opening
 * marker to grow the persistent FIFO. A matching card is updated in place so
 * its stable DOM identity can be retained by the caller-provided merge. */
export function appendUniqueProvisionalCards<T>(
  provisionalCards: T[],
  appendedCards: T[],
  fingerprint: (card: T) => string,
  merge: (existing: T, replacement: T) => T = (_existing, replacement) => replacement,
): T[] {
  const result = [...provisionalCards];
  for (const card of appendedCards) {
    const value = fingerprint(card);
    const duplicateIndex = value
      ? result.findIndex((candidate) => fingerprint(candidate) === value)
      : -1;
    if (duplicateIndex >= 0) {
      result[duplicateIndex] = merge(result[duplicateIndex], card);
    } else {
      result.push(card);
    }
  }
  return result;
}

export interface TerminalCardDelta<T> {
  /** Current version of the card that ended the previous terminal snapshot. */
  updatedTail: T | null;
  /** Cards whose opening markers appeared after the previous terminal tail. */
  appended: T[];
  /** False when capture/reflow removed every recent terminal-only anchor. */
  anchored: boolean;
}

/**
 * Derive terminal-only append events from two bounded snapshots. This never
 * compares a terminal card with Transcript content. A short backward fingerprint
 * context disambiguates repeated markers and survives the capture origin moving.
 */
export function terminalCardDelta<T>(
  previous: T[],
  current: T[],
  fingerprint: (card: T) => string,
  contextSize = 8,
): TerminalCardDelta<T> {
  if (previous.length === 0 || current.length === 0) {
    return { updatedTail: null, appended: [], anchored: false };
  }

  const firstPrevious = Math.max(0, previous.length - Math.max(1, contextSize));
  let best: { previousIndex: number; currentIndex: number; support: number } | null = null;

  for (let previousIndex = previous.length - 1; previousIndex >= firstPrevious; previousIndex--) {
    const wanted = fingerprint(previous[previousIndex]);
    if (!wanted) continue;
    for (let currentIndex = current.length - 1; currentIndex >= 0; currentIndex--) {
      if (fingerprint(current[currentIndex]) !== wanted) continue;
      let support = 1;
      let p = previousIndex - 1;
      let c = currentIndex - 1;
      while (p >= firstPrevious && c >= 0 && fingerprint(previous[p]) === fingerprint(current[c])) {
        support++;
        p--;
        c--;
      }
      if (!best
          || support > best.support
          || (support === best.support && previousIndex > best.previousIndex)
          || (support === best.support && previousIndex === best.previousIndex && currentIndex > best.currentIndex)) {
        best = { previousIndex, currentIndex, support };
      }
    }
  }

  if (!best) return { updatedTail: null, appended: [], anchored: false };

  // If the newest prior marker changed during a redraw, an earlier marker may be
  // the anchor. The same number of old cards after it are updates; only the rest
  // are true appends.
  const oldTailLength = previous.length - best.previousIndex - 1;
  const updatedTailIndex = Math.min(current.length - 1, best.currentIndex + oldTailLength);
  const appendStart = Math.min(current.length, best.currentIndex + oldTailLength + 1);
  // A terminal repaint can append a second copy of an already-visible marker
  // sequence to tmux scrollback. Prefer the newest anchor above, then reject any
  // remaining suffix marker that already occurs before the suffix in this same
  // snapshot. An indistinguishable, intentionally repeated live message may wait
  // for Transcript settlement; displaying it late is safer than persisting a
  // terminal repaint as a duplicate provisional card.
  const seenFingerprints = new Set(
    current.slice(0, appendStart).map(fingerprint).filter(Boolean),
  );
  const appended = current.slice(appendStart).filter((card) => {
    const value = fingerprint(card);
    if (!value || seenFingerprints.has(value)) return false;
    seenFingerprints.add(value);
    return true;
  });

  return {
    updatedTail: current[updatedTailIndex] ?? null,
    appended,
    anchored: true,
  };
}

const DISPLAY_SECTIONS = new Set<MemorexTranscriptSection>([
  'user',
  'inject',
  'assistant',
  'thinking',
  'tool',
]);

const MIN_MATCH_CHARS = 8;

const LOCAL_ONLY_PREFIXES = [
  '<<<SESSION_IDENTITY>>>',
  '<<<SESSION RESUMED>>>',
  '<local-command-caveat>',
  '<command-name>',
  '<local-command-stdout>',
];

function contentToString(value: unknown): string {
  let result = '';
  if (typeof value === 'string') {
    result = value;
  } else if (Array.isArray(value)) {
    const text: string[] = [];
    for (const block of value) {
      if (block && typeof block === 'object' && (block as { type?: string }).type === 'text') {
        text.push(String((block as { text?: unknown }).text ?? ''));
      }
    }
    result = text.join('\n');
  } else if (value !== null && value !== undefined) {
    result = String(value);
  }
  return result;
}

function toolInputToString(value: unknown): string | undefined {
  let result: string | undefined;
  if (typeof value === 'string') {
    result = value;
  } else if (value !== null && value !== undefined) {
    try {
      result = JSON.stringify(value, null, 2);
    } catch {
      result = String(value);
    }
  }
  return result;
}

function isLocalOnlyContent(content: string): boolean {
  const value = content.trimStart();
  return LOCAL_ONLY_PREFIXES.some((prefix) => value.startsWith(prefix));
}

function sectionOf(message: Record<string, unknown>): MemorexTranscriptSection | null {
  const supplied = String(message.section ?? '');
  const explicitType = String(message.type ?? '');
  const type = explicitType || String(message.role ?? '');

  // Message type is authoritative. In particular, Claude tool_result records have
  // role=user at the transport layer and must never inherit a stale user section.
  if (type === 'tool_use' || type === 'tool_result') return 'tool';
  if (type === 'thinking') return 'thinking';
  if (type === 'response' || type === 'assistant') return 'assistant';
  if (type === 'injected') return 'inject';
  if (type === 'user') return supplied === 'inject' ? 'inject' : 'user';

  // These normalized records describe the local session, not model messages.
  if (type === 'meta' || type === 'system' || type === 'skill' || type === 'agent_result') {
    return null;
  }

  // Preserve compatibility for adapters that only supply the normalized section.
  if (DISPLAY_SECTIONS.has(supplied as MemorexTranscriptSection)) {
    return supplied as MemorexTranscriptSection;
  }
  return null;
}

/** Flatten read_jsonl's day -> turn -> message view while preserving Transcript Msg numbers. */
export function flattenStructuredTranscript(days: unknown[]): TranscriptRecord[] {
  const records: TranscriptRecord[] = [];
  let msgId = 0;
  let fallbackTurn = 0;

  for (const dayValue of days) {
    const day = (dayValue && typeof dayValue === 'object') ? dayValue as Record<string, unknown> : {};
    const turns = Array.isArray(day.turns) ? day.turns : [];
    for (const turnValue of turns) {
      const turn = (turnValue && typeof turnValue === 'object') ? turnValue as Record<string, unknown> : {};
      fallbackTurn++;
      const turnNum = typeof turn.number === 'number' ? turn.number : fallbackTurn;
      const messages = Array.isArray(turn.messages) ? turn.messages : [];
      for (const messageValue of messages) {
        msgId++;
        const message = (messageValue && typeof messageValue === 'object')
          ? messageValue as Record<string, unknown>
          : {};
        const content = contentToString(message.content);
        if (isLocalOnlyContent(content)) continue;
        const section = sectionOf(message);
        if (!section) continue;
        records.push({
          msgId,
          turnNum,
          type: String(message.type ?? message.role ?? 'unknown'),
          section,
          timestamp: String(message.timestamp ?? ''),
          content,
          toolName: message.tool_name ? String(message.tool_name) : undefined,
          toolInput: toolInputToString(message.tool_input),
          toolCallId: message.tool_call_id ? String(message.tool_call_id) : undefined,
        });
      }
    }
  }
  return records;
}

function hashText(value: string): string {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i++) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function proseLabel(section: MemorexTranscriptSection, assistantLabel: string): string {
  let result = '';
  if (section === 'user') result = 'YOU';
  else if (section === 'inject') result = 'COMMS';
  else if (section === 'assistant') result = assistantLabel;
  else if (section === 'thinking') result = 'THINKING';
  return result;
}

/**
 * Render an AskUserQuestion tool input as readable lines instead of raw JSON. The
 * CLI formats this tool into a boxed question/options/preview view; the transcript
 * only has the structured input, so Memorex must format it itself. Each option's
 * `preview` carries real newlines (escaped as \n in the raw JSON string); JSON.parse
 * restores them so a preview renders as its intended multi-line snippet rather than
 * one escaped blob. Returns null if the input isn't AskUserQuestion-shaped.
 */
function askUserQuestionLines(toolInput: string | undefined): string[] | null {
  if (!toolInput) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(toolInput);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const questions = (parsed as { questions?: unknown }).questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;
  const out: string[] = [];
  for (const [questionIndex, q] of questions.entries()) {
    if (!q || typeof q !== 'object' || Array.isArray(q)) return null;
    const question = q as Record<string, unknown>;
    if (typeof question.question !== 'string' || !question.question.trim()
      || !Array.isArray(question.options) || question.options.length === 0) return null;
    const options = question.options;
    if (!options.every(opt => opt && typeof opt === 'object' && !Array.isArray(opt)
      && typeof (opt as Record<string, unknown>).label === 'string'
      && !!String((opt as Record<string, unknown>).label).trim()
      && typeof (opt as Record<string, unknown>).description === 'string'
      && ((opt as Record<string, unknown>).preview === undefined
        || typeof (opt as Record<string, unknown>).preview === 'string'))) return null;
    if (questionIndex > 0) out.push('');
    out.push(question.question);
    options.forEach((optValue, index) => {
      const opt = optValue as Record<string, unknown>;
      out.push(`  ${index + 1}. ${String(opt.label)}`);
      if (String(opt.description)) {
        for (const line of String(opt.description).split(/\r?\n/)) out.push(`     ${line}`);
      }
      if (typeof opt.preview === 'string' && opt.preview) {
        // Draw the preview in a box, mirroring the CLI's boxed presentation.
        // Settled card lines render verbatim (no re-classification), so the
        // box-drawing survives intact. Pad to the widest line for straight edges.
        const previewLines = opt.preview.split(/\r?\n/);
        const width = previewLines.reduce((max, line) => Math.max(max, line.length), 0);
        const indent = '     ';
        out.push(`${indent}┌${'─'.repeat(width + 2)}┐`);
        for (const line of previewLines) out.push(`${indent}│ ${line.padEnd(width)} │`);
        out.push(`${indent}└${'─'.repeat(width + 2)}┘`);
      }
    });
  }
  return out;
}

function toolFallbackLines(record: TranscriptRecord): string[] {
  const name = record.toolName || 'Tool';
  const lines: string[] = [];
  if (record.type === 'tool_use') {
    lines.push(`${name}`);
    if (name === 'AskUserQuestion') {
      const formatted = askUserQuestionLines(record.toolInput);
      if (formatted) {
        lines.push(...formatted);
        return lines;
      }
    }
    if (record.toolInput) lines.push(...record.toolInput.split('\n'));
  } else {
    const count = record.content ? record.content.split('\n').length : 0;
    lines.push(`Result${count > 0 ? ` — ${count} transcript lines` : ''}`);
  }
  return lines;
}

function refreshBlockVersion(block: SettledTranscriptBlock): void {
  const source = [
    block.firstMsgId,
    block.lastMsgId,
    block.section,
    block.label,
    block.lines.join('\n'),
  ].join('|');
  block.version = hashText(source);
}

/**
 * Build the settled DOM model. Prose is exactly one block per transcript message.
 * A tool_use and its tool_result share one folded block, keyed by tool_call_id.
 */
export function buildSettledTranscriptBlocks(
  records: TranscriptRecord[],
  assistantLabel: string,
): SettledTranscriptBlock[] {
  const blocks: SettledTranscriptBlock[] = [];
  const toolByCallId = new Map<string, SettledTranscriptBlock>();

  for (const record of records) {
    if (record.section !== 'tool') {
      const lines = record.content.split('\n');
      const block: SettledTranscriptBlock = {
        key: `transcript:${record.msgId}`,
        firstMsgId: record.msgId,
        lastMsgId: record.msgId,
        turnNum: record.turnNum,
        section: record.section,
        timestamp: record.timestamp,
        label: proseLabel(record.section, assistantLabel),
        content: record.content,
        lines,
        version: '',
      };
      refreshBlockVersion(block);
      blocks.push(block);
      continue;
    }

    const existing = record.toolCallId ? toolByCallId.get(record.toolCallId) : undefined;
    if (record.type === 'tool_result' && existing) {
      existing.lastMsgId = record.msgId;
      const resultLines = toolFallbackLines(record);
      existing.lines.push(...resultLines);
      refreshBlockVersion(existing);
      continue;
    }

    const fallbackLines = toolFallbackLines(record);
    const block: SettledTranscriptBlock = {
      key: `transcript:${record.msgId}`,
      firstMsgId: record.msgId,
      lastMsgId: record.msgId,
      turnNum: record.turnNum,
      section: 'tool',
      timestamp: record.timestamp,
      label: record.toolName || 'TOOL',
      content: record.type === 'tool_use' ? (record.toolInput || '') : '',
      lines: fallbackLines,
      toolName: record.toolName,
      toolCallId: record.toolCallId,
      version: '',
    };
    refreshBlockVersion(block);
    blocks.push(block);
    if (record.toolCallId) toolByCallId.set(record.toolCallId, block);
  }

  return blocks;
}

/** Tool-identity comparison form; whitespace, ANSI, markers, and Markdown are presentation. */
function normalizeToolIdentityText(value: string): string {
  return value
    .replace(/\x1b\][0-9]*;[^\x07\x1b]*(?:\x07|\x1b\\)/g, '')
    .replace(/\x1b\[[0-9;]*m/g, '')
    .replace(/(?<!\x1b)\[[0-9;]+m/g, '')
    .replace(/^[\s─-╿⏺•▪●·✻✽✳✢✿❯◦∴⎿⧉‣▸▹▶✦✧>\-]+/, '')
    .replace(/[*`#_]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function collectStringValues(value: unknown, values: string[]): void {
  if (typeof value === 'string') {
    values.push(value);
  } else if (Array.isArray(value)) {
    for (const item of value) collectStringValues(item, values);
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value as Record<string, unknown>)) {
      collectStringValues(item, values);
    }
  }
}

/**
 * A folded terminal tool view is reused only when it identifies the expected
 * transcript tool. This affects presentation only; it never places the live seam.
 */
function toolRangeMatches(block: SettledTranscriptBlock, rangeLines: string[]): boolean {
  const terminal = normalizeToolIdentityText(rangeLines.join(' '));
  const hints: string[] = [];
  if (block.toolName) {
    const name = normalizeToolIdentityText(block.toolName);
    if (name.length >= 3 && terminal.includes(name)) return true;
  }

  if (block.content) {
    try {
      collectStringValues(JSON.parse(block.content), hints);
    } catch {
      hints.push(...block.content.split('\n'));
    }
    const pathMatches = block.content.matchAll(/(?:Update|Add|Delete) File:\s*(.+)/g);
    for (const match of pathMatches) hints.push(match[1]);
  }

  for (const hint of hints) {
    const normalized = normalizeToolIdentityText(hint);
    if (normalized.length < MIN_MATCH_CHARS) continue;
    if (terminal.includes(normalized)) return true;
    // Terminal tool cards truncate long commands/paths. A substantial leading
    // fragment still identifies the expected call without relying on its position.
    const prefix = normalized.slice(0, Math.min(32, normalized.length));
    if (prefix.length >= 16 && terminal.includes(prefix)) return true;
  }
  return false;
}

/**
 * Recover the terminal's compact tool cards for an existing transcript on mount.
 * Pairing is identity-checked from the newest end; prose is never paired this way.
 */
export function collectTerminalToolViews(
  blocks: SettledTranscriptBlock[],
  terminalLines: string[],
  terminalKinds: string[],
  end: number,
): Map<string, string[]> {
  const ranges: Array<{ start: number; end: number }> = [];
  let index = 0;
  while (index < end) {
    if (terminalKinds[index] !== 'tool') {
      index++;
      continue;
    }
    const start = index;
    index++;
    while (index < end) {
      const kind = terminalKinds[index];
      if (kind && kind !== 'cont' && kind !== 'separator') break;
      index++;
    }
    ranges.push({ start, end: index });
  }

  const tools = blocks.filter((block) => block.section === 'tool');
  const views = new Map<string, string[]>();
  const unused = new Set(ranges.map((_, rangeIndex) => rangeIndex));
  for (let blockIndex = tools.length - 1; blockIndex >= 0; blockIndex--) {
    const block = tools[blockIndex];
    for (let rangeIndex = ranges.length - 1; rangeIndex >= 0; rangeIndex--) {
      if (!unused.has(rangeIndex)) continue;
      const range = ranges[rangeIndex];
      const rangeLines = terminalLines.slice(range.start, range.end);
      if (!toolRangeMatches(block, rangeLines)) continue;
      views.set(block.key, rangeLines);
      unused.delete(rangeIndex);
      break;
    }
  }
  return views;
}

/** Replace transcript tool fallbacks with the terminal's compact/folded rendering. */
export function applyTerminalToolViews(
  blocks: SettledTranscriptBlock[],
  toolViews: Map<string, string[]>,
): SettledTranscriptBlock[] {
  return blocks.map((block) => {
    const terminalLines = toolViews.get(block.key);
    if (block.section !== 'tool' || !terminalLines || terminalLines.length === 0) return block;
    const next = { ...block, lines: terminalLines.slice() };
    refreshBlockVersion(next);
    return next;
  });
}
