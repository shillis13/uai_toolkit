import { assert, connectHarness } from './test-harness';

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await h.waitFor('.navigator');

    const tabs = await h.js<string[]>(`Array.from(document.querySelectorAll('.nav-tab')).map((el) => (el.textContent || '').trim())`);
    assert(tabs.length === 3, `Expected 3 navigator tabs, got ${tabs.length}`);
    assert(tabs.includes('Sessions'), 'Navigator missing Sessions tab');
    assert(tabs.includes('Teams'), 'Navigator missing Teams tab');
    assert(tabs.includes('Projects'), 'Navigator missing Projects tab');

    await h.clickText('Sessions', '.nav-tab');
    await h.waitFor('.nav-search-input');

    const sessionCountBefore = await h.count('.session-card');
    await h.type('.nav-search-input', 'Continuity');
    await h.sleep(150);
    const sessionCountAfter = await h.count('.session-card');
    assert(sessionCountAfter <= sessionCountBefore, `Search filter did not reduce card count (${sessionCountBefore} -> ${sessionCountAfter})`);
    assert(sessionCountAfter >= 0, 'Filtered session count should not be negative');

    const filterLabels = await h.js<string[]>(`Array.from(document.querySelectorAll('.filter-pill')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['Active', 'Stopped', 'Claude', 'Codex', 'Gemini']) {
      assert(filterLabels.includes(label), `Missing filter pill: ${label}`);
    }

    await h.clickText('Claude', '.filter-pill');
    const claudeActive = await h.js<boolean>(`(() => {
      const btn = Array.from(document.querySelectorAll('.filter-pill')).find((el) => (el.textContent || '').trim() === 'Claude');
      return Boolean(btn && btn.classList.contains('active'));
    })()`);
    assert(claudeActive, 'Claude filter pill did not toggle active');
    await h.clickText('Claude', '.filter-pill');

    const workspaceTabsBefore = await h.count('.workspace-tab');
    if (await h.exists('.session-card')) {
      await h.click('.session-card');
      await h.sleep(200);
      const workspaceTabsAfter = await h.count('.workspace-tab');
      assert(workspaceTabsAfter >= Math.max(1, workspaceTabsBefore), 'Clicking a session card did not open/activate a workspace tab');
    }

    const totalSessions = await h.js<number>('window.uai.sessions.list().then((items) => items.length)');
    const recentCount = await h.count('.nav-recent-item');
    const expectedRecent = Math.min(8, totalSessions);
    assert(recentCount === expectedRecent, `Expected ${expectedRecent} recent sessions, got ${recentCount}`);
    const iconCount = await h.count('.nav-recent-icon');
    assert(iconCount === recentCount, `Expected ${recentCount} recent session icons, got ${iconCount}`);

    await h.click('.nav-new-btn');
    await h.waitFor('.context-menu');
    const newMenuItems = await h.js<string[]>(`Array.from(document.querySelectorAll('.context-menu-item')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['Claude', 'Codex', 'Gemini', 'Custom...', 'Group', 'Folder']) {
      assert(newMenuItems.includes(label), `Missing + New menu item: ${label}`);
    }
  } finally {
    await h.close();
  }
}
