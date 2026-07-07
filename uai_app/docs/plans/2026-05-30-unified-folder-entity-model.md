# Unified Folder Entity Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Group entity, establish Folders as universal containers (session + project), add Team-based tab bar bracketing, and add a Tabs menu to the Electron menu bar.

**Architecture:** Three phases shipped sequentially. Phase 1 removes Groups and adds Team tab bracketing as a single cutover. Phase 2 generalizes Folders to accept project entities. Phase 3 adds a dynamic Tabs menu to the menu bar.

**Tech Stack:** TypeScript, React, Electron (main + renderer), containers.json (persistence), entity_relationships SQLite (team membership)

**Spec:** `ai_general/todos/todo_0303_uai_unified_folder_entity_model/2026-05-30-unified-folder-entity-model.md`

**Deferred (not in this plan):**
- "Assign to Team" context menu action (requires slot-selection UI — separate task)
- Terminal/WebUI entity contracts (prerequisite for making them folderable)

---

## Phase 1: Remove Groups + Team Tab Bracketing

### Task 1: Remove Group from type contracts

**Files:**
- Modify: `architecture/contracts/entities.ts:12,24` (EntityType, CardId)
- Modify: `architecture/contracts/cards.ts:15,82-85,120,124-126,140-142` (ContainerType, GroupCard, AnyCard, isContainerCard, isGroupCard)
- Modify: `architecture/contracts/components.ts:201` (NavigatorTab)
- Modify: `packages/shared/src/cards.ts:10,14` (re-exports)

- [ ] **Step 1: Update EntityType and CardId**

In `architecture/contracts/entities.ts`:

Line 12:
```typescript
export type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder';
```

Line 24 — remove `group:${string}` from CardId:
```typescript
export type CardId = `session:${string}` | `brief:${string}` | `project:${string}` | `team:${string}` | `folder:${string}`;
```

- [ ] **Step 2: Update ContainerType**

In `architecture/contracts/cards.ts:15`:
```typescript
export type ContainerType = 'folder';
```

- [ ] **Step 3: Remove GroupCard interface, isGroupCard, update AnyCard and isContainerCard**

In `architecture/contracts/cards.ts`:
- Delete `GroupCard` interface (lines 82-85)
- Delete `isGroupCard` function (lines 140-142)
- Update `AnyCard` (line 120):
```typescript
export type AnyCard = SessionCard | BriefCard | FolderCard | ProjectCard | TeamCard;
```
- Update `isContainerCard` (lines 124-126):
```typescript
export function isContainerCard(card: BaseCard): card is FolderCard {
  return card.entity_type === 'folder' && card.container !== undefined;
}
```

- [ ] **Step 4: Update NavigatorTab**

In `architecture/contracts/components.ts:201`:
```typescript
export type NavigatorTab = 'sessions' | 'briefs' | 'teams' | 'projects';
```

- [ ] **Step 5: Update shared cards re-exports**

In `packages/shared/src/cards.ts`:
- Remove `GroupCard` from the type export on line 10
- Remove `isGroupCard` from the function export on line 14

- [ ] **Step 6: Compile check**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1 | head -30`
Expected: Type errors in Navigator, Workspace, card-store, CardRenderer — fixed in subsequent tasks.

- [ ] **Step 7: Commit**

```bash
git add architecture/contracts/ packages/shared/src/cards.ts
git commit -m "refactor: remove Group from type contracts (todo_0303 Phase 1)"
```

---

### Task 2: Clean up Navigator — remove Groups tab, GroupContextMenu, and group imports

**Files:**
- Modify: `packages/renderer-ui/src/components/Navigator.tsx`

- [ ] **Step 1: Remove GroupContextMenu component**

Delete the entire `GroupContextMenu` function component (around lines 392-452).

- [ ] **Step 2: Remove group-related state and callbacks**

Remove from the Navigator component body:
- `groupContextMenu` state (line 960)
- `createGroup` callback (line 1048)
- `handleGroupContextMenu` callback (line 1069)
- `handleGroupCardClick` callback
- `const { groups } = cardStore` destructuring (line 946)
- The `+ New Group` button that calls `createGroup`

- [ ] **Step 3: Remove Groups tab content**

Remove the `{activeTab === 'groups' && (...)}` block (the entire `<>...</>` with new-session-bar and CardListView for groups).

- [ ] **Step 4: Remove GroupContextMenu rendering**

Remove the `{groupContextMenu && (<GroupContextMenu .../>)}` block.

- [ ] **Step 5: Remove group imports**

Remove `GroupCard` and `isGroupCard` from the import of `@uai/shared/cards`.

- [ ] **Step 6: Compile check**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1 | head -30`
Expected: Errors reduced — remaining errors in Workspace, card-store, CardRenderer.

