/**
 * prompt-block.ts — display helper for the 🔒 prompt-block chip.
 *
 * A session carries `prompt_block` (from Noctis's prompt_blocks backend, via the
 * main session-list payload) when it is blocked from receiving prompts from
 * anyone but PianoMan. This formats a compact chip (glyph + short suffix) and a
 * descriptive tooltip, kept visually consistent with the CLI statusline
 * indicator ('🔒 blocked·2t', '🔒 blocked·til 23:00'). Read-only — the app
 * never sets/clears blocks.
 */

import type { PromptBlock } from '@uai/shared/types';

export interface PromptBlockChip {
  glyph: string;     // 🔒
  short: string;     // compact label for the chip, e.g. '🔒', '🔒·2t', '🔒·til 23:00'
  tooltip: string;   // multi-line detail
}

function fmtTime(iso?: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** Build the chip for a session's prompt-block, or null when not blocked. */
export function promptBlockChip(block?: PromptBlock | null): PromptBlockChip | null {
  if (!block) return null;
  const glyph = '🔒';

  let suffix = '';
  const tip: string[] = ['Prompt-blocked — only PianoMan can prompt this session'];

  if (block.mode === 'turns' && block.turns_remaining != null) {
    suffix = `·${block.turns_remaining}t`;
    tip.push(`${block.turns_remaining} turn${block.turns_remaining === 1 ? '' : 's'} remaining (auto-counts down)`);
  } else if (block.expires_at) {
    const t = fmtTime(block.expires_at);
    suffix = t ? `·til ${t}` : '·timed';
    const full = new Date(block.expires_at);
    tip.push(`Until ${isNaN(full.getTime()) ? block.expires_at : full.toLocaleString()}`);
  } else {
    // indefinite
    tip.push('Indefinite — until manually unblocked');
  }

  if (block.reason) tip.push(`Reason: ${block.reason}`);
  tip.push('Held prompts are delivered on unblock');

  return { glyph, short: `${glyph}${suffix}`, tooltip: tip.join('\n') };
}
