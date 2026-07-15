/**
 * Activity Log — main process JSONL writer + reader.
 *
 * Workstream 1D: Observability
 *
 * Writes structured JSONL entries per UAI Next Architecture Section 2.
 * Format: {"ts","session","participant","event","conversation","payload","correlation_id"}
 * Event namespace: domain.action (e.g., command.executed, session.started, lifecycle.error)
 *
 * The command bus after-hook writes entries here. The renderer reads via IPC.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import * as readline from 'node:readline';

// ─── Types ────────────────────────────────────────────────────────────────

export interface ActivityLogEntry {
  ts: string;
  session: string;
  participant: string;
  event: string;
  conversation?: string;
  payload: Record<string, unknown>;
  correlation_id?: string;
}

export interface TopProcess {
  name: string;
  pid: number;
  cpu_pct: number;
  phys_gb: number;
}

export interface TokenBucket { in: number; out: number; total: number }

export interface SysmonEvent {
  kind: 'alert' | 'assessment' | 'episode';
  severity: number;                 // sysmon severity (≥4 warn/crit, 2–3 notice)
  message: string;
  since?: string;                   // local time the event first opened
  updated?: string;                 // local time it was last refreshed (chronic vs fresh)
  category?: string;                // top-level kind (memory/cpu/disk/sysmon) for grouping
}

export interface SystemMetrics {
  cpu_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  heap_used_mb: number;
  heap_total_mb: number;
  active_sessions: number;
  uptime_seconds: number;       // APP process uptime (legacy; use system_uptime_seconds for the box)
  error_count: number;

  // ── sysmon-derived (from ai_general/data/system_monitoring/summary.json) ──
  // Null/absent when summary.json is missing or unreadable (UI falls back).
  sysmon_status?: 'ok' | 'warn' | 'crit' | 'unknown';   // matches `sysmon status` header (_stoplight)
  sysmon_summary?: string;                               // e.g. "swap 11.2G · memory rising"
  sysmon_stale?: boolean;                                // summary.json older than the freshness window
  mem_pressure?: string;                                 // memory.pressure (normal|warn|critical)
  mem_committed_gb?: number;                             // memory.committed_gb
  mem_total_gb?: number;                                 // memory.total_gb (physical, e.g. 64)
  mem_level?: number;                                    // kern.memorystatus_level
  swap_gb?: number;                                      // memory.swap_gb
  disk_free_gb?: number;
  disk_total_gb?: number;
  disk_used_pct?: number;                                // computed (total-free)/total
  system_uptime_seconds?: number;                        // os.uptime() — real machine uptime
  load_avg?: [number, number, number];                   // os.loadavg() 1/5/15m
  cpu_avg_15m?: number;                                   // sysmon cpu_avg_15m
  cpu_avg_1h?: number;                                    // sysmon cpu_avg_1h
  cpu_avg_6h?: number;                                    // sysmon cpu_avg_6h

  // ── Top resource users (from sysmon top_cpu/top_mem_processes) ──
  top_cpu_processes?: TopProcess[];
  top_mem_processes?: TopProcess[];

  // ── Active sysmon events (alerts / assessments / episode) while they persist ──
  sysmon_events?: SysmonEvent[];

  // ── Overall Claude token counters (day/month/year/inception to date) ──
  claude_tokens?: { dtd?: TokenBucket; mtd?: TokenBucket; ytd?: TokenBucket; itd?: TokenBucket };

  // ── 1-hour sparkline series per metric (for the inline gauge graphs) ──
  sparks?: Record<string, number[]>;

  // ── Claude Code usage (bridged from the statusline via ~/.claude/rate_limits.json) ──
  claude_5h_pct?: number | null;
  claude_5h_reset?: string | null;
  claude_7d_pct?: number | null;
  claude_7d_reset?: string | null;
}

// ─── State ────────────────────────────────────────────────────────────────

let logPath: string | null = null;
let errorPath: string | null = null;
let errorCount = 0;
const startTime = Date.now();

// Ring buffer of the most recent error/warn events, for the status bar.
export interface RecentError {
  ts: string;
  source: string;   // 'main' | 'renderer' | 'scaffolding' | 'command'
  session: string;
  message: string;
}
const recentErrors: RecentError[] = [];
const RECENT_ERRORS_MAX = 50;

export function getRecentErrors(limit = 10): RecentError[] {
  return recentErrors.slice(-limit).reverse();
}

export function getLastError(): RecentError | null {
  return recentErrors.length > 0 ? recentErrors[recentErrors.length - 1] : null;
}

/** Clear the recent-errors ring buffer (status-bar dismissal). Does NOT touch
 *  the persistent uai_errors.jsonl log — only the in-memory bar feed. */