- [ ] **Step 7: Commit**

```bash
git add packages/renderer-ui/src/components/Navigator.tsx
git commit -m "refactor: remove Groups tab and GroupContextMenu from Navigator"
```

---

### Task 3: Clean up Workspace — remove dead group code, keep groupId brackets

**Files:**
- Modify: `packages/renderer-ui/src/components/Workspace.tsx`

**Pre-audit — what stays vs goes:**

| Symbol | Used by groupId bracket code? | Action |
|--------|-------------------------------|--------|
| `GROUP_COLORS` | YES (line 458) | KEEP |
| `GRID_LAYOUTS` | NO (was in old group header only) | REMOVE |
| `GroupTabState` interface | YES (type for `groupStates`) | KEEP |
| `groupStates` state | YES (line 457) | KEEP |
| `toggleGroupCollapse` | YES (lines 476, 488) | KEEP |
| `hideInGroup` | NO | REMOVE |
| `setGroupLayout` | NO | REMOVE |
| `closeGroup` | NO | REMOVE |
| `GroupCard` import | NO | REMOVE |
| Group init `useEffect` (line 315) | NO (watches `tab.type === 'group'`) | REMOVE |
| Group grid rendering (line 613) | NO (renders `tab.type === 'group'` content) | REMOVE |
| `handleCloseTab` group branch (line 384) | NO | REMOVE |

- [ ] **Step 1: Remove dead symbols**

Remove: `GRID_LAYOUTS`, `hideInGroup`, `setGroupLayout`, `closeGroup`, `GroupCard` import.

- [ ] **Step 2: Remove group init useEffect**

Remove the `useEffect` block (around line 315) that initializes `groupStates` for new `tab.type === 'group'` tabs.

- [ ] **Step 3: Remove group content rendering**

Remove the `activeTab.type === 'group'` grid-layout rendering block (around line 613).

- [ ] **Step 4: Remove handleCloseTab group branch**

In `handleCloseTab`, remove the `if (tab?.type === 'group') { closeGroup(tab.targetId); }` branch — just call `executeCloseTab(tabId)` for all tabs.

- [ ] **Step 5: Compile check**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1 | head -30`
Expected: Errors only in card-store and CardRenderer.

- [ ] **Step 6: Commit**

```bash
git add packages/renderer-ui/src/components/Workspace.tsx
git commit -m "refactor: remove group entity code from Workspace, keep groupId brackets"
```

---

### Task 4: Clean up card-store, TabContentPane, and CardRenderer

**Files:**
- Modify: `packages/renderer-ui/src/stores/card-store.ts`
- Modify: `packages/renderer-ui/src/components/TabContentPane.tsx`
- Modify: `packages/renderer-ui/src/components/cards/CardRenderer.tsx`

- [ ] **Step 1: Update containerToCard adapter in card-store**

In `card-store.ts`, the `containerToCard` function (line 66) has a `group` branch at line 83:
```typescript
if (entry.container_type === 'group') {
    return { ...base, entity_type: 'group' as const } as GroupCard;
}
```
Change to skip group entries:
```typescript
if (entry.container_type === 'group') {
    return null;  // Groups removed — skip
}
```
Update the caller `hydrateContainers` (line 90) to handle the null return.

- [ ] **Step 2: Remove groups selector from card-store**

Remove `groups` computed value and any `isGroupCard` usage from the store's public API.

- [ ] **Step 3: Remove GroupContent from TabContentPane**

Delete the `GroupContent` component and remove its `case 'group':` dispatch in the tab content router.

- [ ] **Step 4: Remove isGroupCard import from CardRenderer**

In `packages/renderer-ui/src/components/cards/CardRenderer.tsx` line 8, remove `isGroupCard` from the import. Remove any `isGroupCard(card)` rendering branch.

- [ ] **Step 5: Compile check**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1 | head -30`
Expected: Clean compile (only pre-existing errors if any).

