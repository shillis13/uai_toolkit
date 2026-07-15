/**
 * useMention — headless controller for the reusable `@`-autocomplete.
 *
 * Wire it to a textarea:
 *   const m = useMention({ textareaRef, sources, onApply });
 *   <textarea onChange={e => { setText(e.target.value); m.sync(e.target.value, e.target.selectionStart ?? 0); }}
 *             onKeyDown={e => { if (m.handleKeyDown(e)) return; ...your keys... }}
 *             onClick={e => m.sync(e.currentTarget.value, e.currentTarget.selectionStart ?? 0)} />
 *   <MentionPopover state={m} />
 *
 * `onApply(nextValue, caret)` is where the host commits the replaced text (set state,
 * persist, restore focus + selection). The hook stays agnostic about how text is stored.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getCaretRect, type CaretRect } from './caret';
import type { MentionItem, MentionMatch, MentionSource } from './types';

export interface UseMentionResult {
  open: boolean;
  items: MentionItem[];
  activeIndex: number;
  anchor: CaretRect | null;
  hint?: string;
  setActiveIndex: (i: number) => void;
  /** Recompute suggestions from the current value + caret. Call on input/click. */
  sync: (value: string, caret: number) => void;
  /** Handle nav/select/dismiss keys. Returns true when the event was consumed. */
  handleKeyDown: (e: React.KeyboardEvent) => boolean;
  /** Commit a suggestion. */
  apply: (item: MentionItem) => void;
  close: () => void;
}

export interface UseMentionOpts {
  textareaRef: React.RefObject<HTMLTextAreaElement>;
  sources: MentionSource[];
  onApply: (nextValue: string, caret: number) => void;
}

export function useMention({ textareaRef, sources, onApply }: UseMentionOpts): UseMentionResult {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<MentionItem[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [anchor, setAnchor] = useState<CaretRect | null>(null);
  const [hint, setHint] = useState<string | undefined>(undefined);
  const matchRef = useRef<MentionMatch | null>(null);
  const reqRef = useRef(0);
  // Which source produced the currently-displayed items. Used to drop stale items
  // the instant the source kind changes (e.g. recipient → path), so an async fetch
  // never leaves one source's rows showing under another's hint.
  const itemsSourceRef = useRef<string | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setItems([]);
    setActiveIndex(0);
    setAnchor(null);
    setHint(undefined);
    matchRef.current = null;
    itemsSourceRef.current = null;
    reqRef.current++; // invalidate any in-flight async fetch
  }, []);

  const sync = useCallback((value: string, caret: number) => {
    const before = value.slice(0, caret);
    let match: MentionMatch | null = null;
    let source: MentionSource | null = null;
    for (const s of sources) {
      const m = s.match(before);
      if (m) { match = m; source = s; break; }
    }
    if (!match || !source) { close(); return; }

    matchRef.current = match;
    setHint(source.hint);
    const ta = textareaRef.current;
    if (ta) setAnchor(getCaretRect(ta, match.startIndex));

    // Source kind changed → drop the previous source's items now, before the (maybe
    // async) fetch resolves, so we never flash stale rows under the new hint.
    if (itemsSourceRef.current !== source.id) {
      setItems([]);
      setActiveIndex(0);
      itemsSourceRef.current = source.id;
    }

    const reqId = ++reqRef.current;
    Promise.resolve(source.getItems(match.query, match))
      .then((list) => {
        if (reqRef.current !== reqId) return; // superseded
        itemsSourceRef.current = source.id;
        setItems(list);
        setActiveIndex(0);
        setOpen(list.length > 0);
      })
      .catch(() => {
        if (reqRef.current !== reqId) return;
        setItems([]);
        setOpen(false);
      });
  }, [sources, close, textareaRef]);

  const apply = useCallback((item: MentionItem) => {
    const match = matchRef.current;
    const ta = textareaRef.current;
    if (!match || !ta) return;
    const value = ta.value;
    const next = value.slice(0, match.startIndex) + item.insert + value.slice(match.endIndex);
    const caret = match.startIndex + item.insert.length;
    onApply(next, caret);
    if (item.keepOpen) {
      // Directory drilled into — re-detect at the new caret once the value settles.
      requestAnimationFrame(() => sync(next, caret));
    } else {
      close();
    }
  }, [onApply, close, textareaRef, sync]);

  // Dismiss on click/focus away — the popover was "too sticky" because it only
  // closed on Escape / apply / a broken match. Any pointer-down outside the
  // textarea AND outside the popover closes it. Uses capture so it fires before
  // the click lands; the popover rows preventDefault their mousedown, so this
  // never races an in-progress selection.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node | null;
      const ta = textareaRef.current;
      if (ta && t && ta.contains(t)) return;
      if (t && (t as HTMLElement).closest?.('.mention-popover')) return;
      close();
    };
    // Focus leaving the textarea for anything other than the popover also
    // dismisses (a second signal, in case a click lands somewhere the mousedown
    // path doesn't cover). Popover rows preventDefault their mousedown, so
    // selecting an item never blurs the textarea.
    const onFocusOut = (e: FocusEvent) => {
      const next = e.relatedTarget as Node | null;
      if (next && (next as HTMLElement).closest?.('.mention-popover')) return;
      close();
    };
    const ta = textareaRef.current;
    document.addEventListener('mousedown', onDown, true);
    ta?.addEventListener('focusout', onFocusOut);
    return () => {
      document.removeEventListener('mousedown', onDown, true);
      ta?.removeEventListener('focusout', onFocusOut);
    };
  }, [open, close, textareaRef]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent): boolean => {
    if (!open || items.length === 0) return false;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault(); setActiveIndex((i) => (i + 1) % items.length); return true;
      case 'ArrowUp':
        e.preventDefault(); setActiveIndex((i) => (i - 1 + items.length) % items.length); return true;
      case 'Enter':
      case 'Tab':
        e.preventDefault(); apply(items[Math.min(activeIndex, items.length - 1)]); return true;
      case 'Escape':
        e.preventDefault(); close(); return true;
      default:
        return false;
    }
  }, [open, items, activeIndex, apply, close]);

  return { open, items, activeIndex, anchor, hint, setActiveIndex, sync, handleKeyDown, apply, close };
}
