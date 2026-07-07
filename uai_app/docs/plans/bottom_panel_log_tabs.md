# Bottom Panel: Configurable Log Tabs

**Date:** 2026-05-14
**Author:** PianoMan + Refract (20260428_215507_8a4223ea_cla)
**Status:** Design captured — ready for implementation

## Core Concept

Every bottom panel tab is a **LogFileTab** — a live viewer bound to any file on disk, with formatting and filtering driven by a schema. Tabs are configurable at runtime: add/remove, reorder, link to any file.

The bottom panel becomes a generic log file viewer host, not a collection of hardcoded purpose-built tabs.

## Data Model

```typescript
interface LogFileTab {
  id: string;
  label: string;
  filePath: string;            // absolute path to the file being tailed
  schema?: LogFileSchema;      // drives formatting + filtering; auto-detected if absent
  filters?: LogFilter[];       // user-applied runtime filters
  order: number;               // tab position (supports drag reorder)
  pinned?: boolean;            // prevent accidental close
}

interface LogFileSchema {
  format: 'jsonl' | 'text' | 'csv' | 'structured';
  fields?: LogFieldDef[];      // for structured formats
  timestampField?: string;     // which field contains the timestamp
  levelField?: string;         // which field is severity/level
  levelColors?: Record<string, string>; // e.g., { error: '#f7768e', warn: '#e0af68' }
  sessionField?: string;       // for per-session filtering
  groupBy?: string;            // optional grouping field
  maxLines?: number;           // display buffer size (default 1000)
}

interface LogFieldDef {
  name: string;
  type: 'string' | 'number' | 'timestamp' | 'json' | 'enum';
  label?: string;              // display label (defaults to name)
  color?: string;              // field value color
  mono?: boolean;              // monospace rendering
  hidden?: boolean;            // in schema but not displayed by default
  width?: string;              // column width hint
}

interface LogFilter {
  field: string;
  op: 'eq' | 'neq' | 'contains' | 'regex' | 'gt' | 'lt';
  value: string;
  enabled: boolean;
}
```

## Known Log Sources (Auto-Schema)

When a tab points to a known path, auto-apply the appropriate schema:

| Path Pattern | Format | Schema |
|---|---|---|
| `*/activity_log.jsonl` | jsonl | ts, session, participant, event, payload. Level from event prefix. |
| `*/sessions.changed` | text | Raw signal file — show touch timestamps |
| `*.jsonl` (generic) | jsonl | Auto-detect fields from first line |
| `*.log` | text | Plain text tail, line-by-line |
| `*.csv` | csv | Header row defines fields |

Unknown files default to plain text tail mode.

## Architecture

### Main Process: File Tail Service

```typescript
// New: src/main/file-tail.ts
interface TailSession {
  id: string;
  filePath: string;
  watcher: fs.FSWatcher;
  offset: number;              // byte offset of last read position
  lineBuffer: string[];        // recent lines (ring buffer, max maxLines)
}

// IPC channels:
// 'log:tail:start' — begin tailing a file, returns initial content
// 'log:tail:stop' — stop tailing
// 'log:tail:data' — main→renderer event with new lines
```

Uses `fs.watch` + read-from-offset on change. Debounced to avoid flooding renderer on rapid writes. Sends new lines as batched IPC events.

### Renderer: LogFileViewer Component

```
LogFileViewer
  ├── LogToolbar (filter chips, search, pause/resume, clear)
  ├── LogContent (virtualized scrollable list of formatted lines)
  │   ├── LogLine (formatted according to schema)
  │   └── LogLine ...
  └── LogStatusBar (line count, file path, tail status)
```

- **Virtualized rendering** — only render visible lines (react-window or similar)
- **Auto-scroll** — follows tail unless user scrolls up (pause indicator)
- **Schema-driven rendering** — each line parsed according to schema, fields colored/formatted
- **Filter toolbar** — filter chips per field, text search, regex toggle
- **Pause/resume** — stop auto-scroll, buffer incoming lines, resume catches up

### Renderer: Bottom Panel Refactor

```
BottomPanel
  ├── TabBar (draggable tabs + "+" button)
  │   ├── LogFileTab
  │   ├── LogFileTab
  │   └── AddTabButton → file picker or preset selector
  ├── ActiveTabContent → LogFileViewer
  └── ResizeHandle (existing)
```

- Tabs stored in `appState.bottomPanelTabs: LogFileTab[]`
- Tab order is drag-reorderable
- "+" button offers presets (Activity Log, Command Log, Session Log for active session) + "Browse..." for arbitrary file
- Close button on non-pinned tabs

## Migration from Current Bottom Panel

The existing 4 tabs become default LogFileTab presets:

| Current Tab | Migration |
|---|---|
| Related Entities | Not a log — stays as a special tab type (not LogFileTab) |
| Session Log | LogFileTab pointing to session's activity_log file, filtered by active session |
| App Log | LogFileTab pointing to UAI app's activity_log.jsonl |
| System Monitor | Not a log — stays as a special tab type |

The tab container supports both LogFileTab and special-purpose tabs. The tab type discriminant handles this:

```typescript
type BottomPanelTab = LogFileTab | SpecialTab;
interface SpecialTab { id: string; label: string; type: 'relationships' | 'sysmon'; order: number; }
```

## Implementation Sequence

1. **File tail service** — main process file watcher + IPC
2. **LogFileViewer component** — generic log renderer with schema support
3. **LogFileSchema auto-detection** — JSONL field sniffing, known path matching
4. **Bottom panel tab refactor** — dynamic tab management, add/remove/reorder
5. **Filter toolbar** — per-field filtering, search, regex
6. **Presets** — Activity Log, Command Log, Session Log defaults
7. **Persistence** — save tab config in app_state

## Open Questions

1. **Virtualization library** — react-window, react-virtuoso, or custom? Need to handle variable-height lines (expanded JSON).
2. **Max buffer size** — how many lines to keep in memory per tab? 1000? 10000? Configurable per tab?
3. **Binary/large files** — what happens if someone points a tab at a 500MB file? Need size guard.
4. **Remote files** — future: tail files on remote hosts via SSH? Or only local for now?
5. **Schema registry** — should schemas be registered centrally (like component descriptions) or inline per tab?