- [ ] **Step 6: Commit**

```bash
git add packages/renderer-ui/src/stores/card-store.ts packages/renderer-ui/src/components/TabContentPane.tsx packages/renderer-ui/src/components/cards/CardRenderer.tsx
git commit -m "refactor: remove group selectors, GroupContent, and isGroupCard usage"
```

---

### Task 5: Add migrations for containers.json and app_state.json

**Files:**
- Modify: `app/main/container-manager.ts`
- Modify: `app/main/command-handlers.ts`

- [ ] **Step 1: Add group container migration in container-manager**

In container-manager.ts, during load/normalization, add before returning data:
```typescript
// Migration: drop group containers
for (const [id, container] of Object.entries(data.containers || {})) {
  if (container.type === 'group') {
    console.warn(`[migration] Dropping group container "${container.name}" (${container.children.length} members)`);
    delete data.containers[id];
  }
}
```

- [ ] **Step 2: Remove `group` from TYPE_PLACEMENT map**

In container-manager.ts line 158-161, remove the group entry:
```typescript
const TYPE_PLACEMENT: Record<string, PlacementRule> = {
  folder: 'exclusive',
};
```

- [ ] **Step 3: Remove `'group'` from VALID_TAB_TYPES and filter group tabs**

In command-handlers.ts:
- Line 44: remove `'group'` from the `VALID_TAB_TYPES` set
- In the normalizer function, add: `tabs = tabs.filter((t: any) => t.type !== 'group');`

- [ ] **Step 4: Restrict container.create to folder type**

In command-handlers.ts, in the `container.create` handler (around line 858), narrow the accepted type:
```typescript
const type = command.payload.type;
if (type !== 'folder') {
  return { ok: false, command_id: command.id, error: { code: 'INVALID_TYPE', message: `Only folder containers are supported. Got: ${type}` } };
}
```

- [ ] **Step 5: Compile check + manual test**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1`
Expected: Clean compile.

- [ ] **Step 6: Commit**

```bash
git add app/main/container-manager.ts app/main/command-handlers.ts
git commit -m "feat: add migration to drop group containers/tabs, restrict to folders (todo_0303)"
```

---

### Task 6: Build, deploy, verify Phase 1

- [ ] **Step 1: Full compile check**

Run: `npx tsc -p app/tsconfig.json --noEmit 2>&1`
Expected: Clean.

- [ ] **Step 2: Build and deploy**

Bump version in package.json, run `npm run build`, deploy to `apps/unified_ai_ui/UnifiedAI.app`.

- [ ] **Step 3: Verify**

- App launches without crash
- Navigator has no Groups tab
- Folder tree works normally
- Tab bar renders standalone tabs (no brackets since no teams assigned yet)
- No `type: 'group'` tabs appear
- Teams tab still works
- Projects tab still works
- Console shows migration warnings for any dropped group containers

---

## Phase 2: Generalize Folders

### Task 7: Update folder display label and Navigator tab

**Files:**
- Modify: `packages/renderer-ui/src/stores/folder-store.ts:25` — change default name
- Modify: `packages/renderer-ui/src/components/Navigator.tsx` — rename tab label

- [ ] **Step 1: Change default root folder display name**

In folder-store.ts line 25:
```typescript
name: 'All Entities',   // was 'All Sessions'
```

Note: storage key `roots.sessions` stays unchanged for backward compat.

- [ ] **Step 2: Rename Navigator tab label**

In Navigator.tsx, replace the tab bar rendering that uses `tab.charAt(0).toUpperCase() + tab.slice(1)` with a label map:
```typescript
const TAB_LABELS: Record<string, string> = { sessions: 'Folders', teams: 'Teams', projects: 'Projects' };
// In JSX:
{TAB_LABELS[tab] || tab}
```

- [ ] **Step 3: Commit**

```bash
git add packages/renderer-ui/src/stores/folder-store.ts packages/renderer-ui/src/components/Navigator.tsx
git commit -m "feat: rename Sessions tab to Folders, root to All Entities"
```

---

### Task 8: Enable project cards in folders

**Files:**
- Modify: `app/main/container-manager.ts:165-168` — update cardRootType
- Modify: `packages/renderer-ui/src/components/folders/FolderContextMenu.tsx` — add "Add Project" action

- [ ] **Step 1: Update cardRootType to accept project cards**

In container-manager.ts, update the `cardRootType` function (line 165):
```typescript
function cardRootType(cardId: string): string | null {
  if (cardId.startsWith('session:')) return 'sessions';
  if (cardId.startsWith('brief:')) return 'briefs';
  if (cardId.startsWith('project:')) return 'sessions';  // projects go in entities root
  return null;
}
```

- [ ] **Step 2: Verify ProjectCard renders in FolderContent**

FolderContent uses `CardListView → CardRenderer` which already handles `isProjectCard` via `ProjectCardVisual`. No changes needed — verify by adding a project to a folder and checking it renders.

- [ ] **Step 3: Add "Add Project" to folder context menu**

In FolderContextMenu.tsx, add an "Add Project" submenu item. Pattern matches existing "Add Session" item but picks from `cardStore.projects` not already in the folder.

- [ ] **Step 4: Update folder.moveCard command to accept project IDs**

Verify `folder.moveCard` in command-handlers.ts works for `project:*` IDs — the `cardRootType` fix in Step 1 should handle root validation. Test manually.

- [ ] **Step 5: Compile check + build + deploy**

- [ ] **Step 6: Commit**

```bash
git add app/main/container-manager.ts packages/renderer-ui/src/components/folders/FolderContextMenu.tsx
git commit -m "feat: enable project cards in folders (todo_0303 Phase 2)"
```

---

### Task 9: Update filter drawer with Entity Types

**Files:**
- Modify: `packages/renderer-ui/src/components/TabContentPane.tsx`

- [ ] **Step 1: Rename SessionFilter to FolderFilter, add entityTypes**

```typescript
interface FolderFilter {
  entityTypes: Set<string>;  // 'session' | 'project'
  status: Set<string>;
  platform: Set<string>;
  search: string;
  dateRange: DateRange | null;
  tags: Set<string>;
}

