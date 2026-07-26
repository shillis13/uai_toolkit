/**
 * smoke-mount.ts — pre-ship renderer mount smoke test (todo_0631).
 *
 * Why this exists: on 2026-07-23 a circular-import TDZ error (todo_0557) threw
 * during module evaluation, before React mounted — the whole renderer bundle died
 * and the app showed a black window. It shipped through THREE builds because
 * verification was `--no-launch` + grep-for-code-strings, which proves a module
 * LOADED, not that the app MOUNTS. This test closes that gap: it launches the
 * packaged app and asserts the renderer actually mounts.
 *
 * Unlike the other e2e scripts (which assume a live app on CDP 9226), this one owns
 * the app lifecycle: it SPAWNS an isolated instance and kills it. It deliberately
 * launches the packaged binary DIRECTLY (not through the session-launcher /
 * lib_cli_wrapper orchestrator) with:
 *   - a throwaway --user-data-dir (never touches real session data or the user's
 *     running instance), and
 *   - a unique UAI_DEBUG_PORT (no CDP-port clash with a live app on 9226).
 * The app renders via showInactive(), so it never steals the user's focus.
 *
 * Run from app/:  npx tsx tests/e2e/smoke-mount.ts
 * Exit 0 = renderer mounted; exit 1 = it didn't (with the reason).
 */

import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { WebSocket as WsWebSocket } from 'ws';
import { CdpHarness } from './test-harness';

// The CDP harness needs a global WebSocket. Node < 22 (this repo runs Node 20) has no
// stable global WebSocket, so the harness throws "Global WebSocket is not available".
// Polyfill from `ws` (its WebSocket implements the browser addEventListener API the
// harness uses). Only sets it when absent, so Node 22+ is unaffected.
// (Follow-up: the harness's ensureWebSocket() could carry this fallback itself so the
//  whole e2e suite runs under Node 20 — kept local here to avoid touching shared infra.)
if (typeof (globalThis as { WebSocket?: unknown }).WebSocket === 'undefined') {
  (globalThis as { WebSocket?: unknown }).WebSocket = WsWebSocket;
}

const APP_BINARY = process.env.UAI_SMOKE_BINARY
  || '$AI_ROOT/ai_general/apps/unified_ai_ui/UnifiedAI.app/Contents/MacOS/unified-ai-interface';
const DEBUG_PORT_OVERRIDE = Number(process.env.UAI_SMOKE_PORT || 0);
const BOOT_TIMEOUT_MS = Number(process.env.UAI_SMOKE_BOOT_MS || 30000);   // CDP target appears
const MOUNT_TIMEOUT_MS = Number(process.env.UAI_SMOKE_MOUNT_MS || 20000); // #root gets children

// Session isolation (todo_0631): the spawned app is run with UAI_SMOKE=1, which the
// main process honors by SKIPPING all real-session PTY attach (app/main/terminal.ts).
// Without it, booting the app attaches `session_ops.py attach <name>` to every live
// tmux session — a smoke test must never touch real sessions. (An earlier attempt to
// isolate via an empty AI_ROOT did NOT work: the attach command uses a hardcoded root
// path, so AI_ROOT can't gate it — hence the explicit UAI_SMOKE guard.)
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function findFreeDebugPort(): Promise<number> {
  if (DEBUG_PORT_OVERRIDE) {
    if (!Number.isInteger(DEBUG_PORT_OVERRIDE)
        || DEBUG_PORT_OVERRIDE < 1
        || DEBUG_PORT_OVERRIDE > 65535) {
      throw new Error(`invalid UAI_SMOKE_PORT: ${process.env.UAI_SMOKE_PORT}`);
    }
    return DEBUG_PORT_OVERRIDE;
  }
  return await new Promise<number>((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close((error) => {
        if (error) reject(error);
        else if (!port) reject(new Error('could not allocate an ephemeral CDP port'));
        else resolve(port);
      });
    });
  });
}

// Renderer-side probes (kept as plain-string IIFEs — evaluated in the page).
const ROOT_CHILD_COUNT =
  "(function(){var r=document.getElementById('root');return r?r.childElementCount:0;})()";
const BOOT_ERROR_TEXT =
  "(function(){var r=document.getElementById('root');" +
  "return (r&&r.textContent&&r.textContent.indexOf('UnifiedAI failed to start')>=0)" +
  "?r.textContent.slice(0,600):'';})()";