export function clearRecentErrors(): void {
  recentErrors.length = 0;
}

// ─── Init ─────────────────────────────────────────────────────────────────

/**
 * Initialize the activity log path. Must be called before writing.
 * Creates the data directory if it doesn't exist.
 */
export function initActivityLog(aiRoot: string): void {
  const dataDir = path.join(aiRoot, 'ai_general', 'data');
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }
  logPath = path.join(dataDir, 'activity_log.jsonl');
  errorPath = path.join(dataDir, 'uai_errors.jsonl');
}

// ─── Write ────────────────────────────────────────────────────────────────

/**
 * Append a single activity log entry as a JSONL line.
 * Non-blocking: errors are swallowed to avoid disrupting the app.
 */
export function writeActivityLog(entry: ActivityLogEntry): void {
  if (!logPath) return;
  try {
    const line = JSON.stringify(entry) + '\n';
    fs.appendFileSync(logPath, line, 'utf-8');
  } catch {
    // Swallow write errors — logging should never crash the app
    errorCount++;
  }
}

/**
 * Convenience: write a command execution entry.
 * Called from the command bus after-hook.
 */
export function logCommandExecution(
  commandType: string,
  origin: string,
  ok: boolean,
  durationMs: number,
  errorCode?: string,
  correlationId?: string,
  targetSession?: string,
): void {
  const entry: ActivityLogEntry = {
    ts: new Date().toISOString(),
    session: targetSession || 'uai_app',
    participant: 'uai_app',
    event: 'command.executed',
    payload: {
      type: commandType,
      origin,
      ok,
      duration_ms: durationMs,
      ...(errorCode ? { error_code: errorCode } : {}),
    },
    ...(correlationId ? { correlation_id: correlationId } : {}),
  };
  writeActivityLog(entry);
}

/**
 * Write a lifecycle event (app started, stopped, error, etc.).
 */
export function logLifecycleEvent(
  event: string,
  payload: Record<string, unknown> = {},
): void {
  writeActivityLog({
    ts: new Date().toISOString(),
    session: 'uai_app',
    participant: 'uai_app',
    event,
    payload,
  });
}

/**
 * Log an error or warning. Writes to BOTH the activity log (so it appears in
 * the App/Session Log tabs as an `error`/`warn` event) AND a dedicated
 * uai_errors.jsonl file, and records it in the recent-errors ring buffer
 * for the status bar. `source` is one of main|renderer|scaffolding|command.
 */
export function logError(
  source: string,
  message: string,
  opts: { session?: string; stack?: string; level?: 'error' | 'warn'; detail?: Record<string, unknown> } = {},
): void {
  const ts = new Date().toISOString();
  const session = opts.session || 'uai_app';
  const level = opts.level || 'error';
  const event = level === 'warn' ? 'app.warn' : 'app.error';

  // Truncate very long messages for the activity log
  const shortMsg = message.length > 2000 ? message.slice(0, 2000) + '…' : message;

  // 1. Activity log — visible in App Log / Session Log tabs
  writeActivityLog({
    ts,
    session,
    participant: 'uai_app',
    event,
    payload: {
      source,
      message: shortMsg,
      ...(opts.detail || {}),
    },
  });

  // 2. Dedicated error log with full detail (incl. stack)
  if (errorPath) {
    try {
      const errEntry = {
        ts, source, session, level, message,
        ...(opts.stack ? { stack: opts.stack } : {}),
        ...(opts.detail || {}),
      };
      fs.appendFileSync(errorPath, JSON.stringify(errEntry) + '\n', 'utf-8');
    } catch { /* never crash on logging */ }
  }

  // 3. Recent-errors ring buffer for the status bar
  recentErrors.push({ ts, source, session, message: shortMsg });
  if (recentErrors.length > RECENT_ERRORS_MAX) recentErrors.shift();

  if (level === 'error') errorCount++;
}

