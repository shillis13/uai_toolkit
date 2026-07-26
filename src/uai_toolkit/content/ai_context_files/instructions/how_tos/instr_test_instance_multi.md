---
name: uai_test_instance_pattern
description: UAI has no single-instance lock — deploy test builds to separate .app
  paths
status: active
---

UAI has no single-instance lock. Multiple instances can run simultaneously.

To test alongside production, deploy to a separate `.app` path (e.g., `UnifiedAI-Test.app`) and `open` it.

**Why:** The original Electron boilerplate single-instance lock was removed. Changing `package.json` name to create a "dev" build breaks Electron Forge output paths and module resolution — never do that.

**How to apply:** For test builds, just deploy to a different `.app` path. Same `package.json` name, same binary. macOS treats them as separate processes because they're separate `.app` bundles.
