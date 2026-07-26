---
name: Python compatibility for non-Homebrew contexts
description: Scripts called from KM, launchd, or cron may use system Python 3.9 —
  avoid 3.10+ syntax
status: active
---

**When writing Python scripts that may be invoked outside the terminal** (Keyboard Maestro, launchd, cron, AppleScript), assume Python 3.9 (system `/usr/bin/python3`).

**Why:** Homebrew Python is 3.12+ but isn't on the PATH in these contexts. User hit this with KM calling screenshot_mover.py — `str | Path` type hints crashed.

**How to apply:**
- Add `from __future__ import annotations` as first line after shebang
- Or avoid `X | Y` type hints entirely (use `Optional[X]`, `Union[X, Y]`)
- Avoid importing heavy dependencies that may not be installed in system Python (e.g., `jsonschema`)
- If a library has heavy top-level imports, make them lazy (only import when the specific function is called)
- Test scripts with `/usr/bin/python3` before declaring them ready for KM/launchd use

**Related fix:** Made `lib_extensions.py` lazy-import `yaml_utils` so `ExtensionInfo` (CSV-only) works without `jsonschema`.