// ─── Read ─────────────────────────────────────────────────────────────────

/**
 * Read the last N entries from the activity log.
 * Returns entries in chronological order (oldest first).
 */
export async function readActivityLog(opts: {
  limit?: number;
  sessionFilter?: string;
  eventFilter?: string;
}): Promise<ActivityLogEntry[]> {
  if (!logPath || !fs.existsSync(logPath)) return [];

  const limit = opts.limit || 200;
  const entries: ActivityLogEntry[] = [];

  const fileStream = fs.createReadStream(logPath, { encoding: 'utf-8' });
  const rl = readline.createInterface({ input: fileStream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const entry: ActivityLogEntry = JSON.parse(line);
      if (opts.sessionFilter && entry.session !== opts.sessionFilter) continue;
      if (opts.eventFilter && !entry.event.startsWith(opts.eventFilter)) continue;
      entries.push(entry);
    } catch {
      // Skip malformed lines
    }
  }

  // Return last N entries
  return entries.slice(-limit);
}

/**
 * Read entries newer than a given timestamp.
 * Used for incremental tailing from the renderer.
 */
export async function tailActivityLog(sinceTs: string, limit?: number): Promise<ActivityLogEntry[]> {
  if (!logPath || !fs.existsSync(logPath)) return [];

  const maxEntries = limit || 100;
  const entries: ActivityLogEntry[] = [];

  const fileStream = fs.createReadStream(logPath, { encoding: 'utf-8' });
  const rl = readline.createInterface({ input: fileStream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const entry: ActivityLogEntry = JSON.parse(line);
      if (entry.ts > sinceTs) {
        entries.push(entry);
      }
    } catch {
      // Skip malformed lines
    }
  }

  return entries.slice(-maxEntries);
}

// ─── System Metrics ───────────────────────────────────────────────────────

/**
 * Gather basic system metrics for the System Monitor tab.
 */
function metricsAiRoot(): string {
  return process.env.AI_ROOT_MAIN || process.env.AI_ROOT || path.join(os.homedir(), 'AI/ai_root');
}

/** Read sysmon's summary.json (source of truth for memory/disk/status). */
function readSysmonSummary(): { data: any; ageSec: number } | null {
  try {
    const p = path.join(metricsAiRoot(), 'ai_general/data/system_monitoring/summary.json');
    const raw = fs.readFileSync(p, 'utf8');
    const data = JSON.parse(raw);
    const genTs = typeof data.generated_ts === 'number' ? data.generated_ts : null;
    const ageSec = genTs ? Math.max(0, (Date.now() - genTs) / 1000) : Number(data.data_freshness_sec) || 0;
    return { data, ageSec };
  } catch {
    return null;
  }
}

/** System-health stoplight — a faithful port of sysmon's `_stoplight()` so the
 *  app's overall status matches the `sysmon status` header exactly. Inputs all
 *  come from summary.json (memorystatus_level, memory.pressure/.swap_gb, alerts). */
function computeStoplight(level: number, pressure: string, swapGb: number, alerts: any[]): {
  status: 'ok' | 'warn' | 'crit' | 'unknown'; summary: string;
} {
  let status: 'ok' | 'warn' | 'crit' | 'unknown';
  if (pressure === 'critical' || (level > 0 && level < 20)) status = 'crit';
  else if (pressure === 'warn' || (level > 0 && level < 35) || swapGb > 2.0 ||
           (alerts || []).some(a => (a?.severity ?? 0) >= 4)) status = 'warn';
  else if (level === 0) status = 'unknown';
  else status = 'ok';

  const parts: string[] = [];
  if (pressure && pressure !== 'normal' && pressure !== 'unknown') parts.push(`pressure ${pressure}`);
  if (swapGb > 0.1) parts.push(`swap ${swapGb.toFixed(1)}G`);
  const memAlert = (alerts || []).some(a => /memory/.test((a?.metric || '') + (a?.rule_name || '')));
  if (memAlert && status !== 'crit') parts.push('memory rising');
  return { status, summary: parts.join(' · ') };
}

