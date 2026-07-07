/**
 * caret — viewport-relative pixel rect of a textarea caret at a character index.
 *
 * Uses the well-worn "mirror div" technique: clone the textarea's text metrics into
 * a hidden div, place a marker span at the target offset, and read its position.
 * This is what lets the mention popover sit right under the `@` the user is typing,
 * rather than at a fixed corner of the box.
 */

export interface CaretRect {
  /** Viewport x of the caret (px). */
  left: number;
  /** Viewport y of the caret's top (px). */
  top: number;
  /** Line height at the caret (px). */
  height: number;
}

// Style properties that affect text layout — copied onto the mirror div.
const MIRRORED_PROPS = [
  'direction', 'boxSizing', 'width', 'height', 'overflowX', 'overflowY',
  'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'fontStyle', 'fontVariant', 'fontWeight', 'fontStretch', 'fontSize',
  'lineHeight', 'fontFamily', 'textAlign', 'textTransform', 'textIndent',
  'letterSpacing', 'wordSpacing', 'tabSize',
] as const;

export function getCaretRect(el: HTMLTextAreaElement, index: number): CaretRect {
  const doc = el.ownerDocument;
  const div = doc.createElement('div');
  const computed = getComputedStyle(el);
  const s = div.style;
  s.position = 'absolute';
  s.visibility = 'hidden';
  s.whiteSpace = 'pre-wrap';
  s.wordWrap = 'break-word';
  s.overflow = 'hidden';
  for (const prop of MIRRORED_PROPS) {
    (s as unknown as Record<string, string>)[prop] = (computed as unknown as Record<string, string>)[prop];
  }
  // The div must wrap exactly like the textarea's content box.
  s.width = `${el.clientWidth}px`;
  s.height = 'auto';

  div.textContent = el.value.slice(0, index);
  const marker = doc.createElement('span');
  // A non-empty marker so it has a box; the trailing text after the caret does not
  // affect the marker's position.
  marker.textContent = el.value.slice(index) || '.';
  div.appendChild(marker);
  doc.body.appendChild(div);

  const rect = el.getBoundingClientRect();
  const lineHeight = parseFloat(computed.lineHeight) || parseFloat(computed.fontSize) || 16;
  const out: CaretRect = {
    left: rect.left + marker.offsetLeft - el.scrollLeft,
    top: rect.top + marker.offsetTop - el.scrollTop,
    height: lineHeight,
  };
  doc.body.removeChild(div);
  return out;
}
