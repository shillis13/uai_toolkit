# Project Editor — Center Pane UI/UX Design

**Date:** 2026-06-21
**Author:** Mullion (session 20260621_031933_50aaa957_cla, Claude CLI) with PianoMan
**Status:** Design — structure & key decisions LOCKED (PianoMan approved 2026-06-21)
**Supersedes:** `project_creator_editor_design.md` (2026-06-06) — see §8 for what carries forward
**Companion:** unified work-tracking spec (`ai_general/work/todos/todo_0307_unified_work_tracking_system/2026-06-11-unified-work-tracking-design.md`); UAI arch (`architecture/uai_architecture_v1.1.md`)
**Visual:** `docs/designs/2026-06-21-project-editor-center-pane-mock.html`

## Terms
- **Center Pane** — the main-window region that fills with the focused tab's content. Main window = Tabs · Left Panel · Center Pane · Bottom Panel.
- **Aspect** — a top-level view of a project, selected from the Navigator Panel. The four aspects: Overview, Work List, Team, Comms.
- **Doc Folder / Work Folder** — project-scoped folder hierarchies, distinct from the global Folder concept (folders.json). Both are the *same* generic mechanism (see §3, decision 2).
- **Right Panel** — the contextual detail panel on the right of the Center Pane; the same component a Session tab uses (ContextPanel, arch §5.9).

---

## 1. Frame — the Project Editor fills the Center Pane

When a **Project tab** is focused, the Project Editor fills the Center Pane and splits it three ways — exactly parallel to how a Session tab splits into Title Bar / Live Terminal / Prompt Box / Right Panel:

```
┌ Title Bar ─ 📁 uai_app › <aspect> ─────────────────────── ● active · main ┐
├──────────────┬──────────────────────────────────┬──────────────────────┤
│ Navigator    │  Detail Area                     │  Right Panel         │
│ Panel        │  (the active aspect's editor)    │  (contextual detail) │
│ (aspects +   │                                  │  file meta / AI meta │
│  their items)│                                  │  / overflow state    │
└──────────────┴──────────────────────────────────┴──────────────────────┘
```

- **Navigator Panel (left)** — lists the four aspects. Each aspect **expands** into its primary items (decision 1). Clicking an item loads its detail in the Detail Area; clicking an aspect header loads the aspect's landing view.
- **Detail Area (center)** — the active aspect's editor/viewer.
- **Right Panel** — when a Detail item carries more state than fits inline, it surfaces here. Reuses the Session tab's ContextPanel (decision 3).

---

## 2. The four aspects

### 2.1 Overview
All project metadata + two collapsible areas.
- **Metadata** — `name`, `goal`, `lifecycle_status`, `owner`, `branch`, `working_dir`, `tags` (inline-editable, pencil affordance — carried from 2026-06-06). Create/Register/Edit workflows live here.
- **▾ Docs** (collapsible) — a **Doc Folder hierarchy** (decision 2). Double-click a doc **opens** it (in OS, `openFile`). Multi-select; action bar on selection: **Move to Doc Folder · Open · Archive** (Delete = move to archive, never hard-delete).
- **▾ Team** (collapsible) — summary of Roles & AIs; a launcher into the full Team aspect.

### 2.2 Work List
The collection of all work assigned to the project = **the project todo board**.
- Navigator's Work aspect **expands into the project's todos** (decision 1).
- Click a todo → **Work detail** in the Detail Area: the TODO item details (status, owner, project, tags, notes.md) + associated state.
- Below the todo detail: a **Work Folder hierarchy** + work files (same mechanism as Doc Folders, decision 2). Click a file → its **metadata in the Right Panel**. **Open** a work file → opens in OS.

### 2.3 Team
- **Top of Detail Area:** Roles & AIs assigned to them. Each AI rendered in its **own session-identity color**.
- Click an AI → its **metadata in the Right Panel** (the same ContextPanel a Session tab shows, decision 3).
- Click an AI → its **work and files in the lower Detail Area**.
- Double-click / Open an AI → **opens the Session tab** for it.

### 2.4 Comms
Channel-based view over the project team's communications. **(Richest already-wired backend — see §4.)**
- **Channels:** PianoMan/Hamilton ↔ lead; one channel per **AI-pair that has directly communicated**; a **team chat** channel.
- Each channel shows its **messages**.
- Below the channel: a **prompt box** for PianoMan to **inject** a message into the selected channel.
- Selecting a team member to see all their comms → opens that member's **Session tab**.

---

## 3. Locked decisions (PianoMan approved 2026-06-21)

1. **Navigator expands uniformly.** Every aspect expands into its items in the Navigator — Work→todos, Team→AIs, Comms→channels (not just Work).
2. **Doc Folder == Work Folder == one mechanism.** A single generic **project-scoped folder tree** component (multi-select · move · open · archive-not-delete), instantiated twice: Docs in Overview, work-files under a Work todo.
3. **Right Panel == the Session tab's ContextPanel, reused.** Same component; content switches on what's selected in the Detail Area (file → file metadata; AI → the same session detail a Session tab shows).

---

## 4. Verified data reality & build order (checked in `app/main/preload.ts`, 2026-06-21)

