# Viewport Description System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live runtime viewport description system so agents can query what's actually visible and act through the same command paths users use.

**Architecture:** Renderer-side `ViewportRegistry` singleton with `useViewport` hook. Components register reporters that return `ViewportNode` trees on demand. Exposed via preload API. Zero cost when not queried.

**Tech Stack:** TypeScript, React hooks, Electron IPC, Vitest

**Spec:** `ai_general/todos/todo_0296_uai_component_viewport_description_system/2026-05-22-viewport-description-system-design.md`

---

### File Map

**Create:**
| File | Responsibility |
|------|---------------|
| `architecture/contracts/viewport.ts` | `ViewportNode`, `ViewportAction` type contracts |
| `packages/renderer-ui/src/viewport/viewport-registry.ts` | `ViewportRegistry` singleton — register, unregister, tree walk |
| `packages/renderer-ui/src/viewport/use-viewport.ts` | `useViewport` React hook |
| `packages/renderer-ui/src/viewport/index.ts` | Barrel export |
| `app/tests/contract-viewport.test.ts` | Contract tests for viewport system |

**Modify:**
| File | Change |
|------|--------|
| `architecture/contracts/index.ts` | Add `export * from './viewport'` |
| `packages/shared/src/types.ts` | Add `VIEWPORT_DESCRIBE` IPC constant |
| `app/main/index.ts` | Add IPC handler for viewport describe |
| `app/main/preload.ts` | Add `viewport.describeViewport()` to preload API |
| `app/renderer/App.tsx` | Wire `useViewport('app', ...)` |
| `packages/renderer-ui/src/components/Navigator.tsx` | Wire `useViewport('session_navigator', ...)` |
| `packages/renderer-ui/src/components/Workspace.tsx` | Wire `useViewport('workspace', ...)` |
| `packages/renderer-ui/src/components/TabContentPane.tsx` | Wire `useViewport('entity_view', ...)` |
| `packages/renderer-ui/src/components/ContextPanel.tsx` | Wire `useViewport('context_panel', ...)` |
| `packages/renderer-ui/src/components/BottomPanel.tsx` | Wire `useViewport('bottom_panel', ...)` |

---

### Task 1: Type Contracts

**Files:**
- Create: `architecture/contracts/viewport.ts`
- Modify: `architecture/contracts/index.ts`

- [ ] **Step 1: Write viewport.ts with ViewportNode and ViewportAction types**

```typescript
// architecture/contracts/viewport.ts

/**
 * Viewport Description Contracts
 *
 * Live runtime viewport state. Complements static ComponentDescription
 * (what components CAN do) with what's ACTUALLY visible and actionable.
 */

/** A node in the live viewport tree. */
export interface ViewportNode {
  /** Matches ComponentRegistry id */
  id: string;
  /** Is this component currently rendered? */
  visible: boolean;
  /** Human context: "Sessions tab", "Ember session" */
  label?: string;
  /** Only children the parent is currently rendering */
  children: ViewportNode[];
  /** Key/value pairs reflecting current state */
  state?: Record<string, unknown>;
  /** Actions available at this node right now */
  actions?: ViewportAction[];
  /** ISO timestamp — present only on the root node */
  timestamp?: string;
}

/** An action available at a viewport node. */
export interface ViewportAction {
  /** Action identifier, e.g., "toggle", "selectTab" */
  id: string;
  /** CommandBus command type — the SAME command the UI button fires */
  command: string;
  /** Pre-filled payload for this context */
  payload?: Record<string, unknown>;
  /** Human-readable description */
  label: string;
}

/** Reporter function that components provide to the ViewportRegistry. */
export type ViewportReporter = () => ViewportReporterResult;

/** Return type of a viewport reporter. */
export interface ViewportReporterResult {
  visible: boolean;
  label?: string;
  /** String = registered child ID to recurse into. ViewportNode = inline child. */
  children: (string | ViewportNode)[];
  state?: Record<string, unknown>;
  actions?: ViewportAction[];
}
```

