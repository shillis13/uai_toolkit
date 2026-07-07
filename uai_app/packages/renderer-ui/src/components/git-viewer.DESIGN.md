# Git Viewer — design & implementation

Read this before modifying `GitViewerPane.tsx`, `GitFileViewPane.tsx`,
`GitCommitViewPane.tsx`, `git-file-view-scope.ts`, or
`stores/git-viewer-state-store.ts`. Companion feature/API reference (for agents
and callers) lives at `ai_general/ai_context_files/knowledge/specs/spec_git_viewer.md`.

## Terms
- **Net delta** — the combined Added/Modified/Deleted effect of a *span* of
  commits `[from..to]`, reconstructed client-side from the per-commit changelog
  (equivalent to `git diff from^..to` scoped to the dir).
- **Scope** — the inputs that define what a Git File View shows: repo/dir + date
  range (`since`/`until`) + the delta filter (contributor / AI session / todo).
- **Scope command** — `setGitFileViewScope()`, the programmatic way to set a
  mounted view's scope (see below).

## Component tree
```
GitViewerPane (wrapper, tabId)            ── the "Git Viewer" app tool
├─ tabbar: TabNavArrows + title + [Git File View | Git Commit View]
├─ GitFileViewPane   (tabId, onOpenCommit) ── dir × date-range → A/M/D tree + timeline
└─ GitCommitViewPane (tabId, commitHash, dir, active) ── one commit's detail + diff
```
Both children stay **mounted** (`display:none` on the inactive one) so switching
sub-tabs preserves their in-memory state. Cross-nav: clicking a commit hash in the
File View calls `onOpenCommit(hash, dir)` → wrapper switches to the Commit View.

## Backend — `ai_general/scripts/utils/git_file_view.py`
Flag-driven (per `ai_general/scripts/DESIGN.md`: flags, not subcommands; nonzero
exit on failure). Modes:
| Invocation | Returns |
|---|---|
| `--dir D [--since S --until U]` (default) | changelog: every commit touching `D`, oldest→newest, each with per-file A/M/D + `requesters`/`todos`/`body` (parsed from `Requester:`/`Todo:` trailers) |
| `--dir D --file F --from H1 --to H2` | unified diff of `F` across `H1^..H2` + `size_at_to` |
| `--dir D --commit H` | one commit's full detail (message, files, requesters, todos) |
| `--dir D --file F --show REF` | file CONTENT at `REF` (`{ok, exists, content, bytes}`; `exists:false`, not error, when absent) — powers Before/After |
| `--dir D --repos` | workspace git repos (walks `.git` dirs AND submodule `.git` files, depth-bounded, prunes `node_modules`/`.venv`/`_archive`) with origin remote + detected host |

## Data flow — why scrubbing is real-time
The changelog is fetched **once** per (dir, range). The net delta between the two
selected commit indices is computed **client-side** (`computeNetDelta`), so
dragging the timeline handles re-derives the tree with no backend round-trip. The
diff / content / commit / repos modes are separate on-demand calls (debounced
200ms so a slider drag doesn't fire one per tick; the prior diff stays on screen
until the new one lands — no blanking).

`computeNetDelta` semantics: walk `[lo..hi]`, track first & last status per path.
`A` then not-`D` → Added; existed-before → `D` if last is delete else `M`;
`A` then `D` (added-and-removed within span) → dropped. An optional `match`
predicate applies the filter during the walk.

**Filter-driven timeline & zoom.** When a filter is active:
- Only the *matching* commits render as ticks (the timeline shows just the todo's
  commits, etc.).
- The From/To handles snap to the earliest/latest matching commit and the axis
  starts **zoomed** to that duration (the "initial zoom" / fit). The summary counts
  *matching* commits ("N commits (filtered)"), not the raw span width.
- Three zoom references (no history stack — named anchors + free manual zoom):
  **Fit** = the filtered extent (default; "↺ Reset zoom" returns here when a filter
  is active); **Full range** = the whole loaded data range (the "⊞ Full range"
  button — un-zooms the axis but keeps the filtered selection); **manual** =
  "⤢ Zoom to selection" dives into any sub-range. The outer bound is the loaded
  data range, set at the scope level (dir + since/until — host-driven for embeds).
- The fit re-applies only when the matching set changes (filter/data), so dragging
  or manually zooming afterward is preserved. Clearing the filter → full range.
- Commit ticks (solid, accent, bottom-anchored) are styled distinctly from the
  date gridlines (dashed, full-height, aligned with the axis labels).

