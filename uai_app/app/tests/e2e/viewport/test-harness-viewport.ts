import { CdpHarness } from '../test-harness';

interface ViewportNode {
  id: string;
  visible: boolean;
  label?: string;
  children: ViewportNode[];
  state?: Record<string, unknown>;
  actions?: Array<{ id: string; command: string; payload?: Record<string, unknown>; label: string }>;
  timestamp?: string;
}

export class ViewportTestHarness {
  constructor(private cdp: CdpHarness) {}

  static async connect(): Promise<ViewportTestHarness> {
    const cdp = await CdpHarness.connect();
    return new ViewportTestHarness(cdp);
  }

  async viewport(): Promise<ViewportNode> {
    return await this.cdp.js<ViewportNode>('window.__viewportRegistry.describeViewport()');
  }

  async execute(type: string, payload: Record<string, unknown> = {}): Promise<unknown> {
    return await this.cdp.js(`window.uai.execute({ id: crypto.randomUUID(), type: ${JSON.stringify(type)}, payload: ${JSON.stringify(payload)}, origin: 'debug', timestamp: new Date().toISOString() })`);
  }

  findNodeInTree(tree: ViewportNode, id: string): ViewportNode | null {
    if (tree.id === id) return tree;
    for (const child of tree.children) {
      const found = this.findNodeInTree(child, id);
      if (found) return found;
    }
    return null;
  }

  async findNode(id: string): Promise<ViewportNode | null> {
    const tree = await this.viewport();
    return this.findNodeInTree(tree, id);
  }

  async assertVisible(id: string, msg?: string): Promise<void> {
    const node = await this.findNode(id);
    if (!node || !node.visible) {
      throw new Error(msg || `Expected ${id} to be visible, but ${node ? 'visible=false' : 'not found in tree'}`);
    }
  }

  async assertNotVisible(id: string, msg?: string): Promise<void> {
    const node = await this.findNode(id);
    if (node && node.visible) {
      throw new Error(msg || `Expected ${id} to be not visible, but visible=true`);
    }
  }

  async assertState(id: string, key: string, expected: unknown, msg?: string): Promise<void> {
    const node = await this.findNode(id);
    if (!node) throw new Error(msg || `Node ${id} not found`);
    const actual = node.state?.[key];
    if (actual !== expected) {
      throw new Error(msg || `Expected ${id}.state.${key} = ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
    }
  }

  async assertLabel(id: string, expected: string | RegExp, msg?: string): Promise<void> {
    const node = await this.findNode(id);
    if (!node) throw new Error(msg || `Node ${id} not found`);
    const matches = typeof expected === 'string' ? node.label === expected : expected.test(node.label || '');
    if (!matches) {
      throw new Error(msg || `Expected ${id}.label to match ${expected}, got "${node.label}"`);
    }
  }

  async assertHasChild(parentId: string, childId: string, msg?: string): Promise<void> {
    const parent = await this.findNode(parentId);
    if (!parent) throw new Error(msg || `Parent ${parentId} not found`);
    if (!parent.children.some(c => c.id === childId)) {
      throw new Error(msg || `Expected ${parentId} to have child ${childId}, children: [${parent.children.map(c => c.id).join(', ')}]`);
    }
  }

  async triggerAction(nodeId: string, actionId: string): Promise<void> {
    const node = await this.findNode(nodeId);
    if (!node) throw new Error(`Node ${nodeId} not found for action ${actionId}`);
    const action = node.actions?.find(a => a.id === actionId);
    if (!action) throw new Error(`Action ${actionId} not found on node ${nodeId}. Available: [${(node.actions || []).map(a => a.id).join(', ')}]`);
    await this.execute(action.command, action.payload || {});
  }

  async waitForViewport(predicate: (tree: ViewportNode) => boolean, timeout = 10000): Promise<ViewportNode> {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      const tree = await this.viewport();
      if (predicate(tree)) return tree;
      await new Promise(r => setTimeout(r, 200));
    }
    throw new Error(`waitForViewport timed out after ${timeout}ms`);
  }

  async js<T = unknown>(expression: string): Promise<T> {
    return await this.cdp.js<T>(expression);
  }

  async sleep(ms: number): Promise<void> {
    await new Promise(r => setTimeout(r, ms));
  }

  async close(): Promise<void> {
    await this.cdp.close();
  }
}