- [ ] **Step 2: Add export to contracts index**

In `architecture/contracts/index.ts`, add:
```typescript
export * from './viewport';
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd app && npx tsc --noEmit 2>&1 | head -5`
Expected: No new errors.

- [ ] **Step 4: Commit**

```bash
git add architecture/contracts/viewport.ts architecture/contracts/index.ts
git commit -m "feat(viewport): add ViewportNode and ViewportAction type contracts"
```

---

### Task 2: ViewportRegistry Singleton

**Files:**
- Create: `packages/renderer-ui/src/viewport/viewport-registry.ts`

- [ ] **Step 1: Write the ViewportRegistry**

```typescript
// packages/renderer-ui/src/viewport/viewport-registry.ts

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
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd app && npx tsc --noEmit 2>&1 | head -5`

- [ ] **Step 3: Commit**

```bash
git add packages/renderer-ui/src/viewport/viewport-registry.ts
git commit -m "feat(viewport): add ViewportRegistry singleton with tree walk"
```

---

### Task 3: useViewport Hook

**Files:**
- Create: `packages/renderer-ui/src/viewport/use-viewport.ts`
- Create: `packages/renderer-ui/src/viewport/index.ts`

- [ ] **Step 1: Write the useViewport hook**

```typescript
// packages/renderer-ui/src/viewport/use-viewport.ts

import { useRef, useEffect } from 'react';
import { ViewportRegistry } from './viewport-registry';
import type { ViewportReporter } from '@contracts/viewport';

/**
 * Register a viewport reporter for this component.
 *
 * The reporter is called on-demand when describeViewport() is invoked.
 * Zero runtime cost otherwise. Callers do NOT need to useCallback.
 *
 * @param id - Component ID matching ComponentRegistry
 * @param reporter - Function returning current viewport state
 */
export function useViewport(id: string, reporter: ViewportReporter): void {
  const reporterRef = useRef(reporter);
  reporterRef.current = reporter;

  useEffect(() => {
    const stableReporter: ViewportReporter = () => reporterRef.current();
    ViewportRegistry.register(id, stableReporter);
    return () => ViewportRegistry.unregister(id);
  }, [id]);
}
```

- [ ] **Step 2: Write barrel export**

```typescript
// packages/renderer-ui/src/viewport/index.ts

export { ViewportRegistry } from './viewport-registry';
export { useViewport } from './use-viewport';
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd app && npx tsc --noEmit 2>&1 | head -5`

- [ ] **Step 4: Commit**

```bash
git add packages/renderer-ui/src/viewport/
git commit -m "feat(viewport): add useViewport hook and barrel export"
```

---

### Task 4: Contract Tests

**Files:**
- Create: `app/tests/contract-viewport.test.ts`

- [ ] **Step 1: Write contract tests**

