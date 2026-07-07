/**
 * mention — reusable `@`-autocomplete for any textarea.
 *
 * Drop-in usage (see PromptBox.tsx for a live example):
 *   const sources = useMemo(() => [
 *     makeRecipientSource(() => targets),
 *     makePathSource({ baseDir: () => session?.project_dir }),
 *   ], [targets, session]);
 *   const mention = useMention({ textareaRef, sources, onApply: (next, caret) => { ... } });
 *   // in the textarea: onChange → mention.sync(value, caret); onKeyDown → if (mention.handleKeyDown(e)) return;
 *   // render: <MentionPopover state={mention} />
 *
 * Sources are pluggable — add your own for @-commands, emoji, tags, etc.
 */

export { useMention } from './useMention';
export type { UseMentionResult, UseMentionOpts } from './useMention';
export { MentionPopover } from './MentionPopover';
export { makeRecipientSource, makePathSource } from './sources';
export type { RecipientTarget, PathSourceOpts } from './sources';
export { getCaretRect } from './caret';
export type { CaretRect } from './caret';
export type { MentionItem, MentionMatch, MentionSource, MentionKind } from './types';