| Aspect / piece | Backend | Status |
|---|---|---|
| **Comms** channels + inject | `comms.inboxList/sentList/archiveList/send(replyTo)/markRead` + queue/locks | 🟢 **live now** |
| **Team** roster + linked work | `sessions` list + `relationships.forEntity` | 🟢 live now |
| **Work List** display | `todos.list` / `todos.read` (read-only) | 🟢 live now |
| **Overview** metadata | project.yml via ProjectCard | 🟢 live now |
| **Todo editing** (status/owner/project writes) | — none — | 🔴 needs IPC (todo_mgr CLI has ops; wire a `todos.write` channel) |
| **Docs tree / Work-files tree / doc discovery** | — none — (`uai:project:readDir`/`listDocs` specced 2026-06-06 but never built) | 🔴 needs IPC — **todo_0317** |
| **File blame-by-session** color | Component-7 attribution | 🟠 other fork; non-blocking color overlay |

**Build order follows readiness:** Comms → Team → Work(read) → Overview(meta) light up against real data first. Docs/Work-file trees and todo editing land when the IPC I own is wired. Blame coloring is a late, non-blocking overlay.

**IPC I owe (mine to build, Project Editor plumbing):**
- `window.uai.fs.listDir` (lazy dir tree) + doc discovery — **todo_0317**.
- `window.uai.todos.write` — status/owner/project mutations routed through `todo_mgr`.

---

## 5. Component sectioning (the divvy-up)

```
app.project_editor                     ── ProjectEditor (SHELL — single owner: Mullion)
│   owns: project ref, active aspect, Navigator+Detail+RightPanel split, routing
├── .navigator     ProjectNavigatorPanel — aspect list, each expandable into items
├── .overview      ProjectOverview        — metadata + Docs(collapse) + Team(collapse)
│      └ DocFolderTree  ◄─┐
├── .work          ProjectWork            — todo board; selected todo → detail + files
│      └ WorkFolderTree ◄─┴── ProjectFolderTree (ONE generic component, two mounts)
├── .team          ProjectTeam            — Roles&AIs; selected AI → work/files + RightPanel
├── .comms         ProjectComms           — channel list + messages + inject prompt box
└── .right_panel   reuse ContextPanel (§5.9) — file meta / AI meta / overflow
```

**Divvy boundaries:** the **shell + navigator** is the single shared integration point (Mullion owns it). The four aspects + `ProjectFolderTree` are independently ownable files → fan out to subagents partitioned by file (parent does the integrated build/verify, the pattern proven in the parent session). Shared services *consumed* (not owned) by aspects: `SessionStore`, todo data layer, comms store, the identity-color map, ContextPanel, the fs/todo-write IPC, and (late) Component-7 attribution.

Every aspect is an **architectural component** per arch §5: typed `get/list/describe` (sync reads vs snapshots) + `execute(command)` for mutations; Views never mutate durable state; reflect external ground truth; subscribe, don't poll. **Per the agreed staging: lock boundaries + MVC/command-bus conformance now; full `describe()` JSON schemas are a fast-follow once each aspect's UX settles.**

---

## 6. Build sequence

1. **Shell + Navigator** (`ProjectEditor`, `ProjectNavigatorPanel`) — the Center-Pane split, aspect routing, uniform-expand nav. Wire into `TabContentPane` project-tab routing (absorbs/retires `WorkerProjectDetail.tsx`). *Single owner.*
2. **Comms aspect** — live backend; first real aspect.
3. **Team aspect** — roster + linked work + AI-meta Right Panel (reuse session detail).
4. **Work List aspect** (read) — todo board + todo detail.
5. **Overview aspect** — metadata (+ create/register/edit from 2026-06-06) + Docs/Team collapse areas.
6. **IPC: `fs.listDir` + doc discovery** (todo_0317) → light up Docs + Work-file trees via `ProjectFolderTree`.
7. **IPC: `todos.write`** → todo editor mutations.
8. **Component-7 attribution overlay** → file blame coloring (consume other fork's output).

Each step: typecheck + vite build green before moving on; **render-verify only in a coordinated app-handoff window** (PianoMan concedes the app — display is the real constraint).

---

## 7. Open / deferred
- Full `describe()` schemas per aspect (fast-follow once UX settles).
- Project taxonomy surfacing (Active/Registered/Sandbox/Done/Orphaned) — lives in the Projects *Navigator tab* (2026-06-06), not the editor; unchanged.
- Color/theming: mock uses light tinted zones (nav cool · detail neutral · right warm) to break the monochrome; refine during build.

## 8. Carried forward from the 2026-06-06 design (not discarded)
- `project.yml` schema (`name/goal/lifecycle_status/owner/tags/working_dir/devtree/created`).
- Project taxonomy + classification (Active/Registered/Sandbox/Done/Orphaned).
- Create / Register / Edit-metadata workflows (now inside Overview).
- IPC intent for `readDir`/`listDocs` — **re-homed** as the `fs.listDir`/doc-discovery work in todo_0317.

**Replaced:** the flat scrolling Detail View (Identity/Paths/Git/Sessions/Files/Docs/Tags stacked) → Navigator Panel + four aspect views.