```typescript
// app/tests/contract-viewport.test.ts

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { ViewportRegistry } from '@uai/renderer-ui/viewport/viewport-registry';
import type { ViewportNode } from '../../architecture/contracts/viewport';

describe('ViewportRegistry contract tests', () => {
  beforeEach(() => {
    // Reset all reporters between tests
    (ViewportRegistry as any).reporters.clear();
  });

  it('returns not-visible node for unregistered component', () => {
    const tree = ViewportRegistry.describeViewport('nonexistent');
    expect(tree.id).toBe('nonexistent');
    expect(tree.visible).toBe(false);
    expect(tree.children).toEqual([]);
  });

  it('returns visible node for registered component', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: [],
    }));
    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.id).toBe('app');
    expect(tree.visible).toBe(true);
    expect(tree.timestamp).toBeDefined();
  });

  it('walks children recursively', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: ['child1', 'child2'],
    }));
    ViewportRegistry.register('child1', () => ({
      visible: true,
      label: 'First',
      children: [],
    }));
    ViewportRegistry.register('child2', () => ({
      visible: false,
      children: ['grandchild'],
    }));
    ViewportRegistry.register('grandchild', () => ({
      visible: true,
      children: [],
    }));

    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.children).toHaveLength(2);
    expect(tree.children[0].id).toBe('child1');
    expect(tree.children[0].visible).toBe(true);
    expect(tree.children[0].label).toBe('First');
    // child2 is not visible — should NOT recurse into grandchild
    expect(tree.children[1].id).toBe('child2');
    expect(tree.children[1].visible).toBe(false);
    expect(tree.children[1].children).toEqual([]);
  });

  it('includes inline ViewportNode children as-is', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      children: [
        { id: 'inline_child', visible: true, children: [] },
      ],
    }));
    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.children).toHaveLength(1);
    expect(tree.children[0].id).toBe('inline_child');
  });

  it('respects maxDepth', () => {
    ViewportRegistry.register('app', () => ({ visible: true, children: ['child1'] }));
    ViewportRegistry.register('child1', () => ({ visible: true, children: ['grandchild'] }));
    ViewportRegistry.register('grandchild', () => ({ visible: true, children: [] }));

    const tree = ViewportRegistry.describeViewport('app', 1);
    expect(tree.children).toHaveLength(1);
    expect(tree.children[0].id).toBe('child1');
    // grandchild should be a leaf (depth exceeded)
    expect(tree.children[0].children).toEqual([]);
  });

  it('includes state and actions', () => {
    ViewportRegistry.register('app', () => ({
      visible: true,
      state: { activeTab: 'sessions' },
      actions: [
        { id: 'toggle', command: 'app.state.update', payload: { open: false }, label: 'Close' },
      ],
      children: [],
    }));
    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.state).toEqual({ activeTab: 'sessions' });
    expect(tree.actions).toHaveLength(1);
    expect(tree.actions![0].command).toBe('app.state.update');
  });

  it('handles reporter that throws', () => {
    ViewportRegistry.register('app', () => {
      throw new Error('reporter failed');
    });
    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.visible).toBe(false);
    expect(tree.children).toEqual([]);
  });

  it('register and unregister lifecycle', () => {
    expect(ViewportRegistry.has('app')).toBe(false);
    ViewportRegistry.register('app', () => ({ visible: true, children: [] }));
    expect(ViewportRegistry.has('app')).toBe(true);
    ViewportRegistry.unregister('app');
    expect(ViewportRegistry.has('app')).toBe(false);
  });

  it('re-registration overwrites previous reporter', () => {
    ViewportRegistry.register('app', () => ({ visible: true, label: 'first', children: [] }));
    ViewportRegistry.register('app', () => ({ visible: true, label: 'second', children: [] }));
    const tree = ViewportRegistry.describeViewport('app');
    expect(tree.label).toBe('second');
  });
});

// Note: useViewport hook tests require a React testing environment (jsdom + @testing-library/react).
// The vitest config uses environment: 'node'. Hook lifecycle testing (mount/unmount/ref updates)
// is deferred to Phase 2 when a jsdom test harness is added. The contract tests above validate
// the registry's behavior, which is the critical path.
```

- [ ] **Step 2: Run tests**

Run: `cd app && npx vitest run tests/contract-viewport.test.ts`
Expected: All 8 tests pass.

- [ ] **Step 3: Commit**

```bash
git add app/tests/contract-viewport.test.ts
git commit -m "test(viewport): add contract tests for ViewportRegistry"
```

---

### Task 5: Wire Top-Level Components

**Files:**
- Modify: `app/renderer/App.tsx`
- Modify: `packages/renderer-ui/src/components/Navigator.tsx`
- Modify: `packages/renderer-ui/src/components/Workspace.tsx`
- Modify: `packages/renderer-ui/src/components/TabContentPane.tsx`
- Modify: `packages/renderer-ui/src/components/ContextPanel.tsx`
- Modify: `packages/renderer-ui/src/components/BottomPanel.tsx`

