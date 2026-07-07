# UCI IPC Channel Reference

**Generated:** 2026-04-14
**Source:** `src/src/main/preload.ts` (343 lines — single `contextBridge.exposeInMainWorld('terminalApi', api)`)

## Overview

- **Pattern:** `contextBridge` + `ipcRenderer.invoke` (request/response) and `ipcRenderer.send` / `ipcRenderer.on` (fire-and-forget / push events)
- **Bridge object:** `window.terminalApi` — all renderer access goes through this
- **Main process handlers:** `src/src/main/index.ts` — `ipcMain.handle()` and `ipcMain.on()` registrations
- **Type declarations:** `src/src/renderer/global.d.ts`

---

## Session Manager (14 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `sessionManager:list` | `sessionManager.list(filter?)` | R→M | optional filter object | `Session[]` | List sessions with optional filtering |
| `sessionManager:get` | `sessionManager.get(id)` | R→M | session id | `Session \| undefined` | Get single session by ID |
| `sessionManager:create` | `sessionManager.create(opts)` | R→M | creation options | `Session` | Create session metadata entry |
| `sessionManager:update` | `sessionManager.update(id, patch)` | R→M | id, partial metadata | `Session \| undefined` | Patch session metadata |
| `sessionManager:delete` | `sessionManager.delete(id)` | R→M | id | `boolean` | Delete session from registry |
| `sessionManager:getStore` | `sessionManager.getStore()` | R→M | none | `MetadataStore` | Get raw metadata store |
| `sessionManager:spawnWorker` | `sessionManager.spawnWorker(parentId, opts)` | R→M | parent id, options | `Session` | Create worker session linked to parent |
| `sessionManager:getChildren` | `sessionManager.getChildren(id)` | R→M | id | `Session[]` | Get child/worker sessions |
| `sessionManager:getAncestors` | `sessionManager.getAncestors(id)` | R→M | id | `Session[]` | Get parent chain |
| `sessionManager:recentSessions` | `sessionManager.recentSessions()` | R→M | none | `any[]` | List recently active sessions |
| `sessionManager:promoteWorker` | `sessionManager.promoteWorker(id)` | R→M | id | `Session \| undefined` | Promote worker to chat type |
| `sessionManager:incrementExchangeCount` | `sessionManager.incrementExchangeCount(id)` | R→M | session id | `{ exchangeCount }` | Bump exchange counter |
| `sessionManager:discoverSessions` | `sessionManager.discoverSessions()` | R→M | none | `{ imported }` | Scan filesystem for unregistered sessions |
| `sessionManager:saveTabs` / `loadTabs` | `sessionManager.saveTabs(tabs)` / `loadTabs()` | R→M | tab state | `void` / tab state | Persist/restore open tabs across restarts |

## Groups & Filters (6 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `sessionManager:listGroups` | `sessionManager.listGroups()` | R→M | none | `Group[]` | List all groups |
| `sessionManager:createGroup` | `sessionManager.createGroup(group)` | R→M | group options | `Group` | Create new group |
| `sessionManager:addToGroup` | `sessionManager.addToGroup(sid, gid)` | R→M | session id, group id | `{ success }` | Add session to group |
| `sessionManager:removeFromGroup` | `sessionManager.removeFromGroup(sid, gid)` | R→M | session id, group id | `{ success }` | Remove session from group |
| `sessionManager:deleteGroup` | `sessionManager.deleteGroup(gid)` | R→M | group id | `boolean` | Delete a group |
| `sessionManager:updateGroup` | `sessionManager.updateGroup(gid, patch)` | R→M | group id, patch | `Group \| undefined` | Update group metadata |

## Groups & Filters v2 (4 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `groups:list` | `groups.list()` | R→M | none | `GroupV2[]` | List v2 groups |
| `groups:save` | `groups.save(groups)` | R→M | groups array | `{ success, error? }` | Save v2 groups |
| `filters:list` | `filters.list()` | R→M | none | `Filter[]` | List saved filters |
| `filters:save` | `filters.save(filters)` | R→M | filters array | `{ success, error? }` | Save filters |

## Session Lifecycle (4 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `sessions:create` | `createSession(platform, size?, workDir?, opts?)` | R→M | platform, size, workDir, forkFrom, autoApprove, extraArgs, name, role, model, prompt, systemPrompt, parentTrackingId | `{ session, zellijSession }` | Launch new CLI session |
| `sessions:resume` | `resumeSession(id, cliId?, size?, autoApprove?, extraArgs?)` | R→M | session id, cli session id, size, flags | `{ session, zellijSession }` | Resume stopped session |
| `sessions:kill` | `killSession(zellijSession)` | R→M | zellij session name | `{ success }` | Kill running session |
| `sessions:spawnWorker` | `spawnWorkerSession(parentId, opts?)` | R→M | parent id, platform, role, name, size | `{ session, zellijSession }` | Spawn worker with terminal |