const DEFAULT_FOLDER_FILTER: FolderFilter = {
  entityTypes: new Set(),
  status: new Set(),
  platform: new Set(),
  search: '',
  dateRange: null,
  tags: new Set(),
};
```

- [ ] **Step 2: Update applySessionFilter (rename to applyFolderFilter)**

Add entity type check as first filter:
```typescript
if (filter.entityTypes.size > 0 && !filter.entityTypes.has(c.entity_type)) return false;
```

- [ ] **Step 3: Add Entity Types pills to FolderFilterDrawer**

Add a row at the top of the filter drawer:
```typescript
<div className="nav-filter-row">
  <button className={`filter-pill${filter.entityTypes.has('session') ? ' active' : ''}`}
    onClick={() => toggleFilter('entityTypes', 'session')}>Session</button>
  <button className={`filter-pill${filter.entityTypes.has('project') ? ' active' : ''}`}
    onClick={() => toggleFilter('entityTypes', 'project')}>Project</button>
</div>
```

- [ ] **Step 4: Compile check + build + deploy**

- [ ] **Step 5: Commit**

```bash
git add packages/renderer-ui/src/components/TabContentPane.tsx
git commit -m "feat: add entity type filter to folder view (todo_0303 Phase 2)"
```

---

### Task 10: Update folder counts with tooltip

**Files:**
- Modify: `packages/renderer-ui/src/components/folders/FolderTree.tsx`

- [ ] **Step 1: Count by entity type**

When rendering folder counts, categorize cards by entity_id prefix:
```typescript
const sessionCount = folder.cards.filter(id => id.startsWith('session:')).length;
const projectCount = folder.cards.filter(id => id.startsWith('project:')).length;
const total = folder.cards.length;
```

- [ ] **Step 2: Render total with tooltip**

```typescript
<span className="folder-count" title={`Sessions: ${sessionCount}, Projects: ${projectCount}`}>
  {total}
