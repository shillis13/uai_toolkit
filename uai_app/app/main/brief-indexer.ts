/**
 * BriefIndexer — scans session briefs directory and returns BriefCard objects.
 *
 * Reads YAML files from ai_general/data/session_briefs/, parses brief_meta
 * frontmatter, and maps to BriefCard for the card store.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import type { BriefCard } from '@uai/shared/cards';
import type { EntityId } from '@uai/shared/types';
import { aiRootMain as getAiRootMain } from './paths';


function getBriefsDir(): string {
  return path.join(getAiRootMain(), 'ai_general', 'data', 'session_briefs');
}

interface BriefMeta {
  name?: string;
  description?: string;
  status?: string;
  created?: string;
  condenser_session?: string;
}

function parseYamlFrontmatter(content: string): BriefMeta {
  const meta: BriefMeta = {};

  // Try brief_meta: block first (has name, description, status, created, condenser_session)
  const briefMetaMatch = content.match(/brief_meta:\s*\n([\s\S]*?)(?:\n\w|\n---|$)/);
  if (briefMetaMatch) {
    const block = briefMetaMatch[1];
    const nameMatch = block.match(/^\s+name:\s*(.+)$/m);
    const descMatch = block.match(/^\s+description:\s*(.+)$/m);
    const statusMatch = block.match(/^\s+status:\s*(.+)$/m);
    const createdMatch = block.match(/^\s+created:\s*'?(.+?)'?\s*$/m);
    const condenserMatch = block.match(/^\s+condenser_session:\s*(.+)$/m);

    if (nameMatch) meta.name = nameMatch[1].trim();
    if (descMatch) meta.description = descMatch[1].trim();
    if (statusMatch) meta.status = statusMatch[1].trim();
    if (createdMatch) meta.created = createdMatch[1].trim();
    if (condenserMatch) meta.condenser_session = condenserMatch[1].trim();
    return meta;
  }

  // Fall back to meta: block (has topic, status, objective)
  const metaMatch = content.match(/meta:\s*\n([\s\S]*?)(?:\n\w|\n---|$)/);
  if (metaMatch) {
    const block = metaMatch[1];
    const topicMatch = block.match(/^\s+topic:\s*"?(.+?)"?\s*$/m);
    const statusMatch = block.match(/^\s+status:\s*(.+)$/m);
    const objectiveMatch = block.match(/^\s+objective:\s*(.+)$/m);

    // Map topic to description (name will fall back to filename stem)
    if (topicMatch) meta.description = topicMatch[1].trim();
    if (statusMatch) meta.status = statusMatch[1].trim();
    if (objectiveMatch && !meta.description) meta.description = objectiveMatch[1].trim();
  }

  return meta;
}

function collectYamlFiles(dir: string, relPrefix: string = ''): Array<{ filePath: string; relDir: string; file: string }> {
  const results: Array<{ filePath: string; relDir: string; file: string }> = [];
  if (!fs.existsSync(dir)) return results;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectYamlFiles(fullPath, relPrefix ? `${relPrefix}/${entry.name}` : entry.name));
    } else if (entry.name.endsWith('.yml') || entry.name.endsWith('.yaml')) {
      results.push({ filePath: fullPath, relDir: relPrefix, file: entry.name });
    }
  }
  return results;
}

export function indexBriefs(): BriefCard[] {
  const briefsDir = getBriefsDir();
  if (!fs.existsSync(briefsDir)) return [];

  const files = collectYamlFiles(briefsDir);
  const cards: BriefCard[] = [];

  for (const { filePath, relDir, file } of files) {
    try {
      const stat = fs.statSync(filePath);
      const content = fs.readFileSync(filePath, 'utf-8');
      const meta = parseYamlFrontmatter(content);
      const stem = file.replace(/\.ya?ml$/, '');
      const qualifiedName = relDir ? `${relDir}/${stem}` : stem;

      cards.push({
        entity_id: `brief:${qualifiedName}` as EntityId,
        entity_type: 'brief',
        display_name: meta.name || stem,
        created_at: meta.created || stat.birthtime.toISOString(),
        last_activity: stat.mtime.toISOString(),
        tags: [],
        name: qualifiedName,
        description: meta.description || null,
        status: (meta.status as 'active' | 'superseded' | 'archived') || 'active',
        brief_path: filePath,
        file_size: stat.size,
        condenser_session: meta.condenser_session || null,
        content_hash: null,
      });
    } catch (err) {
      console.warn(`[brief-indexer] Failed to load brief "${file}":`, err);
    }
  }

  return cards.sort((a, b) => b.last_activity.localeCompare(a.last_activity));
}
