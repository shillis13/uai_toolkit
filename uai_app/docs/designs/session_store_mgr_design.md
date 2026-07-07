# Session Store Manager — UI Design Document

**Date:** 2026-06-03
**Status:** Design — ready for implementation review

---

## 1. Backend Capabilities Summary

### 1.1 session_store.py — SQLite Session Registry

Location: `ai_general/scripts/session_mgmt/session_store.py`

SQLite-backed store for all session identity and metadata. Already called via `callStore()` in `app/main/session-store.ts`.

**Core session fields (sessions table):**

| Field | Type | Mutable | Description |
|---|---|---|---|
| tracking_id | TEXT PK | no | `YYYYMMDD_HHMMSS_{uuid8}_{code}` |
| terminal_session | TEXT | yes | tmux/zellij session name |
| cli_session_id | TEXT | yes | Platform UUID |
| platform | TEXT | no | `claude_cli`, `codex_cli`, `gemini_cli` |
| session_dir | TEXT | no | Per-session data directory |
| project_dir | TEXT | no | Working directory / project root |
| display_name | TEXT | yes | Human-readable name |
| model | TEXT | yes | AI model string |
| substrate | TEXT | yes | `tmux`, `zellij`, `none` |
| tmux_server | TEXT | yes | Named tmux server |
| roles | TEXT | yes | JSON array of role strings |
| notes | TEXT | yes | Free-text annotation |
| status | TEXT | yes | `running`, `stopped`, `exited` |
| identity_status | TEXT | yes | `draft`, `pending`, `confirmed`, `failed`, `orphaned` |
| created_at | TEXT | no | ISO 8601 UTC |
| archived | BOOLEAN | yes | Soft-deleted flag |
| last_activity | TEXT | yes | ISO 8601 UTC |

**Additional tables:** `session_tags`, `entity_relationships`, `brief_metadata`, `change_log`.

**CLI commands:**
- `list [--json] [--platform X] [--status X] [--text X]`
- `get <tracking_id>` / `update <tracking_id> --set field=value`
- `delete <tracking_id>`
- `get_tags` / `add_tag` / `remove_tag`
- `history [--tracking-id X] [--limit N]`
- `validate_running_sessions [--fix]` / `find_orphans`
- `export [--format json|csv]`

**Signal file:** `ai_general/data/sessions.changed` — touched on every write. Existing `fs.watch` in app detects changes.

### 1.2 store.py — Per-Session Key-Value State

Location: `ai_general/scripts/session_mgmt/store.py`

Per-session JSON file at `{session_dir}/{tracking_id}_state.json`. File-locked, atomic writes.

**Known key namespaces:**

| Namespace | Examples | Writer |
|---|---|---|
| env.* | `AI_TRACKING_ID`, `AI_SESSION_PLATFORM` | launcher |
| session.* | `display_name`, `last_activity` | ai/mcp |
| compact.* | `auto_brief`, `start`, `pre_ctx_pct` | hook |
| context.* | `used_pct`, `tokens`, `cost_usd` | hook |
| loaded.* | `docs`, `traits`, `roles`, `manifest` | ai/mcp |
| transcript.* | `turns`, `messages`, `tool_calls` | hook |
| usage.* | `5h.used_pct`, `5h.resets_at` | hook |
| (legacy) | `role`, `features`, `ai_root` | launcher/ai |

**Operations via session_mgr.py:**
- `state_get / state_set / state_delete / state_list / state_increment`
- Auto-coerces types (bool/int/float)

### 1.3 session_registry.py — Process Discovery

Discovers running sessions by scanning process trees. Used for bootstrap/reconciliation. App uses `session_store.py` (SQLite) as primary source.

### 1.4 session_ops.py — Terminal Interaction

Reads/writes to live terminal sessions. `get-status`, `read-terminal`, `write-to`. Already used by the app's status polling system.

---

## 2. Use Cases

1. **UC-01 — Browse all sessions**: Filterable by status/platform, sortable, with lifecycle indicators
2. **UC-02 — Inspect session store fields**: View all SQLite fields in readable layout
3. **UC-03 — Edit mutable session fields**: Inline edit `display_name`, `notes`, `roles`, `model`, etc.
4. **UC-04 — View per-session state variables**: All KV entries from state JSON, grouped by namespace
5. **UC-05 — Edit per-session state variables**: Change value, delete key, add new key
6. **UC-06 — View session change history**: Change log — who changed what, when, old→new
7. **UC-07 — Search across sessions**: Filter by any text field
8. **UC-08 — Manage session tags**: Add/remove tags
9. **UC-09 — Validate/diagnose sessions**: Find orphans, stale running sessions
10. **UC-10 — View session lineage**: Parent/children fork tree
11. **UC-11 — Archive/delete session**: Soft-delete or hard-delete
12. **UC-12 — Edit from Session Details**: [Edit] button in Right Panel opens store editor pre-loaded

---

## 3. Workflow Descriptions

