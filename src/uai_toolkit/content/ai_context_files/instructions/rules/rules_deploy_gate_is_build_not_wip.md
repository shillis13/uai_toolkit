---
name: feedback_deploy_gate_is_build_not_wip
description: Don't use other sessions' uncommitted WIP as a reason not to build+deploy
  — it cascades into a deploy freeze. The deploy gate is \"does it build clean\",
  which the build itself verifies. Deploy UAI via ai_general/scripts/ui/uai.sh.
status: active
---

PianoMan (2026-06-22): "Many of you are starting to use this as a reason not to build and deploy... waiting just becomes a cascading blocker to anyone building and deploying." He's right — refusing to deploy because the shared tree has other sessions' uncommitted WIP is a self-inflicted freeze.

**Why:** A session shouldn't end a turn with broken code (build-after-every-change implies the tree compiles at turn boundaries). So uncommitted WIP is **not** presumptively broken — it's presumptively working-but-incomplete. The only genuinely-broken state is an active mid-write instant or an actual error.

**How to apply:**
- **The deploy gate is "does it build clean," not "is there WIP."** Run the build; if it succeeds, deploy. Only if the build *fails* is there a real blocker — and then identify *whose* breakage and surface it, don't just refuse.
- Shipping a compiling-but-incomplete feature is acceptable (continuous deploy + version bump beats a deploy freeze); a broken build is not.
- **The UAI deploy script exists: `ai_general/scripts/ui/uai.sh`** (NOT in the project's `scripts/` — don't claim it's missing). `--rebuild` bumps patch; `--minor`/`--major` bump and reset lower levels to 0; `--set X.Y.Z`; `--no-bump`; **`--no-launch` deploys the new bundle without disturbing the running instance** (user picks it up on quit+relaunch — the safe path that respects [[feedback_dont_kill_user_app]]).
- Reconciles with [[feedback_build_after_every_change]]: build+deploy every change; the shared tree is not an excuse, the build result is the arbiter.
