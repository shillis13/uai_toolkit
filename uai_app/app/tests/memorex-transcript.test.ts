import { describe, expect, it } from 'vitest';
import {
  appendUniqueProvisionalCards,
  applyTerminalToolViews,
  buildSettledTranscriptBlocks,
  calculateVirtualWindow,
  collectTerminalToolViews,
  flattenStructuredTranscript,
  restoredScrollTop,
  settleProvisionalCards,
  terminalCardDelta,
  type SettledTranscriptBlock,
} from '@uai/renderer-ui/components/memorex-transcript';

function block(
  msgId: number,
  section: 'user' | 'inject' | 'assistant' | 'thinking' | 'tool',
  content: string,
): SettledTranscriptBlock {
  return {
    key: `transcript:${msgId}`,
    firstMsgId: msgId,
    lastMsgId: msgId,
    turnNum: 1,
    section,
    timestamp: '',
    label: section.toUpperCase(),
    content,
    lines: content.split('\n'),
    version: String(msgId),
  };
}

const kinds = (lines: string[]): string[] => lines.map((line) => {
  if (line.startsWith('TOOL:')) return 'tool';
  if (line.startsWith('NEXT:')) return 'assistant';
  return 'cont';
});

describe('transcript-authoritative Memorex blocks', () => {
  it('replaces the first persistent provisional for each appended Transcript card', () => {
    expect(settleProvisionalCards(['p1', 'p2', 'p3'], 1)).toEqual(['p2', 'p3']);
    expect(settleProvisionalCards(['p1', 'p2', 'p3'], 2)).toEqual(['p3']);
  });

  it('appends a settled Transcript card when there is no provisional to replace', () => {
    expect(settleProvisionalCards([], 1)).toEqual([]);
  });

  it('updates a repeated provisional marker in place instead of growing the FIFO', () => {
    const prior = [{ key: 'p1', fp: 'same', text: 'partial' }];
    const result = appendUniqueProvisionalCards(
      prior,
      [{ key: 'new', fp: 'same', text: 'complete' }],
      (card) => card.fp,
      (existing, replacement) => ({ ...replacement, key: existing.key }),
    );
    expect(result).toEqual([{ key: 'p1', fp: 'same', text: 'complete' }]);
  });

  it('maintains a terminal-only stream tail without comparing it to Transcript', () => {
    const previous = [{ fp: 'a', text: 'partial' }];
    const current = [{ fp: 'a', text: 'complete' }, { fp: 'b', text: 'new' }];
    const delta = terminalCardDelta(previous, current, (card) => card.fp);
    expect(delta.anchored).toBe(true);
    expect(delta.updatedTail).toEqual(current[0]);
    expect(delta.appended).toEqual([current[1]]);
  });

  it('survives a bounded terminal capture dropping old cards', () => {
    const previous = [{ fp: 'old' }, { fp: 'a' }, { fp: 'b' }];
    const current = [{ fp: 'a' }, { fp: 'b' }, { fp: 'c' }];
    const delta = terminalCardDelta(previous, current, (card) => card.fp);
    expect(delta.anchored).toBe(true);
    expect(delta.updatedTail).toEqual(current[1]);
    expect(delta.appended).toEqual([current[2]]);
  });

  it('suppresses an indistinguishable repeated terminal card as repaint output', () => {
    const previous = [{ fp: 'same' }];
    const current = [{ fp: 'same' }, { fp: 'same' }];
    const delta = terminalCardDelta(previous, current, (card) => card.fp);
    expect(delta.appended).toEqual([]);
  });

  it('anchors on the newest repeated context instead of appending a repaint copy', () => {
    const previous = [{ fp: 'a' }, { fp: 'b' }, { fp: 'c' }];
    const current = [
      { fp: 'a' }, { fp: 'b' }, { fp: 'c' },
      { fp: 'a' }, { fp: 'b' }, { fp: 'c' },
    ];
    const delta = terminalCardDelta(previous, current, (card) => card.fp);
    expect(delta.anchored).toBe(true);
    expect(delta.appended).toEqual([]);
    expect(delta.updatedTail).toEqual(current[5]);
  });

  it('treats a changed in-progress marker as an update before later appends', () => {
    const previous = [{ fp: 'anchor' }, { fp: 'working' }];
    const current = [{ fp: 'anchor' }, { fp: 'finished' }, { fp: 'next' }];
    const delta = terminalCardDelta(previous, current, (card) => card.fp);
    expect(delta.updatedTail).toEqual(current[1]);
    expect(delta.appended).toEqual([current[2]]);
  });

  it('windows a large card list around the viewport with spacer heights', () => {
    const range = calculateVirtualWindow(
      Array.from({ length: 1000 }, () => 20),
      10000,
      500,
      500,
    );
    expect(range.start).toBeGreaterThan(400);
    expect(range.end - range.start).toBeLessThan(100);
    expect(range.beforePx + (range.end - range.start) * 20 + range.afterPx).toBe(20000);
  });

  it('renders the final card window while following the bottom', () => {
    const range = calculateVirtualWindow([100, 100, 100, 100], 250, 150, 150);
    expect(range.end).toBe(4);
    expect(range.totalPx).toBe(400);
  });

  it('restores the bottom after a settled DOM rebuild', () => {
    expect(restoredScrollTop(900, 1000, 100, 1600, true)).toBe(1500);
  });

  it('preserves a deliberate distance from the bottom across a rebuild', () => {
    // 200px above the old bottom remains 200px above the new bottom.
    expect(restoredScrollTop(700, 1000, 100, 1600, false)).toBe(1300);
  });

  it('keeps Transcript numbering while skipping non-display meta records', () => {
    const records = flattenStructuredTranscript([{
      date: '2026-07-20',
      turns: [{
        number: 4,
        messages: [
          { type: 'meta', section: 'meta', content: 'local only' },
          { type: 'user', section: 'user', content: 'hello' },
          { type: 'response', section: 'assistant', content: 'world' },
        ],
      }],
    }]);
    expect(records.map((record) => [record.msgId, record.section])).toEqual([
      [2, 'user'],
      [3, 'assistant'],
    ]);
  });

  it('classifies tool results by type even when their role and section say user', () => {
    const records = flattenStructuredTranscript([{
      turns: [{
        number: 1,
        messages: [
          { type: 'tool_result', role: 'user', section: 'user', tool_call_id: 'call-1', content: 'result' },
        ],
      }],
    }]);
    expect(records).toHaveLength(1);
    expect(records[0].section).toBe('tool');
  });

  it('skips local-only Claude records without renumbering later transcript messages', () => {
    const records = flattenStructuredTranscript([{
      turns: [{
        number: 1,
        messages: [
          { type: 'user', section: 'user', content: '<<<SESSION_IDENTITY>>> local metadata' },
          { type: 'injected', section: 'inject', content: '<<<SESSION RESUMED>>> local metadata' },
          { type: 'injected', section: 'inject', content: '<local-command-caveat>local command</local-command-caveat>' },
          { type: 'user', section: 'user', content: '<command-name>/usage</command-name>' },
          { type: 'user', section: 'user', content: '<local-command-stdout>usage output</local-command-stdout>' },
          { type: 'response', section: 'assistant', content: 'visible' },
        ],
      }],
    }]);
    expect(records.map((record) => [record.msgId, record.section, record.content])).toEqual([
      [6, 'assistant', 'visible'],
    ]);
  });

  it('keeps normalized injected user messages in the COMMS category', () => {
    const records = flattenStructuredTranscript([{
      turns: [{
        number: 1,
        messages: [
          { type: 'user', role: 'user', section: 'inject', content: 'Broadcast message' },
        ],
      }],
    }]);
    expect(records[0].section).toBe('inject');
  });

  it('merges a tool call and result into one folded block while counting both messages', () => {
    const records = flattenStructuredTranscript([{
      turns: [{
        number: 2,
        messages: [
          { type: 'tool_use', section: 'tool', tool_name: 'Read', tool_call_id: 'call-1', tool_input: { path: '/tmp/x' } },
          { type: 'tool_result', section: 'tool', tool_call_id: 'call-1', content: 'one\ntwo' },
        ],
      }],
    }]);
    const blocks = buildSettledTranscriptBlocks(records, 'CLAUDE');
    expect(blocks).toHaveLength(1);
    expect(blocks[0].firstMsgId).toBe(1);
    expect(blocks[0].lastMsgId).toBe(2);
    expect(blocks[0].lines.at(-1)).toBe('Result — 2 transcript lines');
  });

  it('uses the terminal folded tool view when one was captured', () => {
    const source = block(7, 'tool', 'full transcript result');
    const views = new Map([['transcript:7', ['TOOL: Read(file)', '  ⎿ Read 2000 lines']]]);
    const [rendered] = applyTerminalToolViews([source], views);
    expect(rendered.lines).toEqual(['TOOL: Read(file)', '  ⎿ Read 2000 lines']);
    expect(source.lines).toEqual(['full transcript result']);
  });

  it('pairs existing folded tool cards from the newest end on mount', () => {
    const blocks = [block(1, 'tool', 'one'), block(2, 'assistant', 'prose'), block(3, 'tool', 'three')];
    blocks[0].toolName = 'One';
    blocks[2].toolName = 'Three';
    const lines = ['TOOL: One', '  ⎿ first', 'NEXT: prose', 'TOOL: Three', '  ⎿ last', 'prompt'];
    const views = collectTerminalToolViews(blocks, lines, kinds(lines), 5);
    expect(views.get('transcript:1')).toEqual(['TOOL: One', '  ⎿ first']);
    expect(views.get('transcript:3')).toEqual(['TOOL: Three', '  ⎿ last']);
  });

  it('does not shift folded views onto an unrelated newer live tool', () => {
    const read = block(1, 'tool', 'input');
    read.toolName = 'Read';
    const lines = ['TOOL: Read(file)', '  ⎿ settled', 'TOOL: Write(file)', '  ⎿ live', 'prompt'];
    const views = collectTerminalToolViews([read], lines, kinds(lines), 4);
    expect(views.get(read.key)).toEqual(['TOOL: Read(file)', '  ⎿ settled']);
  });
});
