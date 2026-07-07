import { assert, connectHarness } from './test-harness';

async function ensureSessionOpen(h: Awaited<ReturnType<typeof connectHarness>>): Promise<void> {
  await h.clickText('Sessions', '.nav-tab');
  if (await h.exists('.nav-recent-item')) {
    await h.click('.nav-recent-item');
  } else {
    await h.click('.session-card');
  }
  await h.waitFor('.workspace-tab');
}

function sectionRegex(title: string, total: number): RegExp {
  return new RegExp(`${title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\(\\d+\\/${total}\\)`);
}

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await ensureSessionOpen(h);

    const toggleClosedBox = await h.boundingBox('.context-panel-toggle-bar');
    await h.click('.context-panel-toggle-bar');
    await h.waitFor('.context-panel');
    const toggleOpenBox = await h.boundingBox('.context-panel-toggle-bar.open');
    assert(Boolean(toggleClosedBox && toggleOpenBox), 'Context panel toggle bar bounding boxes unavailable');
    assert(Math.abs((toggleClosedBox?.y || 0) - (toggleOpenBox?.y || 0)) < 8, 'Context panel toggle moved vertically when opening');

    const tabLabels = await h.js<string[]>(`Array.from(document.querySelectorAll('.ctx-tab-btn')).map((el) => (el.textContent || '').replace(/\d+/g, '').trim())`);
    for (const label of ['Details', 'Context', 'Prompts', 'Messages']) {
      assert(tabLabels.some((value) => value.startsWith(label)), `Missing context-panel tab: ${label}`);
    }

    const detailsText = await h.js<string>(`document.querySelector('.context-panel-body')?.innerText || ''`);
    for (const label of ['Tracking ID', 'Platform', 'Status', 'Project Dir']) {
      assert(detailsText.includes(label), `Details tab missing label: ${label}`);
    }

    await h.clickText('Context', '.ctx-tab-btn');
    await h.sleep(200);
    const contextInfo = await h.js<{ bodyText: string; totals: Record<string, number> }>(`(async () => {
      const state = await window.uai.appState.get();
      const activeTab = state.tabs.find((tab) => tab.id === state.activeTabId);
      const sessionId = activeTab?.type === 'session' ? activeTab.targetId : null;
      const items = sessionId ? await window.uai.traits.list(sessionId) : [];
      const totals = { traits: 0, roles: 0, skills: 0, mslots: 0 };
      for (const item of items) {
        if (item.type === 'roles') {
          if (item.name.startsWith('skill:')) totals.skills += 1;
          else totals.roles += 1;
        } else if (item.type === 'mslots') {
          totals.mslots += 1;
        } else {
          totals.traits += 1;
        }
      }
      return {
        bodyText: document.querySelector('.context-panel-body')?.innerText || '',
        totals,
      };
    })()`);
    if (contextInfo.totals.traits > 0) assert(sectionRegex('Traits & Docs', contextInfo.totals.traits).test(contextInfo.bodyText), 'Traits & Docs count does not match API');
    if (contextInfo.totals.roles > 0) assert(sectionRegex('Roles', contextInfo.totals.roles).test(contextInfo.bodyText), 'Roles count does not match API');
    if (contextInfo.totals.skills > 0) assert(sectionRegex('Skills', contextInfo.totals.skills).test(contextInfo.bodyText), 'Skills count does not match API');
    if (contextInfo.totals.mslots > 0) assert(sectionRegex('Memory Slots', contextInfo.totals.mslots).test(contextInfo.bodyText), 'Memory Slots count does not match API');

    await h.clickText('Messages', '.ctx-tab-btn');
    await h.waitFor('.msg-folder-btn');
    const folders = await h.js<string[]>(`Array.from(document.querySelectorAll('.msg-folder-btn')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['Inbox', 'Sent', 'Archive']) {
      assert(folders.includes(label), `Messages tab missing folder: ${label}`);
    }

    const widthBefore = (await h.boundingBox('.context-panel'))?.width || 0;
    await h.drag('.context-panel-resize', -80, 0);
    await h.sleep(150);
    const widthAfter = (await h.boundingBox('.context-panel'))?.width || 0;
    assert(widthAfter !== widthBefore, 'Context panel width did not change after resize drag');
  } finally {
    await h.close();
  }
}