## Terminal / xterm.js Bridge (8 channels)

| Channel | Exposed As | Dir | Type | Params | Purpose |
|---------|-----------|-----|------|--------|---------|
| `xterm:input` | `sendTerminalInput(sid, data)` | R→M | send | session id, keystroke data | Forward user keystrokes to PTY |
| `xterm:writeChars` | `writeCharsToSession(sid, text)` | R→M | invoke | session id, text | Write text to terminal (via session_ops) |
| `xterm:writePrompt` | `writePromptToTerminal(sid, text, submit)` | R→M | invoke | session id, prompt text, submit flag | Write prompt text, optionally press Enter |
| `xterm:resize` | `sendTerminalResize(sid, cols, rows)` | R→M | send | session id, dimensions | Notify PTY of terminal resize |
| `xterm:attach` | `terminalAttach(sid, name, cols, rows)` | R→M | invoke | session id, zellij name, dimensions | Attach PTY bridge to session |
| `xterm:detach` | `terminalDetach(sid)` | R→M | invoke | session id | Detach PTY bridge |
| `xterm:data` | `onTerminalData(cb)` | M→R | push | session id, output data | Terminal output from PTY to xterm.js |
| `xterm:exit` | `onTerminalExit(cb)` | M→R | push | session id, exit code | Terminal process exited |

## Clipboard & Shell (3 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `clipboard:write` | `writeClipboard(text)` | R→M | text | `{ success }` | Write to system clipboard |
| `shell:openExternal` | `openUrl(url)` | R→M | URL string | `{ success, error? }` | Open URL in default browser |
| `shell:openInTerminal` | `openInTerminal(dirPath)` | R→M | directory path | `{ success, error? }` | Open directory in iTerm |

## Terminal Control (3 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `terminal:activeZellijSession` | `setActiveZellijSession(name)` | R→M (send) | session name or null | void | Tell main which session is focused |
| `terminal:capturePane` | `capturePane(zellijSession, lines?)` | R→M | zellij name, optional line count | `{ success, output, error? }` | Capture terminal scrollback text |
| `terminal:openITerm` | `openITerm(zellijSession)` | R→M | zellij session name | `{ success, error? }` | Open session in iTerm2 |

## Transcript & History (2 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `sessions:history` | `getSessionHistory(sessionId)` | R→M | session id | `unknown[]` | Get session history entries |
| `transcript:readJsonl` | `readTranscriptJsonl(zellij, cliId?, format?)` | R→M | zellij name, cli session id, format | `{ ok, days?, records?, uuid?, error? }` | Read JSONL transcript as structured data |

## UUID Discovery (1 channel)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `sessions:captureUuid` | `captureUuid(zellij, electronId)` | R→M | zellij name, electron session id | `{ ok, uuid?, source?, error? }` | Discover CLI session UUID from terminal scrollback |

## Prompt Queue (4 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `promptQueue:getForSession` | `promptQueue.getForSession(sid)` | R→M | session id | `Prompt[]` | Get queued prompts for session |
| `promptQueue:getAll` | `promptQueue.getAll()` | R→M | none | `Prompt[]` | Get all queued prompts |
| `promptQueue:getAllCounts` | `promptQueue.getAllCounts()` | R→M | none | `Record<string, number>` | Get prompt counts per session |
| `promptQueue:markSubmitted` | `promptQueue.markSubmitted(sid, pid)` | R→M | session id, prompt id | `boolean` | Mark prompt as submitted |

## Message Inbox (4 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `messageInbox:getForRecipient` | `messageInbox.getForRecipient(r)` | R→M | recipient string | `InboxMessage[]` | Get messages for recipient |
| `messageInbox:getAll` | `messageInbox.getAll()` | R→M | none | `InboxMessage[]` | Get all messages |
| `messageInbox:getAllUnreadCounts` | `messageInbox.getAllUnreadCounts()` | R→M | none | `Record<string, number>` | Unread count per recipient |
| `messageInbox:markRead` | `messageInbox.markRead(r, mid)` | R→M | recipient, message id | `boolean` | Mark message as read |