- [ ] **Step 1: Wire App.tsx**

Add import and hook call:
```typescript
import { useViewport } from '@uai/renderer-ui/viewport';

// Inside App() function body, before return:
useViewport('app', () => ({
  visible: true,
  children: ['session_navigator', 'workspace', 'bottom_panel'],
}));
```

- [ ] **Step 2: Wire Navigator.tsx**

Add import and hook call inside the Navigator component:
```typescript
import { useViewport } from '../viewport';

// Inside Navigator() function body:
useViewport('session_navigator', () => ({
  visible: true,
  label: `${activeTab} tab`,
  state: {
    activeTab,
    visibleCards: filteredSessionCards.length,
    filterActive: filter.search !== '' || filter.status.size > 0 || filter.platform.size > 0,
  },
  children: [],
}));
```

- [ ] **Step 3: Wire Workspace.tsx**

```typescript
import { useViewport } from '../viewport';

// Inside Workspace() function body:
useViewport('workspace', () => ({
  visible: true,
  state: {
    activeTabId,
    tabCount: tabs.length,
  },
  children: activeTab ? ['entity_view'] : [],
}));
```

- [ ] **Step 4: Wire TabContentPane.tsx — entity_view**

Inside the `SessionContent` function (and similarly for other content functions that render a detail panel):
```typescript
import { useViewport } from '../viewport';

// Inside SessionContent:
useViewport('entity_view', () => ({
  visible: true,
  label: `session: ${session?.display_name || tab.targetId}`,
  children: ['session_pane', 'context_panel'],
}));
```

Note: Only the active entity view content function should register. Since React unmounts inactive content, only the visible one will be registered at any time. In Phase 1, only `SessionContent` and `TranscriptContent` wire `entity_view`. Other content types (folder, project, team, etc.) can be wired in Phase 2. When a non-session tab is active and no content function registers `entity_view`, the workspace reporter's `['entity_view']` child will resolve to `{ id: 'entity_view', visible: false }` — which is accurate.

- [ ] **Step 5: Wire ContextPanel.tsx**

```typescript
import { useViewport } from '../viewport';

// Inside ContextPanel():
useViewport('context_panel', () => ({
  visible: isOpen,
  state: { activeTab: activeRightTab, open: isOpen, width },
  actions: [
    {
      id: 'toggle',
      command: 'app.state.update',
      payload: { contextPanelOpen: !isOpen },
      label: isOpen ? 'Close panel' : 'Open panel',
    },
  ],
  children: [],
}));
```

- [ ] **Step 6: Wire BottomPanel.tsx**

```typescript
import { useViewport } from '../viewport';

// Inside BottomPanel(), using the existing `isOpen` variable:
useViewport('bottom_panel', () => ({
  visible: true,
  state: { collapsed: !isOpen },
  actions: [
    {
      id: 'toggle',
      command: 'app.state.update',
      payload: { bottomPanelOpen: !isOpen },
      label: isOpen ? 'Collapse panel' : 'Expand panel',
    },
  ],
  children: [],
}));
```

- [ ] **Step 7: Verify TypeScript compiles**

Run: `cd app && npx tsc --noEmit 2>&1 | head -10`
Expected: No new errors.

- [ ] **Step 8: Commit**

```bash
git add app/renderer/App.tsx packages/renderer-ui/src/components/Navigator.tsx \
  packages/renderer-ui/src/components/Workspace.tsx \
  packages/renderer-ui/src/components/TabContentPane.tsx \
  packages/renderer-ui/src/components/ContextPanel.tsx \
  packages/renderer-ui/src/components/BottomPanel.tsx
git commit -m "feat(viewport): wire useViewport to 6 top-level components"
```

---

### Task 6: IPC Handler and Preload API Exposure

**Files:**
- Modify: `app/main/index.ts`
- Modify: `app/main/preload.ts`
- Modify: `packages/shared/src/types.ts`

