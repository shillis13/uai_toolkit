/**
 * TranscriptCacheService — a persistent, main-process cache of parsed session
 * transcripts, shared across renderer tabs.
 *
 * Why it exists: the Memorex overlay used to parse the whole JSONL from scratch on a
 * 10s timer, and its cache lived inside the (per-tab) React component — so switching
 * tabs threw the cache away and returning rebuilt from zero. This service moves the
 * cache OUT of the component and into the main process, and keeps an LRU POOL of the
 * last N viewed sessions warm, each with its own file WATCHER. Result:
 *   - file changes normally refresh through the watcher immediately; an explicit
 *     warm-cache read also verifies size+mtime so a missed watcher event self-heals;
 *   - instant tab-return: a pooled session's cache is already parsed AND kept current
 *     by its watcher (only a session evicted past N pays a cold, from-scratch load);
 *   - one place the boundary walk can read from + advance as messages arrive.
 *
 * Watcher delay is configured by ai_general/data/memorex/palette.json or the
 * UAI_TRANSCRIPT_REFRESH_DEBOUNCE_MS environment override. Zero means immediate.
 *
 * The cache stays a read-only, re-derivable reflection of the JSONL (DESIGN.md #1/#6 —
 * the file is ground truth; the cache never persists and always rebuilds from it).
 *
 * Indexing is LOCAL-FIRST: cold + refresh both go through read_jsonl (the canonical
 * parser) for correct msg#/turn#/section. `readRecords()` is the single seam where a
 * future incremental tail-read or Broken-Clock's shared stored-seq index can slot in
 * without touching the pool/watcher machinery.
 */

import * as fs from 'node:fs';
import { execFile } from 'node:child_process';
import * as path from 'node:path';
import { aiRootMain as getAiRootMain, shellPath } from './paths';

export interface TranscriptReadResult {
  ok: boolean;
  days?: unknown[];
  error?: string;
  path?: string;
  cached?: boolean;   // true = served warm from the pool (no re-parse this call)
  revision?: string;  // file size + mtime for renderer-side incremental updates
}

interface CacheEntry {
  refs: Set<string>;           // every id/name/uuid that resolved to this file
  filePath: string;
  size: number;
  mtimeMs: number;
  days: unknown[];             // parsed structured transcript (read_jsonl --format structured)
  watcher: fs.FSWatcher | null;
  lastViewed: number;          // LRU key
  debounce: NodeJS.Timeout | null;
  refreshPromise: Promise<void> | null;
  refreshQueued: boolean;       // another file event arrived while refreshPromise was running
}

const MAX_POOL = 5;            // keep the last 5 viewed sessions warm
const READ_MAXBUFFER = 256 * 1024 * 1024;

export interface TranscriptCacheServiceOptions {
  refreshDebounceMs?: number;
}

function configuredRefreshDebounceMs(): number {
  const envValue = process.env.UAI_TRANSCRIPT_REFRESH_DEBOUNCE_MS;
  if (envValue !== undefined) {
    const parsed = Number(envValue);
    if (Number.isFinite(parsed) && parsed >= 0) return parsed;
  }
  try {
    const configPath = path.join(
      getAiRootMain(),
      'ai_general/data/memorex/palette.json',
    );
    const parsed = JSON.parse(fs.readFileSync(configPath, 'utf8')) as {
      runtime?: { transcriptRefreshDebounceMs?: unknown };
    };
    const value = Number(parsed.runtime?.transcriptRefreshDebounceMs);
    if (Number.isFinite(value) && value >= 0) return value;
  } catch { /* absent/invalid config uses the low-latency default */ }
  return 0;
}

export class TranscriptCacheService {
  /** One parsed entry per canonical JSONL path, shared by Memorex + Transcript. */
  private pool = new Map<string, CacheEntry>();
  private aliases = new Map<string, string>();
  private coldLoads = new Map<string, Promise<unknown[]>>();
  private readonly refreshDebounceMs: number;
  /** Set by index.ts to push a `transcript:updated` event to the renderer. */
  onUpdate: ((ref: string) => void) | null = null;

  constructor(options: TranscriptCacheServiceOptions = {}) {
    const configured = options.refreshDebounceMs ?? configuredRefreshDebounceMs();
    this.refreshDebounceMs = Number.isFinite(configured) && configured >= 0 ? configured : 0;
  }

  /** Resolve + parse a session's transcript, serving a warm pooled copy when possible. */
  async get(ref: string): Promise<TranscriptReadResult> {
    if (!ref) return { ok: false, error: 'no session ref' };
    const knownPath = this.aliases.get(ref);
    const filePath = knownPath || await this.resolveFile(ref);
    if (!filePath) return { ok: false, error: `Session file not found for ${ref}` };

    const existing = this.pool.get(filePath);
    if (existing) {
      existing.refs.add(ref);
      this.aliases.set(ref, filePath);
      existing.lastViewed = Date.now();
      // A watcher can fail or miss an event. Rechecking metadata on an explicit
      // read keeps the cache correct without bringing back timer-based polling.
      await this.refresh(existing);
      return {
        ok: true,
        days: existing.days,
        path: existing.filePath,
        cached: true,
        revision: this.revision(existing),
      };
    }
    return this.coldLoad(ref, filePath);
  }

  private async coldLoad(ref: string, filePath: string): Promise<TranscriptReadResult> {
    let days: unknown[];
    let load = this.coldLoads.get(filePath);
    if (!load) {
      load = this.readRecords(filePath);
      this.coldLoads.set(filePath, load);
    }
    try {
      days = await load;
    } catch (err: unknown) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    } finally {
      if (this.coldLoads.get(filePath) === load) this.coldLoads.delete(filePath);
    }

