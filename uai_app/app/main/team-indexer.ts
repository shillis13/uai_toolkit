/**
 * TeamIndexer — scans team YAML definitions and returns TeamCard objects.
 *
 * Reads YAML files from the canonical main ai_root teams directory and combines
 * them with entity_relationships occupancy from session_store.py.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import type { TeamCard } from '@uai/shared/cards';
import type {
  CommsBoardRef,
  CommsPlan,
  EntityId,
  EntityRelationship,
  Platform,
  Team,
  TeamSlot,
  TeamStatus,
} from '@uai/shared/types';
import { callStore as callSessionStore } from './session-store';

interface RawTeamYaml {
  schema_version?: unknown;
  name?: unknown;
  description?: unknown;
  status?: unknown;
  tags?: unknown;
  created_at?: unknown;
  slots?: unknown;
  comms?: unknown;
  projects?: unknown;
}

const VALID_TEAM_STATUSES = new Set<TeamStatus>(['active', 'disbanded', 'paused']);
const VALID_PLATFORMS = new Set<Platform>(['claude_cli', 'codex_cli', 'gemini_cli']);
const VALID_FEEDBACK = new Set(['none', 'message', 'prompt']);

function getAiRoot(): string {
  return process.env.AI_ROOT || path.join(os.homedir(), 'AI/ai_root');
}

function getTeamsDir(): string {
  return path.join(getAiRoot(), 'ai_general', 'data', 'teams');
}

function pythonYamlLoaderScript(): string {
  return [
    'import json, sys',
    'from pathlib import Path',
    'import yaml',
    'data = yaml.safe_load(Path(sys.argv[1]).read_text())',
    'print(json.dumps(data if data is not None else {}))',
  ].join('; ');
}

function readYamlFile(filePath: string): RawTeamYaml {
  const stdout = execFileSync('python3', ['-c', pythonYamlLoaderScript(), filePath], {
    encoding: 'utf-8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    maxBuffer: 1024 * 1024,
  });
  const parsed = JSON.parse(stdout);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return {};
  }
  return parsed as RawTeamYaml;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map(item => item.trim());
}

function normalizeTeamStatus(value: unknown): TeamStatus {
  return typeof value === 'string' && VALID_TEAM_STATUSES.has(value as TeamStatus)
    ? value as TeamStatus
    : 'active';
}

function normalizePlatform(value: unknown): Platform | 'any' {
  if (value === 'any') return 'any';
  return typeof value === 'string' && VALID_PLATFORMS.has(value as Platform)
    ? value as Platform
    : 'any';
}

function normalizeSlot(raw: unknown): TeamSlot | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;
  const role = asString(source.role);
  if (!role) return null;

  const countValue = typeof source.count === 'number'
    ? source.count
    : typeof source.count === 'string'
      ? Number.parseInt(source.count, 10)
      : NaN;

  return {
    role,
    description: asString(source.description),
    platform: normalizePlatform(source.platform),
    profile_ref: asString(source.profile_ref),
    count: Number.isFinite(countValue) && countValue > 0 ? countValue : 1,
  };
}

function normalizeBoard(raw: unknown): CommsBoardRef | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const source = raw as Record<string, unknown>;
  const type = asString(source.type);
  const scope = asString(source.scope);
  const id = asString(source.id);
  if (!type || !scope || !id) return null;
  return { type, scope, id };
}

function normalizeComms(raw: unknown): CommsPlan {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : {};
  const feedback = asString(source.feedback_mechanism);
  const timeout = typeof source.feedback_timeout === 'number'
    ? source.feedback_timeout
    : typeof source.feedback_timeout === 'string'
      ? Number.parseInt(source.feedback_timeout, 10)
      : 0;

  const routing: Record<string, string[]> = {};
  const rawRouting = source.notification_routing;
  if (rawRouting && typeof rawRouting === 'object' && !Array.isArray(rawRouting)) {
    for (const [key, value] of Object.entries(rawRouting as Record<string, unknown>)) {
      routing[key] = asStringArray(value);
    }
  }

  const boards = Array.isArray(source.boards)
    ? source.boards.map(normalizeBoard).filter((board): board is CommsBoardRef => board !== null)
    : [];

  return {
    escalation_chain: asStringArray(source.escalation_chain),
    feedback_mechanism: feedback && VALID_FEEDBACK.has(feedback) ? feedback as 'none' | 'message' | 'prompt' : 'none',
    feedback_timeout: Number.isFinite(timeout) && timeout >= 0 ? timeout : 0,
    notification_routing: routing,
    boards,
  };
}

function computeContentHash(content: string): string {
  return createHash('sha1').update(content).digest('hex');
}

export interface TeamDefinition extends Team {
  slots: TeamSlot[];
}

function normalizeTeamDefinition(teamId: string, filePath: string, raw: RawTeamYaml, stat: fs.Stats, contentHash: string): TeamDefinition {
  const slots = Array.isArray(raw.slots)
    ? raw.slots.map(normalizeSlot).filter((slot): slot is TeamSlot => slot !== null)
    : [];

  return {
    id: teamId,
    name: asString(raw.name) || teamId,
    description: asString(raw.description),
    status: normalizeTeamStatus(raw.status),
    slots,
    comms_plan: normalizeComms(raw.comms),
    tags: asStringArray(raw.tags),
    created_at: asString(raw.created_at) || stat.birthtime.toISOString(),
    project_ids: asStringArray(raw.projects),
    source_path: filePath,
    content_hash: contentHash,
    indexed_at: new Date().toISOString(),
    availability: 'available',
    parse_error: null,
  };
}

function buildParseErrorDefinition(teamId: string, filePath: string, stat: fs.Stats, contentHash: string, err: unknown): TeamDefinition {
  return {
    id: teamId,
    name: teamId,
    description: null,
    status: 'active',
    slots: [],
    comms_plan: {
      escalation_chain: [],
      feedback_mechanism: 'none',
      feedback_timeout: 0,
      notification_routing: {},
      boards: [],
    },
    tags: [],
    created_at: stat.birthtime.toISOString(),
    project_ids: [],
    source_path: filePath,
    content_hash: contentHash,
    indexed_at: new Date().toISOString(),
    availability: 'parse_error',
    parse_error: err instanceof Error ? err.message : String(err),
  };
}

export function loadTeamDefinition(teamId: string): TeamDefinition | null {
  const filePath = path.join(getTeamsDir(), `${teamId}.yml`);
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    return null;
  }

  const stat = fs.statSync(filePath);
  const content = fs.readFileSync(filePath, 'utf-8');
  const contentHash = computeContentHash(content);

  try {
    const raw = readYamlFile(filePath);
    return normalizeTeamDefinition(teamId, filePath, raw, stat, contentHash);
  } catch (err) {
    return buildParseErrorDefinition(teamId, filePath, stat, contentHash, err);
  }
}

export function loadAllTeamDefinitions(): TeamDefinition[] {
  const teamsDir = getTeamsDir();
  if (!fs.existsSync(teamsDir)) return [];

  const files = fs.readdirSync(teamsDir).filter(name => name.endsWith('.yml') || name.endsWith('.yaml'));
  return files.map((fileName) => {
    const filePath = path.join(teamsDir, fileName);
    const stat = fs.statSync(filePath);
    const content = fs.readFileSync(filePath, 'utf-8');
    const contentHash = computeContentHash(content);
    const teamId = fileName.replace(/\.ya?ml$/i, '');

    try {
      const raw = readYamlFile(filePath);
      return normalizeTeamDefinition(teamId, filePath, raw, stat, contentHash);
    } catch (err) {
      return buildParseErrorDefinition(teamId, filePath, stat, contentHash, err);
    }
  });
}

function extractFilledCount(teamId: string, relationships: EntityRelationship[]): number {
  return relationships.filter((row) =>
    row.relation_type === 'member_of'
    && row.source_type === 'session'
    && row.target_type === 'team'
    && row.target_id === teamId,
  ).length;
}

function extractAssignedProjectIds(team: TeamDefinition, relationships: EntityRelationship[]): string[] {
  const relatedProjects = relationships
    .filter((row) =>
      row.relation_type === 'assigned_to'
      && row.source_type === 'team'
      && row.target_type === 'project'
      && row.source_id === team.id,
    )
    .map((row) => row.target_id);

  if (relatedProjects.length > 0) {
    return Array.from(new Set(relatedProjects));
  }
  return Array.from(new Set(team.project_ids));
}

export async function listTeams(): Promise<TeamCard[]> {
  const definitions = loadAllTeamDefinitions();
  if (definitions.length === 0) {
    return [];
  }

  const cards = await Promise.all(definitions.map(async (team) => {
    let relationships: EntityRelationship[] = [];
    try {
      relationships = await callSessionStore(['get_relationships', 'team', team.id]) as EntityRelationship[];
    } catch {
      relationships = [];
    }

    const slotCount = team.slots.reduce((sum, slot) => sum + slot.count, 0);

    return {
      entity_id: `team:${team.id}` as EntityId,
      entity_type: 'team',
      display_name: team.name,
      created_at: team.created_at,
      last_activity: (() => {
        try {
          return fs.statSync(team.source_path).mtime.toISOString();
        } catch {
          return team.indexed_at || team.created_at;
        }
      })(),
      tags: team.tags,
      description: team.description,
      status: team.status,
      slot_count: slotCount,
      filled_count: extractFilledCount(team.id, relationships),
      project_ids: extractAssignedProjectIds(team, relationships),
      source_path: team.source_path,
      availability: team.availability,
    } satisfies TeamCard;
  }));

  return cards.sort((a, b) => a.display_name.localeCompare(b.display_name));
}
