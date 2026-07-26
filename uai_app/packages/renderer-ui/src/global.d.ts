/**
 * Global type declarations for the UAI renderer-ui package.
 *
 * Declares window.uai with the types needed by renderer components.
 * The actual runtime implementation is injected by Electron's contextBridge
 * in app/main/preload.ts.
 */

import type {
  Session,
  Command,
  CommandResult,
  StoreChangedEvent,
  RuntimeChangedEvent,
  AppState,
  FolderStoreData,
  Tag,
  EntityRelationship,
} from '@uai/shared/types';
import type { ContainerStoreData, ProjectCard, BriefCard } from '@uai/shared/cards';

interface ActivityLogEntry {
  ts: string;
  session: string;
  participant: string;
  event: string;
  payload: Record<string, unknown>;
  correlation_id?: string;
}

interface CommandLogEntry {
  command_id: string;
  type: string;
  origin: string;
  timestamp: string;
  duration_ms: number;
  ok: boolean;
  error_code?: string;
}

interface SystemMetrics {
  cpu_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  heap_used_mb: number;
  heap_total_mb: number;
  active_sessions: number;
  uptime_seconds: number;
  error_count: number;
  // sysmon-derived + Claude usage (see app/main/activity-log.ts SystemMetrics)
  sysmon_status?: 'ok' | 'warn' | 'crit' | 'unknown';
  sysmon_summary?: string;
  sysmon_stale?: boolean;
  mem_pressure?: string;
  mem_committed_gb?: number;
  mem_total_gb?: number;
  mem_level?: number;
  swap_gb?: number;
  disk_free_gb?: number;
  disk_total_gb?: number;
  disk_used_pct?: number;
  system_uptime_seconds?: number;
  load_avg?: [number, number, number];
  cpu_avg_15m?: number;
  cpu_avg_1h?: number;
  cpu_avg_6h?: number;
  top_cpu_processes?: TopProcess[];
  top_mem_processes?: TopProcess[];
  claude_tokens?: { dtd?: TokenBucket; wtd?: TokenBucket; mtd?: TokenBucket; ytd?: TokenBucket; itd?: TokenBucket };
  sparks?: Record<string, number[]>;
  sysmon_events?: SysmonEvent[];
  claude_5h_pct?: number | null;
  claude_5h_reset?: string | null;
  claude_7d_pct?: number | null;
  claude_7d_reset?: string | null;
}

/** A top resource-using process for the CPU/Memory card details. */
interface TopProcess {
  name: string;
  pid: number;
  cpu_pct: number;
  phys_gb: number;
}

/** Token counter bucket (day/month/year/inception to date). `since` = local ISO
 *  timestamp this window started counting (itd = ledger inception). */
interface TokenBucket { in: number; out: number; total: number; cost?: number; since?: string }

/** An active sysmon event (alert / assessment / episode) while it persists. */
interface SysmonEvent {
  kind: 'alert' | 'assessment' | 'episode';
  severity: number;
  message: string;
  since?: string;
  updated?: string;
  category?: string;
}

/** A mounted disk volume (from `df`), for the Disk gauge details. */
interface DiskVolume {
  mount: string;
  fs: string;
  total_gb: number;
  used_gb: number;
  free_gb: number;
  used_pct: number;
}

/** One entry in the AI awareness feed (ai_comms/feed/activity.jsonl). */
interface FeedEntry {
  ts: string;
  session: string;
  name: string;
  channel: string;
  kind: string;
  text: string;
  ref?: string[];
}

