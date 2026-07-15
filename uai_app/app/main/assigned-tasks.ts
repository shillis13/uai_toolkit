/**
 * Assigned Tasks — backend orchestrator for AI-driven task discovery.
 *
 * Reads user_prompts.jsonl to find prompts the user sent to AI sessions,
 * uses an AI engine (lllm_prompt.py or claude CLI) to discover tasks from
 * those prompts, then analyzes session transcripts to determine task status.
 *
 * Two-phase scan:
 *   Phase 1 (discovery): identify tasks from prompt previews
 *   Phase 2 (analysis):  read session transcripts to determine status
 */

import { readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';
import * as path from 'node:path';
import * as readline from 'node:readline';
import { createReadStream } from 'node:fs';
import * as os from 'node:os';
import { shellPath as getPythonPath } from './paths';

const execFileAsync = promisify(execFile);

// ── Types ──────────────────────────────────────────────────────────────

export interface AssignedTask {
  id: string;
  summary: string;
  details: string;
  decisions: string[];
  sourcePrompts: Array<{ ts: string; preview: string; sessionName: string }>;
  status: 'planned' | 'in-progress' | 'needs-input' | 'completed' | 'cancelled' | 'deferred' | 'unknown';
  statusSource: 'scan' | 'user';
  sessionId: string;
  sessionName: string;
  platform: string;
  assignedDate: string;
  confidence: number;
  dismissed: boolean;
  userNotes: string;
  scanMeta: {
    scannedAt: string;
    engine: string;
    daysBack: number;
  };
}

export interface AssignedTaskStore {
  version: 1;
  lastScanAt: string | null;
  tasks: AssignedTask[];
}

export type ScanEngine = 'lllm' | 'claude';

export interface ScanProgress {
  phase: 'discovery' | 'analysis';
  current: number;
  total: number;
  message: string;
}

// ── Internal types ─────────────────────────────────────────────────────

interface PromptEntry {
  ts: string;
  tracking_id: string;
  session_name: string;
  platform: string;
  prompt_preview: string;
  prompt_length: number;
  cwd: string;
}

interface SessionGroup {
  trackingId: string;
  sessionName: string;
  platform: string;
  prompts: PromptEntry[];
}

interface DiscoveredTask {
  summary: string;
  assignedDate: string;
  confidence: number;
  relevantPrompts: number[];
}

interface StatusResult {
  status: AssignedTask['status'];
  details: string;
  decisions: string[];
}

// ── Store I/O ──────────────────────────────────────────────────────────

function getStorePath(aiRoot: string): string {
  return path.join(aiRoot, 'ai_general', 'data', 'assigned_tasks.json');
}

export async function loadStore(aiRoot: string): Promise<AssignedTaskStore> {
  const p = getStorePath(aiRoot);
  if (!existsSync(p)) return { version: 1, lastScanAt: null, tasks: [] };
  try {
    const raw = await readFile(p, 'utf-8');
    return JSON.parse(raw);
  } catch {
    return { version: 1, lastScanAt: null, tasks: [] };
  }
}

export async function saveStore(aiRoot: string, store: AssignedTaskStore): Promise<void> {
  const p = getStorePath(aiRoot);
  await writeFile(p, JSON.stringify(store, null, 2), 'utf-8');
}


/**
 * Extract JSON from an AI response that may contain markdown fences or preamble.
 * Looks for the first [ or { and parses from there.
 */
function extractJson(text: string): unknown {
  // Try direct parse first
  const trimmed = text.trim();
  try {
    return JSON.parse(trimmed);
  } catch { /* continue */ }

  // Strip markdown code fences
  const fenceMatch = trimmed.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (fenceMatch) {
    try {
      return JSON.parse(fenceMatch[1].trim());
    } catch { /* continue */ }
  }

  // Find first [ or { and try to parse from there
  const arrayStart = trimmed.indexOf('[');
  const objStart = trimmed.indexOf('{');
  const start = arrayStart >= 0 && (objStart < 0 || arrayStart < objStart) ? arrayStart : objStart;
  if (start >= 0) {
    try {
      return JSON.parse(trimmed.slice(start));
    } catch { /* continue */ }
  }

  return null;
}

// ── 1. Read user prompts ───────────────────────────────────────────────

export async function readUserPrompts(
  aiRoot: string,
  fromDate: Date,
  toDate: Date,
): Promise<SessionGroup[]> {
  const promptsPath = path.join(aiRoot, 'ai_general', 'data', 'audit', 'user_prompts.jsonl');
  if (!existsSync(promptsPath)) return [];

  const fromIso = fromDate.toISOString();
  const toIso = toDate.toISOString();

  const bySession = new Map<string, SessionGroup>();

  const fileStream = createReadStream(promptsPath, { encoding: 'utf-8' });
  const rl = readline.createInterface({ input: fileStream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const entry: PromptEntry = JSON.parse(line);
      if (!entry.ts || !entry.tracking_id) continue;

      // Normalize timestamp — some entries may not have timezone info
      const entryTs = entry.ts.endsWith('Z') || entry.ts.includes('+') ? entry.ts : entry.ts + 'Z';
      if (entryTs < fromIso || entryTs > toIso) continue;

      let group = bySession.get(entry.tracking_id);
      if (!group) {
        group = {
          trackingId: entry.tracking_id,
          sessionName: entry.session_name || '',
          platform: entry.platform || '',
          prompts: [],
        };
        bySession.set(entry.tracking_id, group);
      }
      group.prompts.push(entry);

      // Update session name if a later prompt has one
      if (entry.session_name && !group.sessionName) {
        group.sessionName = entry.session_name;
      }
    } catch {
      // Skip malformed lines
    }
  }

  return Array.from(bySession.values());
}

// ── 2. Extract session excerpt ─────────────────────────────────────────

export async function extractSessionExcerpt(
  aiRoot: string,
  cliSessionId: string,
  maxChars: number = 50000,
): Promise<string> {
  // Look for session JSONL files in common locations
  const searchDirs = [
    path.join(os.homedir(), '.claude', 'projects'),
  ];

  for (const searchDir of searchDirs) {
    if (!existsSync(searchDir)) continue;

    // List project directories under .claude/projects/
    let projectDirs: string[];
    try {
      const { stdout } = await execFileAsync('ls', ['-1', searchDir]);
      projectDirs = stdout.trim().split('\n').filter(Boolean);
    } catch {
      continue;
    }

    for (const projDir of projectDirs) {
      const projPath = path.join(searchDir, projDir);
      // Look for JSONL files matching the session ID
      let files: string[];
      try {
        const { stdout } = await execFileAsync('ls', ['-1', projPath]);
        files = stdout.trim().split('\n').filter(Boolean);
      } catch {
        continue;
      }

      const matchingFile = files.find(f =>
        f.includes(cliSessionId) && f.endsWith('.jsonl')
      );

      if (matchingFile) {
        return await readSessionJsonl(path.join(projPath, matchingFile), maxChars);
      }
    }
  }

  return '';
}

async function readSessionJsonl(filePath: string, maxChars: number): Promise<string> {
  const parts: string[] = [];
  let totalChars = 0;

  const fileStream = createReadStream(filePath, { encoding: 'utf-8' });
  const rl = readline.createInterface({ input: fileStream, crlfDelay: Infinity });

  for await (const line of rl) {
    if (!line.trim()) continue;
    if (totalChars >= maxChars) break;

    try {
      const entry = JSON.parse(line);
      const role = entry.role || entry.type;
      if (role !== 'user' && role !== 'assistant') continue;

      // Extract text content
      let text = '';
      if (typeof entry.content === 'string') {
        text = entry.content;
      } else if (Array.isArray(entry.content)) {
        text = entry.content
          .filter((b: { type: string }) => b.type === 'text')
          .map((b: { text: string }) => b.text || '')
          .join('\n');
      } else if (entry.message?.content) {
        if (typeof entry.message.content === 'string') {
          text = entry.message.content;
        } else if (Array.isArray(entry.message.content)) {
          text = entry.message.content
            .filter((b: { type: string }) => b.type === 'text')
            .map((b: { text: string }) => b.text || '')
            .join('\n');
        }
      }

      if (!text) continue;

      const chunk = `[${role}]: ${text}\n`;
      if (totalChars + chunk.length > maxChars) {
        parts.push(chunk.slice(0, maxChars - totalChars));
        break;
      }
      parts.push(chunk);
      totalChars += chunk.length;
    } catch {
      // Skip malformed lines
    }
  }

  return parts.join('');
}

// ── 3. AI engine call ──────────────────────────────────────────────────

export async function callAiEngine(
  engine: ScanEngine,
  systemPrompt: string,
  userInput: string,
  aiRoot: string,
): Promise<string> {
  try {
    if (engine === 'lllm') {
      const scriptPath = path.join(aiRoot, 'ai_general', 'scripts', 'lllm', 'lllm_prompt.py');
      const { stdout } = await execFileAsync(
        'python3',
        [scriptPath, systemPrompt, '--text', userInput],
        {
          env: { ...process.env, PATH: getPythonPath(), AI_ROOT: aiRoot },
          maxBuffer: 10 * 1024 * 1024,
          timeout: 120_000,
        },
      );
      return String(stdout).trim();
    }

    if (engine === 'claude') {
      const { stdout } = await execFileAsync(
        'claude',
        ['-p', '--max-turns', '1'],
        {
          env: { ...process.env, PATH: getPythonPath() },
          maxBuffer: 10 * 1024 * 1024,
          timeout: 120_000,
          input: `${systemPrompt}\n\n${userInput}`,
        } as Parameters<typeof execFileAsync>[2] & { input: string },
      );
      return String(stdout).trim();
    }

    return '';
  } catch (err) {
    console.error(`[UAI] callAiEngine(${engine}) failed:`, err);
    return '';
  }
}

// ── 4. Discover tasks (Phase 1) ────────────────────────────────────────

const DISCOVERY_SYSTEM_PROMPT = `You are analyzing a user's prompts to AI coding assistants. Identify distinct tasks or assignments the user gave to the AI session.

A "task" is a concrete piece of work the user asked the AI to do — not a question, not a follow-up clarification, not a notification.

Respond with ONLY valid JSON — no explanation, no markdown. Return an array:
[
  {
    "summary": "Brief 1-line description of the task",
    "assignedDate": "ISO date string of when it was assigned",
    "confidence": 0.0 to 1.0,
    "relevantPrompts": [0, 2, 5]
  }
]

If no tasks found, return [].
Only include tasks with confidence >= 0.4.
Combine closely related prompts into a single task.`;

export async function discoverTasks(
  sessionGroups: SessionGroup[],
  engine: ScanEngine,
  aiRoot: string,
  progressCallback?: (p: ScanProgress) => void,
  signal?: AbortSignal,
): Promise<AssignedTask[]> {
  const allTasks: AssignedTask[] = [];
  const now = new Date().toISOString();

  for (let i = 0; i < sessionGroups.length; i++) {
    if (signal?.aborted) break;

    const group = sessionGroups[i];

    progressCallback?.({
      phase: 'discovery',
      current: i + 1,
      total: sessionGroups.length,
      message: `Scanning session: ${group.sessionName || group.trackingId}`,
    });

    // Build prompt listing
    const promptListing = group.prompts
      .map((p, idx) => `[${idx}] (${p.ts}) ${p.prompt_preview}`)
      .join('\n');

    const userInput = `Session: ${group.sessionName || group.trackingId} (${group.platform})
Prompts:
${promptListing}`;

    const response = await callAiEngine(engine, DISCOVERY_SYSTEM_PROMPT, userInput, aiRoot);
    if (!response) continue;

    const parsed = extractJson(response);
    if (!Array.isArray(parsed)) continue;

    for (const raw of parsed as DiscoveredTask[]) {
      if (!raw.summary || typeof raw.confidence !== 'number') continue;
      if (raw.confidence < 0.4) continue;

      const taskId = createHash('sha256')
        .update(group.trackingId + raw.summary)
        .digest('hex')
        .slice(0, 12);

      const sourcePrompts = (raw.relevantPrompts || [])
        .filter((idx: number) => idx >= 0 && idx < group.prompts.length)
        .map((idx: number) => ({
          ts: group.prompts[idx].ts,
          preview: group.prompts[idx].prompt_preview,
          sessionName: group.prompts[idx].session_name || group.sessionName,
        }));

      allTasks.push({
        id: taskId,
        summary: raw.summary,
        details: '',
        decisions: [],
        sourcePrompts,
        status: 'unknown',
        statusSource: 'scan',
        sessionId: group.trackingId,
        sessionName: group.sessionName,
        platform: group.platform,
        assignedDate: raw.assignedDate || (sourcePrompts[0]?.ts ?? now),
        confidence: raw.confidence,
        dismissed: false,
        userNotes: '',
        scanMeta: {
          scannedAt: now,
          engine,
          daysBack: 0, // filled in by runFullScan
        },
      });
    }
  }

  return allTasks;
}

// ── 5. Analyze task status (Phase 2) ───────────────────────────────────

const STATUS_SYSTEM_PROMPT = `You are analyzing a session transcript to determine the status of a specific task.

The task is described below. Read the transcript and determine:
1. The current status of the task
2. A brief description of what happened
3. Any key decisions made

Respond with ONLY valid JSON — no explanation, no markdown:
{
  "status": "planned|in-progress|needs-input|completed|cancelled|deferred",
  "details": "Brief description of current state",
  "decisions": ["Decision 1", "Decision 2"]
}

Status meanings:
- planned: Task acknowledged but work hasn't started
- in-progress: Work is actively happening
- needs-input: Blocked waiting for user input or clarification
- completed: Task is finished
- cancelled: Task was explicitly cancelled
- deferred: Task was postponed to later`;

export async function analyzeTaskStatus(
  task: AssignedTask,
  engine: ScanEngine,
  aiRoot: string,
): Promise<void> {
  const excerpt = await extractSessionExcerpt(aiRoot, task.sessionId);
  if (!excerpt) {
    // No transcript available — leave as unknown
    return;
  }

  const userInput = `Task: ${task.summary}
Session: ${task.sessionName || task.sessionId}

Transcript excerpt:
${excerpt}`;

  const response = await callAiEngine(engine, STATUS_SYSTEM_PROMPT, userInput, aiRoot);
  if (!response) return;

  const parsed = extractJson(response) as StatusResult | null;
  if (!parsed || typeof parsed !== 'object') return;

  const validStatuses: AssignedTask['status'][] = [
    'planned', 'in-progress', 'needs-input', 'completed', 'cancelled', 'deferred',
  ];

  if (parsed.status && validStatuses.includes(parsed.status)) {
    task.status = parsed.status;
  }
  if (typeof parsed.details === 'string') {
    task.details = parsed.details;
  }
  if (Array.isArray(parsed.decisions)) {
    task.decisions = parsed.decisions.filter((d): d is string => typeof d === 'string');
  }
}

// ── 6. Merge scan results ──────────────────────────────────────────────

export function mergeScanResults(
  existing: AssignedTask[],
  newTasks: AssignedTask[],
): AssignedTask[] {
  const existingById = new Map(existing.map(t => [t.id, t]));
  const merged = new Map<string, AssignedTask>();

  // Start with all existing tasks
  for (const task of existing) {
    merged.set(task.id, { ...task });
  }

  // Merge new tasks
  for (const newTask of newTasks) {
    const prev = existingById.get(newTask.id);

    if (!prev) {
      // Brand new task
      merged.set(newTask.id, newTask);
      continue;
    }

    if (prev.statusSource === 'user') {
      // User has manually set status — preserve user overrides, update AI fields
      merged.set(newTask.id, {
        ...newTask,
        status: prev.status,
        statusSource: prev.statusSource,
        dismissed: prev.dismissed,
        userNotes: prev.userNotes,
      });
    } else {
      // Both are scan-derived — take the new scan data
      merged.set(newTask.id, {
        ...newTask,
        dismissed: prev.dismissed,
        userNotes: prev.userNotes,
      });
    }
  }

  return Array.from(merged.values());
}

// ── 7. Full scan orchestrator ──────────────────────────────────────────

export async function runFullScan(
  aiRoot: string,
  engine: ScanEngine,
  daysBack: number,
  progressCallback: (p: ScanProgress) => void,
  signal?: AbortSignal,
): Promise<AssignedTaskStore> {
  const store = await loadStore(aiRoot);

  // Calculate date range
  const toDate = new Date();
  const fromDate = new Date();
  fromDate.setDate(fromDate.getDate() - daysBack);

  // Phase 1: Read prompts and discover tasks
  progressCallback({
    phase: 'discovery',
    current: 0,
    total: 0,
    message: 'Reading user prompts...',
  });

  if (signal?.aborted) return store;

  const sessionGroups = await readUserPrompts(aiRoot, fromDate, toDate);
  if (signal?.aborted) return store;

  const discovered = await discoverTasks(sessionGroups, engine, aiRoot, progressCallback, signal);
  if (signal?.aborted) return store;

  // Stamp daysBack on all discovered tasks
  for (const task of discovered) {
    task.scanMeta.daysBack = daysBack;
  }

  // Phase 2: Analyze status for each discovered task
  for (let i = 0; i < discovered.length; i++) {
    if (signal?.aborted) break;

    progressCallback({
      phase: 'analysis',
      current: i + 1,
      total: discovered.length,
      message: `Analyzing: ${discovered[i].summary}`,
    });

    try {
      await analyzeTaskStatus(discovered[i], engine, aiRoot);
    } catch (err) {
      console.error(`[UAI] Failed to analyze task ${discovered[i].id}:`, err);
      // Continue with next task — don't crash the scan
    }
  }

  // Merge and save
  store.tasks = mergeScanResults(store.tasks, discovered);
  store.lastScanAt = new Date().toISOString();
  await saveStore(aiRoot, store);

  return store;
}

// ── 8. Update a single task ────────────────────────────────────────────

export async function updateTask(
  aiRoot: string,
  taskId: string,
  patch: { status?: string; dismissed?: boolean; userNotes?: string },
): Promise<AssignedTaskStore> {
  const store = await loadStore(aiRoot);
  const task = store.tasks.find(t => t.id === taskId);

  if (!task) {
    throw new Error(`Task not found: ${taskId}`);
  }

  if (patch.status !== undefined) {
    const validStatuses: AssignedTask['status'][] = [
      'planned', 'in-progress', 'needs-input', 'completed', 'cancelled', 'deferred', 'unknown',
    ];
    if (validStatuses.includes(patch.status as AssignedTask['status'])) {
      task.status = patch.status as AssignedTask['status'];
      task.statusSource = 'user';
    }
  }

  if (patch.dismissed !== undefined) {
    task.dismissed = patch.dismissed;
    task.statusSource = 'user';
  }

  if (patch.userNotes !== undefined) {
    task.userNotes = patch.userNotes;
    task.statusSource = 'user';
  }

  await saveStore(aiRoot, store);
  return store;
}
