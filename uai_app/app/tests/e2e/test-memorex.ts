import { assert, connectHarness } from './test-harness';

async function ensureTranscriptVisible(h: Awaited<ReturnType<typeof connectHarness>>): Promise<void> {
  await h.clickText('Sessions', '.nav-tab');
  if (await h.exists('.nav-recent-item')) {
    await h.click('.nav-recent-item');
  } else {
    await h.click('.session-card');
  }
  await h.waitFor('.memorex-toggle');
  await h.click('.memorex-toggle');
  await h.waitFor('.memorex-container');
}

export async function run(): Promise<void> {
  const h = await connectHarness();
  try {
    await ensureTranscriptVisible(h);

    const pillLabels = await h.js<string[]>(`Array.from(document.querySelectorAll('.memorex-filter-pill')).map((el) => (el.textContent || '').trim())`);
    for (const label of ['You', 'Claude', 'Tools', 'Thinking']) {
      assert(pillLabels.includes(label), `Memorex missing filter pill: ${label}`);
    }

    const alignment = await h.js<{ barCenter: number; firstPillCenter: number } | null>(`(() => {
      const bar = document.querySelector('.memorex-filter-bar');
      const pill = document.querySelector('.memorex-filter-pill-group');
      if (!(bar instanceof HTMLElement) || !(pill instanceof HTMLElement)) return null;
      const barRect = bar.getBoundingClientRect();
      const pillRect = pill.getBoundingClientRect();
      return { barCenter: barRect.left + barRect.width / 2, firstPillCenter: pillRect.left + pillRect.width / 2 };
    })()`);
    assert(Boolean(alignment), 'Could not measure Memorex filter alignment');
    assert((alignment?.firstPillCenter || 0) > (alignment?.barCenter || 0), 'Memorex filter pills are not right-aligned');

    const styles = await h.js<Record<string, string>>(`(() => {
      const mapping = {
        user: '.memorex-block-user',
        assistant: '.memorex-block-assistant',
        tool_use: '.memorex-block-tool_use',
        tool_result: '.memorex-block-tool_result',
        thinking: '.memorex-block-thinking',
      };
      const result = {};
      for (const [key, selector] of Object.entries(mapping)) {
        const el = document.querySelector(selector);
        if (el instanceof HTMLElement) {
          result[key] = getComputedStyle(el).backgroundColor;
        }
      }
      return result;
    })()`);
    const expectedSubstrings: Record<string, string> = {
      user: '247, 118, 142',
      assistant: '122, 162, 247',
      tool_use: '158, 206, 106',
      tool_result: '158, 206, 106',
      thinking: '187, 154, 247',
    };
    for (const [key, needle] of Object.entries(expectedSubstrings)) {
      if (styles[key]) {
        assert(styles[key].includes(needle), `Memorex block ${key} has wrong background color: ${styles[key]}`);
      }
    }

    const collapsibleSelector = '.memorex-block-tool_use .memorex-block-header, .memorex-block-tool_result .memorex-block-header, .memorex-block-thinking .memorex-block-header';
    const collapsibleCount = await h.count(collapsibleSelector);
    assert(collapsibleCount > 0, 'No collapsible Memorex blocks were available to test');
    const visibleBefore = await h.count('.memorex-block-content');
    await h.click(collapsibleSelector);
    await h.sleep(150);
    const visibleAfterCollapse = await h.count('.memorex-block-content');
    assert(visibleAfterCollapse < visibleBefore, 'Collapsing a Memorex block did not reduce visible content blocks');
    await h.click(collapsibleSelector);
    await h.sleep(150);
    const visibleAfterExpand = await h.count('.memorex-block-content');
    assert(visibleAfterExpand >= visibleAfterCollapse, 'Expanding a Memorex block did not restore content visibility');
  } finally {
    await h.close();
  }
}