The ViewportRegistry lives in the renderer. The preload uses `contextBridge` which serializes values across the context isolation boundary, so `require()` of renderer modules won't work. Instead, use the standard IPC pattern: renderer builds the tree, returns it through `ipcRenderer.invoke()` → `ipcMain.handle()`.

- [ ] **Step 1: Add IPC constant**

In `packages/shared/src/types.ts`, add to the `IPC` constants object:
```typescript
VIEWPORT_DESCRIBE: 'uai:viewport:describeViewport',
```

- [ ] **Step 2: Add IPC handler in main process**

In `app/main/index.ts`, the main process needs to ask the renderer to build the tree. Use `webContents.executeJavaScript()`:

```typescript
ipcMain.handle(IPC.VIEWPORT_DESCRIBE, async () => {
  // Dev gate
  if (process.env.UAI_VIEWPORT !== '1' && app.isPackaged) return null;
  if (!mainWindow || mainWindow.isDestroyed()) return null;

  try {
    return await mainWindow.webContents.executeJavaScript(
      'window.__viewportRegistry?.describeViewport() ?? null'
    );
  } catch {
    return null;
  }
});
```

- [ ] **Step 3: Expose ViewportRegistry on window in renderer entry**

In `packages/renderer-ui/src/viewport/viewport-registry.ts`, after the singleton export, add:

```typescript
// Expose for IPC bridge (main process calls via executeJavaScript)
if (typeof window !== 'undefined') {
  (window as any).__viewportRegistry = ViewportRegistry;
}
```

- [ ] **Step 4: Add viewport namespace to preload API**

In `app/main/preload.ts`, add to the `uaiApi` object:

```typescript
import type { ViewportNode } from '@contracts/viewport';

// ── Viewport Description ─────────────────────────────────────────────
viewport: {
  describeViewport: (): Promise<ViewportNode | null> =>
    ipcRenderer.invoke(IPC.VIEWPORT_DESCRIBE),
},
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd app && npx tsc --noEmit 2>&1 | head -5`

- [ ] **Step 6: Commit**

```bash
git add app/main/index.ts app/main/preload.ts packages/shared/src/types.ts
git commit -m "feat(viewport): IPC handler and preload API for describeViewport()"
```

---

### Task 7: Smoke Test — Build and Verify

**Files:** None (verification only)

- [ ] **Step 1: Run all contract tests**

Run: `cd app && npx vitest run`
Expected: All tests pass including the new viewport tests.

- [ ] **Step 2: Build packaged app**

```bash
cd app && rm -rf .vite/ out/ && npx electron-forge package
```
Expected: Build succeeds.

- [ ] **Step 3: Launch and verify via DevTools console**

Launch the app. Open DevTools (Cmd+Option+I). Run:
```javascript
await window.uai.viewport.describeViewport()
```
Expected: Returns a ViewportNode tree with `app` as root, children for navigator/workspace/bottom_panel, correct visibility states.

- [ ] **Step 4: Version bump and deploy**

Increment version in `app/package.json`, build, deploy to `ai_general/apps/unified_ai_ui/UnifiedAI.app`.

- [ ] **Step 5: Commit version bump**

```bash
git add app/package.json
git commit -m "chore: bump version for viewport description system"
```

---

### Task 8: Architecture Documentation

**Files:**
- Modify: `architecture/uai_architecture_v1.1.md`

- [ ] **Step 1: Add Viewport Description System section**

Add a new section (after the Component API section) documenting:
- The three-layer model (Static/Live/Action)
- `ViewportNode` contract reference
- `useViewport` hook usage
- `window.uai.viewport.describeViewport()` API
- The "Same Path" principle
- Relationship between `ViewportNode.state` and `ComponentDescription.state`

- [ ] **Step 2: Commit**

```bash
git add architecture/uai_architecture_v1.1.md
git commit -m "docs: add Viewport Description System to architecture spec"
```
