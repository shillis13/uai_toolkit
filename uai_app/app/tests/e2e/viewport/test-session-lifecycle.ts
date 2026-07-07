import { ViewportTestHarness } from './test-harness-viewport';

export async function run(h: ViewportTestHarness): Promise<void> {
  // Verify workspace is visible
  await h.assertVisible('workspace');

  // Verify navigator is visible with state
  await h.assertVisible('session_navigator');
  const nav = await h.findNode('session_navigator');
  if (!nav?.state?.activeTab) {
    throw new Error('Navigator missing activeTab state');
  }

  // If there are tabs open, verify entity_view
  const ws = await h.findNode('workspace');
  if (ws && ws.children.length > 0) {
    await h.assertVisible('entity_view');
    const ev = await h.findNode('entity_view');
    if (ev?.label) {
      // Label should start with "session:" or "transcript:"
      if (!ev.label.startsWith('session:') && !ev.label.startsWith('transcript:')) {
        throw new Error(`entity_view label should start with session: or transcript:, got: ${ev.label}`);
      }
    }
  }
}
