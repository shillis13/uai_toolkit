---
name: feedback_version_on_deploy
description: Always state the deployed version number when telling user to restart
  the app
status: active
---

Always state the deployed version number when telling the user to restart the app (e.g. "Deployed
v1.3.342 — restart UAI at your convenience"). (This note folds in the former
feedback_state_version_on_deploy.)

**Why:** Multiple sessions build and deploy concurrently. Without the version number the user can't
verify which session's changes are running, or confirm the deploy took effect — they could restart
on a different session's build and not know.

**How to apply:** After every UAI build+deploy, extract the version from the deployed asar /
Info.plist and include it in the message. Every deploy message must carry the version string.
Related: [[feedback_version_bump_build_increment_default]], [[feedback_build_after_every_change]].
