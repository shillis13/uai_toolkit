/**
 * CommsReader — reads prompt queue and inbox from disk.
 *
 * Read-only access to the AI Communication Protocol v1.0 data:
 * - Prompt queue: ai_comms/prompts_inbox/{session_tracking_id}/
 * - Inbox: ai_comms/messages/inbox/{session_tracking_id}/
 *
 * Parses YAML files into structured types for the renderer.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import yaml from 'js-yaml';
import type { QueueEntry, InboxMessage } from '@uai/shared/types';

function getAiRootMain(): string {
  return process.env.AI_ROOT_MAIN || path.join(os.homedir(), 'AI/ai_root');
}

function getCommsRoot(): string {
  // ai_comms lives INSIDE ai_root (ai_root/ai_comms), not as a sibling.
  if (process.env.AI_COMMS) return process.env.AI_COMMS;
  return path.join(getAiRootMain(), 'ai_comms');
}

/**
 * Parse a message/queue YAML file into a plain object.
 *
 * Uses js-yaml (safe load) rather than a hand-rolled parser. The previous
 * line-based parser could not handle nested block sequences — notably the
 * `read_by:` / `acknowledgments:` lists of maps — so it silently dropped them,
 * which made the app treat every message as unread regardless of its on-disk
 * read state. It also truncated multi-line quoted `content`. A real parser
 * fixes both.
 */
function parseYaml(content: string): Record<string, any> {
  const parsed = yaml.load(content);
  return (parsed && typeof parsed === 'object') ? parsed as Record<string, any> : {};
}

function readYamlFiles<T>(dirPath: string, mapper: (raw: Record<string, any>) => T): T[] {
  try {
    if (!fs.existsSync(dirPath)) return [];
    const files = fs.readdirSync(dirPath).filter(f => f.endsWith('.yml') || f.endsWith('.yaml'));
    const results: T[] = [];
    for (const file of files) {
      try {
        const content = fs.readFileSync(path.join(dirPath, file), 'utf-8');
        const parsed = parseYaml(content);
        results.push(mapper(parsed));
      } catch {
        // Skip unparseable files
      }
    }
    return results;
  } catch {
    return [];
  }
}

function mapQueueEntry(raw: Record<string, any>): QueueEntry {
  return {
    id: raw.id || '',
    message_id: raw.message_id || undefined,
    to: raw.to || '',
    content: raw.content || '',
    urgency: raw.urgency || 'prompt',
    delivery: raw.delivery || 'post-prompt',
    ready_for_delivery: raw.ready_for_delivery !== false,
    queued_at: raw.queued_at || '',
    expires_at: raw.expires_at || undefined,
    source: raw.source || 'unknown',
    callback_endpoint: raw.callback_endpoint || null,
  };
}

function mapInboxMessage(raw: Record<string, any>): InboxMessage {
  return {
    id: raw.id || '',
    type: raw.type || 'advisory',
    urgency: raw.urgency || 'async',
    response_type: raw.response_type || 'none',
    from: raw.from || 'unknown',
    to: raw.to || '',
    subject: raw.subject || undefined,
    content: raw.content || '',
    // When a large body was offloaded to a file, the message references it here
    // (comms_message body_file). The UI surfaces a link to the offloaded data.
    body_file: raw.body_file || raw.bodyFile || undefined,
    created_at: raw.created_at || '',
    ttl_seconds: raw.ttl_seconds ?? null,
    expires_at: raw.expires_at || undefined,
    reply_to: raw.reply_to || null,
    // Thread linkage: conversation_id groups a thread; replying_to points at the
    // parent message (replies set replying_to, not reply_to). Surfaced so the UI
    // can render a message's conversation thread.
    conversation_id: raw.conversation_id || null,
    replying_to: raw.replying_to || null,
    callback_endpoint: raw.callback_endpoint || null,
    read_by: Array.isArray(raw.read_by) ? raw.read_by : [],
    acknowledgments: Array.isArray(raw.acknowledgments) ? raw.acknowledgments : [],
  };
}

// ─── Public API ──────────────────────────────────────────────────────────

export function listQueueEntries(sessionTrackingId: string): QueueEntry[] {
  const commsRoot = getCommsRoot();
  const queueDir = path.join(commsRoot, 'prompts_inbox', sessionTrackingId);
  return readYamlFiles(queueDir, mapQueueEntry);
}

