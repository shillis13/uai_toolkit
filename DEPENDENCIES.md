# uai_toolkit — External Dependencies

The complete external-dependency picture for **this** package (the portable kit).
Derived from an AST import scan of `src/uai_toolkit/` (2026-07-15), stdlib + internal
modules filtered, cross-checked against the installed environment.

**The canonical install manifest is `pyproject.toml`** — this file is the
human-readable inventory + the things pip can't express (system binaries, Node,
platform notes, known gaps). Terms: *import-name* is what `import X` uses;
*pip-name* is what you install (`yaml`→`pyyaml`, `PIL`→`pillow`).

## 1. Python packages (all declared in `pyproject.toml`)

Install: `pip install uai-toolkit` (core) or `pip install 'uai-toolkit[full,mcp]'`
for the heavier features. Nothing here is macOS-specific — the toolkit is the
WSL/Windows-portable subset.

| Package | pip name | Tier (`pyproject`) | Why |
|---|---|---|---|
| pyyaml | `pyyaml>=6` | **core** | pervasive — YAML config/content (26 modules) |
| tomli | `tomli; python<3.11` | **core** | `config.toml` on Python < 3.11 (stdlib `tomllib` on 3.11+) |
| psutil | `psutil>=5.9` | `full` | process/session discovery |
| httpx | `httpx>=0.27` | `full` | local-LLM quality gate + session tools |
| websockets | `websockets>=12` | `full` | CDP / live session tooling |
| tqdm | `tqdm>=4` | `full` | progress bars |
| mcp | `mcp>=1.0` | `mcp` | Model Context Protocol SDK (the server surface) |
| jsonschema | `jsonschema>=4` | `mcp` | MCP tool-schema validation |
| pillow | `pillow>=10` | `images` | image-dimension-check hook (guarded lazy import) |
| pytest | `pytest>=7` | `dev` | test runner |

**Added this pass:** `pillow` (`images` extra) — the scan found `from PIL import
Image` in the image-dimension hook, previously undeclared. It's a guarded lazy
import, so without it the hook skips the check instead of crashing.

## 2. System binaries (not pip; OS package manager)

Needed by the vendored tools that shell out. Install via Homebrew (mac) / apt (WSL):

| Tool | Purpose | WSL/Windows |
|---|---|---|
| `zellij` / `tmux` | terminal-multiplexer substrate | work on WSL |
| `ripgrep` (`rg`) | fast search | `apt install ripgrep` |
| `git` | version control | native everywhere |
| `node` + `npm` | build/run the vendored `uai_app/` Electron monorepo | native everywhere |

## 3. Node (the `uai_app/` sibling)

The repo also vendors the UAI Electron app at repo-root `uai_app/` (materialized
source, not Python package-data). Its JS dependencies live in its own
`package.json` files — restore with `npm ci`. Not part of the Python install.

## 4. Known gaps — unvendored internal imports (portability TODO)

Two lazy imports reference internal modules that the materialize keystone does NOT
vendor into the toolkit, so they'd fail **if that code path runs** on a fresh box.
They're lazy (inside functions), so import-time is safe, but the feature breaks:

| Import | Where | Status |
|---|---|---|
| `lllm_prompt` | `jsonl/summarizer.py` (local-LLM summary path) | not vendored, not a pip pkg — vendor it or guard the feature |
| `lib_branch_index` | `jsonl/read_jsonl.py` (devTree branch index) | not vendored — vendor it or guard the feature |

These are tracked here rather than silently shipped as if resolvable. Fix =
add them to the materialize manifest (`MODULES`) or gate the calling feature
behind a capability check.
