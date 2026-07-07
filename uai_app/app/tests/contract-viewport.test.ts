/**
 * Contract Test: ViewportRegistry
 *
 * Validates that ViewportRegistry correctly builds a ViewportNode tree
 * from registered reporters, including visibility gating, depth limits,
 * inline children, state/actions, and graceful error handling.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { ViewportRegistry } from '@uai/renderer-ui/viewport/viewport-registry';
import type { ViewportNode, ViewportReporterResult } from '@contracts/viewport';

beforeEach(() => {
  (ViewportRegistry as any).reporters.clear();
});

describe('ViewportRegistry contract tests', () => {
  it('returns not-visible node for unregistered component', () => {
    const node = ViewportRegistry.describeViewport('nonexistent');
    expect(node.id).toBe('nonexistent');
    expect(node.visible).toBe(false);
    expect(node.children).toEqual([]);
  });

  it('returns visible node for registered component with timestamp', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: [],
    }));

    const node = ViewportRegistry.describeViewport('app');
    expect(node.id).toBe('app');
    expect(node.visible).toBe(true);
    expect(node.timestamp).toBeTypeOf('string');
    // Verify it's a valid ISO timestamp
    expect(new Date(node.timestamp!).toISOString()).toBe(node.timestamp);
  });

  it('walks children recursively', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: ['sidebar'],
    }));
    ViewportRegistry.register('sidebar', () => ({
      visible: true,
      label: 'Sidebar',
      children: ['nav'],
    }));
    ViewportRegistry.register('nav', () => ({
      visible: true,
      label: 'Navigation',
      children: [],
    }));

    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.children).toHaveLength(1);
    expect(tree.children[0].id).toBe('sidebar');
    expect(tree.children[0].label).toBe('Sidebar');
    expect(tree.children[0].children).toHaveLength(1);
    expect(tree.children[0].children[0].id).toBe('nav');
    expect(tree.children[0].children[0].label).toBe('Navigation');
  });

  it('non-visible children do not recurse (visibility gating)', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: ['hidden_panel'],
    }));
    ViewportRegistry.register('hidden_panel', () => ({
      visible: false,
      children: ['deep_child'],
    }));
    ViewportRegistry.register('deep_child', () => ({
      visible: true,
      label: 'Should not appear',
      children: [],
    }));

    const tree = ViewportRegistry.describeViewport('app');
    const hiddenPanel = tree.children[0];
    expect(hiddenPanel.id).toBe('hidden_panel');
    expect(hiddenPanel.visible).toBe(false);
    // Visibility gating: children of non-visible nodes are NOT recursed
    expect(hiddenPanel.children).toEqual([]);
  });

  it('includes inline ViewportNode children as-is', () => {
    const inlineChild: ViewportNode = {
      id: 'inline_tab',
      visible: true,
      label: 'Tab A',
      children: [],
      state: { active: true },
    };

    ViewportRegistry.register('tabs', () => ({
      visible: true,
      children: [inlineChild],
    }));

    const tree = ViewportRegistry.describeViewport('tabs');
    expect(tree.children).toHaveLength(1);
    expect(tree.children[0]).toBe(inlineChild);
    expect(tree.children[0].id).toBe('inline_tab');
    expect(tree.children[0].label).toBe('Tab A');
    expect(tree.children[0].state).toEqual({ active: true });
  });

  it('respects maxDepth', () => {
    ViewportRegistry.register('root', () => ({
      visible: true,
      children: ['level1'],
    }));
    ViewportRegistry.register('level1', () => ({
      visible: true,
      children: ['level2'],
    }));
    ViewportRegistry.register('level2', () => ({
      visible: true,
      children: ['level3'],
    }));
    ViewportRegistry.register('level3', () => ({
      visible: true,
      label: 'Too deep',
      children: [],
    }));

    // maxDepth=2 means: root(0) -> level1(1) -> level2(2, stop here)
    const tree = ViewportRegistry.describeViewport('root', 2);
    expect(tree.children).toHaveLength(1);
    expect(tree.children[0].id).toBe('level1');
    expect(tree.children[0].children).toHaveLength(1);
    expect(tree.children[0].children[0].id).toBe('level2');
    // level2 should have no children because we hit maxDepth
    expect(tree.children[0].children[0].children).toEqual([]);
  });

  it('includes state and actions', () => {
    ViewportRegistry.register('panel', () => ({
      visible: true,
      children: [],
      state: { collapsed: false, width: 300 },
      actions: [
        {
          id: 'toggle',
          command: 'panel.toggle',
          label: 'Toggle panel',
          payload: { target: 'panel' },
        },
      ],
    }));

    const tree = ViewportRegistry.describeViewport('panel');
    expect(tree.state).toEqual({ collapsed: false, width: 300 });
    expect(tree.actions).toHaveLength(1);
    expect(tree.actions![0].id).toBe('toggle');
    expect(tree.actions![0].command).toBe('panel.toggle');
    expect(tree.actions![0].label).toBe('Toggle panel');
    expect(tree.actions![0].payload).toEqual({ target: 'panel' });
  });

  it('handles reporter that throws (degrade gracefully)', () => {
    ViewportRegistry.register('broken', () => {
      throw new Error('Reporter exploded');
    });

    const tree = ViewportRegistry.describeViewport('broken');
    expect(tree.id).toBe('broken');
    expect(tree.visible).toBe(false);
    expect(tree.children).toEqual([]);
    // Should still get a timestamp on the root
    expect(tree.timestamp).toBeTypeOf('string');
  });

  it('register and unregister lifecycle', () => {
    expect(ViewportRegistry.has('lifecycle')).toBe(false);
    expect(ViewportRegistry.size).toBe(0);

    ViewportRegistry.register('lifecycle', () => ({
      visible: true,
      children: [],
    }));

    expect(ViewportRegistry.has('lifecycle')).toBe(true);
    expect(ViewportRegistry.size).toBe(1);

    ViewportRegistry.unregister('lifecycle');

    expect(ViewportRegistry.has('lifecycle')).toBe(false);
    expect(ViewportRegistry.size).toBe(0);

    // After unregister, describeViewport returns not-visible
    const node = ViewportRegistry.describeViewport('lifecycle');
    expect(node.visible).toBe(false);
  });

  it('re-registration overwrites previous reporter', () => {
    ViewportRegistry.register('widget', () => ({
      visible: true,
      label: 'Version 1',
      children: [],
    }));

    let tree = ViewportRegistry.describeViewport('widget');
    expect(tree.label).toBe('Version 1');

    ViewportRegistry.register('widget', () => ({
      visible: true,
      label: 'Version 2',
      children: [],
    }));

    // Size should not increase — it's the same ID
    expect(ViewportRegistry.size).toBe(1);

    tree = ViewportRegistry.describeViewport('widget');
    expect(tree.label).toBe('Version 2');
  });
});

// NOTE: useViewport hook tests are deferred to Phase 2.
// The hook requires a React rendering environment (jsdom/happy-dom)
// which is not available in the current node-based test environment.