### WF-1: Browse and Inspect
1. Open "Session Store" from Navigator Tools.
2. Sessions list loads grouped by status (Active, Stopped, Archived).
3. Each row: platform dot, display_name, tracking_id (truncated), age, tag pills.
4. Click row → right panel loads SQLite fields in labeled sections.

### WF-2: Edit a Session Field
1. Viewing session detail. Click pencil icon next to editable field.
2. Field transitions to inline input. Current value pre-filled.
3. Enter to save, Escape to cancel. IPC call fires.
4. Success: field shows new value with brief "Saved" flash. Error: red border + message.

### WF-3: View and Edit State Variables
1. In detail panel, click "State" sub-tab.
2. Keys render grouped by namespace — each group collapsible.
3. Each row: key name, type badge (str/int/float/bool/list), value, edit/delete icons.
4. Click pencil → inline edit. Click `+` → new key form (key + value inputs).
5. `env.*` keys are read-only (set by launcher).

### WF-4: View Change History
1. Click "History" sub-tab.
2. Timeline of changes — newest first.
3. Each entry: timestamp, field name, old value → new value, PID.
4. "Load More" to paginate.

### WF-5: Search Sessions
1. Search input at top of list. 250ms debounce.
2. Filters by display_name, tracking_id, project_dir, roles, notes.

### WF-6: Manage Tags
1. In Identity section, tag chips displayed with `+` icon.
2. Click `+` → inline text input. Enter to add.
3. Click `x` on chip to remove.

### WF-7: Validate
1. Click "Validate" top-level tab.
2. Two cards: "Orphaned Sessions" and "Stale Running Sessions".
3. "Check" buttons fire validation. Results list with "Fix" buttons.

### WF-8: Edit from Right Panel
1. Viewing session in workspace, right panel Session Details tab.
2. Click [Edit] button in header.
3. Session Store Manager pane opens with that session pre-selected.

---

## 4. UI Component Design

### Overall Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Session Store Manager                           [Refresh]  │
├─────────────────────────────────────────────────────────────┤
│  [Sessions] [Validate]                                      │
├───────────────────────────┬─────────────────────────────────┤
│  FILTER BAR               │                                 │
│  [All][Active][Stopped]   │    SESSION DETAIL PANEL          │
│  [Claude][Codex][Gemini]  │                                 │
│  [Search___________]      │    [Store Fields][State][History]│
│                           │                                 │
│  SESSION LIST             │    ▾ Identity                   │
│  ─── Active (3) ───       │      Tracking ID  20260530...   │
│  ● Kael           active  │      Display Name Kael     [✏] │
│  ● Pixel          active  │      ...                        │
│  ─── Stopped (12) ───     │    ▾ Classification             │
│  ○ Turnstyle      stopped │    ▾ Paths                      │
│  ...                      │    ▾ Notes                      │
│                           │    ▾ Tags                       │
│                           │    ▾ Timestamps                 │
└───────────────────────────┴─────────────────────────────────┘
```

### Detail Panel Sub-Tabs

**Store Fields** — Collapsible sections:
- Identity: tracking_id (copy), cli_session_id (copy), display_name (edit), identity_status, status
- Classification: platform, substrate, tmux_server, model (edit), roles (edit), parent
- Paths: project_dir (copy), session_dir (copy), history_file (copy)
- Notes: free-text (edit)
- Tags: chip pills with add/remove
- Timestamps: created_at, last_activity

**State Vars** — Namespace-grouped KV list:
- Header: "+ New Key" button, Refresh button
- Groups: context, transcript, env (read-only), loaded, compact, usage, (other)
- Each row: key, type badge, value, edit/delete icons
- `env.*` group: read-only, explanatory note

**History** — Change log timeline:
- Rows: timestamp, field, old→new, PID
- "Load More" pagination (50 at a time)

### Validate View
- Two cards side by side: Orphaned Sessions, Stale Running Sessions
- Each: description, "Check" button, results list with "Fix"/"Delete" actions

### Component States
| State | Treatment |
|---|---|
| Loading | Spinner text (`.traits-mgr-loading`) |
| Error | Red banner (`.traits-mgr-error`) |
| Empty list | Muted text (`.traits-mgr-empty`) |
| No selection | "Select a session to inspect" centered |
| Saving | "Saving..." flash, disabled input |
| Save error | Red input border + inline message |

---

## 5. Alternate Entry Points

### A. [Edit] Button in Session Details Right Panel
- `SessionDetailFields.tsx` gets `onEditInStore?: () => void` prop
- Renders `[Edit]` button in header when prop provided
- Opens Session Store Manager tab with session pre-selected

### B. Session Card Context Menu
- `SessionContextMenu.tsx` — add "View in Store Manager" item
- Same behavior as the [Edit] button

### C. Session Detail Metrics — "View raw state..." link
- Bottom of Metrics section in `SessionDetailFields.tsx`
- Opens Session Store Manager with State Vars sub-tab active

### D. Inline Tag Editing from Session Cards
- Context menu "Manage Tags" item → opens Store Manager at that session's Store Fields

---

## 6. IPC Channel Design

### Preload API: `window.uai.sessionStore`

```typescript
sessionStore: {
  list: (opts?: { text?: string; status?: string; platform?: string }) => Promise<SessionStoreRecord[]>
  update: (trackingId: string, fields: Record<string, string | null>) => Promise<{ ok: boolean; error?: string }>
  history: (trackingId: string, opts?: { limit?: number }) => Promise<ChangeLogEntry[]>
  stateList: (trackingId: string, prefix?: string) => Promise<Record<string, unknown>>
  stateSet: (trackingId: string, key: string, value: string) => Promise<{ ok: boolean; error?: string }>
  stateDelete: (trackingId: string, key: string) => Promise<{ ok: boolean; error?: string }>
  addTag: (trackingId: string, tag: string) => Promise<{ ok: boolean; error?: string }>
  removeTag: (trackingId: string, tag: string) => Promise<{ ok: boolean; error?: string }>
  findOrphans: () => Promise<SessionStoreRecord[]>
  validateRunning: (fix?: boolean) => Promise<ValidationResult>
  delete: (trackingId: string) => Promise<{ ok: boolean; error?: string }>
}
```

### Backend Script Routing

| IPC Channel | Script | Command |
|---|---|---|
| list | session_store.py | `list --json [--text X] [--status X] [--platform X]` |
| update | session_store.py | `update <tid> --set field=value` |
| history | session_store.py | `history --tracking-id <tid> --limit N` |
| stateList | session_mgr.py | `state_list <tid>` |
| stateSet | session_mgr.py | `state_set <tid> <key> <value>` |
| stateDelete | session_mgr.py | `state_delete <tid> <key>` |
| addTag / removeTag | session_store.py | `add_tag` / `remove_tag` |
| findOrphans | session_store.py | `find_orphans` |
| validateRunning | session_store.py | `validate_running_sessions [--fix]` |
| delete | session_store.py | `delete <tid>` |

### Data Flow

```
Edit field → window.uai.sessionStore.update(tid, {display_name: val})
  → ipcMain.handle → callStore(['update', tid, '--set', 'display_name=val'])
  → session_store.py update → touches sessions.changed signal
  → existing fs.watch → Navigator session list auto-refreshes
