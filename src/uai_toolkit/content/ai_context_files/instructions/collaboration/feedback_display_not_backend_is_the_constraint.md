---
name: feedback_display_not_backend_is_the_constraint
description: For UAI test/render work the real constraint is not disrupting PianoMan's
  display/running app without a coordinated handoff — he downplayed backend-bleed/inject;
  coordinate the app-handoff rather than treat a 2nd instance as forbidden.
status: active
---

When verifying UAI UI changes (render-verify, test instances), the gating constraint is **don't control or be messy with PianoMan's display / running app without a coordinated handoff window** — NOT "never run a second instance against the shared backend."

PianoMan's verbatim (2026-06-20): "I'm not that concerned about inject messages, instances, etc. Controlling or messy with my display is a different story. We can coordinate times where I concede the app to you, or even the whole computer, but we would need to coordinate that."

**Why:** An earlier framing (Anvil's auto-generated handoff brief, repeated in ~12 spots) elevated *shared-backend bleed* to a near-absolute "never drive a 2nd instance." But UAI is overwhelmingly a **reader** (the "External Ground Truth" principle: reflect, never diverge), so a 2nd reader is mostly harmless. The autonomous write surface is just **two app-owned files** — `ai_general/data/app_state.json` (tabs/activeTab/UI prefs) and `ai_general/data/containers.json` (folder tree) — and **both already have isolation built in**: env vars `UAI_APP_STATE_PATH` and `UAI_CONTAINERS_PATH` redirect those writes to isolated files for a test instance (`app/main/app-state-path.ts`, `app/main/container-manager.ts`). The 2026-06-20 bleed happened because the test instance isolated only the Electron *profile* + CDP port and did **not** set those two env vars — so its tab switches wrote the shared `app_state.json`, making the user's instance follow ("controlling one bleeds to the other" = exactly the cross-instance tab bleed-over the app-state-path.ts comment predicts). The remaining writes (comms.send, brief creation, assigned-tasks scan cache, lock/pid markers) are explicit-action-only — a *passive* render-verify never triggers them.

**How to apply:** Primary path = **coordinate an app-handoff window** (his real requirement; don't touch his display uncoordinated). For a safe offscreen render-verify when you can't get a window, the isolation already exists: set **`UAI_APP_STATE_PATH` + `UAI_CONTAINERS_PATH`** to isolated files (seed containers from the real ~4 KB `containers.json` if you need the existing folders) + offscreen window + separate CDP port + `UAI_ALLOW_MULTI=1`. That protects the only two files UAI autonomously writes; don't actively drive mini-chats/brief-creation in such a test (those hit shared comms). Batch verifications into one handoff so you ask for the app only once. Briefs are generated/guarded artifacts — this correction lives here, not in the brief. Refines [[feedback_dont_kill_user_app]], [[feedback_test_instance_hidden]], [[reference_uai_multi_instance_testing]].
