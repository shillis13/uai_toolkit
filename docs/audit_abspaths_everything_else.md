# Absolute-Path Audit — Everything Except uai_app

Generated from a scan of the materialized source (content trees + vendored Python
modules) **after** the scrubber runs (`/Users/shawnhillis/AI/ai_root`→`$AI_ROOT`,
`/Users/shawnhillis/bin/ai`→`$AI_BIN`, `/Users/shawnhillis`→`$HOME`). What remains
below are absolute paths the scrubber does **not** rewrite. Companion list:
`audit_abspaths_uai_app.md`.

Detector: `/Users/*`, `/opt/*`, `/private/*`, `/Applications/*`, `/home/*`
(doc placeholders like `/Users/...`, `/Users/<x>`, `/Users/test` excluded from the
"real" count but shown where they add noise).

**Terms.** *Benign fallback* = a macOS install dir added to a PATH search list; a
non-existent entry on Linux/WSL is silently ignored, so it does not break a
portable install. *False positive* = the token is in a comment/docstring/example,
not executed. *Owner-scoped* = lives in code another session is actively reworking.

---

## Verdict: content trees are clean; Python modules carry only benign/parked items

Nothing here blocks a WSL install. One real portability nit (a hardcoded `zellij`
binary) is **fixed**; the rest are false positives, benign macOS PATH fallbacks, or
owner-scoped scheduling code.

---

## A. FIXED this pass

┌──────────────────────────────────────────┬──────────┬───────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ **File**                                 │ **Line** │ **Was**                               │ **Now**                                                │
├──────────────────────────────────────────┼──────────┼───────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ `scripts/cli/capture_uuid_playwright.py` │ 28       │ `ZELLIJ = '/opt/homebrew/bin/zellij'` │ `shutil.which('zellij') or '/opt/homebrew/bin/zellij'` │
└──────────────────────────────────────────┴──────────┴───────────────────────────────────────┴────────────────────────────────────────────────────────┘

- Portable: resolves `zellij` from PATH, keeps the Homebrew path as fallback.
- **Design-boundary note (flagged, not fixed):** per `scripts/cli/DESIGN.md` the
  substrate-isolation rule says no `zellij` knowledge outside the substrate layer
  (`session_mgmt/lib_session_substrate.py`). This diagnostic shouldn't reference a
  multiplexer binary at all — the proper home for zellij resolution is the
  substrate. Left as a future refactor; the one-liner above is a neutral interim.

## B. Benign macOS PATH fallbacks — no fix needed

These add `/opt/homebrew/bin` (etc.) to a *search list*. On Linux/WSL the path
doesn't exist and is ignored. Fixing = churn with no portability payoff; a future
pass could append the Linuxbrew dir (`/home/linuxbrew/.linuxbrew/bin`).

┌─────────────────────────────────────────────────┬──────────┬──────────────────────────────────────────────────┐
│ **File**                                        │ **Line** │ **Context**                                      │
├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
│ `scripts/session_mgmt/lib_session_substrate.py` │ 30–31    │ `_FALLBACK_BINARY_DIRS` (GUI-launch PATH repair) │
├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
│ `scripts/cli/lib_cli_wrapper.py`                │ 72       │ `fallback_dirs = [...]`                          │
├─────────────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────┤
│ `scripts/prompting/get_prompt_area_texts.py`    │ 53       │ `"/opt/homebrew/bin", "/usr/local/bin", ...`     │
└─────────────────────────────────────────────────┴──────────┴──────────────────────────────────────────────────┘

## C. Owner-scoped — scheduling cross-platform rework (Noctis, per PORT_INSTRUCTIONS.md)

launchd/Task-Scheduler split is a separate migration; do not edit here.

┌─────────────────────────────────────────────────┬───────────┬───────────────────────────────────────────────────────────┐
│ **File**                                        │ **Line**  │ **Context**                                               │
├─────────────────────────────────────────────────┼───────────┼───────────────────────────────────────────────────────────┤
│ `scripts/scheduling/install_scheduled_tasks.py` │ 265, 1833 │ `PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"` │
├─────────────────────────────────────────────────┼───────────┼───────────────────────────────────────────────────────────┤
│ `scripts/scheduling/scheduled_task_mgr.py`      │ 265, 1833 │ same (duplicate of the above)                             │
├─────────────────────────────────────────────────┼───────────┼───────────────────────────────────────────────────────────┤
│ `scripts/scheduling/launchd_backend.py`         │ 31        │ `GLOBAL_ENV = {"PATH": ".../opt/homebrew/bin:..."}`       │
└─────────────────────────────────────────────────┴───────────┴───────────────────────────────────────────────────────────┘

## D. False positives — comment / docstring / example text

┌─────────────────────────────────────────────────────────────────────┬──────────┬─────────────────────────────────┬───────────────────────────────────────────┐
│ **File**                                                            │ **Line** │ **Token**                       │ **Why**                                   │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│ `scripts/hooks/handlers/Stop/05_intent_without_action_async.py`     │ 44       │ `/opt/homebrew/bin/python3`     │ in a comment:                             │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│                                                                     │          │                                 │ `PYTHON = AI_PYTHON  # was hardcoded ...` │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│                                                                     │          │                                 │ (already fixed)                           │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│ `scripts/session_mgmt/lib_session_substrate.py`                     │ 193      │ `/opt/homebrew/bin`             │ docstring prose                           │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│ `scripts/cli/fork_into_dir.py`                                      │ 49       │ `/Users/foo/my_project`         │ slug-conversion example in a comment      │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│ `content/ai_context_files/instructions/how_tos/instr_cli_agents.md` │ 154      │ `/Applications/Google\ Chrome…` │ doc example command (macOS-specific by    │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│                                                                     │          │                                 │ nature)                                   │
├─────────────────────────────────────────────────────────────────────┼──────────┼─────────────────────────────────┼───────────────────────────────────────────┤
│ `content/ai_context_files/knowledge/specs/spec_session_identity.md` │ 190, 193 │ `/Users/.../…`                  │ elided example paths in a spec            │
└─────────────────────────────────────────────────────────────────────┴──────────┴─────────────────────────────────┴───────────────────────────────────────────┘