async function main(): Promise<void> {
  const debugPort = await findFreeDebugPort();
  const profile = mkdtempSync(join(tmpdir(), 'uai_smoke_'));
  let processOutputTail = '';
  let sawRealTerminalAttach = false;
  const captureOutput = (chunk: Buffer) => {
    processOutputTail = (processOutputTail + chunk.toString()).slice(-12000);
    if (processOutputTail.includes('[terminal] attachTerminal: ')) {
      sawRealTerminalAttach = true;
    }
  };
  const spawnEnv: NodeJS.ProcessEnv = {
    ...process.env,
    UAI_DEBUG_PORT: String(debugPort),
    UAI_SMOKE: '1',            // main process skips real-session PTY attach (app/main/terminal.ts)
    UAI_TEST_OFFSCREEN: '1',   // render off-screen/hidden so it never appears over the user's app
  };
  const child: ChildProcess = spawn(APP_BINARY, ['--user-data-dir=' + profile], {
    env: spawnEnv,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout?.on('data', captureOutput);
  child.stderr?.on('data', captureOutput);

  let harness: CdpHarness | undefined;
  let failure: string | null = null;
  const spawnState: { error: Error | null } = { error: null };
  const exited = new Promise<number>((resolve) => {
    let settled = false;
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      resolve(code);
    };
    child.once('exit', (code) => finish(code ?? -1));
    child.once('error', (error) => {
      spawnState.error = error;
      finish(-1);
    });
  });
  const isRunning = () =>
    spawnState.error === null && child.exitCode === null && child.signalCode === null;

  try {
    // 1) Wait for the app to expose a CDP page target (or crash trying).
    const bootDeadline = Date.now() + BOOT_TIMEOUT_MS;
    let lastConnectErr = '';
    while (Date.now() < bootDeadline) {
      if (!isRunning()) {
        const exitReason = spawnState.error
          ? `spawn failed: ${spawnState.error.message}`
          : child.signalCode
            ? `signal ${child.signalCode}`
            : `code ${child.exitCode}`;
        throw new Error('app process exited (' + exitReason + ') before CDP came up — '
          + 'it likely crashed in the MAIN process at boot.\n--- process output tail ---\n'
          + processOutputTail);
      }
      try { harness = await CdpHarness.connect(debugPort); break; }
      catch (e) { lastConnectErr = e instanceof Error ? e.message : String(e); await sleep(500); }
    }
    if (!harness) {
      throw new Error('no CDP page target within ' + BOOT_TIMEOUT_MS + 'ms. last connect error: '
        + lastConnectErr + '\n--- process output tail ---\n' + processOutputTail);
    }

    // 2) Wait for the renderer to actually MOUNT (#root gets children).
    let childCount = 0;
    const mountDeadline = Date.now() + MOUNT_TIMEOUT_MS;
    while (Date.now() < mountDeadline) {
      childCount = await harness.js<number>(ROOT_CHILD_COUNT);
      if (childCount > 0) break;
      await sleep(500);
    }
    // Give mount-triggered session cards one short turn to request terminals, then
    // enforce the safety contract from the child output. The SKIPPED marker is
    // allowed; the normal attach marker means this smoke run touched a real PTY.
    await sleep(750);
    if (sawRealTerminalAttach) {
      throw new Error('UAI_SMOKE safety failure: the test instance attempted a real-session '
        + 'PTY attach.\n--- process output tail ---\n' + processOutputTail);
    }

    // 3) Did the bootstrap error surfacer (todo_0630) fire? That IS a mount failure.
    const bootError = await harness.js<string>(BOOT_ERROR_TEXT);
    try { await harness.screenshot('smoke_mount'); } catch { /* screenshot is best-effort */ }

    if (bootError) {
      throw new Error('renderer showed the bootstrap-error panel (todo_0630) — it crashed before '
        + 'mounting:\n' + bootError);
    }
    if (childCount === 0) {
      throw new Error('#root never received children within ' + MOUNT_TIMEOUT_MS + 'ms — the renderer '
        + 'did not mount (no boot-error panel either; likely a hang or an error before the handler).');
    }
    console.log('SMOKE PASS: renderer mounted — #root has ' + childCount + ' child element(s), '
      + 'no bootstrap-error panel.');
  } catch (e) {
    failure = e instanceof Error ? e.message : String(e);
  } finally {
    if (harness) { try { await harness.close(); } catch { /* ignore */ } }
    if (isRunning()) {
      try { child.kill('SIGTERM'); } catch { /* ignore */ }
      await Promise.race([exited, sleep(3000)]);
      if (isRunning()) {
        try { child.kill('SIGKILL'); } catch { /* ignore */ }
        await Promise.race([exited, sleep(1000)]);
      }
    }
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  }

  if (failure) { console.error('SMOKE FAIL: ' + failure); process.exit(1); }
  process.exit(0);
}

void main();
