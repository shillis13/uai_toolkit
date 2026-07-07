// Node 20 needs WebSocket polyfill for CDP
import { WebSocket } from 'ws';
if (!globalThis.WebSocket) (globalThis as any).WebSocket = WebSocket;

import { ViewportTestHarness } from './test-harness-viewport';
import * as sessionLifecycle from './test-session-lifecycle';
import * as panels from './test-panels';
import * as navigator from './test-navigator';
import * as tabTypes from './test-tab-types';
import * as contextMenus from './test-context-menus';

interface TestResult {
  name: string;
  passed: boolean;
  error?: string;
  durationMs: number;
}

async function runTest(name: string, fn: (h: ViewportTestHarness) => Promise<void>, h: ViewportTestHarness): Promise<TestResult> {
  const start = Date.now();
  try {
    await fn(h);
    return { name, passed: true, durationMs: Date.now() - start };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return { name, passed: false, error: msg, durationMs: Date.now() - start };
  }
}

async function main(): Promise<void> {
  console.log('=== UAI Viewport Regression Tests ===\n');

  const h = await ViewportTestHarness.connect();

  // Preamble: verify minimum viewport tree
  try {
    const tree = await h.viewport();
    const required = ['app', 'workspace', 'session_navigator', 'bottom_panel'];
    const missing = required.filter(id => {
      const found = h.findNodeInTree(tree, id);
      return !found;
    });
    if (missing.length > 0) {
      console.error(`ABORT: Required viewport nodes not registered: ${missing.join(', ')}`);
      console.error('Ensure the app is running with viewport wiring enabled.');
      process.exit(1);
    }
    console.log(`Viewport tree OK — ${required.length} required nodes present\n`);
  } catch (err) {
    console.error('ABORT: Could not read viewport tree:', err);
    process.exit(1);
  }

  const results: TestResult[] = [];

  results.push(await runTest('Session lifecycle', sessionLifecycle.run, h));
  results.push(await runTest('Panel toggles', panels.run, h));
  results.push(await runTest('Navigator state', navigator.run, h));
  results.push(await runTest('Tab types (terminal, app, webai)', tabTypes.run, h));
  results.push(await runTest('Context menus', contextMenus.run, h));

  await h.close();

  // Summary
  console.log('\n--- Results ---');
  for (const r of results) {
    const icon = r.passed ? '\u2713' : '\u2717';
    const time = `(${r.durationMs}ms)`;
    console.log(`${icon} ${r.name} ${time}${r.error ? ` — ${r.error}` : ''}`);
  }

  const passed = results.filter(r => r.passed).length;
  const total = results.length;
  console.log(`\n${passed}/${total} passed`);

  if (passed < total) process.exit(1);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
