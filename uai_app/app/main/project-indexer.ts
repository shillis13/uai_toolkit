/**
 * ProjectIndexer — discovers devTrees and projects on the filesystem.
 *
 * Workstream 2G: Projects Entity
 *
 * Scans ~/Documents/AI/devTrees/ for devTree directories and
 * ai_general/projects/ for project metadata. Returns ProjectCard[]
 * for the renderer to display.
 *
 * This is a read-only indexer. Projects are discovered, not created
 * through the app. The filesystem is the source of truth.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { execFile } from 'node:child_process';
import type { ProjectCard } from '@uai/shared/cards';
import type { EntityId } from '@uai/shared/types';
import { aiRootMain as getAiRootMain } from './paths';


function getDevTreesDir(): string {
  return path.join(os.homedir(), 'Documents/AI/devTrees');
}

function getProjectsDir(): string {
  return path.join(getAiRootMain(), 'ai_general', 'projects');
}

// ─── Git helpers ─────────────────────────────────────────────────────────

function gitBranch(gitDir: string): Promise<string | null> {
  return new Promise((resolve) => {
    execFile('git', ['-C', gitDir, 'branch', '--show-current'], { timeout: 5000 }, (err, stdout) => {
      if (err) { resolve(null); return; }
      resolve(stdout.trim() || null);
    });
  });
}

function gitStatus(gitDir: string): Promise<'clean' | 'dirty' | 'unknown'> {
  return new Promise((resolve) => {
    execFile('git', ['-C', gitDir, 'status', '--porcelain'], { timeout: 5000 }, (err, stdout) => {
      if (err) { resolve('unknown'); return; }
      resolve(stdout.trim().length === 0 ? 'clean' : 'dirty');
    });
  });
}

// ─── DevTree Discovery ───────────────────────────────────────────────────

interface DevTreeInfo {
  name: string;
  path: string;
  aiGeneralPath: string;
  gitPath: string | null;
}

function discoverDevTrees(): DevTreeInfo[] {
  const devTreesDir = getDevTreesDir();
  if (!fs.existsSync(devTreesDir)) return [];

  const entries = fs.readdirSync(devTreesDir, { withFileTypes: true });
  const devTrees: DevTreeInfo[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;

    const treePath = path.join(devTreesDir, entry.name);
    const aiGeneralPath = path.join(treePath, 'ai_general');

    if (!fs.existsSync(aiGeneralPath)) continue;

    // Check for git (worktree .git file or .git directory)
    const gitFile = path.join(aiGeneralPath, '.git');
    const hasGit = fs.existsSync(gitFile);

    devTrees.push({
      name: entry.name.replace(/^AI_ROOT_/, ''),
      path: treePath,
      aiGeneralPath,
      gitPath: hasGit ? aiGeneralPath : null,
    });
  }

  return devTrees;
}

// ─── project.yml Parsing ─────────────────────────────────────────────────

const VALID_LIFECYCLE: ReadonlySet<string> = new Set(['active', 'sandbox', 'paused', 'complete', 'archived']);

interface ProjectYmlMeta {
  name: string | null;
  goal: string | null;
  lifecycle_status: 'active' | 'paused' | 'complete' | 'archived' | null;
  tags: string[];
}

/**
 * Parse a project.yml file using simple regex (no YAML library).
 * All fields are optional; returns null values for anything missing.
 */