export function countQueueEntries(sessionTrackingId: string): number {
  const commsRoot = getCommsRoot();
  const queueDir = path.join(commsRoot, 'prompts_inbox', sessionTrackingId);
  try {
    if (!fs.existsSync(queueDir)) return 0;
    return fs.readdirSync(queueDir).filter(f => f.endsWith('.yml') || f.endsWith('.yaml')).length;
  } catch {
    return 0;
  }
}

export function listInboxMessages(sessionTrackingId: string): InboxMessage[] {
  const commsRoot = getCommsRoot();
  const inboxDir = path.join(commsRoot, 'messages', 'inbox', sessionTrackingId);
  return readYamlFiles(inboxDir, mapInboxMessage);
}

export function listArchiveMessages(sessionTrackingId: string): InboxMessage[] {
  const commsRoot = getCommsRoot();
  const archiveDir = path.join(commsRoot, 'messages', 'archive', sessionTrackingId);
  return readYamlFiles(archiveDir, mapInboxMessage);
}

export function listSentMessages(sessionTrackingId: string, identities?: string[]): InboxMessage[] {
  // A session's sent messages are keyed by whatever it put in the `from` field
  // — and that's recorded inconsistently across the fleet: some sessions send
  // with their tracking ID, others with their display name (e.g. "Mullion").
  // So match against ALL of this session's known identities, and read the
  // CANONICAL sent store (messages/sent/<from>/, hardlinks created on send that
  // survive the recipient deleting their copy) rather than only reconstructing
  // from inbox/archive. Previously this matched the tracking ID alone against
  // inbox/archive, so name-keyed senders showed an empty Sent box entirely.
  const commsRoot = getCommsRoot();
  const keys = (identities && identities.length ? identities : [sessionTrackingId]).filter(Boolean);

  const byId = new Map<string, InboxMessage>();
  const add = (m: InboxMessage) => { if (m.id && !byId.has(m.id)) byId.set(m.id, m); };

  // 1) Canonical sent store: messages/sent/<from>/ keyed by the exact `from`.
  const sentBase = path.join(commsRoot, 'messages', 'sent');
  for (const key of keys) {
    for (const m of readYamlFiles(path.join(sentBase, key), mapInboxMessage)) add(m);
  }

  // 2) Supplement from inbox/archive — catches sent messages without a sent/
  //    hardlink (e.g. pre-retention-feature) and `from: "Name (id)"` forms.
  for (const folder of ['inbox', 'archive']) {
    const base = path.join(commsRoot, 'messages', folder);
    try {
      if (!fs.existsSync(base)) continue;
      for (const sub of fs.readdirSync(base)) {
        const subDir = path.join(base, sub);
        if (!fs.statSync(subDir).isDirectory()) continue;
        for (const m of readYamlFiles(subDir, mapInboxMessage)) {
          if (m.from && keys.some(k => m.from.includes(k))) add(m);
        }
      }
    } catch { /* skip */ }
  }

  return Array.from(byId.values())
    .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
}

export function countInboxMessages(sessionTrackingId: string): { total: number; unread: number } {
  const messages = listInboxMessages(sessionTrackingId);
  // A message's read state for this recipient = whether the recipient session
  // appears in read_by (matches messaging.py check_unread). For a direct message
  // there's only one relevant reader (the recipient), so this is the single
  // effective read state that drives unread reminders / get-unread.
  const unread = messages.filter(m => !(m.read_by && m.read_by.some(r => r.by === sessionTrackingId))).length;
  return { total: messages.length, unread };
}

// ─── Queue Management (Phase 2) ─────────────────────────────────────────

function findQueueFile(sessionTrackingId: string, entryId: string): string | null {
  const commsRoot = getCommsRoot();
  const queueDir = path.join(commsRoot, 'prompts_inbox', sessionTrackingId);
  if (!fs.existsSync(queueDir)) return null;
  const files = fs.readdirSync(queueDir).filter(f => f.endsWith('.yml') || f.endsWith('.yaml'));
  for (const file of files) {
    const filePath = path.join(queueDir, file);
    const content = fs.readFileSync(filePath, 'utf-8');
    if (content.includes(`id: ${entryId}`) || file.includes(entryId)) {
      return filePath;
    }
  }
  return null;
}

