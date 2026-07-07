import { captureFailureScreenshot } from './test-harness';
import { run as navigatorRun } from './test-navigator';
import { run as workspaceRun } from './test-workspace';
import { run as contextPanelRun } from './test-context-panel';
import { run as bottomPanelRun } from './test-bottom-panel';
import { run as projectsRun } from './test-projects';
import { run as briefsRun } from './test-briefs';
import { run as memorexRun } from './test-memorex';
import { run as promptBoxRun } from './test-prompt-box';

interface TestCase {
  name: string;
  run: () => Promise<void>;
}

const TESTS: TestCase[] = [
  { name: 'navigator', run: navigatorRun },
  { name: 'workspace', run: workspaceRun },
  { name: 'context-panel', run: contextPanelRun },
  { name: 'bottom-panel', run: bottomPanelRun },
  { name: 'projects', run: projectsRun },
  { name: 'briefs', run: briefsRun },
  { name: 'memorex', run: memorexRun },
  { name: 'prompt-box', run: promptBoxRun },
];

async function main(): Promise<void> {
  console.log('UAI E2E runner: assuming Electron app is already running with CDP on port 9226');
  let failures = 0;

  for (const testCase of TESTS) {
    const startedAt = Date.now();
    process.stdout.write(`\n[RUN] ${testCase.name} ... `);
    try {
      await testCase.run();
      const elapsed = Date.now() - startedAt;
      console.log(`PASS (${elapsed}ms)`);
    } catch (error) {
      failures += 1;
      const elapsed = Date.now() - startedAt;
      const screenshot = await captureFailureScreenshot(testCase.name);
      console.log(`FAIL (${elapsed}ms)`);
      console.error(error instanceof Error ? error.message : error);
      if (screenshot) {
        console.error(`Failure screenshot: ${screenshot}`);
      }
    }
  }

  if (failures > 0) {
    throw new Error(`${failures} E2E test(s) failed`);
  }

  console.log('\nAll UAI E2E tests passed.');
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : error);
  process.exitCode = 1;
});
