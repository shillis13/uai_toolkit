import { describe, expect, it } from 'vitest';
import { TranscriptCacheService } from '../main/transcript-cache-service';

describe('TranscriptCacheService', () => {
  it('shares one cold parse across concurrent aliases for the same JSONL path', async () => {
    const service = new TranscriptCacheService();
    const internals = service as unknown as {
      resolveFile(ref: string): Promise<string>;
      readRecords(path: string): Promise<unknown[]>;
      attachWatcher(entry: unknown): void;
    };
    const days = [{ date: '2026-07-20', turns: [] }];
    let reads = 0;

    internals.resolveFile = async () => '/virtual/same-session.jsonl';
    internals.readRecords = async () => {
      reads++;
      await new Promise((resolve) => setTimeout(resolve, 5));
      return days;
    };
    internals.attachWatcher = () => {};

    const [byTrackingId, byUuid] = await Promise.all([
      service.get('tracking-id'),
      service.get('cli-uuid'),
    ]);

    expect(reads).toBe(1);
    expect(byTrackingId.ok).toBe(true);
    expect(byUuid.ok).toBe(true);
    expect(byTrackingId.days).toBe(days);
    expect(byUuid.days).toBe(days);
    expect(byTrackingId.path).toBe('/virtual/same-session.jsonl');
    expect(byUuid.path).toBe('/virtual/same-session.jsonl');

    const warm = await service.get('tracking-id');
    expect(warm.cached).toBe(true);
    expect(warm.days).toBe(days);
    expect(reads).toBe(1);
    service.dispose();
  });

  it('processes file changes immediately when the debounce is zero', async () => {
    const service = new TranscriptCacheService({ refreshDebounceMs: 0 });
    const internals = service as unknown as {
      onFileChange(entry: unknown): void;
      refresh(entry: unknown): Promise<void>;
    };
    let refreshes = 0;
    internals.refresh = async () => { refreshes++; };
    internals.onFileChange({ debounce: null });
    await Promise.resolve();
    expect(refreshes).toBe(1);
    service.dispose();
  });

  it('runs another refresh when a file event arrives during an active refresh', async () => {
    const service = new TranscriptCacheService({ refreshDebounceMs: 0 });
    let releaseFirst!: () => void;
    const firstPass = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const entry = {
      filePath: '/virtual/growing-session.jsonl',
      debounce: null,
      refreshPromise: null,
      refreshQueued: false,
    };
    const internals = service as unknown as {
      pool: Map<string, unknown>;
      refresh(entry: unknown): Promise<void>;
      refreshOnce(entry: unknown): Promise<void>;
    };
    internals.pool.set(entry.filePath, entry);
    let passes = 0;
    internals.refreshOnce = async () => {
      passes++;
      if (passes === 1) await firstPass;
    };

    const first = internals.refresh(entry);
    await Promise.resolve();
    const second = internals.refresh(entry);
    releaseFirst();
    await Promise.all([first, second]);

    expect(passes).toBe(2);
    service.dispose();
  });
});