/** Active sysmon events (alerts + assessments + episode), mirroring the event
 *  block in the `sysmon status` footer.
 *
 *  Tier suppression (highest tier wins per kind): an EPISODE (a sustained incident)
 *  supersedes alerts AND assessments of the same kind; an ALERT (a fired rule)
 *  supersedes assessments of the same kind. "Kind" = the top-level metric category
 *  (memory / cpu / disk / sysmon). This collapses the common redundancy where a
 *  swap_growth episode, a swap_growth alert, and a memory assessment are all the
 *  same underlying condition. */
function readSysmonEvents(d: any): SysmonEvent[] {
  const localTs = (ms: any): string | undefined => {
    const n = Number(ms);
    if (!isFinite(n) || n <= 0) return undefined;
    try { return new Date(n).toLocaleString(); } catch { return undefined; }
  };
  // Top-level category for cross-tier matching: "memory.swap_gb" → "memory".
  const catOf = (metric: any, fallback = ''): string =>
    (String(metric ?? '').split('.')[0] || fallback).toLowerCase();

  const alerts = (d.active_alerts || []).map((a: any) => ({
    kind: 'alert' as const, severity: Number(a?.severity) || 0,
    message: a?.message || a?.rule_name || 'alert',
    since: localTs(a?.opened_ts), updated: localTs(a?.opened_ts),
    category: catOf(a?.metric, a?.rule_name),
  }));
  const assessments = (d.active_assessments || [])
    .filter((a: any) => !a?.status || a.status === 'active')
    .map((a: any) => ({
      kind: 'assessment' as const, severity: Number(a?.severity) || 0,
      message: a?.headline || a?.category || 'assessment',
      // Chronic assessments carry an old created_ts but a fresh updated_ts — show
      // BOTH so a still-live concern doesn't read as a months-old stale item.
      since: localTs(a?.created_ts), updated: localTs(a?.updated_ts),
      category: catOf(a?.category),
    }));
  const ep = d.active_episode;
  const episodes: SysmonEvent[] = [];
  if (ep) {
    const detail = ep.trigger_metric != null
      ? `${ep.episode_type} (${ep.trigger_metric}=${Number(ep.trigger_value).toFixed(1)})`
      : (ep.summary || ep.episode_type || 'episode');
    episodes.push({
      kind: 'episode', severity: Number(ep?.severity) || 0,
      message: ep.summary || detail, since: localTs(ep?.start_ts), updated: localTs(ep?.start_ts),
      category: catOf(ep?.trigger_metric, ep?.episode_type),
    });
  }

  const episodeKinds = new Set(episodes.map(e => e.category).filter(Boolean));
  // Alerts superseded by a same-kind episode drop out.
  const keptAlerts = alerts.filter((a: SysmonEvent) => !episodeKinds.has(a.category));
  const alertKinds = new Set(keptAlerts.map((a: SysmonEvent) => a.category).filter(Boolean));
  // Assessments superseded by a same-kind episode OR alert drop out.
  const keptAssessments = assessments.filter(
    (a: SysmonEvent) => !episodeKinds.has(a.category) && !alertKinds.has(a.category),
  );

  const events: SysmonEvent[] = [...episodes, ...keptAlerts, ...keptAssessments];
  // Highest-severity first so the banner-adjacent strip leads with the worst.
  events.sort((a, b) => b.severity - a.severity);
  return events;
}

/** Normalize sysmon's top_cpu/top_mem_processes rows for the CPU/Memory cards. */
function readTopProcesses(rows: any): TopProcess[] {
  if (!Array.isArray(rows)) return [];
  return rows.map((r: any) => ({
    name: String(r?.name ?? '—'),
    pid: Number(r?.pid) || 0,
    cpu_pct: Number(r?.cpu_pct) || 0,
    phys_gb: Number(r?.phys_gb) || 0,
  }));
}

