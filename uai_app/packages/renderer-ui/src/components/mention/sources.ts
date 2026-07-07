/**
 * sources — built-in MentionSources for the reusable `@`-autocomplete.
 *
 *   makeRecipientSource — `@name` → sessions / teams / projects (host supplies targets)
 *   makePathSource      — `@/…`, `@~/…`, `@./…` → files & folders (via window.uai.fs.listDir)
 *
 * Both share the `@` trigger; disambiguation is by the first char after `@`
 * (`/ ~ .` → path, otherwise a name). Compose them in the order you want tried.
 */

import type { MentionItem, MentionSource } from './types';

/** A messageable target the recipient source can suggest. */
export interface RecipientTarget {
  /** Bare word or `"quoted name"` inserted after `@`. */
  token: string;
  label: string;
  kind: 'session' | 'team' | 'project' | string;
  /** How many sessions it expands to (1 for a session). */
  count: number;
}

/**
 * `@name` recipient autocomplete. `getTargets` is a getter so the caller can pass
 * live, memoized state without rebuilding the source each render.
 */
export function makeRecipientSource(getTargets: () => RecipientTarget[]): MentionSource {
  return {
    id: 'recipient',
    hint: `Recipients · ↑↓ then ↵`,
    match(before) {
      // `@"partial name` (spaces allowed) …
      const quoted = before.match(/(?:^|\s)@"([^"]*)$/);
      if (quoted) {
        return { query: quoted[1], startIndex: before.length - quoted[1].length - 2, endIndex: before.length };
      }
      // … or a bare `@word`. The required leading alphanumeric class means `@/`,
      // `@~`, `@.` never match here — those fall through to the path source.
      const bare = before.match(/(?:^|\s)@([A-Za-z0-9_-]*)$/);
      if (bare) {
        return { query: bare[1], startIndex: before.length - bare[1].length - 1, endIndex: before.length };
      }
      return null;
    },
    getItems(query) {
      const q = query.toLowerCase();
      return getTargets()
        .filter((t) => !q
          || t.label.toLowerCase().includes(q)
          || t.token.toLowerCase().replace(/"/g, '').includes(q))
        // sessions first, then alpha
        .sort((a, b) =>
          (b.kind !== 'session' ? 1 : 0) - (a.kind !== 'session' ? 1 : 0)
          || a.label.localeCompare(b.label))
        .map<MentionItem>((t) => ({
          id: `${t.kind}:${t.token}`,
          insert: `@${t.token} `,
          label: t.label,
          kind: t.kind,
          badge: t.kind !== 'session' ? `${t.kind} · ${t.count}` : undefined,
        }));
    },
  };
}

/** Options for the path source. */
export interface PathSourceOpts {
  /** Base dir for resolving `./` and `../` queries (e.g. the session's project dir).
   *  A getter so it can track the active session. Absolute `/…` and `~/…` ignore it. */
  baseDir?: () => string | null | undefined;
  /** Cap on rows returned (default 60). */
  limit?: number;
}

/**
 * `@/…`, `@~/…`, `@./…` file & folder autocomplete. Directories insert with a
 * trailing `/` and keepOpen (drill in); files insert with a trailing space.
 */
export function makePathSource(opts: PathSourceOpts = {}): MentionSource {
  const limit = opts.limit ?? 60;
  return {
    id: 'path',
    hint: `Files & folders · ↑↓ then ↵`,
    match(before) {
      // `@` immediately followed by a path lead char, then anything up to the caret
      // (spaces allowed — mac paths like "Application Support").
      const m = before.match(/(?:^|\s)@([~./][^\n]*)$/);
      if (!m) return null;
      return { query: m[1], startIndex: before.length - m[1].length - 1, endIndex: before.length };
    },
    async getItems(query) {
      const lastSlash = query.lastIndexOf('/');
      let prefix: string;  // text after `@` to keep before the entry name (ends in '/')
      let partial: string; // the fragment being completed
      let dirPart: string; // directory to list
      if (lastSlash === -1) {
        // Bare lead: `~`, `.`, `..` — list that base, no partial yet.
        prefix = query.replace(/\/*$/, '') + '/';
        partial = '';
        dirPart = query;
      } else {
        prefix = query.slice(0, lastSlash + 1);
        partial = query.slice(lastSlash + 1);
        dirPart = query.slice(0, lastSlash) || '/';
      }

      // Resolve relative dirs against baseDir; absolute / home pass through
      // (main-process listDir expands `~`).
      let listPath = dirPart;
      const base = opts.baseDir?.();
      if (base && /^\.\.?(\/|$)/.test(dirPart)) {
        listPath = `${base.replace(/\/$/, '')}/${dirPart}`;
      }

      const showHidden = partial.startsWith('.');
      let rows: Array<{ name: string; path: string; type: 'file' | 'directory' }> = [];
      try {
        rows = await window.uai.fs.listDir(listPath, { showHidden });
      } catch {
        rows = [];
      }

      const p = partial.toLowerCase();
      return rows
        .filter((r) => !p || r.name.toLowerCase().startsWith(p))
        .slice(0, limit)
        .map<MentionItem>((r) => {
          const isDir = r.type === 'directory';
          return {
            id: r.path,
            insert: `@${prefix}${r.name}${isDir ? '/' : ' '}`,
            label: r.name + (isDir ? '/' : ''),
            kind: isDir ? 'directory' : 'file',
            keepOpen: isDir,
          };
        });
    },
  };
}
