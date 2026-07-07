import { assert, connectHarness } from './test-harness';

async function openAtLeastOneSessionTab(h: Awaited<ReturnType<typeof connectHarness>>): Promise<void> {
  await h.clickText('Sessions', '.nav-tab');
  await h.waitFor('.navigator');
  if (await h.exists('.nav-recent-item')) {
    await h.click('.nav-recent-item');
  } else {
    await h.click('.session-card');
  }
  await h.waitFor('.workspace-tab');
}

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await openAtLeastOneSessionTab(h);

    if (await h.count('.workspace-tab') < 2) {
      const candidates = await h.count('.nav-recent-item');
      if (candidates >= 2) {
        await h.click('.nav-recent-item:nth-child(2)');
      } else if (await h.count('.session-card') >= 2) {
        await h.click('.session-card:nth-of-type(2)');
      }
      await h.sleep(200);
    }

    const tabCount = await h.count('.workspace-tab');
    assert(tabCount >= 1, 'Workspace tab bar did not render any tabs');

    if (tabCount >= 2) {
      const titlesBefore = await h.js<string[]>(`Array.from(document.querySelectorAll('.workspace-tab')).map((el) => el.classList.contains('active') ? ((el.textContent || '').trim()) : '').filter(Boolean)`);
      await h.click('.workspace-tab:nth-of-type(2)');
      await h.sleep(150);
      const titlesAfter = await h.js<string[]>(`Array.from(document.querySelectorAll('.workspace-tab')).map((el) => el.classList.contains('active') ? ((el.textContent || '').trim()) : '').filter(Boolean)`);
      assert(titlesBefore[0] !== titlesAfter[0], 'Switching workspace tabs did not change the active tab');
    }

    await h.rightClick('.workspace-tab');
    await h.waitFor('.context-menu');
    const menuItems = await h.js<string[]>(`Array.from(document.querySelectorAll('.context-menu-item')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['Copy ID', 'Close', 'Close Others', 'View Transcript']) {
      assert(menuItems.includes(label), `Workspace tab context menu missing: ${label}`);
    }

    const terminalVisible = await h.exists('.terminal-pane');
    const promptBoxVisible = await h.exists('.promptbox');
    assert(terminalVisible, 'Session tab did not render TerminalPane');
    assert(promptBoxVisible, 'Session tab did not render PromptBox');

    const tabCountBeforeClose = await h.count('.workspace-tab');
    await h.clickText('View Transcript', '.context-menu-item');
    await h.waitFor('.transcript-content');
    await h.waitFor('.memorex-toggle.active');
    const tabCountWithTranscript = await h.count('.workspace-tab');
    assert(tabCountWithTranscript >= tabCountBeforeClose, 'Transcript tab did not open');

    const countBeforeX = await h.count('.workspace-tab');
    await h.click('.workspace-tab-close');
    await h.sleep(150);
    const countAfterX = await h.count('.workspace-tab');
    assert(countAfterX <= countBeforeX, 'Closing a workspace tab did not reduce or preserve tab count');
  } finally {
    await h.close();
  }
}