## State & persistence (#6)
Each pane owns its React state. Because `Workspace` mounts **only the active app
tab**, switching tools unmounts the Git Viewer — so state is snapshotted per tab
in `stores/git-viewer-state-store.ts` (module-level `Map<tabId, …>`, ephemeral,
mirrors `search-state-store.ts`):
- `GfvSnapshot` — dir/since/until, the loaded `data` (so return is instant, no
  reload flash), from/to, lockSide, zoom, selPath, diffView, filter, barOpen,
  collapsed[], expandedCommits[].
- `GitViewerSnapshot` — activeTab, commitHash, commitDir.

Panes hydrate from `getGfvSnapshot(tabId)` / `getGitViewerSnapshot(tabId)` on
mount and write back on every change. **Mount-load guard:** on first mount, if a
snapshot with `data` is restored and no scope prop was passed, the auto-load is
skipped (don't clobber restored data). Embedded instances (`embedded`) never use
snapshots — they're prop-driven.

## Scope command (#4) — `git-file-view-scope.ts`
`setGitFileViewScope({tabId?, dir?, since?, until?, filter?})` dispatches a window
`CustomEvent`. Every mounted `GitFileViewPane` listens; it applies the present
fields and reloads if any of dir/since/until changed. `filter`: an object filters
by contributor/AI-session/todo, `null` clears it, an **omitted key** leaves it
unchanged. `tabId` targets one instance; omit to broadcast to all. It's a
renderer-local window event (not a main CommandBus command) because it mutates a
mounted component's transient view state — which the main process has no handle
on. This is the component's "execute actions" API.

## Embeddability (#6) — `GfvProps`
`dir/since/until` preset scope · `embedded` compacts + skips snapshot/registration
· `showScopeBar` (default `!embedded`) starts the editable bar open vs collapsed
to the ⚙ Scope chip · `allowScopeChange` (default `!embedded`) whether the user
may change scope at all (bar + chip) · `filter` a **controlled** delta filter
(`{kind,value}` or `null`) that the host drives via prop (synced to internal state
on change) · `onOpenCommit` cross-nav. A **fixed embed** passes `showScopeBar={false}
allowScopeChange={false}` — scope is the host's and the user can't touch it, but
the host can still drive it via the `filter` prop or the scope command. Viewport
ids are per-instance when embedded (`git_file_view_embed_${tabId}`) so multiple
placements don't collide.

**Reference embed — Work Mgr → todo → Files tab** (`TodoItemView.tsx`): renders
`<GitFileViewPane embedded showScopeBar={false} allowScopeChange={false}
dir="ai_general" since={todo.created} filter={{kind:'todo', value: todoKey}} />`
so the Files tab is a git-backed change view of exactly the commits carrying the
selected todo's `Todo:` trailer. Selecting another todo re-drives `filter`/`since`.

## Component-architecture conformance (#7)
- **Viewport reporters** (the "get state" API): `git_viewer` (activeTab +
  children), `git_file_view` (scope, span, counts, selection, filter — 7 child
  bars), `git_commit_view` (loaded commit, files, selected file). Registered via
  `useViewport`; surfaced through the viewport describe IPC.
- **Actions** via the scope command + `workspace.tabs.open` (to open the tool).
- **Theme tokens** — no raw hex; all colors are CSS vars. The four top bars use
  named `--gfv-bar-*` tokens (`color-mix` over accent tokens) so they recolor with
  Settings→Themes for free.

## Gotchas / invariants
1. **`min-width:0` + `overflow:hidden` down the whole flex chain**
   (`.gviewer-pane`/`.gviewer-body`/tab-wrappers + `.gfv-filename`). A long tree
   row is `white-space:nowrap`; without this the flex chain grows to content width
   (~1.29M px) and shoves the detail panel off-screen. Verified via CDP measuring
   `detailLeft`.
2. **Class names:** the toolbar dir/hash inputs use `.gfv-dir-input`; tree dir
   rows use `.gfv-row.gfv-dir`. Don't reuse `.gfv-dir` for an input — it collides.
3. **Net-delta is client-side** — don't add a backend call per slider tick.
4. **Verify UI via CDP** on an isolated off-screen instance before claiming a fix
   (own `UAI_APP_STATE_PATH` + `--user-data-dir` + `--remote-debugging-port`;
   never touch PianoMan's running app). Layout bugs have survived reasoning-only
   "fixes"; reproduce at his window width WITH a file selected.
5. **Large edits post-context-offload** can be written to disk as offload-ref
   placeholders (valid text, blank UI). Use heredoc writes + `grep 'input
   archived'` after building.