## Doc Tracker (7 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `docTracker:getTree` | `docTracker.getTree()` | R→M | none | `AnnotatedDocNode[]` | Get document tree |
| `docTracker:getAnnotatedTree` | `docTracker.getAnnotatedTree(sid)` | R→M | session id | `AnnotatedDocNode[]` | Get tree annotated with session's load state |
| `docTracker:markLoaded` | `docTracker.markLoaded(sid, path)` | R→M | session id, doc path | `{ success }` | Mark doc as loaded by session |
| `docTracker:markUnloaded` | `docTracker.markUnloaded(sid, path)` | R→M | session id, doc path | `{ success }` | Mark doc as unloaded |
| `docTracker:markStale` | `docTracker.markStale(sid, path)` | R→M | session id, doc path | `{ success }` | Mark doc as stale |
| `docTracker:getLoaded` | `docTracker.getLoaded(sid)` | R→M | session id | `LoadedDoc[]` | Get docs loaded by session |
| `docTracker:getSessionCounts` | `docTracker.getSessionCounts(sid)` | R→M | session id | `{ loaded, total }` | Doc load counts for session |

## Memory Slots (6 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `memorySlots:getSlots` | `memorySlots.getSlots()` | R→M | none | `MemorySlot[]` | Get all memory slots |
| `memorySlots:getAnnotatedSlots` | `memorySlots.getAnnotatedSlots(sid)` | R→M | session id | `AnnotatedMemorySlot[]` | Slots annotated with session load state |
| `memorySlots:markLoaded` | `memorySlots.markLoaded(sid, slotId, owner?)` | R→M | session id, slot id, owner | `{ success }` | Mark slot as loaded |
| `memorySlots:markUnloaded` | `memorySlots.markUnloaded(sid, slotId, owner?)` | R→M | session id, slot id, owner | `{ success }` | Mark slot as unloaded |
| `memorySlots:getLoaded` | `memorySlots.getLoaded(sid)` | R→M | session id | `string[]` | Get loaded slot IDs |
| `memorySlots:getSessionCounts` | `memorySlots.getSessionCounts(sid)` | R→M | session id | `{ loaded, total }` | Slot load counts |

## Search (1 channel)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `search:query` | `search(params)` | R→M | `{ query, mode, filters }` | search results | Search session files via ripgrep |

## Config (1 channel)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `config:get` | `getConfig()` | R→M | none | config object | Read app config.json |

## Debug (3 channels)

| Channel | Exposed As | Dir | Params | Returns | Purpose |
|---------|-----------|-----|--------|---------|---------|
| `debug:getState` | `debug.getState()` | R→M | none | app state summary | Get session/group/tab state for testing |
| `debug:getFullState` | `debug.getFullState()` | R→M | none | full state | Complete state dump |
| `debug:pushRendererState` | `debug.pushRendererState(state)` | R→M | state object | any | Renderer pushes state for full picture |

## Push Events (Main → Renderer, 6 channels)

| Channel | Exposed As | Dir | Purpose |
|---------|-----------|-----|---------|
| `session:added` | `onSessionAdded(cb)` | M→R | New session detected (zellij watcher) |
| `session:removed` | `onSessionRemoved(cb)` | M→R | Session removed |
| `session:activity` | `onSessionActivity(cb)` | M→R | Session activity detected |
| `clipboard:copy` | `onClipboardCopy(cb)` | M→R | CMD+C intercepted — carries zellij selection |
| `tab:switchTo` | `onTabSwitchTo(cb)` | M→R | CMD+1-9 intercepted — switch to tab N |
| `tab:prev` / `tab:next` | `onTabPrev(cb)` / `onTabNext(cb)` | M→R | CMD+Shift+[ / ] — cycle tabs |

---

## Summary

| Category | Channels | Pattern |
|----------|----------|---------|
| Session Manager | 14 | invoke |
| Groups & Filters | 10 | invoke |
| Session Lifecycle | 4 | invoke |
| Terminal/xterm | 8 | 4 invoke, 2 send, 2 push |
| Clipboard/Shell | 3 | invoke |
| Terminal Control | 3 | 1 send, 2 invoke |
| Transcript | 2 | invoke |
| UUID Discovery | 1 | invoke |
| Prompt Queue | 4 | invoke |
| Message Inbox | 4 | invoke |
| Doc Tracker | 7 | invoke |
| Memory Slots | 6 | invoke |
| Search | 1 | invoke |
| Config | 1 | invoke |
| Debug | 3 | invoke |
| Push Events | 6 | on/send |
| **Total** | **77** | |
