# Background App Automation on macOS

**Version:** 1.0.0
**Created:** 2026-05-02
**Maintainer:** PianoMan + Whetstone (Claude CLI)
**Status:** active
**Change Notes:** Initial version from spike proving full non-intrusive app lifecycle

## Purpose

Launch, screenshot, interact with, and close macOS applications without stealing
focus from the user. Supports both native apps (via Accessibility API) and
Electron apps (via Chrome DevTools Protocol).

## Prerequisites

- **Hammerspoon** installed and running with `require("hs.ipc")` in `~/.hammerspoon/init.lua`
- **`hs` CLI** on PATH (symlinked from Hammerspoon.app)
- Accessibility permissions granted to Hammerspoon
- For Electron apps: `--remote-debugging-port` enabled in the app

## Architecture

Two tools, two layers:

┌────────────────┬────────────────────────────────┬──────────────────────────────────────────────────────────────────┐
│ **Layer**      │ **Tool**                       │ **Handles**                                                      │
├────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ OS             │ Hammerspoon IPC (`hs -c`)      │ Launch, window discovery, screenshot, hide/unhide, close, AX API │
├────────────────┼────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
│ App (Electron) │ Chrome DevTools Protocol (CDP) │ DOM read/write, click, type, page state                          │
└────────────────┴────────────────────────────────┴──────────────────────────────────────────────────────────────────┘

Native macOS apps use Hammerspoon for everything (AX API provides full UI access).
Electron apps have sparse AX trees (window chrome only), so CDP handles interaction.

## Procedure

### 1. Launch Without Focus Steal

**Native apps:**
```bash
open -g -a "Calculator"
```

**Electron apps (two instances):**

The second instance MUST have a different version number than the user's
running instance AND be launched from a different path. This is critical:

1. **Different version number** — bump the version in package.json before
   building so the window title (e.g. "v4.4.1-mvcr5-dev") is visually
   distinguishable from the user's instance. Without this, you cannot tell
   which window belongs to which instance in screenshots or the process list.
2. **Different path** — same-path launches route to the existing instance.
   Build output (`src/out/`) vs deployed app (`apps/.../AppName.app.mvcr5`)
   are different paths. Alternatively, copy and rename the `.app` bundle.

```bash
# 1. Bump version in package.json
# 2. Build
npm run build
# 3. Launch from build output path (NOT the deployed path)
open -g /path/to/src/out/AppName-darwin-arm64/AppName.app
```

To prevent the brief focus flash on Electron apps, set up a Hammerspoon
window.filter trap BEFORE launch:

```lua
-- Set trap (replace YOUR_PID with the PID of the user's running instance)
local wf = hs.window.filter.new(false)
wf:setAppFilter("AppName", {allowRoles="*"})
wf:subscribe(hs.window.filter.windowCreated, function(win)
    if win then
        local app = win:application()
        if app and app:pid() ~= YOUR_PID then
            hs.timer.doAfter(0.5, function()
                if app:isRunning() then app:hide() end
            end)
        end
        wf:unsubscribeAll()
    end
end)
```

Then launch. The new window will be hidden within ~500ms.

### 2. Discover Windows

```lua
-- Via hs CLI
hs -c '
local app = hs.application.find("AppName")
local wins = app:allWindows()
for _, w in ipairs(wins) do
    local f = w:frame()
    print(w:id() .. " " .. w:title() .. " " .. f.w .. "x" .. f.h)
end
'
```

### 3. Screenshot Without Activation

**Visible or behind-other-windows:**
```lua
local win = hs.window.get(WINDOW_ID)
local img = win:snapshot()
img:saveToFile("/tmp/screenshot.png")
```

**Hidden windows (app:hide() state):**

`win:snapshot()` returns nil on hidden windows. Workaround:

```lua
app:unhide()
hs.timer.usleep(200000)  -- 200ms for render
local win = app:mainWindow()
win:setFrame({x=-3000, y=0, w=1920, h=1080})  -- off-screen
hs.timer.usleep(300000)  -- 300ms for paint
local img = win:snapshot()
img:saveToFile("/tmp/screenshot.png")
app:hide()  -- re-hide
```

Total time: ~500ms. Window appears at x=-3000 where no display exists.
User never sees it. Focus is not affected.

### 4. Interact with Native Apps (AX API)

Read the accessibility tree:
```lua
local ax = hs.axuielement.windowElement(win)
-- Recursive traversal to find elements by role/title/description
```

Click a button without activation:
```lua
-- Find element, then:
element:performAction("AXPress")
```