function updateQueueField(filePath: string, field: string, value: string): void {
  let content = fs.readFileSync(filePath, 'utf-8');
  const regex = new RegExp(`^(${field}:\\s*)(.*)$`, 'm');
  if (regex.test(content)) {
    content = content.replace(regex, `$1${value}`);
  } else {
    content += `\n${field}: ${value}\n`;
  }
  fs.writeFileSync(filePath, content);
}

export function holdQueueEntry(sessionTrackingId: string, entryId: string): boolean {
  const file = findQueueFile(sessionTrackingId, entryId);
  if (!file) return false;
  updateQueueField(file, 'ready_for_delivery', 'false');
  return true;
}

export function releaseQueueEntry(sessionTrackingId: string, entryId: string): boolean {
  const file = findQueueFile(sessionTrackingId, entryId);
  if (!file) return false;
  updateQueueField(file, 'ready_for_delivery', 'true');
  return true;
}

export function changeQueueDelivery(
  sessionTrackingId: string,
  entryId: string,
  delivery: 'pre-prompt' | 'post-prompt' | 'postResponse',
): boolean {
  const file = findQueueFile(sessionTrackingId, entryId);
  if (!file) return false;
  updateQueueField(file, 'delivery', delivery);
  return true;
}

export function removeQueueEntry(sessionTrackingId: string, entryId: string): boolean {
  const file = findQueueFile(sessionTrackingId, entryId);
  if (!file) return false;
  fs.unlinkSync(file);
  return true;
}

// ─── Message Sending (Phase 3) ──────────────────────────────────────────

import { execFile as execFileCb } from 'node:child_process';

function getMessagingScript(): string {
  return path.join(os.homedir(), 'bin', 'ai', 'messages', 'messaging.py');
}

