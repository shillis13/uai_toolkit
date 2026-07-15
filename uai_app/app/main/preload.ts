/**
 * UAI Preload — exposes typed IPC bridge to renderer.
 *
 * The renderer never calls IPC directly. It calls typed methods on window.uai.
 * This is the only bridge between renderer and main process.
 *
 * Phase 1 additions:
 *   - execute(command) — routes domain mutations through CommandBus
 *   - appState.get/update — AppStateStore IPC
 *   - folders.list — FolderStore IPC
 */

import { contextBridge, ipcRenderer } from 'electron';
import { IPC } from '@uai/shared/types';
import type {
  Session,
  Command,
  CommandResult,
  StoreChangedEvent,
  RuntimeChangedEvent,
  DeepLinkEvent,
  AppState,
  FolderStoreData,
  Tag,
  EntityRelationship,
} from '@uai/shared/types';
import type { ContainerStoreData, ProjectCard, TeamCard, BriefCard } from '@uai/shared/cards';
import type { QueueEntry, InboxMessage } from '@uai/shared/types';

// ── Scheduled Tasks types ─────────────────────────────────────────────────

interface ScheduledJob {
  id: string;
  description: string;
  schedule: string;
  command: string;
  log?: string;
  background?: boolean;
}

interface ScheduledGroup {
  name: string;
  description?: string;
  enabled: boolean;
  jobCount: number;
}

interface ScheduledGroupDetail {
  name: string;
  description?: string;
  enabled: boolean;
  env: Record<string, string>;
  jobs: ScheduledJob[];
}

interface ScheduledTaskRun {
  label?: string;
  exit: number;
  ts: string;
}

interface ScheduledStatusJob {
  id: string;
  schedule: string;
  label: string;
  installed: boolean;
  enabled: boolean;
  once?: boolean;
  lastRun: ScheduledTaskRun | null;
  nextFire: string | null;
  state: string;
}

interface ScheduledStatusGroup {
  name: string;
  jobs: ScheduledStatusJob[];
}

interface ScheduledTasksStatus {
  groups: ScheduledStatusGroup[];
  sync: { inSync: boolean; missing: string[]; extra: string[] };
  errors: string[];
}

interface MutationResult {
  ok: boolean;
  error?: string;
}

interface RunJobResult {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
  error?: string;
}

interface CreateGroupOpts {
  name: string;
  description?: string;
  firstJob: {
    id: string;
    schedule: string;
    command: string;
    description?: string;
    log?: string;
    background?: boolean;
  };
}

interface JobDefinition {
  id: string;
  schedule: string;
  command: string;
  description?: string;
  log?: string;
  background?: boolean;
}

interface GroupPatch {
  description?: string;
  enabled?: boolean;
}

interface JobPatch {
  schedule?: string;
  command?: string;
  description?: string;
  log?: string;
  background?: boolean;
}

// ─── Session Store Manager Types ──────────────────────────────────────────

export interface SessionStoreRecord {
  tracking_id: string;
  terminal_session: string | null;
  cli_session_id: string | null;
  platform: string;
  session_dir: string;
  project_dir: string;
  display_name: string | null;
  model: string | null;
  substrate: string | null;
  tmux_server: string | null;
  roles: string | string[] | null;
  notes: string | null;
  status: string;
  identity_status: string;
  created_at: string;
  archived: boolean | number;
  last_activity: string | null;
  parent_tracking_id?: string | null;
  history_file?: string | null;
  tags?: string[];
}

export interface ChangeLogEntry {
  id?: number;
  tracking_id: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
  changed_by: string | null;
  pid?: number | null;
}

export interface ValidationResult {
  stale?: Array<{ tracking_id: string; display_name?: string; status?: string; last_activity?: string }>;
  fixed?: Array<{ tracking_id: string; action: string }>;
  orphans?: Array<{ tracking_id: string; display_name?: string; reason?: string }>;
  message?: string;
}

// Types for activity/command log and metrics (used by preload API)
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

interface TopProcess {
  name: string; pid: number; cpu_pct: number; phys_gb: number;
}

interface TokenBucket { in: number; out: number; total: number; cost?: number; since?: string }

