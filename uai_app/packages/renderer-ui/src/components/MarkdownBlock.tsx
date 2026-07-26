/**
 * MarkdownBlock — the reusable formatted-text element for the app (todo_0619 VISION).
 *
 * One place that turns Markdown source into safe, styled HTML: marked (gfm, breaks)
 * → DOMPurify → a `.context-mgr-md` container. HTML comments `<!-- x -->` are kept but
 * DIMMED (marked would otherwise drop them) so authoring hints read as muted asides
 * (note_0035). This was previously inlined as NotesBody in TodoItemView; extracting it
 * lets every large text field (todo notes, comments, news, add-note previews) render
 * identically. Reuse this instead of re-implementing marked+DOMPurify.
 *
 * Sizing (todo_0619 pt2): height follows content by default (auto-size). Pass
 * `resizable` to add a user drag-handle (vertical), with `maxHeight` capping runaway
 * content so it scrolls inside the block rather than pushing the page.
 *
 * SECURITY: output is passed through DOMPurify.sanitize() before it reaches the DOM;
 * dangerouslySetInnerHTML below only ever receives sanitized HTML.
 */

import { useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Markdown source → sanitized HTML, with `<!-- comments -->` preserved as dimmed spans. */
export function renderMarkdown(text: string, dimComments = true): string {
  if (!text) return '';
  const prepped = text.replace(/<!--([\s\S]*?)-->/g, (_m, inner) => {
    if (!dimComments) return '';
    const t = String(inner).trim();
    return t ? `<span class="tiv-comment">${escapeHtml(t)}</span>` : '';
  });
  let raw = '';
  // breaks:true keeps manual single newlines as line breaks (todo_0611) — a bare
  // Enter in a Description/comment stays a line break instead of being folded away.
  try { raw = marked.parse(prepped, { async: false, breaks: true }) as string; }
  catch { raw = escapeHtml(prepped); }
  // DOMPurify strips scripts/handlers/unsafe URLs — the string below is always clean.
  return DOMPurify.sanitize(raw);
}

export interface MarkdownBlockProps {
  text: string;
  /** Extra class(es) on the container, in addition to `context-mgr-md`. */
  className?: string;
  /** Add a user-draggable vertical resize handle. Default false (auto-size to content). */
  resizable?: boolean;
  /** Cap height (px) so long content scrolls inside the block instead of the page. */
  maxHeight?: number;
  /** Floor height (px) when resizable, so the drag handle has room. */
  minHeight?: number;
  /** Keep `<!-- comments -->` as dimmed text (default) vs. strip them entirely. */
  dimComments?: boolean;
  style?: React.CSSProperties;
}

export default function MarkdownBlock({
  text, className, resizable = false, maxHeight, minHeight, dimComments = true, style,
}: MarkdownBlockProps): JSX.Element {
  // renderMarkdown() sanitizes with DOMPurify; the result is safe for innerHTML.
  const safeHtml = useMemo(() => renderMarkdown(text, dimComments), [text, dimComments]);

  const sizeStyle: React.CSSProperties = resizable
    ? { resize: 'vertical', overflow: 'auto', minHeight: minHeight ?? 60, maxHeight: maxHeight ?? undefined }
    : maxHeight != null
      ? { overflowY: 'auto', maxHeight }
      : {};

  return (
    <div
      className={`context-mgr-md${className ? ' ' + className : ''}`}
      style={{ ...sizeStyle, ...style }}
      dangerouslySetInnerHTML={{ __html: safeHtml }}
    />
  );
}
