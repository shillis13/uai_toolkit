# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org):
`MAJOR.MINOR.PATCH`.

**How a release is made** — the version lives in exactly one place,
`src/uai_toolkit/__init__.py` (`pyproject.toml` reads it), and a release is a **git
tag named `vX.Y.Z`** on the commit that carries it. GitHub displays those tags as
named versions; a full GitHub Release can be published from the tag separately.

    1. bump __version__ in src/uai_toolkit/__init__.py
    2. add the entry below
    3. commit, then tag:  git tag -a v0.2.0 -m "uai_toolkit 0.2.0"
    4. push both:         git push origin main v0.2.0

While the package is `0.x`, the API may change between minor versions. `1.0.0` is
reserved for the first release validated on the target platform (Linux/WSL) on a
real machine.

---

## 0.2.0 — 2026-07-27

First coherent, installable, documented release. `0.1.0` was the initial scaffold
and was never tagged; everything below accumulated since.

### Added
- **Materialize keystone** (`tools/`) — regenerates the package from the
  authoritative source tree, so drift is a reviewable diff instead of silent rot.
  Includes a report-only `--prune` that finds files whose source was deleted.
- **Per-feature LLM endpoint client** (`llm/`) — six features (`quality_gate`,
  `intent_check`, `session_assess`, `session_summarize`, `consolidation_summary`,
  `mcp_prompt`), each configured independently, supporting OpenAI-compatible and
  Anthropic endpoints with ordered fallback chains. Nothing is configured by
  default, so the package makes no network connections out of the box.
- **MCP servers** — knowledge and workflow ship as console commands; comms and
  sessions are staged. Reasoning tools (`sessions_reason_on_text` / `_on_file` /
  `list_models`) run over a configured endpoint.
- **Transcript tooling** — one reader across Claude, Codex, Gemini, Grok, and
  Antigravity formats, plus the `j*` JSONL command-line tools.
- **Vendored utilities** — `text_utils` (text cleaning, markdown table reflow),
  `calc` (calculator engine), `file_utils`.
- **Licensing and dependency documentation** — `LICENSE` (MIT), declared license
  metadata, `THIRD_PARTY_NOTICES.md`, `DEPENDENCIES.md`.
- **Security questionnaire answers** (`docs/security_questionnaire.md`) with the
  code evidence behind each.
- **Endpoint protocol tests** — real local HTTP servers speaking both the
  Anthropic and OpenAI/Codex wire formats; no network or credentials required.

### Changed
- Version is now single-sourced from `uai_toolkit.__version__`; `pyproject.toml`
  reads it, so packaged metadata and `uai-toolkit --version` cannot drift apart.
- Hook behavior configs (`intent_without_action`, `stop_gate`, `todo_audit`) and
  `declare_stop.config.yml` now ship with the package. Previously absent, which
  left their handlers running with empty policy — and `declare_stop` failing
  outright.

### Fixed
- Path-scrub artifacts: several modules held literal `"$AI_ROOT/..."` strings that
  Python never expands, silently resolving to bogus relative paths. All now go
  through the path resolver.
- An ambient `ANTHROPIC_API_KEY` no longer causes any endpoint to be contacted; an
  endpoint must be named in configuration.

### Known limitations
- **Not yet validated on a real Linux/WSL machine.** The code is portable and the
  test suite passes on macOS; the target-platform run is outstanding.
- Native Windows (without WSL) is a smaller subset still in progress. Scheduling
  and some desktop-control features remain macOS-only and degrade rather than crash.
- The optional Electron app (`uai_app/`) sets `remote-allow-origins: '*'` on its
  local DevTools port — disclosed in the security questionnaire, hardening tracked.