interface SysmonEvent {
  kind: 'alert' | 'assessment' | 'episode';
  severity: number;
  message: string;
  since?: string;
  updated?: string;
  category?: string;
}

interface DiskVolume {
  mount: string; fs: string; total_gb: number; used_gb: number; free_gb: number; used_pct: number;
}

interface FeedEntry {
  ts: string; session: string; name: string; channel: string; kind: string; text: string; ref?: string[];
}

const uaiApi = {
  // ── Bootstrap ────────────────────────────────────────────────────────
  bootstrap: (): Promise<{ sessions: Session[]; aiRoot: string }> =>
    ipcRenderer.invoke(IPC.BOOTSTRAP),

  // ── Command Bus (Path 1: all domain mutations) ──────────────────────
  execute: (command: Command): Promise<CommandResult> =>
    ipcRenderer.invoke(IPC.COMMAND_EXECUTE, command),

  // ── Session Queries ──────────────────────────────────────────────────
  sessions: {
    list: (): Promise<Session[]> =>
      ipcRenderer.invoke(IPC.SESSION_LIST),
    get: (trackingId: string): Promise<Session | null> =>
      ipcRenderer.invoke(IPC.SESSION_GET, trackingId),
    // Legacy: still works, internally routes through command bus
    update: (trackingId: string, patch: Record<string, string>): Promise<CommandResult> =>
      ipcRenderer.invoke(IPC.SESSION_UPDATE, trackingId, patch),
    create: (opts: {
      platform: string;
      displayName?: string;
      projectDir?: string;
      roles?: string[];
      parentTrackingId?: string;
    }): Promise<CommandResult<{ trackingId: string }>> =>
      ipcRenderer.invoke(IPC.SESSION_CREATE, opts),
  },

  // ── App State ────────────────────────────────────────────────────────
  appState: {
    get: (): Promise<Partial<AppState>> =>
      ipcRenderer.invoke(IPC.APP_STATE_GET),
    update: (patch: Partial<AppState>): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke(IPC.APP_STATE_UPDATE, patch),
  },

  // ── Folders ──────────────────────────────────────────────────────────
  folders: {
    list: (): Promise<FolderStoreData | null> =>
      ipcRenderer.invoke(IPC.FOLDER_LIST),
  },

  // ── Containers (generic — includes folders + groups) ────────────────
  containers: {
    list: (): Promise<ContainerStoreData | null> =>
      ipcRenderer.invoke(IPC.CONTAINER_LIST),
  },

  // ── Projects ─────────────────────────────────────────────────────────
  projects: {
    list: (): Promise<ProjectCard[]> =>
      ipcRenderer.invoke(IPC.PROJECT_LIST),
  },

  // ── Teams ────────────────────────────────────────────────────────────
  teams: {
    list: (): Promise<TeamCard[]> =>
      ipcRenderer.invoke(IPC.TEAM_LIST),
  },

  // ── Briefs ──────────────────────────────────────────────────────────
  briefs: {
    list: (): Promise<BriefCard[]> =>
      ipcRenderer.invoke(IPC.BRIEF_LIST),
    create: (sessionIds: string | string[], opts: {
      name: string;
      description?: string;
      folder: string;
      launch?: boolean;
      launchName?: string;
      launchPlatform?: string;
      condenserSession?: string;
    }): Promise<{ ok: boolean; briefPath?: string; briefName?: string; error?: string }> =>
      ipcRenderer.invoke(IPC.BRIEF_CREATE, sessionIds, opts),
  },

  // ── Tags ────────────────────────────────────────────────────────────
  tags: {
    list: (): Promise<Tag[]> =>
      ipcRenderer.invoke(IPC.TAGS_LIST),
    forCard: (cardId: string): Promise<string[]> =>
      ipcRenderer.invoke(IPC.TAGS_FOR_CARD, cardId),
  },

  // ── Relationships ───────────────────────────────────────────────────
  relationships: {
    forEntity: (entityType: string, entityId: string): Promise<EntityRelationship[]> =>
      ipcRenderer.invoke(IPC.RELATIONSHIPS_FOR_ENTITY, entityType, entityId),
  },

  // ── Comms — Prompt Queue + Inbox (2L) ────────────────────────────────
  comms: {
    queueList: (sessionTrackingId: string): Promise<QueueEntry[]> =>
      ipcRenderer.invoke(IPC.COMMS_QUEUE_LIST, sessionTrackingId),
    queueCount: (sessionTrackingId: string): Promise<number> =>
      ipcRenderer.invoke(IPC.COMMS_QUEUE_COUNT, sessionTrackingId),
    inboxList: (sessionTrackingId: string): Promise<InboxMessage[]> =>
      ipcRenderer.invoke(IPC.COMMS_INBOX_LIST, sessionTrackingId),
    archiveList: (sessionTrackingId: string): Promise<InboxMessage[]> =>
      ipcRenderer.invoke('uai:comms:archive:list', sessionTrackingId),
    sentList: (sessionTrackingId: string): Promise<InboxMessage[]> =>
      ipcRenderer.invoke('uai:comms:sent:list', sessionTrackingId),
    inboxCount: (sessionTrackingId: string): Promise<{ total: number; unread: number }> =>
      ipcRenderer.invoke(IPC.COMMS_INBOX_COUNT, sessionTrackingId),
    send: (opts: { from: string; to: string; content: string; urgency?: string; responseType?: string; ttlSeconds?: number; replyTo?: string }): Promise<{ ok: boolean; messageId?: string; error?: string }> =>
      ipcRenderer.invoke('uai:comms:send', opts),
    markRead: (messageId: string, reader: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:comms:read', messageId, reader),
    archive: (messageId: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:comms:archive', messageId),
    markUnread: (sessionTrackingId: string, messageId: string, reader: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:comms:markUnread', sessionTrackingId, messageId, reader),
    deleteMessage: (sessionTrackingId: string, messageId: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:comms:delete', sessionTrackingId, messageId),
    reply: (messageId: string, from: string, content: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:comms:reply', messageId, from, content),
    queueHold: (sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:queue:hold', sessionTrackingId, entryId),
    queueRelease: (sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:queue:release', sessionTrackingId, entryId),
    queueChangeDelivery: (sessionTrackingId: string, entryId: string, delivery: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:queue:changeDelivery', sessionTrackingId, entryId, delivery),
    queueRemove: (sessionTrackingId: string, entryId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:queue:remove', sessionTrackingId, entryId),
    lockStatus: (sessionTrackingId: string): Promise<boolean> =>
      ipcRenderer.invoke('uai:comms:lock:status', sessionTrackingId),
    lockSet: (sessionTrackingId: string, reason?: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:lock:set', sessionTrackingId, reason),
    lockRemove: (sessionTrackingId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:comms:lock:remove', sessionTrackingId),
    // ── Conversations/messages read CLI (comms_index.py via uai:comms:index) ──
    conversations: (opts?: { status?: string; participants?: string[]; linkedWork?: string; needsInput?: boolean; limit?: number; offset?: number; order?: string }): Promise<any[]> => {
      const a: string[] = [];
      if (opts?.status) a.push('--status', opts.status);
      (opts?.participants || []).forEach(p => a.push('--participant', p));
      if (opts?.linkedWork) a.push('--linked-work', opts.linkedWork);
      if (opts?.needsInput) a.push('--needs-input');
      if (opts?.limit != null) a.push('--limit', String(opts.limit));
      if (opts?.offset != null) a.push('--offset', String(opts.offset));
      if (opts?.order) a.push('--order', opts.order);
      return ipcRenderer.invoke('uai:comms:index', 'conversations', a);
    },
    conversation: (id: string): Promise<any> =>
      ipcRenderer.invoke('uai:comms:index', 'conversation', [id]),
    view: (box: 'inbox' | 'sent' | 'archive', entityId: string, opts?: { limit?: number; offset?: number }): Promise<any[]> => {
      const a: string[] = [box, entityId];
      if (opts?.limit != null) a.push('--limit', String(opts.limit));
      if (opts?.offset != null) a.push('--offset', String(opts.offset));
      return ipcRenderer.invoke('uai:comms:index', 'view', a);
    },
  },

  // ── Traits — Session context browser ────────────────────────────────
  traits: {
    list: (sessionId: string): Promise<Array<{ type: string; name: string; loaded: boolean; src?: string; filePath?: string }>> =>
      ipcRenderer.invoke('traits:list', sessionId),
    load: (sessionId: string, items: Array<{ type: string; name: string }>): Promise<{ success: boolean; results: Array<{ type: string; name: string; success: boolean; error?: string }> }> =>
      ipcRenderer.invoke('traits:load', sessionId, items),
    status: (sessionId: string): Promise<{ loaded: number; available: number; types: Record<string, { loaded: number; available: number }> } | null> =>
      ipcRenderer.invoke('traits:status', sessionId),
    openFile: (filePath: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('traits:openFile', filePath),
  },

  // ── Trait Manager ───────────────────────────────────────────────────
  traitMgr: {
    run: (command: string, args?: string[]): Promise<{ ok: boolean; data?: any; errors?: string; error?: string }> =>
      ipcRenderer.invoke('uai:traitMgr:run', command, args || []),
  },

  // ── Context Manager (read-only verbs) ───────────────────────────────
  context: {
    run: (verb: string, args?: string[]): Promise<{ ok: boolean; data?: any; error?: string }> =>
      ipcRenderer.invoke('uai:context:run', verb, args),
  },
  gitFileView: {
    read: (dir: string, since?: string, until?: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:read', dir, since, until),
    commit: (dir: string, commitHash: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:commit', dir, commitHash),
    diff: (dir: string, file: string, fromHash: string, toHash: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:diff', dir, file, fromHash, toHash),
    content: (dir: string, file: string, ref: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:content', dir, file, ref),
    repos: (root: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:repos', root),
    grep: (dir: string, pattern: string, toRef?: string): Promise<any> =>
      ipcRenderer.invoke('uai:gitFileView:grep', dir, pattern, toRef),
  },

  // ── Globals (context files) ────────────────────────────────────────
  globals: {
    list: (): Promise<Array<{ name: string; path: string; ext: string }>> =>
      ipcRenderer.invoke('uai:globals:list'),
  },

  // ── Filesystem — lazy dir listing for project file/doc trees (todo_0317) ──
  fs: {
    listDir: (dirPath: string, opts?: { dirsOnly?: boolean; showHidden?: boolean }): Promise<Array<{ name: string; path: string; type: 'file' | 'directory'; size: number | null; modified: string | null }>> =>
      ipcRenderer.invoke('uai:fs:listDir', dirPath, opts),
    // Read a text file by absolute path — backs the in-app markdown/document tab.
    readFile: (filePath: string): Promise<{ ok: boolean; content?: string; truncated?: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:fs:readFile', filePath),
  },

  // ── Todo Manager ───────────────────────────────────────────────────
  git: {
    // Files modified for a set of todos, via the `Todo:` commit trailer (todo_0417).
    filesForTodos: (todoIds: string[]): Promise<string[]> =>
      ipcRenderer.invoke('uai:git:filesForTodos', todoIds),
  },
  notes: {
    // Notes this worker is tagged on, by name/id (todo_0419).
    forWorker: (names: string[]): Promise<Array<{ id: string; title: string; status: string }>> =>
      ipcRenderer.invoke('uai:notes:forWorker', names),
  },
  todos: {
    // Full hierarchical contract from todo_mgr json (see docs/designs/work_mgr.md).
    list: (includeFinalized?: boolean): Promise<Array<{
      id: string; ref?: string; name: string; dirName: string; path?: string; rel_path?: string;
      status: string; tags: string[]; flags: string[]; assigned?: string[];
      project?: string | null;
      parent?: string | null; children?: string[]; title?: string; summary?: string;
    }>> =>
      ipcRenderer.invoke('uai:todos:list', includeFinalized),
    read: (id: string): Promise<string> =>
      ipcRenderer.invoke('uai:todos:read', id),
    // Mutations (setStatus/move/assign/unassign/tag/create/writeNotes) route
    // through the Command Bus via window.uai.execute('todo.*') — not IPC.
    open: (id: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:todos:open', id),
    data: (id: string): Promise<Array<{ name: string; path: string; size: number }>> =>
      ipcRenderer.invoke('uai:todos:data', id),
    openData: (id: string, fileName: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:todos:openData', id, fileName),
    provenance: (id: string): Promise<{ origin: Record<string, string>; history: Array<{ ts: string; status: string; session: string; note: string }> }> =>
      ipcRenderer.invoke('uai:todos:provenance', id),
    files: (id: string): Promise<Array<{ rel: string; size: number; isDir: boolean }>> =>
      ipcRenderer.invoke('uai:todos:files', id),
    readFile: (id: string, rel: string): Promise<{ ok: boolean; content?: string; truncated?: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:todos:readFile', id, rel),
  },

  // ── Task Manager ──────────────────────────────────────────────────
  tasks: {
    list: (opts?: { platform?: string; status?: string }): Promise<Array<{ id: string; task_id?: string; status: string; platform: string; file?: string; path?: string; template?: string; description?: string; created?: string }>> =>
      ipcRenderer.invoke('uai:tasks:list', opts),
  },

  // ── MCP Server Discovery & Manager ─────────────────────────────────
  mcp: {
    list: (): Promise<Array<{ name: string; command: string; args?: string[]; status?: string; error?: string; tools: Array<{ name: string; fullName: string; description?: string; inputSchema?: any }> }>> =>
      ipcRenderer.invoke('uai:mcp:list'),
    readConfigFile: (serverName: string): Promise<{ filePath: string; shortPath: string; content: string } | null> =>
      ipcRenderer.invoke('uai:mcp:readConfigFile', serverName),
    listServerFiles: (serverName: string): Promise<Array<{ name: string; size: number; path: string }>> =>
      ipcRenderer.invoke('uai:mcp:listServerFiles', serverName),
    readServerFile: (filePath: string): Promise<string> =>
      ipcRenderer.invoke('uai:mcp:readServerFile', filePath),
  },

  // ── Search ──────────────────────────────────────────────────────────
  search: (query: string, opts?: { limit?: number; caseSensitive?: boolean; sessionFilter?: string; regex?: boolean; deduplicate?: boolean; includeSubagents?: boolean }): Promise<any[]> =>
    ipcRenderer.invoke('uai:search', query, opts),
  searchGrouped: (query: string, opts?: { limit?: number; caseSensitive?: boolean; sessionFilter?: string; regex?: boolean; deduplicate?: boolean; includeSubagents?: boolean }): Promise<{
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
  }> => ipcRenderer.invoke('uai:search:grouped', query, opts),

  // ── Activity Log + Metrics (1D) ──────���──────────────────────────────
  activityLog: {
    read: (opts: { limit?: number; sessionFilter?: string; eventFilter?: string }): Promise<ActivityLogEntry[]> =>
      ipcRenderer.invoke('uai:activityLog:read', opts),
    tail: (sinceTs: string, limit?: number): Promise<ActivityLogEntry[]> =>
      ipcRenderer.invoke('uai:activityLog:tail', sinceTs, limit),
  },

  commandLog: (): Promise<CommandLogEntry[]> =>
    ipcRenderer.invoke('uai:commandLog'),

  systemMetrics: (): Promise<SystemMetrics> =>
    ipcRenderer.invoke('uai:systemMetrics'),

  // On-demand mounted-volume list for the Disk gauge details (runs `df`).
  diskVolumes: (): Promise<DiskVolume[]> =>
    ipcRenderer.invoke('uai:diskVolumes'),

  bootHistory: (limit?: number): Promise<Array<{ when: string }>> =>
    ipcRenderer.invoke('uai:bootHistory', limit),

  aiFeed: {
    read: (limit?: number): Promise<FeedEntry[]> =>
      ipcRenderer.invoke('uai:aiFeed:read', limit),
  },

  // ── Transcript ───────────────────────────────────────────────────────
  transcript: {
    read: (zellijSession: string, cliSessionId: string | undefined, format: string): Promise<{ ok: boolean; days?: unknown[]; error?: string; uuid?: string; format?: string; path?: string }> =>
      ipcRenderer.invoke('transcript:read', zellijSession, cliSessionId, format),
    history: (cliSessionId: string): Promise<{ ok: boolean; messages: Array<{ role: string; content: string; timestamp?: string }>; error?: string }> =>
      ipcRenderer.invoke('transcript:history', cliSessionId),
  },

  // ── File Tail ────────────────────────────────────────────────────────
  logTail: {
    start: (tailId: string, filePath: string): Promise<{ ok: boolean; lines: string[]; error?: string }> =>
      ipcRenderer.invoke('log:tail:start', tailId, filePath),
    stop: (tailId: string): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('log:tail:stop', tailId),
    onData: (callback: (tailId: string, lines: string[]) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, tailId: string, lines: string[]) => callback(tailId, lines);
      ipcRenderer.on('log:tail:data', handler);
      return () => ipcRenderer.removeListener('log:tail:data', handler);
    },
  },

  // ── Scheduled Tasks ──────────────────────────────────────────────────
  scheduledTasks: {
    listGroups: (): Promise<ScheduledGroup[]> =>
      ipcRenderer.invoke('uai:scheduledTasks:listGroups'),
    viewGroup: (group: string): Promise<ScheduledGroupDetail | null> =>
      ipcRenderer.invoke('uai:scheduledTasks:viewGroup', group),
    getStatus: (): Promise<ScheduledTasksStatus> =>
      ipcRenderer.invoke('uai:scheduledTasks:getStatus'),
    getLogTail: (group: string, jobId: string, lines?: number): Promise<string> =>
      ipcRenderer.invoke('uai:scheduledTasks:getLogTail', group, jobId, lines),
    enableGroup: (group: string): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:enableGroup', group),
    disableGroup: (group: string): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:disableGroup', group),
    createGroup: (opts: CreateGroupOpts): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:createGroup', opts),
    addJob: (group: string, job: JobDefinition): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:addJob', group, job),
    editGroup: (group: string, patch: GroupPatch): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:editGroup', group, patch),
    editJob: (group: string, jobId: string, patch: JobPatch): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:editJob', group, jobId, patch),
    deleteGroup: (group: string): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:deleteGroup', group),
    deleteJob: (group: string, jobId: string): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:deleteJob', group, jobId),
    install: (): Promise<MutationResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:install'),
    dryRun: (): Promise<{ ok: boolean; preview: string; error?: string }> =>
      ipcRenderer.invoke('uai:scheduledTasks:dryRun'),
    runJob: (group: string, jobId: string): Promise<RunJobResult> =>
      ipcRenderer.invoke('uai:scheduledTasks:runJob', group, jobId),
  },

  // ── Assigned Tasks ───────────────────────────────────────────────────
  assignedTasks: {
    load: (): Promise<any> =>
      ipcRenderer.invoke('uai:assignedTasks:load'),
    scan: (opts: { engine: string; daysBack: number }): Promise<any> =>
      ipcRenderer.invoke('uai:assignedTasks:scan', opts),
    cancelScan: (): Promise<{ ok: boolean }> =>
      ipcRenderer.invoke('uai:assignedTasks:cancelScan'),
    isScanning: (): Promise<boolean> =>
      ipcRenderer.invoke('uai:assignedTasks:isScanning'),
    updateTask: (taskId: string, patch: { status?: string; dismissed?: boolean; userNotes?: string }): Promise<any> =>
      ipcRenderer.invoke('uai:assignedTasks:updateTask', taskId, patch),
    onProgress: (callback: (progress: any) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, progress: any) => callback(progress);
      ipcRenderer.on('uai:assignedTasks:progress', handler);
      return () => ipcRenderer.removeListener('uai:assignedTasks:progress', handler);
    },
    onScanComplete: (callback: (result: any) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, result: any) => callback(result);
      ipcRenderer.on('uai:assignedTasks:scanComplete', handler);
      return () => ipcRenderer.removeListener('uai:assignedTasks:scanComplete', handler);
    },
  },

  // ── Session Store Manager ────────────────────────────────────────────
  sessionStore: {
    list: (opts?: { text?: string; status?: string; platform?: string }): Promise<SessionStoreRecord[]> =>
      ipcRenderer.invoke('uai:sessionStore:list', opts),
    update: (trackingId: string, fields: Record<string, string | null>): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:update', trackingId, fields),
    history: (trackingId: string, opts?: { limit?: number }): Promise<ChangeLogEntry[]> =>
      ipcRenderer.invoke('uai:sessionStore:history', trackingId, opts),
    stateList: (trackingId: string, prefix?: string): Promise<Record<string, unknown>> =>
      ipcRenderer.invoke('uai:sessionStore:stateList', trackingId, prefix),
    stateSet: (trackingId: string, key: string, value: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:stateSet', trackingId, key, value),
    stateDelete: (trackingId: string, key: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:stateDelete', trackingId, key),
    addTag: (trackingId: string, tag: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:addTag', trackingId, tag),
    removeTag: (trackingId: string, tag: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:removeTag', trackingId, tag),
    findOrphans: (): Promise<SessionStoreRecord[]> =>
      ipcRenderer.invoke('uai:sessionStore:findOrphans'),
    validateRunning: (fix?: boolean): Promise<ValidationResult> =>
      ipcRenderer.invoke('uai:sessionStore:validateRunning', fix),
    delete: (trackingId: string): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:sessionStore:delete', trackingId),
  },

  // ── Clipboard ────────────────────────────────────────────────────────
  clipboard: {
    write: (text: string): Promise<{ success: boolean }> =>
      ipcRenderer.invoke('clipboard:write', text),
    read: (): Promise<string> =>
      ipcRenderer.invoke('clipboard:read'),
    // Save a clipboard image (if any) to a temp PNG; returns its path or null.
    saveImageToTemp: (): Promise<string | null> =>
      ipcRenderer.invoke('uai:clipboard:saveImage'),
  },

  // ── Shell ───────────────────────────────────────────────────────────
  openPath: (filePath: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke('uai:openPath', filePath),
  // Open a web URL in a new tab of the topmost non-incognito Chrome window
  // (launches Chrome / falls back to the OS default opener as needed).
  openUrl: (url: string): Promise<{ ok: boolean; error?: string }> =>
    ipcRenderer.invoke('uai:openUrl', url),

  // ── Prompt Areas ────────────────────────────────────────────────────
  prompts: {
    getPromptAreas: (): Promise<Array<{ tracking_id: string; session_name: string; platform: string; terminal_session: string; prompt_text: string }>> =>
      ipcRenderer.invoke('uai:prompts:getPromptAreas'),
    hasPromptText: (trackingId: string): Promise<boolean> =>
      ipcRenderer.invoke('uai:prompts:hasPromptText', trackingId),
  },

  // ── News & Reports ─────────────────────────────────────────────────
  news: {
    list: (): Promise<Array<{ type: 'news' | 'report'; name: string; path: string; size: number; modified: string; kind?: string; relPath?: string; isDir?: boolean }>> =>
      ipcRenderer.invoke('uai:news:list'),
    readState: (): Promise<string[]> =>
      ipcRenderer.invoke('uai:news:readState'),
    mark: (paths: string[], read: boolean): Promise<{ ok: boolean; error?: string }> =>
      ipcRenderer.invoke('uai:news:mark', paths, read),
  },

  // ── Terminal ─────────────────────────────────────────────────────────
  terminal: {
    attach: (sessionId: string, terminalSession: string, cols: number, rows: number): Promise<void> =>
      ipcRenderer.invoke('terminal:attach', sessionId, terminalSession, cols, rows),
    input: (sessionId: string, data: string): void =>
      ipcRenderer.send('terminal:input', sessionId, data),
    resize: (sessionId: string, cols: number, rows: number): void =>
      ipcRenderer.send('terminal:resize', sessionId, cols, rows),
    detach: (sessionId: string): Promise<void> =>
      ipcRenderer.invoke('terminal:detach', sessionId),
    onData: (callback: (sessionId: string, data: string) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, sessionId: string, data: string) => callback(sessionId, data);
      ipcRenderer.on('terminal:data', handler);
      return () => ipcRenderer.removeListener('terminal:data', handler);
    },
    onExit: (callback: (sessionId: string, exitCode: number) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, sessionId: string, exitCode: number) => callback(sessionId, exitCode);
      ipcRenderer.on('terminal:exit', handler);
      return () => ipcRenderer.removeListener('terminal:exit', handler);
    },
    captureScrollback: (sessionName: string, lines?: number): Promise<{ ok: boolean; text?: string; error?: string }> =>
      ipcRenderer.invoke('terminal:captureScrollback', { sessionName, lines }),
  },

  // ── Dialog (native OS dialogs) ──────────────────────────────────────
  dialog: {
    showOpenDirectory: (defaultPath?: string): Promise<string | null> =>
      ipcRenderer.invoke('uai:dialog:openDirectory', defaultPath),
    // Pick one or more files; returns their absolute paths (or null if cancelled).
    showOpenFile: (defaultPath?: string): Promise<string[] | null> =>
      ipcRenderer.invoke('uai:dialog:openFile', defaultPath),
  },

  // ── Standalone Terminal (raw shell, no session) ─────────────────────
  standaloneTerminal: {
    create: (id: string, cols: number, rows: number, cwd?: string): Promise<{ reattached: boolean }> =>
      ipcRenderer.invoke('standalone-terminal:create', id, cols, rows, cwd),
    input: (id: string, data: string): void =>
      ipcRenderer.send('standalone-terminal:input', id, data),
    resize: (id: string, cols: number, rows: number): void =>
      ipcRenderer.send('standalone-terminal:resize', id, cols, rows),
    close: (id: string): Promise<void> =>
      ipcRenderer.invoke('standalone-terminal:close', id),
    onData: (callback: (id: string, data: string) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, id: string, data: string) => callback(id, data);
      ipcRenderer.on('standalone-terminal:data', handler);
      return () => ipcRenderer.removeListener('standalone-terminal:data', handler);
    },
    onExit: (callback: (id: string, exitCode: number) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, id: string, exitCode: number) => callback(id, exitCode);
      ipcRenderer.on('standalone-terminal:exit', handler);
      return () => ipcRenderer.removeListener('standalone-terminal:exit', handler);
    },
  },

  // ── Path 2: Store/Runtime Change Subscriptions ──────────────────────
  onStoreChanged: (callback: (event: StoreChangedEvent) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: StoreChangedEvent) => callback(data);
    ipcRenderer.on(IPC.STORE_CHANGED, handler);
    return () => ipcRenderer.removeListener(IPC.STORE_CHANGED, handler);
  },

  onRuntimeChanged: (callback: (event: RuntimeChangedEvent) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: RuntimeChangedEvent) => callback(data);
    ipcRenderer.on(IPC.RUNTIME_CHANGED, handler);
    return () => ipcRenderer.removeListener(IPC.RUNTIME_CHANGED, handler);
  },

  // ── Deep Links (uai:// protocol) ──────────────────────────────────
  onDeepLink: (callback: (event: DeepLinkEvent) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: DeepLinkEvent) => callback(data);
    ipcRenderer.on(IPC.DEEP_LINK, handler);
    return () => ipcRenderer.removeListener(IPC.DEEP_LINK, handler);
  },
};

// Add version getter and viewport API
const uaiApiWithVersion = {
  ...uaiApi,
  getVersion: (): Promise<string> => ipcRenderer.invoke('uai:getVersion'),

  // ── Error reporting + recent errors ─────────────────────────────────
  logError: (payload: { message: string; stack?: string; session?: string; level?: 'error' | 'warn' }): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('uai:logError', payload),
  getRecentErrors: (limit?: number): Promise<Array<{ ts: string; source: string; session: string; message: string }>> =>
    ipcRenderer.invoke('uai:getRecentErrors', limit),
  getLastError: (): Promise<{ ts: string; source: string; session: string; message: string } | null> =>
    ipcRenderer.invoke('uai:getLastError'),
  clearErrors: (): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('uai:clearErrors'),

  // ── Viewport Description (dev/test only) ────────────────────────────
  viewport: {
    describeViewport: (): Promise<unknown> =>
      ipcRenderer.invoke('uai:viewport:describeViewport'),
  },
};

contextBridge.exposeInMainWorld('uai', uaiApiWithVersion);

export type UaiApi = typeof uaiApiWithVersion;
