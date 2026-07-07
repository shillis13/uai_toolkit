/**
 * teams-ops — shared bridge to the teams_mgr.py engine (the authoritative team
 * reader/writer), mirroring todo-ops. Used by the team.* Command Bus handlers so
 * all team writes route through the engine (create/update/archive/add-role/
 * remove-role/assign/unassign). See ai_general/scripts/teams/teams_mgr.py.
 */
import * as path from 'node:path';

function getAiRoot(): string {
  return process.env.AI_ROOT_MAIN || process.env.AI_ROOT || path.join(require('node:os').homedir(), 'AI/ai_root');
}

const PY_SRC_ROOT = path.join(process.env.HOME || '', 'bin', 'all_languages', 'python', 'src');
function teamsMgrPy(): string {
  return path.join(getAiRoot(), 'ai_general', 'scripts', 'teams', 'teams_mgr.py');
}

/** Run a teams_mgr verb, returning stdout. */
export async function runTeamsMgr(verb: string, args: string[] = []): Promise<string> {
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = [process.env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin'].join(':');
  const { stdout } = await execFileAsync('python3', [teamsMgrPy(), verb, ...args], {
    timeout: 20000,
    maxBuffer: 16 * 1024 * 1024,
    cwd: getAiRoot(),
    env: {
      ...process.env,
      AI_ROOT: getAiRoot(),
      PYTHONPATH: [PY_SRC_ROOT, path.join(getAiRoot(), 'ai_general', 'scripts')].join(':'),
      PATH: envPath,
    },
  });
  return stdout;
}
