---
name: feedback_file_naming_convention
description: Script names must be self-describing — kind-prefix (lib_/_) + domain
  + specialization, never platform-only or dir-dependent
status: active
---

A script's name must convey WHAT it is and WHAT it's for on its own — it must not lean on its directory for context, must not read like an executable when it's a library, and must not encode only a platform/variant.

**Why:** PianoMan rejected BOTH `codex.py` and `codex_cli.py` for the jsonl platform adapters (2026-07-12): (1) they name only the platform, giving zero hint of purpose — the exact failing of the original; (2) they rely on the `platform_adapters/` dir to supply the missing context; (3) a bare `name.py` reads like an executable when it's actually an imported library.

**How to apply:**
- **Kind prefix:** `lib_*.py` for a library (imported), `_*.py` for internal-execution-only, plain `name.py` ONLY for a genuine CLI/executable. (Verify by shebang / `__main__` / exec-bit / how it's consumed.)
- **Self-describe:** encode domain AND specialization. `lib_jsonl_codex.py` = a LIBRARY, for JSONL, the CODEX-platform variant. Likewise `lib_jsonl_claude.py`, `lib_jsonl_gemini.py`, `lib_jsonl_agy.py`.
- A reader must not have to open the file or know its directory to learn what it is.

Concrete pending application: rename `scripts/jsonl/platform_adapters/{claude,codex,gemini,agy}.py` → `lib_jsonl_<platform>.py` (update `platform_adapters/__init__.py` registry + `read_jsonl.py` import), folded into the multi-platform engine refactor. Applies to all new scripts too. See [[feedback_define_terms_before_use]].
