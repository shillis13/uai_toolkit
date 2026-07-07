import { ViewportTestHarness } from './test-harness-viewport';

export async function run(h: ViewportTestHarness): Promise<void> {
  await h.assertVisible('session_navigator');

  const nav = await h.findNode('session_navigator');
  if (!nav?.state) throw new Error('Navigator has no state');

  // Should have activeTab
  const activeTab = nav.state.activeTab;
  if (!activeTab) throw new Error('Navigator missing activeTab');

  // Should have visibleCards count
  const cards = nav.state.visibleCards;
  if (typeof cards !== 'number') throw new Error(`Navigator visibleCards should be a number, got ${typeof cards}`);
}
