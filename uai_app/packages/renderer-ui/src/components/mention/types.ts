/**
 * mention/types — shared types for the reusable `@`-mention autocomplete.
 *
 * A drop-in `@`-autocomplete for any <textarea>. It is source-driven: each
 * MentionSource owns one grammar (recipients, file paths, …). The host wires the
 * `useMention` hook to a textarea and renders <MentionPopover>. See ./index.ts.
 */

/** Kind drives the row icon + styling. Extensible — any string works. */
export type MentionKind = 'session' | 'team' | 'project' | 'file' | 'directory' | string;

/** One suggestion row. */
export interface MentionItem {
  /** Stable React key (also used for de-dupe / active tracking). */
  id: string;
  /** The exact text that REPLACES the matched span `[startIndex, endIndex)` —
   *  including the trigger char and any trailing space/slash. The source owns
   *  quoting and trailing punctuation. */
  insert: string;
  /** Primary display label. */
  label: string;
  kind: MentionKind;
  /** Optional right-aligned pill (e.g. "team · 3"). */
  badge?: string;
  /** Optional dim secondary text (e.g. a full path). */
  detail?: string;
  /** Keep the popover open after applying (e.g. drilling into a directory). */
  keepOpen?: boolean;
}

/** An in-progress mention detected in the text before the caret. */
export interface MentionMatch {
  /** Partial query between the trigger and the caret, per the source's grammar. */
  query: string;
  /** Absolute index in the value where the replacement starts (the trigger char). */
  startIndex: number;
  /** Absolute index where the replacement ends (usually the caret). */
  endIndex: number;
}

/** A grammar + suggestion provider. Sources are tried in order; first match wins. */
export interface MentionSource {
  id: string;
  /** Optional heading shown at the top of the popover while this source is active. */
  hint?: string;
  /** Detect an in-progress mention in `before` (text up to the caret). null = inactive. */
  match(before: string): MentionMatch | null;
  /** Suggestions for the query. May be sync or async (filesystem, network, …). */
  getItems(query: string, match: MentionMatch): MentionItem[] | Promise<MentionItem[]>;
}
