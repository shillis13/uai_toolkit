# Project Creator & Editor — UI/UX Design

**Date:** 2026-06-06
**Status:** Design — ready for review

---

## 1. Project Taxonomy & Classification

### What is a Project?

A **project** is a conceptual unit of work. It has identity, state, and persistence beyond any single session. Projects are discovered from the filesystem and optionally registered with a `project.yml` metadata file.

### Classification (Navigator Sections)

| Section | Criteria | Color | Description |
|---|---|---|---|
| **Active** | Has `project.yml` with `lifecycle_status: active` AND has a working directory | green | Fully instantiated, actively being worked on |
| **Registered** | Has `project.yml` but no working directory, or status is `paused` | blue | Planned/registered but not yet instantiated, or paused |
| **Sandbox** | Has a project directory but no `project.yml` | yellow | Informal work, not formally registered |
| **Done** | Has `project.yml` with `lifecycle_status: complete` or `archived` | muted | Completed or archived projects |
| **Orphaned DevTrees** | DevTree directory not linked to any registered project | red/muted | Leftover worktrees from merged branches |

### DevTree vs Project

- A **DevTree** is a git worktree at `~/Documents/AI/devTrees/AI_ROOT_*`
- A DevTree becomes project-linked when a registered project's `project.yml` references it as a devtree, OR when the devTree directory itself contains a `project.yml`
- DevTrees without project registration are "orphaned"

### project.yml Schema

```yaml
name: "Unified AI Interface"
goal: "Desktop workspace for managing AI CLI agent sessions"
lifecycle_status: active    # active | sandbox | paused | complete | archived
owner: PianoMan
tags: [electron, typescript, react]
working_dir: /Users/.../ai_general/work/projects/uai_app/unified_ai_interface
devtree: uai-resurrection   # optional — links to ~/Documents/AI/devTrees/AI_ROOT_{devtree}
created: 2026-03-15
```

---

## 2. Use Cases

### Discovery & Viewing
1. **UC-01 — Browse projects by lifecycle** — see all projects in Navigator, grouped by Active/Registered/Sandbox/Done/Orphaned
2. **UC-02 — View project details** — open a project tab showing identity, goal, git state, sessions, documents, directory tree
3. **UC-03 — View project directory tree** — expandable file tree of the project's working directory
4. **UC-04 — View project documents** — list all docs (markdown, design docs, specs) in the project directory
5. **UC-05 — Open document in editor** — click a document to open it (in external editor via `shell.openPath`)

### Registration & Creation
6. **UC-06 — Register existing project** — create a `project.yml` for an existing sandbox directory, promoting it from Sandbox to Active
7. **UC-07 — Create new project from scratch** — create a new project directory + `project.yml` in one flow
8. **UC-08 — Create project devTree** — create a git worktree for an existing project

### Editing
9. **UC-09 — Edit project metadata** — change name, goal, lifecycle_status, owner, tags
10. **UC-10 — Change lifecycle status** — move between active/paused/complete/archived
11. **UC-11 — Link devTree to project** — associate an existing devTree with a project
12. **UC-12 — Add/remove project tags** — tag management (existing)

### Cleanup
13. **UC-13 — Archive project** — set lifecycle to archived
14. **UC-14 — Delete orphaned devTree** — remove an orphaned devTree directory (with confirmation)

---

## 3. Workflows

### WF-1: Register Existing Project (UC-06)
1. User sees a project in the "Sandbox" section
2. Right-click → "Register Project" (or button in project detail view)
3. A form appears with pre-filled fields:
   - **Name**: derived from directory name (editable)
   - **Goal**: empty (editable)
   - **Status**: defaults to `active`
   - **Owner**: defaults to `PianoMan`
   - **Working Dir**: pre-filled from the directory path (read-only)
4. User fills in goal, adjusts name if desired
5. "Register" button writes `project.yml` to the project directory root
6. Project moves from Sandbox → Active in the Navigator

