import { ViewportTestHarness } from './test-harness-viewport';

export async function run(h: ViewportTestHarness): Promise<void> {
  // Context panel toggle
  const cpBefore = await h.findNode('context_panel');
  if (cpBefore?.visible && cpBefore.state?.open === true) {
    // Close it
    await h.triggerAction('context_panel', 'toggle');
    await h.waitForViewport(tree => {
      const cp = h.findNodeInTree(tree, 'context_panel');
      return cp?.state?.open === false;
    });
    await h.assertState('context_panel', 'open', false);

    // Re-read to get fresh action payload, then open it
    await h.triggerAction('context_panel', 'toggle');
    await h.waitForViewport(tree => {
      const cp = h.findNodeInTree(tree, 'context_panel');
      return cp?.state?.open === true;
    });
    await h.assertState('context_panel', 'open', true);
  }

  // Bottom panel toggle
  const bp = await h.findNode('bottom_panel');
  if (bp) {
    const wasClosed = bp.state?.collapsed === true;
    await h.triggerAction('bottom_panel', 'toggle');
    await h.waitForViewport(tree => {
      const node = h.findNodeInTree(tree, 'bottom_panel');
      return node?.state?.collapsed === !wasClosed;
    });
    await h.assertState('bottom_panel', 'collapsed', !wasClosed);

    // Toggle back
    await h.triggerAction('bottom_panel', 'toggle');
    await h.waitForViewport(tree => {
      const node = h.findNodeInTree(tree, 'bottom_panel');
      return node?.state?.collapsed === wasClosed;
    });
    await h.assertState('bottom_panel', 'collapsed', wasClosed);
  }
}