interface UaiApi {
  bootstrap(): Promise<{ sessions: Session[]; aiRoot: string }>;
  execute(command: Command): Promise<CommandResult>;
  sessions: {
    list(): Promise<Session[]>;
    get(trackingId: string): Promise<Session | null>;
    update(trackingId: string, patch: Record<string, string>): Promise<CommandResult>;
    create(opts: {
      platform: string;
      displayName?: string;
      projectDir?: string;
      roles?: string[];
      parentTrackingId?: string;
    }): Promise<CommandResult<{ trackingId: string }>>;
  };
  appState: {
    get(): Promise<Partial<AppState>>;
    update(patch: Partial<AppState>): Promise<{ ok: boolean; error?: string }>;
  };
  folders: {
    list(): Promise<FolderStoreData | null>;
  };
  containers: {
    list(): Promise<ContainerStoreData | null>;
  };
  projects: {
    list(): Promise<ProjectCard[]>;
  };
  briefs: {
    list(): Promise<BriefCard[]>;
    create(sessionIds: string | string[], opts: {
      name: string;
      description?: string;
      folder: string;
      launch?: boolean;
      launchName?: string;
      launchPlatform?: string;
      condenserSession?: string;
    }): Promise<{ ok: boolean; briefPath?: string; briefName?: string; error?: string }>;
  };
  tags: {
    list(): Promise<Tag[]>;
    forCard(cardId: string): Promise<string[]>;
  };
  relationships: {
    forEntity(entityType: string, entityId: string): Promise<EntityRelationship[]>;
  };
  activityLog: {
    read(opts: { limit?: number; sessionFilter?: string; eventFilter?: string }): Promise<ActivityLogEntry[]>;
    tail(sinceTs: string, limit?: number): Promise<ActivityLogEntry[]>;
  };
  commandLog(): Promise<CommandLogEntry[]>;
  systemMetrics(): Promise<SystemMetrics>;
  diskVolumes(): Promise<DiskVolume[]>;
  bootHistory(limit?: number): Promise<Array<{ when: string }>>;
  aiFeed: {
    read(limit?: number): Promise<FeedEntry[]>;
  };
  logError(payload: { message: string; stack?: string; session?: string; level?: 'error' | 'warn' }): Promise<{ ok: boolean }>;
  getVersion(): Promise<string>;
  getRecentErrors(limit?: number): Promise<Array<{ ts: string; source: string; session: string; level: 'error' | 'warn'; message: string }>>;
  getLastError(): Promise<{ ts: string; source: string; session: string; level: 'error' | 'warn'; message: string } | null>;
  clearErrors(): Promise<{ ok: boolean }>;
  transcript: {
    read(zellijSession: string, cliSessionId: string | undefined, format: string): Promise<{ ok: boolean; days?: unknown[]; error?: string; uuid?: string; format?: string; path?: string }>;
    stat(cliSessionId: string | undefined): Promise<{ ok: boolean; size?: number; mtimeMs?: number; path?: string; error?: string }>;
    getCached(ref: string | undefined): Promise<{ ok: boolean; days?: unknown[]; error?: string; path?: string; cached?: boolean; revision?: string }>;
    onUpdated(cb: (ref: string) => void): () => void;
  };
  comms: {
    queueList(sessionTrackingId: string): Promise<unknown[]>;
    queueCount(sessionTrackingId: string): Promise<number>;
    inboxList(sessionTrackingId: string): Promise<unknown[]>;
    archiveList(sessionTrackingId: string): Promise<unknown[]>;
    sentList(sessionTrackingId: string): Promise<unknown[]>;
    inboxCount(sessionTrackingId: string): Promise<{ total: number; unread: number }>;
    send(opts: { from: string; to: string; content: string; urgency?: string; responseType?: string; ttlSeconds?: number; replyTo?: string }): Promise<{ ok: boolean; messageId?: string; error?: string }>;
    markRead(messageId: string, reader: string): Promise<{ ok: boolean; error?: string }>;
    archive(messageId: string): Promise<{ ok: boolean; error?: string }>;
    markUnread(sessionTrackingId: string, messageId: string, reader: string): Promise<{ ok: boolean; error?: string }>;
    deleteMessage(sessionTrackingId: string, messageId: string): Promise<{ ok: boolean; error?: string }>;
    reply(messageId: string, from: string, content: string): Promise<{ ok: boolean; error?: string }>;
    queueHold(sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }>;
    queueRelease(sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }>;
    queueChangeDelivery(sessionTrackingId: string, entryId: string, delivery: string): Promise<{ ok: boolean }>;
    queueRemove(sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }>;
    lockStatus(sessionTrackingId: string): Promise<boolean>;
    lockSet(sessionTrackingId: string, reason?: string): Promise<{ ok: boolean }>;
    lockRemove(sessionTrackingId: string): Promise<{ ok: boolean }>;
    conversations(opts?: { status?: string; participants?: string[]; linkedWork?: string; needsInput?: boolean; limit?: number; offset?: number; order?: string }): Promise<Array<{ id: string; topic: string; status: string; needs_input: boolean; participants: string[]; last_activity: string; created_at: string; linked_work: unknown; message_count: number; last_message_preview: string }>>;
    conversation(id: string): Promise<{ conversation: Record<string, unknown>; messages: Array<Record<string, unknown>>; deliveries: Array<Record<string, unknown>>; obligations: Array<Record<string, unknown>> } | null>;
    view(box: 'inbox' | 'sent' | 'archive', entityId: string, opts?: { limit?: number; offset?: number }): Promise<Array<Record<string, unknown>>>;
  };
  traits: {
    list(sessionId: string): Promise<Array<{ type: string; name: string; loaded: boolean; src?: string; filePath?: string }>>;
    load(sessionId: string, items: Array<{ type: string; name: string }>): Promise<{ success: boolean; results: Array<{ type: string; name: string; success: boolean; error?: string }> }>;
    status(sessionId: string): Promise<{ loaded: number; available: number; types: Record<string, { loaded: number; available: number }> } | null>;
    openFile(filePath: string): Promise<{ ok: boolean; error?: string }>;
  };
  traitMgr: {
    run(command: string, args?: string[]): Promise<{ ok: boolean; data?: any; errors?: string; error?: string }>;
  };
  context: {
    run(verb: string, args?: string[]): Promise<{ ok: boolean; data?: any; error?: string }>;
  };
  gitFileView: {
    read(dir: string, since?: string, until?: string): Promise<unknown>;
    commit(dir: string, commitHash: string): Promise<unknown>;
    diff(dir: string, file: string, fromHash: string, toHash: string): Promise<unknown>;
    content(dir: string, file: string, ref: string): Promise<unknown>;
    repos(root: string): Promise<unknown>;
    grep(dir: string, pattern: string, toRef?: string): Promise<unknown>;
  };
  fs: {
    listDir(dirPath: string, opts?: { dirsOnly?: boolean; showHidden?: boolean }): Promise<Array<{ name: string; path: string; type: 'file' | 'directory'; size: number | null; modified: string | null }>>;
    readFile(filePath: string): Promise<{ ok: boolean; content?: string; truncated?: boolean; error?: string }>;
  };
  git: {
    filesForTodos: (todoIds: string[]) => Promise<string[]>;
  };
  notes: {
    forWorker: (names: string[]) => Promise<Array<{ id: string; title: string; status: string }>>;
  };
  todos: {
    // Full hierarchical contract from todo_mgr json: id, ref, rel_path, parent,
    // children[], assigned[], project, status, tags[], flags[], title,
    // summary — plus dirName (leaf basename) + name (=id) for back-compat.
    list(includeFinalized?: boolean): Promise<Array<{
      id: string; ref?: string; name: string; dirName: string; path?: string; rel_path?: string;
      status: string; tags: string[]; flags: string[]; assigned?: string[];
      project?: string | null;
      parent?: string | null; children?: string[]; title?: string; summary?: string;
    }>>;
    read(id: string): Promise<string>;
    // Mutations route through the Command Bus (window.uai.execute 'todo.*'), not IPC.
    open(id: string): Promise<{ ok: boolean; error?: string }>;
    data(id: string): Promise<Array<{ name: string; path: string; size: number }>>;
    openData(id: string, fileName: string): Promise<{ ok: boolean; error?: string }>;
    provenance(id: string): Promise<{ origin: Record<string, string>; history: Array<{ ts: string; status: string; session: string; note: string }> }>;
    files(id: string): Promise<Array<{ rel: string; size: number; isDir: boolean }>>;
    readFile(id: string, rel: string): Promise<{ ok: boolean; content?: string; truncated?: boolean; error?: string }>;
  };
  tasks: {
    list(opts?: { platform?: string; status?: string }): Promise<Array<{ task_id: string; status: string; platform: string; template?: string; description?: string; created?: string }>>;
  };
  prompts: {
    getPromptAreas(): Promise<Array<{ tracking_id: string; session_name: string; platform: string; terminal_session: string; prompt_text: string }>>;
  };
  search(query: string, opts?: { limit?: number; caseSensitive?: boolean; sessionFilter?: string; regex?: boolean; deduplicate?: boolean }): Promise<any[]>;
  searchGrouped(query: string, opts?: { limit?: number; caseSensitive?: boolean; sessionFilter?: string; regex?: boolean; deduplicate?: boolean }): Promise<{
    results: Array<{
      sessionId: string;
      sessionName: string | null;
      filePath: string;
      projectSlug: string;
      matchCount: number;
      matches: Array<{
        lineNumber: number;
        messageType: string;
        content: string;
        matchText: string;
        matchStart?: number;
        matchEnd?: number;
        timestamp: string;
      }>;
    }>;
    totalMatches: number;
    sessionsSearched: number;
    searchTimeMs: number;
  }>;
  assignedTasks: {
    load(): Promise<{ version: number; lastScanAt: string | null; tasks: Array<{
      id: string; summary: string; details: string; decisions: string[];
      sourcePrompts: Array<{ ts: string; preview: string; sessionName: string }>;
      status: string; statusSource: 'scan' | 'user';
      sessionId: string; sessionName: string; platform: string;
      assignedDate: string; confidence: number; dismissed: boolean; userNotes: string;
      scanMeta: { scannedAt: string; engine: string; daysBack: number };
    }> }>;
    scan(opts: { engine: string; daysBack: number }): Promise<{ version: number; lastScanAt: string | null; tasks: any[] }>;
    cancelScan(): Promise<{ ok: boolean }>;
    isScanning(): Promise<boolean>;
    updateTask(taskId: string, patch: { status?: string; dismissed?: boolean; userNotes?: string }): Promise<{ version: number; lastScanAt: string | null; tasks: any[] }>;
    onProgress(callback: (progress: { phase: string; current: number; total: number; message: string }) => void): () => void;
  };
  scheduledTasks: {
    listGroups(): Promise<Array<{ name: string; description?: string; enabled: boolean; jobCount: number }>>;
    viewGroup(group: string): Promise<{
      name: string; description?: string; enabled: boolean;
      env: Record<string, string>;
      jobs: Array<{ id: string; description: string; schedule: string; command: string; log?: string; background?: boolean }>;
    } | null>;
    getStatus(): Promise<{
      groups: Array<{
        name: string;
        jobs: Array<{
          id: string;
          schedule: string;
          label: string;
          installed: boolean;
          enabled: boolean;
          once?: boolean;
          lastRun: { label?: string; exit: number; ts: string } | null;
          nextFire: string | null;
          state: string;
        }>;
      }>;
      sync: { inSync: boolean; missing: string[]; extra: string[] };
      errors: string[];
    }>;
    getLiveCrontab(): Promise<string>;
    getLogTail(group: string, jobId: string, lines?: number): Promise<string>;
    enableGroup(group: string): Promise<{ ok: boolean; error?: string }>;
    disableGroup(group: string): Promise<{ ok: boolean; error?: string }>;
    createGroup(opts: {
      name: string; description?: string;
      firstJob: { id: string; schedule: string; command: string; description?: string; log?: string; background?: boolean };
    }): Promise<{ ok: boolean; error?: string }>;
    addJob(group: string, job: { id: string; schedule: string; command: string; description?: string; log?: string; background?: boolean }): Promise<{ ok: boolean; error?: string }>;
    editGroup(group: string, patch: { description?: string; enabled?: boolean }): Promise<{ ok: boolean; error?: string }>;
    editJob(group: string, jobId: string, patch: { schedule?: string; command?: string; description?: string; log?: string; background?: boolean }): Promise<{ ok: boolean; error?: string }>;
    deleteGroup(group: string): Promise<{ ok: boolean; error?: string }>;
    deleteJob(group: string, jobId: string): Promise<{ ok: boolean; error?: string }>;
    install(): Promise<{ ok: boolean; error?: string }>;
    reinstallGroup(group: string): Promise<{ ok: boolean; error?: string }>;
    dryRun(): Promise<{ ok: boolean; preview: string; error?: string }>;
    bootstrap(): Promise<{ ok: boolean; error?: string }>;
    runJob(group: string, jobId: string): Promise<{ ok: boolean; exitCode: number; stdout: string; stderr: string; error?: string }>;
  };
  mcp: {
    list(): Promise<Array<{ name: string; command: string; args?: string[]; status?: string; error?: string; tools: Array<{ name: string; fullName: string; description?: string; inputSchema?: any }> }>>;
    readConfigFile(serverName: string): Promise<{ filePath: string; shortPath: string; content: string } | null>;
    listServerFiles(serverName: string): Promise<Array<{ name: string; size: number; path: string }>>;
    readServerFile(filePath: string): Promise<string>;
  };
  openPath(filePath: string): Promise<{ ok: boolean; error?: string }>;
  openUrl(url: string): Promise<{ ok: boolean; error?: string }>;
  globals: {
    list(): Promise<Array<{ name: string; path: string; ext: string }>>;
  };
  news: {
    list(): Promise<Array<{ type: 'news' | 'report'; name: string; path: string; size: number; modified: string; kind?: string; relPath?: string; isDir?: boolean }>>;
    readState(): Promise<string[]>;
    mark(paths: string[], read: boolean): Promise<{ ok: boolean; error?: string }>;
  };
  clipboard: {
    write(text: string): Promise<{ success: boolean }>;
    read(): Promise<string>;
    saveImageToTemp(): Promise<string | null>;
  };
  dialog?: {
    showOpenDirectory(defaultPath?: string): Promise<string | null>;
    showOpenFile(defaultPath?: string): Promise<string[] | null>;
  };
  terminal: {
    attach(sessionId: string, terminalSession: string, cols: number, rows: number): Promise<void>;
    input(sessionId: string, data: string): void;
    resize(sessionId: string, cols: number, rows: number): void;
    detach(sessionId: string): Promise<void>;
    onData(callback: (sessionId: string, data: string) => void): () => void;
    onExit(callback: (sessionId: string, exitCode: number) => void): () => void;
    captureScrollback(sessionName: string, lines?: number): Promise<{ ok: boolean; text?: string; error?: string }>;
  };
  standaloneTerminal: {
    create(id: string, cols: number, rows: number, cwd?: string): Promise<{ reattached: boolean }>;
    input(id: string, data: string): void;
    resize(id: string, cols: number, rows: number): void;
    close(id: string): Promise<void>;
    onData(callback: (id: string, data: string) => void): () => void;
    onExit(callback: (id: string, exitCode: number) => void): () => void;
  };
  onStoreChanged(callback: (event: StoreChangedEvent) => void): () => void;
  onRuntimeChanged(callback: (event: RuntimeChangedEvent) => void): () => void;
}

declare global {
  interface Window {
    uai: UaiApi;
  }
}

export {};