### WF-2: Create New Project (UC-07)
1. User clicks [+ New] → "New Project" in Navigator
2. A project creation form opens in a workspace tab:
   - **Name** (required)
   - **Goal** (optional)
   - **Status**: defaults to `active`
   - **Owner**: defaults to `PianoMan`
   - **Project Directory**: user picks or types a path. Defaults to `ai_general/work/projects/{name_slug}/`
   - **Create DevTree**: checkbox, if checked creates a git worktree
   - **Initial Tags**: tag input
3. "Create" button:
   - Creates the project directory if it doesn't exist
   - Writes `project.yml`
   - Optionally creates devTree via `git worktree add`
   - Opens the project tab

### WF-3: Edit Project Metadata (UC-09)
1. User opens a project tab (click from Navigator or search)
2. Project detail view shows all fields
3. Editable fields have pencil icons (like Session Store Manager):
   - Name, Goal, Lifecycle Status, Owner
4. Click pencil → inline edit mode
5. Save writes updated `project.yml`

### WF-4: View Directory Tree (UC-03)
1. In the project detail view, "Files" section shows an expandable tree
2. Root is the project's `working_dir`
3. Directories are expandable (click to toggle)
4. Files show size and modification time
5. Click a file → opens in external editor via `shell.openPath`
6. Tree is loaded on demand (directory contents fetched when expanded)
7. Common exclusions: `.git`, `node_modules`, `.vite`, `out`, `__pycache__`

### WF-5: View Documents (UC-04)
1. In the project detail view, "Docs" section lists discovered documents
2. Documents = `*.md`, `*.yml`, `*.txt` files in the project root and `docs/` subdirectory
3. Each doc shows: filename, size, last modified
4. Click → opens in external editor
5. "New Document" button → creates a new `.md` file (prompts for name)

---

## 4. UI Component Design

### 4.1 Navigator: Projects Tab (updated sections)

```
▾ Active (2)                          green
  📁 UAI App
  📁 Axis & Allies

▾ Registered (1)                      blue
  📋 Memory Architecture (no dir yet)

▾ Sandbox (8)                         yellow
  📂 compacting_prompts
  📂 system_monitoring
  ...

▾ Done (1)                            muted
  ✓ VBA Refactor

▾ Orphaned DevTrees (2)               red-muted
  ⚠ uai-resurrection
  ⚠ xterm-data-path
```

Context menu on each item:
- **Active/Registered**: Open | Edit | Archive | Copy Path
- **Sandbox**: Open | Register | Copy Path
- **Orphaned DevTrees**: Open in Finder | Delete (with confirm)

### 4.2 Project Detail View (workspace tab)

