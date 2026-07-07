# How to Test Changes

**Version:** 1.0.0
**Created:** 2026-06-19
**Maintainer:** PianoMan + (Claude CLI)
**Status:** active
**Change Notes:** Initial version — testing workflow + live multi-instance app testing.

## Purpose

How to verify changes before claiming they work — from static checks through
running the real app. Applies to any developer, tester, or validator role.

## Core principle: verify with real execution

A typecheck passing, a dry-run succeeding, or "the code looks right" is **not**
verification. Run the thing for real and observe the actual result. When you
report status, state what you ran and the real output. If you only typechecked,
say exactly that — never imply a runtime behavior was confirmed when it wasn't.

## The testing ladder (cheapest → most real)

1. **Static** — typecheck (`tsc --noEmit` in the relevant package) and lint.
   Catches type/shape errors. Necessary, not sufficient.
2. **Build & deploy** — run the project's build/deploy script and confirm it
   succeeds and stamps a version. For UAI: `ai_general/scripts/ui/uai.sh --rebuild`
   (auto-bumps the patch version; `--minor`/`--major`/`--set X.Y.Z` to control;
   `--no-bump` to rebuild in place). Always report the new version on deploy.
3. **Automated tests** — run the suite (UAI: `npm run validate` / vitest in `app/`).
4. **Live / manual** — run the real app and observe the behavior. For UI/UX,
   formatting, or interaction changes this is **mandatory** — static + build do
   not prove the feature works in the running app.

State which rungs you actually completed.

## Live-testing the app without disrupting the user

The user is often running their own instance of the app. **Never** kill, restart,
`/compact`, or otherwise disturb the user's running instance or their data.
Instead launch an **isolated second instance** and drive it programmatically.

### Isolation (the key to safe multi-instance testing)

Two app instances sharing the same data root will fight over shared state. Isolate
only the files the app **writes** — keep reads pointed at the real data so the test
instance still looks fully populated. Do **not** copy the whole data dir.

For UAI, the app writes only two small files under `ai_general/data/`:

- `UAI_APP_STATE_PATH=/tmp/x.json` — UI state (tabs, active tab, prefs). Without
  it, both instances share `app_state.json` and the test instance's tab changes
  make the user's window follow (tab bleed-over).
- `UAI_CONTAINERS_PATH=/tmp/y.json` — folders (and its sibling `.changed` signal).

Everything else (sessions, transcripts, the ~1 GB of data) is read-only for a test
and needs no isolation. Seed a writable file with a `cp` of the real one **only**
if the test needs the existing data (e.g. creating a folder under a real parent);
these files are tiny (KB), so seeding is cheap when wanted.

`ai_comms` is a separate write-surface — only bleeds if a test sends or marks-read
messages.

### Separate debug port

The app exposes a Chrome DevTools Protocol port (`UCI_DEBUG_PORT`/`UAI_DEBUG_PORT`,
default **9226** = the user's instance). Launch the test on a **different** port.

### Launch + drive + clean up

- **Launch** via `bgapp.py` (auto-registers, positions the window off-screen,
  and supports `close`/`screenshot`). See `instr_background_app_automation` for the
  mechanics. Example:
  ```
  UAI_APP_STATE_PATH=/tmp/a.json UAI_CONTAINERS_PATH=/tmp/c.json \
    python3 ai_general/scripts/ui/bgapp.py launch <abs path to .app> --port 9334 --name uai_test
  ```
  Env exported in the shell propagates through `open`. `bgapp` depends on the `hs`
  (Hammerspoon) CLI, which can transiently time out — if launch aborts, just retry.
  Hammerspoon-free fallback: `UAI_APP_STATE_PATH=... UCI_DEBUG_PORT=9334 open -g -n /tmp/copy.app`
  (use a copy of the .app), then move the window off-screen with one `hs` `setFrame` call.
- **The off-screen test window may leave a ~40px sliver at the screen edge** — this
  is acceptable and even desirable: a quiet visual cue that a test instance is live.
- **Drive** via CDP: WebSocket to `http://127.0.0.1:<port>/json` page target →
  `Runtime.evaluate`. Execute commands through the app's command bus, e.g.
  `window.uai.execute({type:'workspace.tabs.open', payload:{...}, origin:'user', timestamp:...})`.
  To set a React-controlled input, use the native value setter + dispatch an `input`
  event (assigning `.value` alone won't fire React's onChange).
- **Verify**, then **clean up**: `bgapp close <name>` (kills by registry PID, removes
  the /tmp copy), and `rm` the temp state files. Prove isolation by confirming the
  user's real files are byte-identical (hash) and untouched. Never kill the user's PID.

## Reporting

Report honestly and specifically: the commands run, the real output, which ladder
rungs you completed, and what you did **not** verify. "Built and deployed v1.2.3;
typecheck clean; not yet click-tested in a running window" is a good status line.
