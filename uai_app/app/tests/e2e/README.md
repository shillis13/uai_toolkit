# UAI E2E Test Suite

This directory contains the standalone end-to-end test scripts for the UAI Electron app.

These are **not** Vitest tests. They are raw TypeScript scripts intended to be run against a **live packaged app** that already has Chrome DevTools Protocol (CDP) exposed on port `9226`.

## Test model

- **Transport:** raw CDP over WebSocket
- **Target:** packaged Electron app already running with CDP on `127.0.0.1:9226`
- **Execution style:** one script per UI surface, each exporting `run(): Promise<void>`
- **Runner:** `run-all.ts` executes the test scripts sequentially and reports pass/fail
- **Screenshots:** captured to `/tmp/uai_e2e/`

## Harness

`test-harness.ts` is the shared utility layer.

It provides:
- `connectHarness()` — connect to the UAI CDP target
- `js(expr)` — evaluate JavaScript in the renderer
- `waitFor(selector)` — poll until a selector appears
- `waitForText(text)` — poll until text appears in `document.body`
- `click(selector)` / `rightClick(selector)`
- `type(selector, text)` — uses the **native input value setter** so React-controlled inputs update correctly
- `pressShortcut(selector, key, modifiers)`
- `drag(selector, dx, dy)`
- `boundingBox(selector)`
- `screenshot(name)`
- `captureFailureScreenshot(name)`

## Files and coverage

### `test-navigator.ts`
Covers the left navigator panel.

Checks:
- top-level navigator tabs: Sessions / Teams / Projects
- session search filtering
- status/platform filter pills
- opening a workspace tab from a session card
- recent sessions strip
- `+ New` menu options

### `test-workspace.ts`
Covers the center workspace area.

Checks:
- tab bar rendering
- tab switching
- tab close behavior
- tab context menu options
- session tabs rendering TerminalPane + PromptBox
- opening transcript tabs and confirming Memorex header state

### `test-context-panel.ts`
Covers the right-side details/context/messages panel.

Checks:
- open/close toggle behavior
- the 4 main tabs: Details / Context / Prompts / Messages
- Details tab field presence
- Context tab section counts against `window.uai.traits.list()`
- Messages tab folder buttons
- resize behavior

### `test-bottom-panel.ts`
Covers the bottom drawer.

Checks:
- status strip summary (version / sessions / errors / CPU)
- open/close behavior
- built-in tabs: Related / Session Log / App Log / Monitor
- Monitor metrics: CPU / Memory / Heap / Sessions / Errors / Uptime

### `test-projects.ts`
Covers the navigator Projects tab and project detail rendering.

Checks:
- project API returns data
- project cards render
- git status badges exist
- clicking a project opens a project detail view
- context menu actions: Copy Path / Open in Tab

### `test-briefs.ts`
Minimal API-level coverage for briefs.

Checks:
- `window.uai.briefs.list()` returns items
- the returned items contain human-usable names

This exists because the dedicated navigator Briefs tab was removed, but brief loading remains part of the app surface.

### `test-memorex.ts`
Covers transcript / Memorex behavior.

Checks:
- Memorex toggle on a session tab
- filter pills render
- filter pills appear right-aligned
- block type backgrounds match expected color families
- collapsible blocks collapse/expand

### `test-prompt-box.ts`
Covers PromptBox behavior for a running session.

Checks:
- PromptBox renders
- typing updates the textarea without forwarding input to the terminal
- `Cmd+Enter` routes through the command bus as `prompt.send`
- resize handle changes PromptBox height

### `run-all.ts`
Sequential runner.

Behavior:
- assumes the app is already running
- runs each `run()` function in order
- logs pass/fail per test
- captures a failure screenshot when possible
- exits non-zero if any test fails

## Running the suite

From `app/`, using a TypeScript runner such as `ts-node` or `tsx`:

```bash
# example only — choose the TS runner available in your environment
npx tsx tests/e2e/run-all.ts
```

The tests intentionally do **not** launch the app themselves.

## Assumptions and caveats

1. **The app must already be running** with CDP on `9226`.
2. These tests are selector- and text-driven. UI wording or class changes will require test updates.
3. Some tests use live app state and available sessions/projects. If the dataset is empty, those checks will fail by design.
4. A few assertions patch `window.uai` methods temporarily (for example, PromptBox command interception). Those tests restore the original functions before exit.
5. The tests are currently **compile-verified only**. They were not executed at creation time.

## Maintenance guidance

When UI structure changes:
- update selectors first,
- then update text assertions,
- then rerun `npx tsc --noEmit` before trying the live suite.

If CDP behavior changes:
- adjust `test-harness.ts` only,
- keep the individual test files focused on UI intent rather than low-level protocol details.