export async function sendMessage(opts: {
  from: string;
  to: string;
  content: string;
  urgency?: string;
  responseType?: string;
  ttlSeconds?: number;
  replyTo?: string;
  subject?: string;
}): Promise<{ ok: boolean; messageId?: string; error?: string }> {
  const script = getMessagingScript();
  // v2 messaging contract: the sender is the TRUSTED resolved identity
  // ($AI_TRACKING_ID), NOT a self-asserted --from wire field (which is now
  // ignored). The UAI sends on behalf of the user, so it authenticates AS the
  // user by setting AI_TRACKING_ID to `opts.from` for this subprocess. --reply-to
  // is required: a real parent msg id for a reply, or the 'none' sentinel for a
  // new thread (which also requires a --subject).
  const isReply = !!opts.replyTo && opts.replyTo !== 'none';
  const args = [
    script, 'send',
    '--to', opts.to,
    '--content', opts.content,
    '--reply-to', isReply ? opts.replyTo! : 'none',
    '--format', 'json',
  ];
  if (!isReply) {
    // New thread: subject is mandatory. Fall back to a trimmed first line.
    const subject = (opts.subject || opts.content).split('\n')[0].slice(0, 80).trim() || 'Message';
    args.push('--subject', subject);
  }
  if (opts.urgency) args.push('--urgency', opts.urgency);
  if (opts.responseType) args.push('--response-type', opts.responseType);
  if (opts.ttlSeconds) args.push('--ttl', String(opts.ttlSeconds));

  const sendEnv = {
    ...process.env,
    AI_TRACKING_ID: opts.from,
    PATH: [process.env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin'].join(':'),
  };

  return new Promise((resolve) => {
    execFileCb('python3', args, { maxBuffer: 1024 * 1024, timeout: 10000, env: sendEnv }, (error, stdout, stderr) => {
      // messaging.py emits a structured JSON result on stdout for BOTH success and
      // failure (e.g. {"success": false, "error": "recipient is ambiguous; …"}).
      // Parse it FIRST — even on a non-zero exit — so we surface the real backend
      // error instead of Node's opaque "Command failed: python3 …" message.string
      // (which is what leaks when we fall back to error.message on empty stderr).
      const out = (stdout || '').trim();
      if (out) {
        try {
          const result = JSON.parse(out);
          if (result && result.success === false) {
            resolve({ ok: false, error: result.error || result.error_type || 'Message send failed' });
            return;
          }
          resolve({ ok: true, messageId: result.id || result.message_id });
          return;
        } catch {
          /* not JSON — fall through to the exit-code check */
        }
      }
      if (error) {
        resolve({ ok: false, error: stderr?.trim() || error.message });
        return;
      }
      resolve({ ok: true });
    });
  });
}

/**
 * Mark an inbox message as read by appending a read_by entry. Shells out to
 * `messaging.py read --id <id> --reader <reader>` (idempotent — the backend
 * skips duplicate readers). `reader` is the inbox owner's tracking ID (the
 * recipient session), since reading in the app is that session reading its mail.
 */
export async function markRead(messageId: string, reader: string): Promise<{ ok: boolean; error?: string }> {
  const script = getMessagingScript();
  const args = [script, 'read', '--id', messageId, '--reader', reader];

  return new Promise((resolve) => {
    execFileCb('python3', args, { maxBuffer: 1024 * 1024, timeout: 10000 }, (error, _stdout, stderr) => {
      if (error) {
        resolve({ ok: false, error: stderr?.trim() || error.message });
        return;
      }
      resolve({ ok: true });
    });
  });
}

// ─── Inbox Message Actions (Archive / Mark-Unread / Delete / Reply) ─────────

/** Locate the on-disk YAML for an inbox message in a session's inbox dir. */
function findInboxFile(sessionTrackingId: string, messageId: string): string | null {
  const inboxDir = path.join(getCommsRoot(), 'messages', 'inbox', sessionTrackingId);
  if (!fs.existsSync(inboxDir)) return null;
  const files = fs.readdirSync(inboxDir).filter(f => f.endsWith('.yml') || f.endsWith('.yaml'));
  for (const file of files) {
    const filePath = path.join(inboxDir, file);
    if (file.includes(messageId)) return filePath;
    try { if (fs.readFileSync(filePath, 'utf-8').includes(`id: ${messageId}`)) return filePath; } catch { /* skip */ }
  }
  return null;
}

/** Archive a message via messaging.py (moves inbox → archive for the recipient). */
export async function archiveMessage(messageId: string): Promise<{ ok: boolean; error?: string }> {
  const args = [getMessagingScript(), 'archive', '--id', messageId];
  return new Promise((resolve) => {
    execFileCb('python3', args, { maxBuffer: 1024 * 1024, timeout: 10000 }, (error, _stdout, stderr) => {
      resolve(error ? { ok: false, error: stderr?.trim() || error.message } : { ok: true });
    });
  });
}

/** Mark a message unread *for a given reader* by removing that reader's read_by
 *  entry (the inverse of markRead). messaging.py has no unread verb, so we edit
 *  the YAML directly with js-yaml (round-trips to valid YAML). */
export function markUnread(sessionTrackingId: string, messageId: string, reader: string): { ok: boolean; error?: string } {
  const file = findInboxFile(sessionTrackingId, messageId);
  if (!file) return { ok: false, error: 'message not found' };
  try {
    const data = parseYaml(fs.readFileSync(file, 'utf-8'));
    if (Array.isArray(data.read_by)) {
      data.read_by = data.read_by.filter((r: any) => r && r.by !== reader);
      fs.writeFileSync(file, yaml.dump(data));
    }
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: e?.message || 'write failed' };
  }
}

/** Delete a message from a session's inbox (unlink the file). */
export function deleteInboxMessage(sessionTrackingId: string, messageId: string): { ok: boolean; error?: string } {
  const file = findInboxFile(sessionTrackingId, messageId);
  if (!file) return { ok: false, error: 'message not found' };
  try {
    fs.unlinkSync(file);
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: e?.message || 'delete failed' };
  }
}

/** Reply to a message via messaging.py reply. `from` is the inbox owner. */
export async function replyToMessage(messageId: string, from: string, content: string): Promise<{ ok: boolean; error?: string }> {
  const args = [getMessagingScript(), 'reply', '--id', messageId, '--from', from, '--content', content];
  return new Promise((resolve) => {
    execFileCb('python3', args, { maxBuffer: 1024 * 1024, timeout: 10000 }, (error, _stdout, stderr) => {
      resolve(error ? { ok: false, error: stderr?.trim() || error.message } : { ok: true });
    });
  });
}
