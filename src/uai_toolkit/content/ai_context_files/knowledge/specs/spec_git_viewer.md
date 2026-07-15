# Git Viewer — feature & API reference

**Version:** 1.0
**Status:** Active
**Component:** UAI (unified_ai_interface) renderer tool "Git Viewer"
**Author:** Prism (20260702_125645_c79426e6_cla)
**Date:** 2026-07-06

## Overview
The **Git Viewer** is a UAI tool for exploring what changed in a git repo over
time. It is a tabbed wrapper over two views, and is designed to be **embeddable**
in other UAI surfaces (a session's Work page, dashboards, etc.).

## Terms
- **Git File View** — files Added/Modified/Deleted under a directory (recursively)
  across a range of commits, chosen with a time slider. The core view.
- **Git Commit View** — one commit's message, metadata (AI-session requesters,
  todos), changed files, and per-file diff.
- **Net delta** — the combined A/M/D effect of the selected commit span.
- **Scope** — repo/dir + date range (`since`/`until`) + delta filter.
- **AI session (requester)** — the AI CLI session that requested a commit's work,
  read from the `Requester:` commit trailer (git author is always the human).
- **Todo** — a `todo_####` referenced in a commit, from the `Todo:` trailer.

## Features
1. **Timeline** — one tick per commit; drag the From/To handles (or click) to pick
   a span; axis auto-labels (hours→days→months); zoom to selection / reset.
2. **Play-through** — Prev/Next steps the span one commit; lock From or To to move
   only the other extent; the span passes cleanly through a single commit.
3. **View toggle** — per selected file: unified **Diff**, or whole-file
   **Before** / **After** the span (line-numbered).
4. **Attribution** — per file: contributors, **AI sessions** (resolved to display
   names), and **todos** (clickable → `uai://todo/<id>`).
5. **Filter** — restrict the delta to one contributor / AI session / todo.
6. **Repo picker** — jump between the workspace's git repos (host-detected:
   GitHub/GitLab/Local/Other).
7. **Scope bar** — editable Repo/Dir/Date controls; hideable (collapses to a
   ⚙ Scope chip); suppressible entirely for fixed embeds.
8. **Persistence** — selections (file, filter, scope, handles, sub-tab) survive
   switching away from and back to the tab.

## API — execute actions

### Open the tool (CommandBus)
```ts
executeCommand('workspace.tabs.open', { type: 'app', targetId: 'git-file-view', label: 'Git Viewer' });
```

### Set a mounted view's scope + filter (renderer command)
Import from `packages/renderer-ui/src/components/git-file-view-scope.ts`:
```ts
setGitFileViewScope({
  tabId?,   // target one instance; omit to broadcast to all mounted views
  dir?,     // repo root or any dir under it (recursive)
  since?,   // 'YYYY-MM-DD' lower bound
  until?,   // 'YYYY-MM-DD' upper bound; '' = latest
  filter?,  // { kind:'author'|'ai'|'todo', value } | { kind:'todos', values:[...] }
            // (todos = the UNION of a set — worker scope); null clears;
            // OMIT the key to leave unchanged
});
```
Applies present fields and reloads if dir/since/until changed. This is the API a
host uses to drive an embedded, scope-locked view.

### Embed the component (props on `<GitFileViewPane>`)
`dir`, `since`, `until` (preset scope); `embedded` (compact); `showScopeBar`
(bar starts open, default `!embedded`); `allowScopeChange` (user may change scope,
default `!embedded`); `filter` (controlled delta filter `{kind,value}` | `null`,
host-driven); `onOpenCommit(hash, dir)`. Fixed embed = `showScopeBar={false}
allowScopeChange={false}` + drive scope/filter via the `filter` prop or
`setGitFileViewScope`. **Reference embeds:** (1) Work Mgr → todo → **Files** tab pins
`filter={{kind:'todo', value: todoId}}` + `dir="ai_general"` + `since=todo.created`.
(2) `WorkerFilesView` (Session Work page + Project/Team Files aspect) pins
`filter={{kind:'todos', values: leafTodoIds}}` — the union of a worker's todos.

### Backend CLI (for non-UI callers)
`python3 ai_general/scripts/utils/git_file_view.py --dir D [--since S --until U]
[--file F --from H1 --to H2 | --commit H | --file F --show REF | --repos |
--grep PATTERN [--to REF]] [--json]`. `--grep` returns repo-relative paths whose
CONTENT at `--to` (or HEAD) matches — backs the File-list **contents** search.
Nonzero exit on failure. IPC mirrors: `window.uai.gitFileView.{read,diff,commit,content,repos,grep}`.

### File-list search
The file list has a search bar with three modes: **Filename** (path substring),
**Metadata** (author / AI-session / todo / net-status of the files' commits,
client-side), **Contents** (backend `--grep` at the To commit, debounced,
intersected with the changed set).

## API — get state data
Query the live viewport tree (`window.uai.viewport.describeViewport()` / the
viewport describe IPC). The Git Viewer registers:

| Node id | State keys |
|---|---|
| `git_viewer` | `activeTab` ('file'\|'commit'), `commitHash`; children → the two views |
| `git_file_view` | `dir`, `since`, `until`, `commitCount`, `span`, `loading`, `error`; child bars report scope, zoom (from/to commits), stats (added/modified/deleted), active filter, tree (changed files), file metadata, contents |
| `git_commit_view` | `commit` (short hash), `subject`, `files`, `selectedFile`, `loading`, `aiSessions`, `todos` |

Only rendered nodes report `visible:true`; embedded File View instances register
under `git_file_view_embed_<tabId>`.

## Files
- `packages/renderer-ui/src/components/GitViewerPane.tsx` — wrapper
- `packages/renderer-ui/src/components/GitFileViewPane.tsx` — File View
- `packages/renderer-ui/src/components/GitCommitViewPane.tsx` — Commit View
- `packages/renderer-ui/src/components/git-file-view-scope.ts` — scope command
- `packages/renderer-ui/src/stores/git-viewer-state-store.ts` — per-tab persistence
- `ai_general/scripts/utils/git_file_view.py` — backend
- Design & implementation notes: `…/src/components/git-viewer.DESIGN.md`
