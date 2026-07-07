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

// ─── Paths ───────────────────────────────────────────────────────────────

function getAiRootMain(): string {
  return process.env.AI_ROOT_MAIN || path.join(os.homedir(), 'AI/ai_root');
}

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

function listRegistryEntities(): ProjectCard[] {
  const dir = getRegistryDir();
  if (!fs.existsSync(dir)) return [];
  const cards: ProjectCard[] = [];
  for (const f of fs.readdirSync(dir)) {
    const isTeam = f.endsWith('.team.yml');
    if (!isTeam && !f.endsWith('.proj.yml')) continue;
    const id = f.replace(/\.(proj|team)\.yml$/, '');
    let content = '';
    try { content = fs.readFileSync(path.join(dir, f), 'utf-8'); } catch { continue; }
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
      assigned_ais: isTeam ? members : [],
      source_path: path.join(dir, f),
      availability: 'available',
      session_count: isTeam ? members.length : 0,
      category: isTeam ? 'team' : null,
    });
  }
  return cards;
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
  const registryCards = listRegistryEntities();
  const regIds = new Set(registryCards.map(c => c.project_id));
  return [...registryCards, ...cards.filter(c => !regIds.has(c.project_id))];
}