```
┌─────────────────────────────────────────────────────────┐
│  📁 Unified AI Interface              [Edit] [Archive]  │
│  Desktop workspace for managing AI CLI agent sessions   │
│  ● active   🔀 dirty   main                            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ▾ Identity                                             │
│    Name        Unified AI Interface            [✏]      │
│    Goal        Desktop workspace for...        [✏]      │
│    Status      active                          [✏]      │
│    Owner       PianoMan                        [✏]      │
│    Project ID  uai_app                                  │
│                                                         │
│  ▾ Paths                                                │
│    Working Dir /Users/.../uai_app/unified...   [copy]   │
│    DevTree     uai-resurrection                [copy]   │
│    Source      .../uai_app/project.yml         [copy]   │
│                                                         │
│  ▾ Git                                                  │
│    Branch      main                            [copy]   │
│    Status      dirty                                    │
│                                                         │
│  ▾ Sessions (3)                                         │
│    ● Lumen          Claude   running                    │
│    ● Way_Finder     Claude   running                    │
│    ○ Kael           Claude   stopped                    │
│                                                         │
│  ▾ Files                                                │
│    ▸ app/                                               │
│    ▸ architecture/                                      │
│    ▸ docs/                                              │
│    ▸ packages/                                          │
│      DESIGN.md          2.3KB   Jun 04                  │
│      package.json       1.1KB   Jun 06                  │
│      tsconfig.json      0.4KB   May 21                  │
│                                                         │
│  ▾ Docs                                                 │
│    DESIGN.md                    2.3KB   Jun 04   [open] │
│    docs/designs/sched...        4.1KB   Jun 03   [open] │
│    docs/designs/session...      5.2KB   Jun 03   [open] │
│    architecture/uai_arch...     8.7KB   May 21   [open] │
│                                                         │
│  ▾ Tags                                                 │
│    [electron] [typescript] [react]        [Edit]        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 4.3 Register Project Form (inline or modal)

```
┌─────────────────────────────────────────────────────────┐
│  Register Project                                       │
│                                                         │
│  Name *       [Compacting Prompts                    ]  │
│  Goal         [                                      ]  │
│  Status       [active ▾]                                │
│  Owner        [PianoMan                              ]  │
│  Working Dir  /Users/.../compacting_prompts   (fixed)   │
│  Tags         [prompt] [optimization] [+]               │
│                                                         │
│                              [Cancel]  [Register]       │
└─────────────────────────────────────────────────────────┘
```

### 4.4 Create Project Form (workspace tab)

```
┌─────────────────────────────────────────────────────────┐
│  Create New Project                                     │
│                                                         │
│  Name *       [                                      ]  │
│  Goal         [                                      ]  │
│  Status       [active ▾]                                │
│  Owner        [PianoMan                              ]  │
│                                                         │
│  Project Dir  [ai_general/work/projects/______       ]  │
│               [Browse...]                               │
│                                                         │
│  ☐ Create DevTree (git worktree)                        │
│    Branch name: [dev/______                          ]  │
│                                                         │
│  Tags         [+]                                       │
│                                                         │
│                              [Cancel]  [Create]         │
└─────────────────────────────────────────────────────────┘
```

---

## 5. IPC Channels

### New channels for project management

```typescript
// Write project.yml to a directory (register or update)
'uai:project:writeYml'
  args: { dirPath: string; meta: ProjectYmlMeta }
  returns: { ok: boolean; error?: string }

// Create project directory + project.yml
'uai:project:create'
  args: { name: string; dirPath: string; meta: ProjectYmlMeta; createDevTree?: boolean; devTreeBranch?: string }
  returns: { ok: boolean; projectId?: string; error?: string }

// Read directory tree (lazy, one level at a time)
'uai:project:readDir'
  args: { dirPath: string; depth?: number }
  returns: Array<{ name: string; type: 'file' | 'directory'; size?: number; modified?: string }>

// List documents in a project
'uai:project:listDocs'
  args: { dirPath: string }
  returns: Array<{ name: string; path: string; size: number; modified: string }>

// Delete an orphaned devTree
'uai:project:deleteDevTree'
  args: { devTreePath: string }
  returns: { ok: boolean; error?: string }
```

### Existing channels used
- `traits:openFile` / `uai:openPath` — open files in external editor
- `uai:dialog:openDirectory` — directory picker for project creation

---

## 6. Files to Create/Modify

### Create
1. `packages/renderer-ui/src/components/ProjectRegisterForm.tsx` — inline registration form
2. `packages/renderer-ui/src/components/ProjectCreateForm.tsx` — full creation form (workspace tab)
3. `packages/renderer-ui/src/components/ProjectFileTree.tsx` — lazy-loading directory tree component

### Modify
4. `app/main/index.ts` — add IPC handlers for project YAML write, dir creation, dir reading, doc listing
5. `app/main/project-indexer.ts` — update classification logic (Active vs Registered vs Sandbox vs Orphaned DevTree)
6. `packages/renderer-ui/src/components/ProjectsTab.tsx` — update sections to match new taxonomy
7. `packages/renderer-ui/src/components/ProjectDetailView.tsx` — add inline editing, file tree, docs section, register button for sandbox projects
8. `packages/renderer-ui/src/components/TabContentPane.tsx` — add routing for project creation tab
9. `app/renderer/styles/styles.css` — add project form and file tree CSS

### Build Sequence
1. Classification fix (indexer + ProjectsTab sections)
2. Directory tree component + IPC
3. Document listing
4. Register form (sandbox → active)
5. Create form (new project from scratch)
6. Inline editing in ProjectDetailView
7. DevTree management (create, link, delete orphaned)