</span>
```

- [ ] **Step 3: Compile check + build + deploy**

- [ ] **Step 4: Commit**

```bash
git add packages/renderer-ui/src/components/folders/FolderTree.tsx
git commit -m "feat: type-aware folder counts with tooltip (todo_0303 Phase 2)"
```

---

## Phase 3: Tabs Menu

### Task 11: Add dynamic Tabs menu to Electron menu bar

**Files:**
- Modify: `app/main/index.ts` — add Tabs menu, rebuild on appState change
- Modify: `app/renderer/App.tsx` or preload — handle activate-tab IPC

- [ ] **Step 1: Create rebuildAppMenu function**

Move the menu template into a function. Use the in-memory appState (not re-reading from disk) to avoid race conditions:

```typescript
function rebuildAppMenu(currentState?: { tabs: any[]; activeTabId: string | null }) {
  const tabs = currentState?.tabs || [];
  const activeTabId = currentState?.activeTabId || null;

  const tabMenuItems: Electron.MenuItemConstructorOptions[] = tabs.map((tab: any, i: number) => ({
    label: tab.label || tab.targetId,
    accelerator: i < 9 ? `CmdOrCtrl+${i + 1}` : undefined,
    click: () => mainWindow?.webContents.send('activate-tab', tab.id),
    checked: tab.id === activeTabId,
    type: 'checkbox' as const,
  }));

  tabMenuItems.push({ type: 'separator' });
  tabMenuItems.push({
    label: 'Close Tab',
    accelerator: 'CmdOrCtrl+W',
    click: () => mainWindow?.webContents.send('close-active-tab'),
  });
  tabMenuItems.push({
    label: 'Close Others',
    click: () => mainWindow?.webContents.send('close-other-tabs'),
  });

  const appMenu = Menu.buildFromTemplate([
    // ... existing menus (App, Edit, View, Window) ...
    { label: 'Tabs', submenu: tabMenuItems },
  ]);
  Menu.setApplicationMenu(appMenu);
}
```

- [ ] **Step 2: Call rebuildAppMenu after appState changes**

After any command that emits `['appState']`, call `rebuildAppMenu(currentState)`.
Also call once on app ready after initial state load.

- [ ] **Step 3: Handle IPC in renderer**

In the renderer, listen for `activate-tab`, `close-active-tab`, and `close-other-tabs`:
```typescript
window.uai.ipc.on('activate-tab', (tabId: string) => {
  executeCommand('workspace.tabs.activate', { tabId });
});
window.uai.ipc.on('close-active-tab', () => {
  // close current active tab
});
window.uai.ipc.on('close-other-tabs', () => {
  // close all except active
});
```

- [ ] **Step 4: Compile check + build + deploy**

- [ ] **Step 5: Verify**

- Tabs menu appears in menu bar
- Lists all open tabs with checkmark on active tab
- Cmd+1 through Cmd+9 activate tabs
- Close Tab and Close Others work
- Menu updates when tabs open/close

- [ ] **Step 6: Commit**

```bash
git add app/main/index.ts
git commit -m "feat: add dynamic Tabs menu to Electron menu bar (todo_0303 Phase 3)"
```

---

## Summary

| Phase | Tasks | Scope |
|-------|-------|-------|
| Phase 1 | Tasks 1-6 | Remove Groups, add Team bracketing, migrations |
| Phase 2 | Tasks 7-10 | Generalize Folders, entity type filter, project cards |
| Phase 3 | Task 11 | Tabs menu in menu bar |

Total: 11 tasks, ~40 steps.

## Review Findings Addressed

| Finding | Resolution |
|---------|------------|
| C1: Missing CardId update | Task 1 Step 1 — CardId updated alongside EntityType |
| C2: Missing VALID_TAB_TYPES cleanup | Task 5 Step 3 — explicitly removes 'group' from set |
| C3: Vague container.create restriction | Task 5 Step 4 — explicit guard rejecting non-folder types |
| C4: Missing containerToCard adapter | Task 4 Step 1 — containerToCard returns null for group entries |
| I3: Task 3 vagueness | Pre-audit table added with definitive keep/remove for each symbol |
| I4: CardRenderer isGroupCard import | Task 4 Step 4 — explicitly removes import |
| I5: cardRootType for project: prefix | Task 8 Step 1 — adds project: → sessions mapping |
| I6: Assign to Team menu | Deferred — noted in plan header |
| I7: Tabs menu Close/Close Others | Task 11 Step 1 — included in menu template |
| S1: rebuildMenu disk read | Task 11 Step 1 — uses in-memory state parameter |
