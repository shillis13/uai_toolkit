---
name: UCI vs UAI paths
description: unified_cli_interface (UCI, old) vs unified_ai_interface (UAI, new) —
  different directories, different apps
status: active
---

**UCI** = Unified CLI Interface (old/production)
- Source: `ai_general/projects/unified_cli_interface/src/`
- Packaged app: `ai_general/apps/unified_cli_ui/UnifiedCLI.app.mvcr3`
- Currently running as production app

**UAI** = Unified AI Interface (new/in-development)
- Source: `ai_general/projects/unified_ai_interface/src/uai-app/`
- Not yet working (E2E tests were falsely attested as passing)

**Critical:** The path difference is `unified_cli_interface` vs `unified_ai_interface`. One letter difference. Misreading this caused investigation in the wrong codebase during the 280K file bug.
