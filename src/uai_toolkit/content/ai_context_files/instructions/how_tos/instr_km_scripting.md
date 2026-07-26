---
name: Keyboard Maestro shell scripting lessons
description: KM macro shell script gotchas — variables, exit codes, Python compat,
  macOS Unicode
status: active
---

**KM shell scripts: always end with `exit 0`** — KM treats the exit code of the last command as the macro result. `[ -s file ]` returning false = exit 1 = "Macro Cancelled" notification.

**Why:** User lost significant debugging time to this. KM's error notification gives no detail — just "failed with status 1."

**How to apply:** Any KM Execute Shell Script action should explicitly `exit 0` on the success path and `exit 1` only when there's a real error.

---

**`%TriggerValue%` does not work inside KM shell scripts.** Must set a KM variable first (Set Variable action → `%TriggerValue%`), then access as `$KMVAR_VariableName` in bash.

**Why:** KM token substitution (`%...%`) only works in KM's own fields, not inside shell script bodies. Forum confirmed: https://forum.keyboardmaestro.com/t/passing-triggervalue-to-shell-script/19632

**How to apply:** Always use a Set Variable action before Execute Shell Script when you need trigger values.

---

**KM uses system Python (`/usr/bin/python3` = 3.9.6).** `str | Path` type hints crash at runtime. Either use `from __future__ import annotations` or remove union type hints entirely.

**Why:** Python 3.10+ syntax on 3.9 = `TypeError: unsupported operand type(s) for |`.

**How to apply:** Any Python script that might be called from KM (or other non-Homebrew contexts) needs `from __future__ import annotations` as the first line after the shebang, or must avoid modern type hint syntax.

---

**macOS screenshot filenames contain `\u202f` (narrow no-break space)** between time and AM/PM. This invisible Unicode character causes `FileNotFoundError` when Python tries to operate on the path.

**Why:** `shutil.move()` fails because the string representation doesn't match the filesystem encoding.

**How to apply:** Normalize file paths from macOS with `unicodedata.normalize("NFC", path)` before using them.

---

**Alerter notifications block the calling process.** If a script calls `alerter` synchronously and KM has a timeout or the user dismisses it, KM reports "Macro Cancelled."

**Why:** `alerter` waits for user interaction or timeout before returning.

**How to apply:** Run alerter in a detached subprocess (`subprocess.Popen` with `start_new_session=True`) so the main script exits immediately.

---

**KM debugging pattern** — redirect to log, check at end:
```bash
LOG_FILE=/tmp/whatever.log
[ -f "${LOG_FILE}" ] && rm -f "${LOG_FILE}"
# ... do work ... >> "${LOG_FILE}" 2>&1
[ -s "${LOG_FILE}" ] && cat "${LOG_FILE}" && exit 1
exit 0
```
