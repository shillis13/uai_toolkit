import { assert, connectHarness } from './test-harness';

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await h.waitFor('.bottom-panel-drawer-bar');
    const versionText = await h.text('.bottom-panel-drawer-version');
    const summaryText = await h.text('.bottom-panel-drawer-summary');
    assert(versionText.length > 0, 'Bottom panel status bar missing version text');
    for (const token of ['Sessions:', 'Errors:', 'CPU:']) {
      assert(summaryText.includes(token), `Bottom panel summary missing ${token}`);
    }

    const drawerBefore = await h.boundingBox('.bottom-panel-drawer-bar');
    await h.click('.bottom-panel-drawer-bar');
    await h.waitFor('.bottom-panel-tab');
    const drawerAfter = await h.boundingBox('.bottom-panel-drawer-bar');
    assert(Boolean(drawerBefore && drawerAfter), 'Bottom panel drawer bar bounding boxes unavailable');
    assert(Math.abs((drawerBefore?.y || 0) - (drawerAfter?.y || 0)) < 8, 'Bottom drawer bar moved away from bottom edge when toggled');

    const tabLabels = await h.js<string[]>(`Array.from(document.querySelectorAll('.bottom-panel-tab')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['Related', 'Session Log', 'App Log', 'Monitor']) {
      assert(tabLabels.includes(label), `Bottom panel missing tab: ${label}`);
    }

    await h.clickText('Session Log', '.bottom-panel-tab');
    await h.sleep(100);
    await h.clickText('App Log', '.bottom-panel-tab');
    await h.sleep(100);
    await h.clickText('Monitor', '.bottom-panel-tab');
    await h.waitFor('.bottom-panel-monitor');

    const monitorLabels = await h.js<string[]>(`Array.from(document.querySelectorAll('.monitor-card-label')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['CPU', 'Memory', 'Heap', 'Sessions', 'Errors', 'Uptime']) {
      assert(monitorLabels.includes(label), `Monitor tab missing metric: ${label}`);
    }
  } finally {
    await h.close();
  }
}