function parseProjectYml(content: string): ProjectYmlMeta {
  const meta: ProjectYmlMeta = { name: null, goal: null, lifecycle_status: null, tags: [] };

  // name: (single-line scalar)
  const nameMatch = content.match(/^name:\s*(.+)$/m);
  if (nameMatch) meta.name = nameMatch[1].trim().replace(/^["']|["']$/g, '');

  // goal: (single-line or YAML >- folded scalar)
  const goalFolded = content.match(/^goal:\s*>-?\s*\n((?:[ \t]+.+\n?)+)/m);
  if (goalFolded) {
    meta.goal = goalFolded[1].replace(/\n\s*/g, ' ').trim();
  } else {
    const goalMatch = content.match(/^goal:\s*(.+)$/m);
    if (goalMatch) meta.goal = goalMatch[1].trim().replace(/^["']|["']$/g, '');
  }

  // lifecycle_status:
  const statusMatch = content.match(/^lifecycle_status:\s*(.+)$/m);
  if (statusMatch) {
    const raw = statusMatch[1].trim();
    if (VALID_LIFECYCLE.has(raw)) {
      meta.lifecycle_status = raw as ProjectYmlMeta['lifecycle_status'];
    }
  }

  // tags: [foo, bar] (inline flow sequence)
  const tagsMatch = content.match(/^tags:\s*\[([^\]]*)\]/m);
  if (tagsMatch) {
    meta.tags = tagsMatch[1]
      .split(',')
      .map(t => t.trim().replace(/^["']|["']$/g, ''))
      .filter(Boolean);
  }

  return meta;
}

/**
 * Look for project.yml at a project root directory and parse it.
 * Returns null if the file doesn't exist, or a parse result otherwise.
 */
function readProjectYml(projectRoot: string): { meta: ProjectYmlMeta; filePath: string } | null {
  const ymlPath = path.join(projectRoot, 'project.yml');
  if (!fs.existsSync(ymlPath)) return null;

  try {
    const content = fs.readFileSync(ymlPath, 'utf-8');
    return { meta: parseProjectYml(content), filePath: ymlPath };
  } catch {
    return null;
  }
}

// ─── Project Metadata Discovery ──────────────────────────────────────────

interface ProjectMeta {
  id: string;
  name: string;
  source_path: string;
  working_dir: string;
  category: string | null;  // parent organizing dir name, null for top-level
}

/** Dirs that are structural, not projects */
const SKIP_DIRS = new Set(['archive', '_archive', '_draftProjects']);

/**
 * Determine if a directory is an organizing dir (contains project subdirs)
 * vs a project itself. An organizing dir has no project.yml and contains
 * at least one subdirectory that isn't hidden/skipped.
 */
function isOrganizingDir(dirPath: string): boolean {
  // If it has a project.yml, it's a project
  if (fs.existsSync(path.join(dirPath, 'project.yml'))) return false;

  const children = fs.readdirSync(dirPath, { withFileTypes: true });
  const childDirs = children.filter(
    e => e.isDirectory() && !e.name.startsWith('.') && !SKIP_DIRS.has(e.name)
  );

  // If every child dir itself has subdirs or files that look project-like,
  // treat this as an organizing dir. Simple heuristic: if it has child dirs
  // and no significant top-level files (besides .DS_Store), it's organizing.
  if (childDirs.length === 0) return false;

  const childFiles = children.filter(
    e => e.isFile() && !e.name.startsWith('.') && e.name !== '.DS_Store'
  );
  // Organizing dirs typically have no top-level files (or just metadata)
  // Projects typically have code/docs at the root level
  return childFiles.length === 0;
}

function discoverProjects(): ProjectMeta[] {
  const projectsDir = getProjectsDir();
  if (!fs.existsSync(projectsDir)) return [];

  const entries = fs.readdirSync(projectsDir, { withFileTypes: true });
  const projects: ProjectMeta[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith('.') || SKIP_DIRS.has(entry.name)) continue;

    const dirPath = path.join(projectsDir, entry.name);

    if (isOrganizingDir(dirPath)) {
      // Scan children as projects under this category
      const categoryName = entry.name;
      const children = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const child of children) {
        if (!child.isDirectory() || child.name.startsWith('.') || SKIP_DIRS.has(child.name)) continue;
        const childPath = path.join(dirPath, child.name);
        projects.push({
          id: `${categoryName}/${child.name}`,
          name: child.name.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
          source_path: childPath,
          working_dir: childPath,
          category: categoryName,
        });
      }
    } else {
      // Top-level project
      projects.push({
        id: entry.name,
        name: entry.name.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        source_path: dirPath,
        working_dir: dirPath,
        category: null,
      });
    }
  }

  return projects;
}

// ─── Session Counting ────────────────────────────────────────────────────

function countSessionsForProject(projectDir: string, allSessionDirs: string[]): number {
  const normalized = path.resolve(projectDir);
  return allSessionDirs.filter(sd => {
    const normSd = path.resolve(sd);
    return normSd === normalized || normSd.startsWith(normalized + path.sep);
  }).length;
}

// ─── Public API ──────────────────────────────────────────────────────────

export interface ProjectListOptions {
  sessionProjectDirs?: string[];  // project_dir values from all sessions, for counting
  includeHidden?: boolean;        // include ui_hidden entities (todo_0532); default false
}

/**
 * Flip the `ui_hidden` visibility flag in an entity's source yml (todo_0532).
 * This is a PURE flag edit — it never moves, renames, or deletes any directory or
 * file. `sourcePath` is the exact yml the card was read from (registry entry,
 * project marker, etc.), so the write always lands on the file the UI reads.
 * Rewrites (or appends) a single `ui_hidden: true|false` line, preserving the rest.
 */
export function setEntityHidden(sourcePath: string, hidden: boolean): void {
  if (!sourcePath || !fs.existsSync(sourcePath)) {
    throw new Error(`setEntityHidden: source file not found: ${sourcePath}`);
  }
  const raw = fs.readFileSync(sourcePath, 'utf-8');
  const lines = raw.split('\n');
  const kept = lines.filter(l => !/^ui_hidden:\s*/.test(l));
  // Drop a trailing empty line so we re-append cleanly, then restore one newline.
  while (kept.length && kept[kept.length - 1].trim() === '') kept.pop();
  kept.push(`ui_hidden: ${hidden ? 'true' : 'false'}`);
  fs.writeFileSync(sourcePath, kept.join('\n') + '\n');
}

// Edit a single entry in an indented block-map (`<blockKey>:`) in a registry yml,
// via direct line editing (same reversible approach as setEntityHidden, todo_0532).
// Three-state `value`:
//   - a string → `key: value`  (set / replace)
//   - ''       → `key:`        (keep an empty slot for the key)
//   - null     → (remove the `key:` line entirely)
// Creates the block if absent; drops the block if it becomes empty. Preserves every
// other line and the file's other keys. Edits the ENTITY's own source yml — the app
// displays this external data but the file stays the source of truth (principle #6).
function editBlockMapEntry(sourcePath: string, blockKey: string, entryKey: string, value: string | null): void {
  if (!sourcePath || !fs.existsSync(sourcePath)) {
    throw new Error(`editBlockMapEntry: source file not found: ${sourcePath}`);
  }
  const key = entryKey.trim();
  if (!key) throw new Error('editBlockMapEntry: entry key is required');
  const valuePart = value ? ` ${value}` : '';         // string → " value"; '' → "" (empty slot)
  const lines = fs.readFileSync(sourcePath, 'utf-8').split('\n');
  const entryRe = /^([ \t]+)([A-Za-z0-9_-]+):[ \t]*(.*)$/;
  const headRe = new RegExp(`^${blockKey}:[ \\t]*$`);

  const blockStart = lines.findIndex(l => headRe.test(l));
  if (blockStart === -1) {
    if (value === null) return;                  // nothing to remove
    const kept = [...lines];
    while (kept.length && kept[kept.length - 1].trim() === '') kept.pop();
    kept.push(`${blockKey}:`, `  ${key}:${valuePart}`);
    fs.writeFileSync(sourcePath, kept.join('\n') + '\n');
    return;
  }

  // Gather the indented body of the block (until a non-indented, non-blank line).
  let i = blockStart + 1;
  const body: string[] = [];
  for (; i < lines.length; i++) {
    if (lines[i].trim() === '') { body.push(lines[i]); continue; }
    if (lines[i].length - lines[i].trimStart().length === 0) break;  // dedent ends block
    body.push(lines[i]);
  }
  const blockEnd = i;

  let found = false;
  const newBody: string[] = [];
  for (const l of body) {
    if (l.trim() === '') continue;               // drop blank lines — keep the map tight
    const m = l.match(entryRe);
    if (m && m[2].toLowerCase() === key.toLowerCase()) {
      found = true;
      if (value !== null) newBody.push(`${m[1]}${key}:${valuePart}`);
      // value === null → drop the line (delete the entry)
    } else {
      newBody.push(l);
    }
  }
  if (!found && value !== null) {
    const anyEntry = body.map(l => l.match(entryRe)).find(Boolean) as RegExpMatchArray | undefined;
    newBody.push(`${anyEntry ? anyEntry[1] : '  '}${key}:${valuePart}`);
  }

  const bodyHasEntry = newBody.some(l => entryRe.test(l));
  const rebuilt = [...lines.slice(0, blockStart)];
  if (bodyHasEntry) {
    rebuilt.push(lines[blockStart]);             // `<blockKey>:`
    while (newBody.length && newBody[newBody.length - 1].trim() === '') newBody.pop();
    rebuilt.push(...newBody);
  }
  rebuilt.push(...lines.slice(blockEnd));
  let text = rebuilt.join('\n');
  if (!text.endsWith('\n')) text += '\n';
  fs.writeFileSync(sourcePath, text);
}

// Role holder in `role_assignments:` — a name assigns, '' keeps an empty slot, null deletes the role.
export function setRoleAssignment(sourcePath: string, role: string, member: string | null): void {
  editBlockMapEntry(sourcePath, 'role_assignments', role, member);
}

// Context reference for a role in `role_contexts:` — a string sets it, null clears it.
export function setRoleContext(sourcePath: string, role: string, context: string | null): void {
  editBlockMapEntry(sourcePath, 'role_contexts', role, context);
}

// Replace a top-level `<key>: [..]` inline list in a registry yml. Same
// direct-source-edit approach as above; reversible. New keys are inserted before
// the role_assignments block (else appended).
function setInlineListField(sourcePath: string, key: string, values: string[]): void {
  if (!sourcePath || !fs.existsSync(sourcePath)) {
    throw new Error(`setInlineListField: source file not found: ${sourcePath}`);
  }
  const clean = values.map(v => v.trim()).filter(Boolean);
  const line = `${key}: [${clean.map(v => quoteRegistryScalar(v, true)).join(', ')}]`;
  const lines = fs.readFileSync(sourcePath, 'utf-8').split('\n');
  const keyRe = new RegExp(`^${key}:`);
  const idx = lines.findIndex(l => keyRe.test(l));
  if (idx >= 0) {
    lines[idx] = line;
    // If the old value was a block list (following `- item` lines), drop them.
    let j = idx + 1;
    while (j < lines.length && /^[ \t]*-[ \t]+/.test(lines[j])) lines.splice(j, 1);
    let text = lines.join('\n');
    if (!text.endsWith('\n')) text += '\n';
    fs.writeFileSync(sourcePath, text);
    return;
  }
  const kept = [...lines];
  while (kept.length && kept[kept.length - 1].trim() === '') kept.pop();
  const raIdx = kept.findIndex(l => /^role_assignments:/.test(l));
  if (raIdx >= 0) kept.splice(raIdx, 0, line); else kept.push(line);
  fs.writeFileSync(sourcePath, kept.join('\n') + '\n');
}

// Team/project members (by display name).
export function setMembers(sourcePath: string, members: string[]): void {
  setInlineListField(sourcePath, 'members', members);
}

// Project Playbook folders — top-level dir names under working_dir (todo_0320).
export function setPlaybook(sourcePath: string, folders: string[]): void {
  setInlineListField(sourcePath, 'playbook', folders);
}

// Render a scalar so it round-trips through BOTH yaml and the app's quote-stripping
// regex parser. This mirrors projects_mgr._reg_value: use a bare value when safe,
// otherwise choose a quote style the regex reader does not need to unescape. Reject
// values neither reader can represent identically instead of silently corrupting
// them (todo_0583 / todo_0633).
function quoteRegistryScalar(value: string, flow = false): string {
  const s = String(value);
  if (/[\r\n]/.test(s)) throw new Error('Registry values must be single-line');
  // regList splits on every comma without honoring quotes.
  if (flow && s.includes(',')) throw new Error('Registry list items cannot contain commas');
  const typey = /^(null|~|none|true|false|yes|no|on|off)$/i.test(s);
  const numy = /^[-+]?\d+(\.\d+)?$/.test(s);
  const sexagesimal = /^\d+(?::\d+)+$/.test(s);
  const leadingIndicators = "!&*?|>%@`\"'#,-[]{} ";
  const needsQuote = s === '' || s !== s.trim() || typey || numy
    || sexagesimal || leadingIndicators.includes(s[0] || '')
    || s.includes(': ') || s.endsWith(':') || s.includes(' #')
    || (flow && /[\[\]{}:]/.test(s));
  if (!needsQuote) return s;
  if (!s.includes("'")) return `'${s}'`;
  if (!s.includes('"') && !s.includes('\\')) return `"${s}"`;
  throw new Error(
    'Registry value cannot round-trip through the app parser when quoting is ' +
    'required and it contains both quote styles or a backslash plus single quote',
  );
}

// Edit or insert a top-level scalar `<key>: <value>` in a registry yml, quoting
// per regScalar. New keys are inserted before the role_assignments block (else
// appended) — same direct-source-edit approach as the list/map editors above.
function setScalarField(sourcePath: string, key: string, value: string): void {
  if (!sourcePath || !fs.existsSync(sourcePath)) {
    throw new Error(`setScalarField: source file not found: ${sourcePath}`);
  }
  const line = `${key}: ${quoteRegistryScalar(value)}`;
  const lines = fs.readFileSync(sourcePath, 'utf-8').split('\n');
  const idx = lines.findIndex(l => new RegExp(`^${key}:`).test(l));
  if (idx >= 0) {
    lines[idx] = line;
  } else {
    while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
    const raIdx = lines.findIndex(l => /^role_assignments:/.test(l));
    if (raIdx >= 0) lines.splice(raIdx, 0, line); else lines.push(line);
  }
  let text = lines.join('\n');
  if (!text.endsWith('\n')) text += '\n';
  fs.writeFileSync(sourcePath, text);
}

// Update a team/project's scalar metadata in its registry yml. Internal caller
// field names map to registry fields: description → goal, status → lifecycle_status.
// Replaces the legacy teams_mgr.py `update` (which wrote data/teams — todo_0633).
export function updateEntity(
  sourcePath: string,
  fields: { name?: string; description?: string; tags?: string[]; status?: string },
): void {
  // Validate every supplied value before the first write so a deterministic
  // serialization error cannot leave a half-updated entity.
  if (fields.name != null) quoteRegistryScalar(fields.name);
  if (fields.description != null) quoteRegistryScalar(fields.description);
  if (fields.tags != null) fields.tags.forEach(v => quoteRegistryScalar(v.trim(), true));
  const status = fields.status?.trim();
  if (status != null && !VALID_LIFECYCLE.has(status)) {
    throw new Error(`invalid lifecycle status: ${status}`);
  }
  if (fields.name != null) setScalarField(sourcePath, 'name', fields.name);
  if (fields.description != null) setScalarField(sourcePath, 'goal', fields.description);
  if (status != null) setScalarField(sourcePath, 'lifecycle_status', status);
  if (fields.tags != null) setInlineListField(sourcePath, 'tags', fields.tags);
}

// ─── Registry: ai_general/data/projects/<id>.{proj,team}.yml ─────────────────
// Filesystem-is-the-source-of-truth registry (no SQLite). Reading = list the dir
// + parse. id+type live in the filename; resolve by id, glob the type.
// Design: docs/designs/2026-06-22-project-team-registry-design.md
function getRegistryDir(): string {
  return path.join(getAiRootMain(), 'ai_general', 'data', 'projects');
}

function regScalar(content: string, key: string): string | null {
  const m = content.match(new RegExp(`^${key}:[ \\t]*(.+)$`, 'm'));
  if (!m) return null;
  const v = m[1].trim().replace(/^["']|["']$/g, '');
  return v === 'null' || v === '' ? null : v;
}
function regList(content: string, key: string): string[] {
  const m = content.match(new RegExp(`^${key}:[ \\t]*\\[(.*)\\]`, 'm'));
  if (!m) return [];
  return m[1].split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
}
// Parse an indented mapping block (e.g. `role_assignments:` → {role: member(s)}).
// Each entry's value may be a scalar (`lead: Hamilton`) or an inline list
// (`reviewers: [A, B]`); both normalize to a string[]. Stops at the next
// top-level (unindented) key, so a following block like `comms_plan:` is not
// swallowed. Registry files use inline scalars/lists only (no block sequences).
function regBlockMap(content: string, key: string): Record<string, string[]> {
  const lines = content.split(/\r?\n/);
  const out: Record<string, string[]> = {};
  let inBlock = false;
  let baseIndent = -1;
  for (const line of lines) {
    if (!inBlock) {
      if (new RegExp(`^${key}:[ \\t]*$`).test(line)) inBlock = true;
      continue;
    }
    if (line.trim() === '') continue;
    const indent = line.length - line.trimStart().length;
    if (indent === 0) break;               // dedent to top level ends the block
    if (baseIndent < 0) baseIndent = indent;
    if (indent < baseIndent) break;
    const m = line.trim().match(/^([A-Za-z0-9_-]+):[ \t]*(.*)$/);
    if (!m) continue;
    const val = m[2].trim();
    let members: string[];
    if (val.startsWith('[') && val.endsWith(']')) {
      members = val.slice(1, -1).split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
    } else if (val === '' || val === 'null') {
      members = [];
    } else {
      members = [val.replace(/^["']|["']$/g, '')];
    }
    out[m[1]] = members;
  }
  return out;
}

function listRegistryEntities(includeHidden = false, hiddenOnly = false): ProjectCard[] {
  const dir = getRegistryDir();
  if (!fs.existsSync(dir)) return [];
  const cards: ProjectCard[] = [];
  for (const f of fs.readdirSync(dir)) {
    const isTeam = f.endsWith('.team.yml');
    if (!isTeam && !f.endsWith('.proj.yml')) continue;
    const id = f.replace(/\.(proj|team)\.yml$/, '');
    let content = '';
    try { content = fs.readFileSync(path.join(dir, f), 'utf-8'); } catch { continue; }
    // ui_hidden: a pure UI visibility flag (todo_0532). Hidden entities are dropped
    // from the default list; nothing on disk is moved or deleted. includeHidden shows
    // them; hiddenOnly returns ONLY hidden ones (backs the Restore-hidden UI).
    const isHidden = regScalar(content, 'ui_hidden') === 'true';
    if (hiddenOnly) { if (!isHidden) continue; }
    else if (!includeHidden && isHidden) continue;
    const members = regList(content, 'members');
    const tags = regList(content, 'tags').filter(t => t !== 'project' && t !== 'team');
    const workingDir = regScalar(content, 'working_dir');
    cards.push({
      entity_id: `project:${id}` as EntityId,
      entity_type: 'project',
      display_name: regScalar(content, 'name') || id,
      created_at: regScalar(content, 'created') || '',
      last_activity: '',
      tags: [isTeam ? 'team' : 'project', ...tags],
      icon: undefined,
      color: undefined,
      project_id: id,
      working_dir: workingDir || '',
      branch: null,
      git_status: 'unknown',
      lifecycle_status: (regScalar(content, 'lifecycle_status') as ProjectYmlMeta['lifecycle_status']) ?? null,
      goal: regScalar(content, 'goal'),
      // Curated member list for BOTH teams and projects (todo_0320) — projects
      // no longer derive membership from the working dir.
      assigned_ais: members,
      role_assignments: regBlockMap(content, 'role_assignments'),
      role_contexts: regBlockMap(content, 'role_contexts'),
      playbook: regList(content, 'playbook'),
      source_path: path.join(dir, f),
      availability: 'available',
      session_count: members.length,
      category: isTeam ? 'team' : null,
    });
  }
  return cards;
}

// Only the ui_hidden registry entities (projects + teams) — backs the "Restore
// hidden" UI. Restoring flips ui_hidden false via the existing setHidden command.
export function listHiddenRegistryEntities(): ProjectCard[] {
  return listRegistryEntities(true, true);
}

// Promote a Team to a Project (todo_0320). A team's "team-ness" is just its
// `.team.yml` filename, so promotion is: give it a home directory and rename the
// registry file `.team.yml` → `.proj.yml`. Members, roles, and role contexts all
// carry over unchanged (same file content). Creates the home dir (with a docs/
// subdir) under ai_general/work/projects/<slug>. Throws if the dir or target file
// already exists. Editing the entity's own registry file (principle #6).
export function promoteTeamToProject(sourcePath: string, dirName?: string): { workingDir: string; newSourcePath: string } {
  if (!sourcePath || !fs.existsSync(sourcePath)) {
    throw new Error(`promoteTeamToProject: source not found: ${sourcePath}`);
  }
  if (!sourcePath.endsWith('.team.yml')) {
    throw new Error('promoteTeamToProject: source is not a .team.yml team file');
  }
  const root = getAiRootMain();
  let content = fs.readFileSync(sourcePath, 'utf-8');
  const nameM = content.match(/^name:[ \t]*(.+)$/m);
  const rawName = (dirName || (nameM ? nameM[1].trim().replace(/^["']|["']$/g, '') : path.basename(sourcePath, '.team.yml')));
  const slug = rawName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'project';
  const workingDir = path.join(root, 'ai_general', 'work', 'projects', slug);
  if (fs.existsSync(workingDir)) throw new Error(`working dir already exists: ${workingDir}`);
  const newSourcePath = sourcePath.replace(/\.team\.yml$/, '.proj.yml');
  if (fs.existsSync(newSourcePath)) throw new Error(`a project registry file already exists: ${newSourcePath}`);

  // Point working_dir at the new home (teams carry working_dir: null).
  if (/^working_dir:.*$/m.test(content)) {
    content = content.replace(/^working_dir:.*$/m, `working_dir: ${workingDir}`);
  } else {
    content = content.replace(/\n*$/, '\n') + `working_dir: ${workingDir}\n`;
  }

  const docsDir = path.join(workingDir, 'docs');
  let targetWritten = false;
  try {
    // Create only this operation's new paths. `wx` closes the race between the
    // existence check above and the write, while keeping the team registry intact
    // until the complete project registry is safely on disk.
    fs.mkdirSync(workingDir);
    fs.mkdirSync(docsDir);
    fs.writeFileSync(newSourcePath, content, { flag: 'wx' });
    targetWritten = true;
    fs.unlinkSync(sourcePath);
    return { workingDir, newSourcePath };
  } catch (err) {
    // Best-effort rollback only artifacts this call created. Non-recursive rmdir
    // refuses to remove either directory if anything else appeared there.
    if (targetWritten && fs.existsSync(sourcePath) && fs.existsSync(newSourcePath)) {
      try { fs.unlinkSync(newSourcePath); } catch { /* leave both registries; no data loss */ }
    }
    try { fs.rmdirSync(docsDir); } catch { /* absent or no longer empty */ }
    try { fs.rmdirSync(workingDir); } catch { /* absent or no longer empty */ }
    throw err;
  }
}

// Create a NEW team as an app-registry entity: data/projects/<slug>.team.yml in
// the app-compatible flat format (the registry the UI actually reads). Replaces the
// legacy teams_mgr.py `create`, which wrote data/teams/<id>.yml — a store the UI
// never reads, so created teams silently never appeared (todo_0633). working_dir is
// null (a team gets a home only when promoted). Throws on id collision. `wx` closes
// the check-then-write race, matching promoteTeamToProject.
export function createTeam(
  name: string,
  description?: string,
  tags?: string[],
): { id: string; sourcePath: string } {
  const cleanName = String(name).trim();
  if (!cleanName) throw new Error('team name is required');
  const slug = cleanName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'team';
  const cleanTags = (tags || []).map(t => t.trim()).filter(Boolean);
  // Render before touching the filesystem so unrepresentable input has no side effect.
  const lines = [
    `id: ${slug}`,
    `name: ${quoteRegistryScalar(cleanName)}`,
    `goal: ${quoteRegistryScalar(description || '')}`,
    'lifecycle_status: active',
    `tags: [${cleanTags.map(t => quoteRegistryScalar(t, true)).join(', ')}]`,
    'working_dir: null',
    `created: ${new Date().toISOString()}`,
    'members: []',
  ];
  const dir = getRegistryDir();
  fs.mkdirSync(dir, { recursive: true });
  for (const suffix of ['.team.yml', '.proj.yml']) {
    if (fs.existsSync(path.join(dir, slug + suffix))) {
      throw new Error(`a project/team with id '${slug}' already exists`);
    }
  }
  const sourcePath = path.join(dir, slug + '.team.yml');
  fs.writeFileSync(sourcePath, lines.join('\n') + '\n', { flag: 'wx' });
  return { id: slug, sourcePath };
}

export async function listProjects(opts?: ProjectListOptions): Promise<ProjectCard[]> {
  const devTrees = discoverDevTrees();
  const projectMetas = discoverProjects();
  const sessionDirs = opts?.sessionProjectDirs || [];
  const cards: ProjectCard[] = [];

  // Index devTrees as projects
  for (const dt of devTrees) {
    const branch = dt.gitPath ? await gitBranch(dt.gitPath) : null;
    const status = dt.gitPath ? await gitStatus(dt.gitPath) : 'unknown';

    // Check for project.yml at the devTree root
    const projYml = readProjectYml(dt.path);
    const baseTags = ['devtree'];
    const mergedTags = projYml ? [...baseTags, ...projYml.meta.tags.filter(t => !baseTags.includes(t))] : baseTags;

    cards.push({
      entity_id: `project:devtree_${dt.name}` as EntityId,
      entity_type: 'project',
      display_name: projYml?.meta.name || dt.name,
      created_at: '',
      last_activity: '',
      tags: mergedTags,
      icon: undefined,
      color: undefined,
      project_id: `devtree_${dt.name}`,
      working_dir: dt.path,
      branch,
      git_status: status,
      lifecycle_status: projYml?.meta.lifecycle_status ?? null,
      goal: projYml?.meta.goal ?? null,
      assigned_ais: [],
      source_path: projYml?.filePath || dt.aiGeneralPath,
      availability: 'available',
      session_count: countSessionsForProject(dt.path, sessionDirs),
      category: null,
    });
  }

  // Index ai_general/projects/ entries (that aren't already represented by a devTree)
  const devTreeWorkingDirs = new Set(devTrees.map(dt => dt.path));

  for (const pm of projectMetas) {
    // Check if this project has a corresponding devTree
    const matchingDevTree = devTrees.find(dt =>
      dt.aiGeneralPath.includes(pm.id) ||
      dt.name.toLowerCase().includes(pm.id.replace(/_/g, '-').toLowerCase())
    );

    if (matchingDevTree) {
      // Already indexed as a devTree — update the devTree card with project metadata
      const existing = cards.find(c => c.working_dir === matchingDevTree.path);
      if (existing) {
        existing.source_path = pm.source_path;
      }
      continue;
    }

    // Check for project.yml at the project directory root
    const projYml = readProjectYml(pm.working_dir);
    const baseTags = ['project'];
    const mergedTags = projYml ? [...baseTags, ...projYml.meta.tags.filter(t => !baseTags.includes(t))] : baseTags;

    cards.push({
      entity_id: `project:${pm.id}` as EntityId,
      entity_type: 'project',
      display_name: projYml?.meta.name || pm.name,
      created_at: '',
      last_activity: '',
      tags: mergedTags,
      icon: undefined,
      color: undefined,
      project_id: pm.id,
      working_dir: pm.working_dir,
      branch: null,
      git_status: 'unknown',
      lifecycle_status: projYml?.meta.lifecycle_status ?? null,
      goal: projYml?.meta.goal ?? null,
      assigned_ais: [],
      source_path: projYml?.filePath || pm.source_path,
      availability: 'available',
      session_count: countSessionsForProject(pm.working_dir, sessionDirs),
      category: pm.category,
    });
  }

  // Registry entities (ai_general/data/projects) are authoritative — prepend them
  // and drop any scanned dir that a registry entry already represents (by id).
  const registryCards = listRegistryEntities(opts?.includeHidden);
  const regIds = new Set(registryCards.map(c => c.project_id));
  return [...registryCards, ...cards.filter(c => !regIds.has(c.project_id))];
}
