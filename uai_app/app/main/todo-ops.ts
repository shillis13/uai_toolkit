/**
 * todo-ops — shared bridge to the todo_mgr.py engine (the authoritative todo
 * reader/writer). Used by BOTH the IPC read handlers (index.ts) and the
 * todo.* Command Bus handlers (command-handlers.ts), so the engine bridge has a
 * single source of truth and the two paths cannot drift.
 *
 * The engine needs common_utils on PYTHONPATH and TODO_ROOT pointing at the
 * todos dir. See docs/designs/work_mgr.md.
 */
import * as path from 'node:path';
import * as fs from 'node:fs';
import { aiRoot as getAiRoot, shellPath } from './paths';


const PY_SRC_ROOT = path.join(process.env.HOME || '', 'bin', 'all_languages', 'python', 'src');
const TODO_MGR_PY = path.join(PY_SRC_ROOT, 'todo_mgr', 'todo_mgr.py');

export function todosRoot(): string {
  return process.env.TODO_ROOT || path.join(getAiRoot(), 'ai_general', 'work', 'todos');
}

/** Run a todo_mgr verb, returning stdout. */
export async function runTodoMgr(verb: string, args: string[] = []): Promise<string> {
  const { execFile: ef } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(ef);
  const envPath = shellPath();
  const { stdout } = await execFileAsync('python3', [TODO_MGR_PY, verb, ...args], {
    timeout: 20000,
    maxBuffer: 16 * 1024 * 1024,
    cwd: getAiRoot(),
    env: {
      ...process.env,
      AI_ROOT: getAiRoot(),
      TODO_ROOT: todosRoot(),
      PYTHONPATH: PY_SRC_ROOT,
      PATH: envPath,
      // Attribute app-initiated edits to the user, not "unknown" (todo_0638). The
      // UAI app is single-user (PianoMan) and is not a CLI session, so todo_mgr's
      // history actor would otherwise fall through to 'unknown'. TODO_ACTOR is read
      // first by todo_mgr.current_session().
      TODO_ACTOR: 'PianoMan',
    },
  });
  return stdout;
}

/**
 * Resolve a todo id (todo_####_slug) to its absolute dir, scanning the nested
 * tree. Guards against traversal — only ids matching the todo_/task_ prefix and
 * living under the todos root are accepted.
 */
export function resolveTodoDir(id: string): string | null {
  if (!id || id.includes('..') || id.includes('/') || id.includes('\\')) return null;
  if (!id.startsWith('todo_') && !id.startsWith('task_')) return null;
  // The canonical id is the bare number handle (todo_NNNN / task_NNNN); the
  // directory carries a human-readable slug (todo_NNNN_short_title). Accept
  // either the exact dir name OR the bare canonical id → its slugged dir.
  const bare = id.match(/^((?:todo|task)_\d{1,4})$/);
  const prefix = bare ? bare[1] + '_' : null;
  const stack: string[] = [todosRoot()];
  while (stack.length) {
    const dir = stack.pop()!;
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { continue; }
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      if (e.name === id) return path.join(dir, e.name);
      if (prefix && e.name.startsWith(prefix)) return path.join(dir, e.name);
      if (e.name.startsWith('todo_') || e.name.startsWith('task_')) stack.push(path.join(dir, e.name));
    }
  }
  return null;
}
