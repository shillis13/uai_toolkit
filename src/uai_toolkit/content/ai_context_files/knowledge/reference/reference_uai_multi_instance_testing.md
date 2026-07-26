---
name: reference_uai_multi_instance_testing
description: How to launch an isolated UAI test instance and drive it via CDP without
  bleeding into the user's running instance
status: active
---

Canonical codebase doc (keep in sync): `ai_general/ai_traits/procedures/instr_testing` (.latest.md), loaded by the dev/tester/validator/dev_lead roles. This memory is the quick-reference; that doc is the authoritative version any dev/test role gets.

Running a second UAI instance for testing (so the user's instance is unaffected):

- **No single-instance lock** — UAI allows multiple instances (index.ts: "No single-instance lock").
- **CDP debug port**: UAI enables `remote-debugging-port` from `UCI_DEBUG_PORT || UAI_DEBUG_PORT || 9226`. The user's instance is on 9226 — launch the test on a *different* port (e.g. 9333).
- **Don't copy `ai_general/data`** (it's ~1 GB). The app only *writes* two tiny files there — `app_state.json` (13K) and `containers.json` (4K); everything else it reads. Tags/relationships/sessions stores are written by external CLIs, not the app. So isolate per-file (reads stay on the real dir → test instance looks fully populated, zero seeding):
  - `UAI_APP_STATE_PATH=/tmp/x.json` (v1.1.90) — tabs/activeTab/prefs. Without it both instances share `app_state.json` and the test's tab open/activate makes the user's window follow (tab bleed-over). Helper: `app/main/app-state-path.ts`.
  - `UAI_CONTAINERS_PATH=/tmp/y.json` (v1.1.91) — folders (+ the sibling `containers.changed` signal, derived from its dirname). Helper: `container-manager.ts getContainersPath()`. Seed with `cp` of the real 4K `containers.json` if the test needs existing folders (else it starts with default roots only).
  - `ai_comms` is a separate write-surface; only bleeds if a test sends/marks-read messages.
- **Launch via bgapp** (preferred — auto-registers, auto-hides, `close`/`screenshot` work): `UAI_APP_STATE_PATH=/tmp/a.json UAI_CONTAINERS_PATH=/tmp/c.json python3 ai_general/scripts/ui/bgapp.py launch <abs path UnifiedAI.app> --port 9334 --name uai_test`. bgapp sets `UCI_DEBUG_PORT` from `--port`; env exported in the shell propagates through `open`. **bgapp name-match is fixed** (matches CFBundleName `unified-ai-interface` via `_app_process_name`, not the filename stem). Caveat: bgapp depends on the `hs` CLI which can transiently time out (10s) — if launch aborts at `_find_user_pids`, just retry.
  - Direct fallback (no Hammerspoon): `UAI_APP_STATE_PATH=... UCI_DEBUG_PORT=9334 open -g -n /tmp/copy.app` (use a copy of the .app), then move the window off-screen with one `hs` `win:setFrame({x=-2200,...})` call excluding the user's PID.
  - The off-screen window often leaves a ~40px sliver at the screen edge (macOS clamps fully-offscreen positions). PianoMan **likes** this — it's a quiet cue that a test instance is live. Don't "fix" it.
- **`UAI_TEST_OFFSCREEN=1` env path** (distinct from the bgapp+hs path above): launch the built binary directly with `UAI_ALLOW_MULTI=1 UAI_TEST_OFFSCREEN=1 UAI_DEBUG_PORT=9227 UAI_APP_STATE_PATH=/tmp/x.json`. As of 2026-06-22 (v1.1.100) this makes the instance **fully invisible** via `opacity:0` + `show:false`→`showInactive()` + `setIgnoreMouseEvents` + skipTaskbar (createWindow in index.ts). Why: macOS **overrides** off-screen window coords on app activation (the old `x:-4000,show:true` produced a *full-screen* visible window — PianoMan's 2026-06-22 complaint). opacity:0 is the robust invisibility mechanism (the window still lands at ~0,40 but is transparent). Renderer/CDP/IPC fully work while invisible. **TENSION:** line below says PianoMan likes a ~40px *sliver* as a live-test cue (that was the hs-setFrame path); fully-invisible opacity:0 removes any cue. He OK'd "completely off screen" on 2026-06-22, but if he wants the cue back, keep a sliver visible (opacity 1 + positioned so an edge shows) instead of opacity:0.
- **Drive via CDP**: WebSocket to `http://127.0.0.1:<port>/json` page target → `Runtime.evaluate` with `window.uai.execute({type:'...',payload:{...},origin:'user',timestamp:...})`. For a React-controlled input, use the native value setter + dispatch an `input` event.
- **Cleanup**: `bgapp close <name>` (kills by registry pid, removes the /tmp copy), then rm temp app_state/containers files. Never kill the user's PID.