    // A concurrent alias lookup may have completed this same shared load first.
    const concurrent = this.pool.get(filePath);
    if (concurrent) {
      concurrent.refs.add(ref);
      this.aliases.set(ref, filePath);
      concurrent.lastViewed = Date.now();
      return {
        ok: true,
        days: concurrent.days,
        path: concurrent.filePath,
        cached: true,
        revision: this.revision(concurrent),
      };
    }
    let size = 0, mtimeMs = 0;
    try { const st = fs.statSync(filePath); size = st.size; mtimeMs = st.mtimeMs; } catch { /* ignore */ }
    const entry: CacheEntry = {
      refs: new Set([ref]),
      filePath,
      size,
      mtimeMs,
      days,
      watcher: null,
      lastViewed: Date.now(),
      debounce: null,
      refreshPromise: null,
      refreshQueued: false,
    };
    this.pool.set(filePath, entry);
    this.aliases.set(ref, filePath);
    this.attachWatcher(entry);
    this.evictIfNeeded();
    return { ok: true, days, path: filePath, cached: false, revision: this.revision(entry) };
  }

  private attachWatcher(entry: CacheEntry): void {
    try {
      const watcher = fs.watch(entry.filePath, { persistent: false }, () => this.onFileChange(entry));
      watcher.on('error', () => {
        try { watcher.close(); } catch { /* ignore */ }
        if (entry.watcher === watcher) entry.watcher = null;
      });
      entry.watcher = watcher;
    } catch {
      entry.watcher = null;   // get() still validates metadata before serving warm data
    }
  }

  private onFileChange(entry: CacheEntry): void {
    if (entry.debounce) clearTimeout(entry.debounce);
    entry.debounce = null;
    if (this.refreshDebounceMs === 0) {
      void this.refresh(entry);
      return;
    }
    entry.debounce = setTimeout(() => { void this.refresh(entry); }, this.refreshDebounceMs);
  }

  private async refresh(entry: CacheEntry): Promise<void> {
    if (entry.refreshPromise) {
      // Do not discard an append that arrives during a full read_jsonl parse. The
      // owner refresh loops once more after its current pass reaches a stable point.
      entry.refreshQueued = true;
      await entry.refreshPromise;
      return;
    }
    entry.refreshPromise = (async () => {
      do {
        entry.refreshQueued = false;
        await this.refreshOnce(entry);
      } while (entry.refreshQueued && this.pool.get(entry.filePath) === entry);
    })();
    try {
      await entry.refreshPromise;
    } finally {
      entry.refreshPromise = null;
    }
  }

  private async refreshOnce(entry: CacheEntry): Promise<void> {
    if (entry.debounce) clearTimeout(entry.debounce);
    entry.debounce = null;
    if (this.pool.get(entry.filePath) !== entry) return;   // evicted/replaced while debouncing
    let st: fs.Stats;
    try { st = fs.statSync(entry.filePath); } catch { return; }
    if (st.size === entry.size && st.mtimeMs === entry.mtimeMs) return;
    let days: unknown[];
    try { days = await this.readRecords(entry.filePath); } catch { return; }
    entry.days = days;
    entry.size = st.size;
    entry.mtimeMs = st.mtimeMs;
    if (this.onUpdate) {
      for (const ref of entry.refs) this.onUpdate(ref);
    }
  }

  private evictIfNeeded(): void {
    while (this.pool.size > MAX_POOL) {
      let lru: CacheEntry | null = null;
      for (const e of this.pool.values()) if (!lru || e.lastViewed < lru.lastViewed) lru = e;
      if (!lru) break;
      try { lru.watcher?.close(); } catch { /* ignore */ }
      if (lru.debounce) clearTimeout(lru.debounce);
      this.pool.delete(lru.filePath);
      for (const ref of lru.refs) this.aliases.delete(ref);
    }
  }

  private revision(entry: CacheEntry): string {
    return `${entry.size}:${entry.mtimeMs}`;
  }

  /** LOCAL-FIRST seam: full structured parse via read_jsonl. A future incremental
   *  tail-read (or BC's shared stored-seq index) replaces THIS method only. */
  private async readRecords(filePath: string): Promise<unknown[]> {
    const out = await this.runReadJsonl(['read-file', filePath, '--format', 'structured']);
    return JSON.parse(out) as unknown[];
  }

  private async resolveFile(ref: string): Promise<string | null> {
    try {
      const out = (await this.runReadJsonl(['find', ref])).trim();
      return out ? out : null;   // find now prints a miss to stderr → empty stdout
    } catch {
      return null;
    }
  }

  private runReadJsonl(args: string[]): Promise<string> {
    const aiRoot = getAiRootMain();
    const script = path.join(aiRoot, 'ai_general/scripts/jsonl/read_jsonl.py');
    const env = { ...process.env, PATH: shellPath(), AI_ROOT: aiRoot } as Record<string, string>;
    return new Promise<string>((resolve, reject) => {
      execFile('python3', [script, ...args], { maxBuffer: READ_MAXBUFFER, timeout: 30000, env },
        (error, stdout, stderr) => {
          if (error) { reject(new Error(stderr || error.message)); return; }
          resolve(stdout);
        });
    });
  }

  /** Tear everything down (app quit). */
  dispose(): void {
    for (const e of this.pool.values()) {
      try { e.watcher?.close(); } catch { /* ignore */ }
      if (e.debounce) clearTimeout(e.debounce);
    }
    this.pool.clear();
    this.aliases.clear();
    this.coldLoads.clear();
  }
}

export const transcriptCache = new TranscriptCacheService();