```

---

## 7. Files to Create/Modify

### Create
1. `packages/renderer-ui/src/components/SessionStoreMgrPane.tsx` — main pane
2. `packages/renderer-ui/src/components/SessionStoreDetail.tsx` — right panel with sub-tabs
3. `packages/renderer-ui/src/components/SessionStoreStateVars.tsx` — state vars sub-tab
4. `packages/renderer-ui/src/components/SessionStoreHistory.tsx` — change log timeline
5. `packages/renderer-ui/src/components/SessionStoreValidate.tsx` — validate view

### Modify
6. `app/main/session-store.ts` — add `callSessionMgr()` helper for session_mgr.py
7. `app/main/index.ts` — register 11 `uai:sessionStore:*` IPC handlers
8. `app/main/preload.ts` — add `sessionStore` namespace + types
9. `packages/shared/types.ts` — add `SessionStoreRecord`, `ChangeLogEntry` types
10. `packages/renderer-ui/src/components/TabContentPane.tsx` — add `case 'session-store-manager'`
11. `packages/renderer-ui/src/components/SessionDetailFields.tsx` — add `onEditInStore` prop + [Edit] button
12. `app/renderer/styles/styles.css` — add `.sess-store-*` CSS classes

### Build Sequence
1. IPC layer (types + preload + index.ts handlers)
2. Component skeleton + CSS + routing
3. Sessions tab read path (list + detail + store fields)
4. State Vars sub-tab (namespace grouping, inline edit)
5. History sub-tab (change log timeline)
6. Mutations (edit fields, add/remove tags, archive/delete)
7. Validate view (orphans + stale running)
8. Alternate entry points ([Edit] button, context menu)

---

## 8. Critical Details

### Immutable Fields
`tracking_id`, `platform`, `created_at`, `session_dir` — render as read-only with click-to-copy.

### Env Namespace Read-Only
`env.*` keys are set by launcher at session start. Render without edit/delete, with explanatory note.

### State Variable Type Coercion
`session_mgr.py state_set` auto-coerces (true/false → bool, integers → int, floats → float). UI shows type badge but doesn't type-force. List-typed keys (role, features) render as comma-separated, serialize back to JSON.

### Destructive Operations
Hard delete requires confirmation dialog. Soft archive does not. Validate "Fix" (mark stopped) does not. "Delete Orphan" requires confirmation.

### Pre-Selection from Right Panel
Tab metadata carries `initialSession` tracking_id. `SessionStoreMgrPane` reads on mount, pre-selects and scrolls.

### CSS Reuse
Reuses existing classes: `.context-mgr-split/list/viewer`, `.traits-mgr-tab-btn`, `.traits-mgr-category-header`, `.traits-mgr-loading/empty/error`. New `.sess-store-*` only for: tag pills, type badges, history rows, validate cards.
