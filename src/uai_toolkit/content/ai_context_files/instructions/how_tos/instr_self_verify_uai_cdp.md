---
name: feedback_self_verify_uai_cdp
description: Verify UAI UI changes yourself via the CDP debug port (DOM + IPC), don't
  rely on PianoMan for visual validation
status: active
---

After any UAI UI change, VERIFY IT YOURSELF before reporting — don't make PianoMan be your eyes. He built these capabilities precisely so I can validate while he's working in the app.

**How:** The running UAI exposes a Chrome DevTools Protocol port at **127.0.0.1:9226**.
- `curl -s http://127.0.0.1:9226/json` → find the page whose title contains `UAI` → `webSocketDebuggerUrl`.
- Open the websocket, send `Runtime.evaluate` with `awaitPromise:true, returnByValue:true`.
- Query the live **IPC** (`await window.uai.prompts.getPromptAreas()`, etc.) AND the rendered **DOM** (`document.querySelectorAll('.nav-recent-item')`, `.nav-badge-prompt`, etc.) to confirm what's actually on screen.
- This is non-intrusive (read-only) and works while the user is using the app.

**Caveats:**
- The external scripts UAI shells out to (e.g. `~/bin/ai/prompting/get_prompt_area_texts.py`) are spawned per call, so fixing them is live with no rebuild — but the app only re-reads on its scan cadence (mount / event / any poll), so trigger or wait for a scan before reading the DOM.
- `screeny` (pixel screenshots) only captures windows the user has APPROVED for screen recording; the UAI window is NOT approved by default, so screeny can't shoot it. CDP DOM inspection is the reliable self-verify path. (If pixel-accurate shots are needed, ask the user to approve the UAI window in screeny.)
- **Test a NEW build before deploying to the user's app — launch a hidden instance and CDP into it.** Recipe (verified 2026-06-19): build to `app/out/...`, then
  `UAI_ALLOW_MULTI=1 UAI_TEST_OFFSCREEN=1 UAI_DEBUG_PORT=9227 nohup <app>/Contents/MacOS/unified-ai-interface &`
  → off-screen (x:-4000), separate CDP port 9227, skips single-instance lock. Verify on 9227, then `kill <pid>` and rsync-deploy. Caveat: it SHARES the data dir, so do NOT activate tabs / mutate app-state (it persists to the shared `app_state.json` and would change the user's view); read-only queries (`captureScrollback`, `__memorex`, DOM) are safe. Only the ACTIVE tab renders a Memorex overlay, so `__memorex` reflects whatever session was active in shared state — you can't observe a background session's overlay without activating it. See [[feedback_test_instance_multi]], [[feedback_test_instance_hidden]].
- **Standalone-core repro ≠ a UAI test.** The standalone memorex core has classification/boundary but NO cover geometry. Verifying a Memorex fix there (or by bundle grep) misses geometry regressions — a trim that fixed classification shrank the length used for cover sizing and slid the overlay over the live prompt/verb line. Geometry must be verified in a running overlay (test instance).
- **`session_ops read-terminal` ≠ the app's `captureScrollback`.** They produce DIFFERENT text. A Memorex bug was invisible in `read-terminal` output but real in the deployed capture: `captureScrollback` returned 52 trailing blank lines below Anvil's content, which defeated the bottom-up prompt-area scan and made the live prompt format as a user message. **To debug Memorex/terminal logic, pull the EXACT deployed bytes** via CDP: `await window.uai.terminal.captureScrollback('<sessionName>', 50000)`, then run the boundary logic on that — not on a `read-terminal` capture.

- **For an "I don't see the change" report, CDP into the USER's live instance (9226) FIRST — don't keep re-verifying your own offscreen instance.** 2026-07-01: PianoMan reported no change to bottom-panel tabs across ~5 deploys. I kept confirming it in my offscreen instance (seeded app_state, panel OPEN) and it looked right. Connecting read-only to HIS 9226 instantly showed the truth: `document.querySelectorAll('.bottom-panel-tab').length === 0` — his panel was COLLAPSED, rendering a DIFFERENT element (`.bottom-panel-strip-tab`) that I'd only styled in its `.active` state (itself gated on `isOpen`, so nothing highlighted while collapsed). His stylesheet HAD my rule; it just applied to an element not on his screen.
- **Match the user's actual UI STATE, not a convenient one.** A component can render different elements per state (collapsed vs open, empty vs populated, focused vs not). Seeding `bottomPanelOpen:true` verified a surface he never looks at. Before declaring a visual fix verified, reproduce the exact state the user is in (read it off their 9226 DOM), or test all states.
- **Bundle-grep / computed-style checks prove the CSS SHIPPED, not that the user SEES it.** The rule was byte-present in the deployed asar and `getComputedStyle` returned my values — all true, all irrelevant, because the styled element wasn't mounted in his view. "Is my selector even on screen?" (`querySelectorAll(sel).length` on the user's instance) is the question that would have saved 5 rounds.

Relates to [[feedback_verify_with_real_execution]], [[feedback_no_fabricated_premises]], [[feedback_devtools_element_picker]], [[feedback_dont_conclude_before_verifying]].
