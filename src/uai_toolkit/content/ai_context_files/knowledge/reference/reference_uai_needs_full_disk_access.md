---
name: reference_uai_needs_full_disk_access
description: UAI-hosted Claude sessions lose access to external volumes after a drive
  remount unless UnifiedAI.app has Full Disk Access
status: active
---

Claude Code sessions launched inside UnifiedAI.app (the Electron UAI, `com.electron.unified-ai-interface`, bundle at `$AI_ROOT/ai_general/apps/unified_ai_ui/UnifiedAI.app`) inherit that app's TCC identity. If UnifiedAI.app lacks **Full Disk Access**, macOS Sandbox/System Policy denies the session `file-read-data`/write on ALL external volumes (ModelVault, TOSHIBA, WD, …) with **EPERM (errno 1)** — internal Macintosh HD still works.

Trap: access appears to work while a volume stays continuously mounted (cached grant), then breaks after any full unmount+remount, which forces TCC re-evaluation. Symptom: `df`/`diskutil` show the volume healthy and mounted, Finder can read it, but the whole Claude process subtree (even fresh child procs, never-cached paths) gets EPERM. Confirm via: `log show --last 5m --predicate 'eventMessage CONTAINS "deny(1)"'` → look for `(Sandbox) System Policy: ... deny(1) file-read-data /Volumes/...` with `responsible=UnifiedAI.app` and `service=kTCCServiceSystemPolicyAllFiles`.

Fix: System Settings → Privacy & Security → Full Disk Access → enable UnifiedAI.app, then relaunch UAI (FDA grants need app restart to take effect; newly-spawned children *sometimes* pick it up without restart — worth retesting first). ModelVault is also an encrypted APFS volume — after a full unmount it needs `diskutil apfs unlockVolume disk5s1` (passphrase; tick "remember in keychain" to auto-remount). Distinct from the mmap-wedge failure: a running llama-server with a model `mmap`'d off ModelVault pins the mount so `diskutil unmount` fails until that process is killed. Related: [[reference_uci_vs_uai]] [[project_uai_resurrection]]