/** Claude Code 5h/7d usage, bridged from the statusline via ~/.claude/rate_limits.json. */
function readClaudeUsage(): Pick<SystemMetrics, 'claude_5h_pct' | 'claude_5h_reset' | 'claude_7d_pct' | 'claude_7d_reset'> {
  try {
    const p = path.join(os.homedir(), '.claude', 'rate_limits.json');
    const d = JSON.parse(fs.readFileSync(p, 'utf8'));
    const num = (v: any) => (v == null || v === '' || isNaN(Number(v)) ? null : Number(v));
    return {
      claude_5h_pct: num(d.five_hour_pct), claude_5h_reset: d.five_hour_reset ?? null,
      claude_7d_pct: num(d.seven_day_pct), claude_7d_reset: d.seven_day_reset ?? null,
    };
  } catch {
    return {};
  }
}

export function getSystemMetrics(activeSessionCount: number): SystemMetrics {
  const mem = process.memoryUsage();
  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const cpus = os.cpus();
  const load = os.loadavg() as [number, number, number];
  const cpuPercent = Math.min(100, Math.round((load[0] / cpus.length) * 100));

  const base: SystemMetrics = {
    cpu_percent: cpuPercent,
    memory_used_mb: Math.round((totalMem - freeMem) / 1024 / 1024),
    memory_total_mb: Math.round(totalMem / 1024 / 1024),
    heap_used_mb: Math.round(mem.heapUsed / 1024 / 1024),
    heap_total_mb: Math.round(mem.heapTotal / 1024 / 1024),
    active_sessions: activeSessionCount,
    uptime_seconds: Math.round((Date.now() - startTime) / 1000),
    error_count: errorCount,
    system_uptime_seconds: Math.round(os.uptime()),
    load_avg: [load[0], load[1], load[2]],
    ...readClaudeUsage(),
  };

  const sm = readSysmonSummary();
  if (sm) {
    const d = sm.data;
    const m = d.memory || {};
    const disk = d.disk || {};
    const level = Number(d.memorystatus_level) || 0;
    const swapGb = Number(m.swap_gb) || 0;
    const light = computeStoplight(level, m.pressure || 'unknown', swapGb, d.active_alerts || []);
    // Disk % from free/total — summary.disk.used_pct is unreliable (contradicts
    // the `sysmon status` header); the header computes used from free/total.
    const dFree = Number(disk.free_gb), dTotal = Number(disk.total_gb);
    const diskUsedPct = (dTotal > 0 && !isNaN(dFree)) ? Math.round(((dTotal - dFree) / dTotal) * 100) : undefined;
    // Prefer sysmon's own CPU reading over the os.loadavg estimate so the gauge
    // matches the `sysmon status` header (all gauges are sysmon-sourced).
    const smCpu = Number(d.cpu_percent);
    Object.assign(base, {
      cpu_percent: isFinite(smCpu) ? Math.round(smCpu) : base.cpu_percent,
      cpu_avg_15m: Number(d.cpu_avg_15m) || undefined,
      cpu_avg_1h: Number(d.cpu_avg_1h) || undefined,
      cpu_avg_6h: Number(d.cpu_avg_6h) || undefined,
      sysmon_status: light.status,
      sysmon_summary: light.summary,
      sysmon_stale: sm.ageSec > 60,
      sysmon_events: readSysmonEvents(d),
      top_cpu_processes: readTopProcesses(d.top_cpu_processes),
      top_mem_processes: readTopProcesses(d.top_mem_processes),
      claude_tokens: d.claude?.tokens,
      sparks: {
        cpu: d.cpu_spark_1h,
        mem: m.spark_1h,
        swap: m.swap_spark_1h,
        disk: disk.used_spark_1h,
        claude_7d: d.claude?.rate_7d_spark_1h,
        tokens: d.claude?.tokens_spark_1h,
      },
      mem_pressure: m.pressure,
      mem_committed_gb: Number(m.committed_gb),
      mem_total_gb: Number(m.total_gb),
      mem_level: level,
      swap_gb: swapGb,
      disk_free_gb: isNaN(dFree) ? undefined : dFree,
      disk_total_gb: isNaN(dTotal) ? undefined : dTotal,
      disk_used_pct: diskUsedPct,
    });
  }
  return base;
}

/**
 * Increment the error counter (called from error handlers).
 */
export function incrementErrorCount(): void {
  errorCount++;
}
