import { assert, connectHarness } from './test-harness';

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await h.clickText('Projects', '.nav-tab');
    await h.waitFor('.projects-tab');

    const projectCount = await h.js<number>('window.uai.projects.list().then((items) => items.length)');
    assert(projectCount > 0, 'Projects API returned no projects');

    const renderedCards = await h.count('.projects-tab .session-card');
    assert(renderedCards > 0, 'Projects tab rendered no project cards');

    const badgeCount = await h.count('.projects-tab .card-badge');
    assert(badgeCount > 0, 'Project cards are missing git status badges');

    await h.click('.projects-tab .session-card');
    await h.waitFor('.project-detail-view');
    const projectDetailText = await h.js<string>(`document.querySelector('.project-detail-view')?.innerText || ''`);
    for (const label of ['Project ID', 'Git Status', 'Working Dir']) {
      assert(projectDetailText.includes(label), `Project detail view missing ${label}`);
    }

    await h.rightClick('.projects-tab .session-card');
    await h.waitFor('.context-menu');
    const menuItems = await h.js<string[]>(`Array.from(document.querySelectorAll('.context-menu-item')).map((el) => (el.textContent || '').trim())`);
    assert(menuItems.includes('Copy Path'), 'Project card context menu missing Copy Path');
    assert(menuItems.includes('Open in Tab'), 'Project card context menu missing Open in Tab');

    const tabCountBefore = await h.count('.workspace-tab');
    await h.clickText('Open in Tab', '.context-menu-item');
    await h.sleep(150);
    const tabCountAfter = await h.count('.workspace-tab');
    assert(tabCountAfter >= tabCountBefore, 'Open in Tab did not preserve or increase workspace tab count');
  } finally {
    await h.close();
  }
}