Read a value:
```lua
local value = element:attributeValue("AXValue")
```

**Note:** Native apps expose full AX trees. Button names use full text
(e.g., "All Clear" not "AC", "Multiply" not "x").

### 5. Interact with Electron Apps (CDP)

Electron's AX tree is sparse (only window chrome). Use CDP instead.

**Connect:**
```python
import websockets, json

# Discover page endpoint
resp = urllib.request.urlopen(f'http://localhost:{port}/json')
pages = json.loads(resp.read())
ws_url = pages[0]['webSocketDebuggerUrl']

async with websockets.connect(ws_url) as ws:
    await ws.send(json.dumps({
        'id': 1,
        'method': 'Runtime.evaluate',
        'params': {'expression': 'document.title'}
    }))
    result = json.loads(await ws.recv())
```

**Query DOM:**
```javascript
// Read elements
document.querySelectorAll('.nav-folder-name')
// Click
document.querySelector('button[title*="Search"]').click()
// Read values
document.querySelector('.tab.active .tab-name').textContent
```

**Multiple instances:** Each instance needs its own debug port. Set via
env var (e.g., `UCI_DEBUG_PORT=9225`) or Electron's `app.commandLine.appendSwitch`.

### 6. Close Without Focus Steal

```lua
local app = hs.application.find("AppName")
app:kill()
```

Or by PID: `kill <pid>`

### 7. Focus Verification

Always verify focus wasn't stolen:
```lua
local front = hs.application.frontmostApplication()
print(front:name() .. " PID " .. front:pid())
```

Check this before and after every operation. If focus shifted, the procedure failed.

## Electron App Configuration for Automation

Add these to the Electron main process for better automation support:

```typescript
// Keep renderer alive when backgrounded (required for CDP screenshots)
app.commandLine.appendSwitch('disable-renderer-backgrounding');
app.commandLine.appendSwitch('disable-backgrounding-occluded-windows');

// In BrowserWindow webPreferences:
backgroundThrottling: false,

// Enable full AX tree (call after app is ready, not at module load):
app.whenReady().then(() => {
    app.setAccessibilitySupportEnabled(true);
});

// Configurable debug port for multi-instance:
app.commandLine.appendSwitch('remote-debugging-port',
    process.env.UCI_DEBUG_PORT || '9224');
```

## Gotchas

- **`open -g` is unreliable for Electron apps** — they often steal focus anyway.
  Use the Hammerspoon hide trap.
- **`app.setAccessibilitySupportEnabled(true)` crashes if called before app is ready.**
  Must be inside `app.whenReady().then(...)`.
- **Same app path = same instance.** macOS Launch Services routes `open` to the
  existing process if the `.app` bundle path matches. Second instances must come
  from a different build output directory.
- **NODE_OPTIONS env var** kills packaged Electron apps on launch. Clear it:
  `env -u NODE_OPTIONS open -g ...` (though `open` via LaunchServices may
  still inherit user-level env vars).
- **Calculator uses invisible Unicode** (U+200E left-to-right marks) in display
  values. Strip them when comparing: `value.replace("\u200e", "")`.
- **Hammerspoon window.filter subscriptions accumulate.** Always call
  `wf:unsubscribeAll()` after the trap fires. Stale filters cause IPC recursion errors.
- **CDP `Page.captureScreenshot` hangs on hidden Electron windows** even with
  `backgroundThrottling: false`. Use the Hammerspoon unhide/offscreen/snapshot/rehide
  workaround instead.

## Proven Results

Tested 2026-05-02 with Calculator (native) and UnifiedCLI (Electron):

| Capability | Native App | Electron App |
|-----------|:---:|:---:|
| Launch without focus | open -g | open -g + hide trap |
| Window discovery | Hammerspoon | Hammerspoon |
| Screenshot (visible) | win:snapshot() | win:snapshot() |
| Screenshot (hidden) | unhide/offscreen/rehide | unhide/offscreen/rehide |
| Read UI elements | AX API (full tree) | CDP (full DOM) |
| Click/interact | AXPress (no focus) | CDP DOM click (no focus) |
| Read values | AX attributeValue | CDP Runtime.evaluate |
| Close | app:kill() | app:kill() |
| Focus preserved | Yes, all steps | Yes, all steps |

## Script Location

Live tool: `ai_general/scripts/ui/bgapp.py`

For the Electron two-instance flow, build and deploy with `ai_general/scripts/ui/uai.sh`
(handles version bump, build, and deploy) instead of a bare `npm run build`.
