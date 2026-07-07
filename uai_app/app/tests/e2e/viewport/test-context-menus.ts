import { ViewportTestHarness } from './test-harness-viewport';

export async function run(h: ViewportTestHarness): Promise<void> {
  // Ensure a session tab is open
  const ws = await h.findNode('workspace');
  if (!ws?.state?.tabCount || ws.state.tabCount === 0) {
    throw new Error('No tabs open — cannot test context menu');
  }

  // Trigger context menu on the active tab via DOM event
  await h.js(`
    (() => {
      const el = document.querySelector('.workspace-tab.active');
      if (el) el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, clientX: 200, clientY: 50 }));
    })();
  `);
  // Wait for context menu to appear in viewport tree
  await h.waitForViewport(tree => {
    const menu = h.findNodeInTree(tree, 'session_context_menu');
    return menu != null && menu.visible;
  });

  // Verify expected menu items are present as actions
  const menu = await h.findNode('session_context_menu');
  if (!menu?.actions) throw new Error('Context menu has no actions');

  const actionIds = menu.actions.map(a => a.id);

  // Core items that should always be present
  for (const required of ['copy_name', 'copy_uri', 'pin', 'close_tab', 'close_others']) {
    if (!actionIds.includes(required)) {
      throw new Error(`Context menu missing required action: ${required}`);
    }
  }

  // Session-specific items (menu always has these since it's a SessionContextMenu)
  if (!actionIds.includes('rename')) throw new Error('Session context menu missing: rename');
  if (!actionIds.includes('session_details')) throw new Error('Session context menu missing: session_details');
  // Should have either stop or resume
  if (!actionIds.includes('stop') && !actionIds.includes('resume')) {
    throw new Error('Session context menu missing both stop and resume');
  }

  // Dismiss context menu by clicking elsewhere
  await h.js(`document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))`);
  await h.sleep(200);

  // Verify menu is gone
  await h.assertNotVisible('session_context_menu');
}
