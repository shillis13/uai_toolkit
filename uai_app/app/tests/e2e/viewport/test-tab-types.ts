import { ViewportTestHarness } from './test-harness-viewport';

interface TabOpenResult {
  ok: boolean;
  data?: { tabId: string };
}

export async function run(h: ViewportTestHarness): Promise<void> {
  // Test 1: Open a standalone terminal tab
  const termResult = await h.execute('workspace.tabs.open', {
    type: 'terminal',
    targetId: 'test-terminal-1',
    label: 'Test Terminal',
  }) as TabOpenResult;
  if (!termResult?.ok || !termResult.data?.tabId) {
    throw new Error('workspace.tabs.open for terminal did not return a tabId');
  }
  await h.sleep(500);

  // Verify workspace has entity_view or at least the tab is open
  let ws = await h.findNode('workspace');
  if (!ws) throw new Error('Workspace not found');
  const termTabCount = ws.state?.tabCount;
  if (typeof termTabCount !== 'number' || termTabCount < 1) {
    throw new Error(`Expected at least 1 tab after opening terminal, got ${termTabCount}`);
  }

  // Close the terminal tab using the actual tab ID returned by open
  await h.execute('workspace.tabs.close', { tabId: termResult.data.tabId });
  await h.sleep(300);

  // Test 2: Open a traits/context manager (app) tab
  const appResult = await h.execute('workspace.tabs.open', {
    type: 'app',
    targetId: 'context-manager',
    label: 'Context Manager',
  }) as TabOpenResult;
  if (!appResult?.ok || !appResult.data?.tabId) {
    throw new Error('workspace.tabs.open for app did not return a tabId');
  }
  await h.sleep(500);

  ws = await h.findNode('workspace');
  if (!ws) throw new Error('Workspace not found');
  if (typeof ws.state?.tabCount !== 'number' || ws.state.tabCount < 1) {
    throw new Error('App tab did not register');
  }

  // Close app tab using the actual tab ID returned by open
  await h.execute('workspace.tabs.close', { tabId: appResult.data.tabId });
  await h.sleep(300);

  // Test 3: Open a WebAI tab
  const webaiResult = await h.execute('workspace.tabs.open', {
    type: 'webai',
    targetId: 'https://chatgpt.com',
    label: 'ChatGPT',
  }) as TabOpenResult;
  if (!webaiResult?.ok || !webaiResult.data?.tabId) {
    throw new Error('workspace.tabs.open for webai did not return a tabId');
  }
  await h.sleep(500);

  ws = await h.findNode('workspace');
  if (!ws) throw new Error('Workspace not found');
  if (typeof ws.state?.tabCount !== 'number' || ws.state.tabCount < 1) {
    throw new Error('WebAI tab did not register');
  }

  // Close webai tab using the actual tab ID returned by open
  await h.execute('workspace.tabs.close', { tabId: webaiResult.data.tabId });
  await h.sleep(300);
}
