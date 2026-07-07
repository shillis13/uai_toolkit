/**
 * ViewportRegistry — live runtime viewport description.
 *
 * Components register reporter functions via useViewport hook.
 * describeViewport() walks the tree on demand, calling reporters
 * to build a ViewportNode tree of what's actually visible.
 *
 * Zero runtime cost when not queried — reporters are only called
 * when describeViewport() is invoked.
 */

import type { ViewportNode, ViewportReporter, ViewportReporterResult } from '@contracts/viewport';

class ViewportRegistryImpl {
  private reporters = new Map<string, ViewportReporter>();

  register(id: string, reporter: ViewportReporter): void {
    // Dev-mode validation: warn if ID doesn't match ComponentRegistry
    if (process.env.NODE_ENV !== 'production') {
      try {
        const { ComponentRegistry } = require('@uai/shared/component-registry');
        if (ComponentRegistry.size > 0 && !ComponentRegistry.has(id)) {
          console.warn(`[ViewportRegistry] ID "${id}" not found in ComponentRegistry — possible typo`);
        }
      } catch { /* ComponentRegistry not available — skip validation */ }
    }
    this.reporters.set(id, reporter);
  }

  unregister(id: string): void {
    this.reporters.delete(id);
  }

  has(id: string): boolean {
    return this.reporters.has(id);
  }

  get size(): number {
    return this.reporters.size;
  }

  describeViewport(rootId: string = 'app', maxDepth: number = 6): ViewportNode {
    const tree = this.walkNode(rootId, 0, maxDepth);
    tree.timestamp = new Date().toISOString();
    return tree;
  }

  private walkNode(id: string, depth: number, maxDepth: number): ViewportNode {
    const reporter = this.reporters.get(id);
    if (!reporter) {
      return { id, visible: false, children: [] };
    }

    let result: ViewportReporterResult;
    try {
      result = reporter();
    } catch {
      return { id, visible: false, children: [] };
    }

    const node: ViewportNode = {
      id,
      visible: result.visible,
      children: [],
    };

    if (result.label) node.label = result.label;
    if (result.state) node.state = result.state;
    if (result.actions && result.actions.length > 0) node.actions = result.actions;

    // Don't recurse into non-visible components
    if (!result.visible) return node;

    // Don't recurse past max depth
    if (depth >= maxDepth) return node;

    for (const child of result.children) {
      if (typeof child === 'string') {
        // Registered child — recurse
        node.children.push(this.walkNode(child, depth + 1, maxDepth));
      } else {
        // Inline ViewportNode — pass through as-is
        node.children.push(child);
      }
    }

    return node;
  }
}

export const ViewportRegistry = new ViewportRegistryImpl();

// Expose for IPC bridge (main process calls via executeJavaScript)
if (typeof window !== 'undefined') {
  (window as any).__viewportRegistry = ViewportRegistry;
}
