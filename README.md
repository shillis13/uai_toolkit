# uai_toolkit

Unified AI toolkit — portable scaffolding and CLI-agent utilities with a largely
AI-platform-agnostic design.

Package name: `uai_toolkit`.

## What this is

A working environment for running **AI coding-agent sessions** (Claude Code, Codex,
Gemini, Grok, Antigravity) as long-lived, coordinated processes rather than one-off
chats. It is the portable extract of a larger personal system: roughly 300 Python
modules across 28 top-level Python packages, plus shipped knowledge content and an
optional desktop app.

The problems it solves, in the order you tend to hit them:

- **Reading what an agent did.** Every CLI writes its transcript in its own JSONL
  dialect. `read_jsonl` and the `j*` tools parse all five behind one interface.
- **Keeping many sessions straight.** A session registry, terminal-multiplexer
  substrate, identity/tracking IDs, and status reporting, so a dozen concurrent
  agents remain individually addressable.
- **Letting sessions talk to each other.** A durable inbox, broadcasts, prompt
  delivery, and callbacks — agents coordinate without a human relaying messages.
- **Governing agent behavior.** Event hooks fire on the CLI's lifecycle (before a
  tool runs, when a session stops) to block unsafe edits, record telemetry, and
  enforce project rules.
- **Not losing context.** Handoff briefs, transcript condensation, memory and
  history search, and context offload for sessions approaching their limit.
- **Tracking the work.** Todos, notes, a prompt library, and per-work-item state
  shared across sessions.

The core is plain Python modules and CLIs. It needs no hosted service or always-on
daemon; state lives in files under your own `AI_ROOT`. The optional Electron app is
a separate Node process.

## Install

```bash
pip install -e .
# or, later: pipx install uai-toolkit
```

Optional extras: `pip install -e '.[full,mcp]'` — see `DEPENDENCIES.md` for what each
one adds. Requires Python >= 3.10.

For instance-specific state, point `AI_ROOT` at your writable instance and customize `config.toml`:

```bash
cp config.example.toml "$AI_ROOT/config.toml"
```

## Commands

| Command | Purpose |
|---|---|
| `uai-toolkit` | install/initialize an `AI_ROOT`, seed content, wire hooks and MCP servers |
| `read_jsonl` | read, filter, and inspect agent session transcripts |
| `jcat` `jgrep` `jhead` `jtail` `jwc` `jfmt` | the familiar text tools, but JSONL-aware |
| `uai-mcp-knowledge` | MCP server: guidance, memory, history, and transcript search |
| `uai-mcp-workflow` | MCP server: todos, notes, dev-trees, prompt library |
| `ai-fa-track-read` `ai-fa-track-write` `ai-fa-check-write` | hook handlers that stop one session from clobbering another's edits |

## What's inside

| Area | Package/module | What it does |
|---|---|---|
| Transcripts | `jsonl` | one reader for Claude/Codex/Gemini/Grok/Antigravity (`agy`) formats, plus archive and search helpers |
| Sessions | `session_mgmt`, `cli`, `session_bounce` | launch, register, attach, fork, resume, and restart agent sessions |
| Coordination | `messages`, `callbacks`, `prompting`, `coordination` | inboxes, broadcasts, prompt delivery, busy detection, activity feed |
| Governance | `hooks`, `file_access`, `audit`, `git_guardian` | lifecycle event handlers, anti-clobber tracking, audit log, gated git operations |
| Knowledge | `guidance`, `memory`, `history`, `context_files`, `content` | role/skill guidance, durable memory, searchable history, and the shipped knowledge base |
| Work tracking | `todo`, `notes`, `work`, `prompts`, `devTrees` | todos, notes, work landscape, reusable prompts, git worktree lifecycle |
| MCP servers | `mcp` | shared framework and four server domains; knowledge/workflow are installable commands today, while comms/sessions are staged for the port |
| Utilities | `common_utils`, `text_utils`, `file_utils`, `calc` | logging, colors, text cleaning, markdown table reflow, a calculator engine |
| Portability | `platform_compat`, `paths` | OS-divergence adapters and `AI_ROOT`/`config.toml` resolution |

Also in the repo, but **not** part of the Python install: `uai_app/` — the source of
a desktop Electron app for watching and driving live sessions. Install its Node
dependencies with `npm ci`, then run the app workspace's build script.

## Layout

- `src/uai_toolkit/` — portable package code.
- `src/uai_toolkit/content/` — knowledge base and profiles, copied into `AI_ROOT` at install.
- `uai_app/` — Electron app source (Node toolchain, built separately).
- `tools/` — the materialize step that regenerates this package from its authoritative source.
- `$AI_ROOT/` — writable local instance: config, logs, overrides. Never overwritten on upgrade.

## Status

Portable and installable; the macOS-to-Linux/WSL path is the near-term target.
Native Windows without WSL is a deliberately smaller subset still in progress —
scheduling and some desktop-control features remain macOS-only and degrade rather
than crash elsewhere.

See `DESIGN.md` for architecture and the porting roadmap, `DEPENDENCIES.md` for
external requirements, and `THIRD_PARTY_NOTICES.md` for dependency licenses.
MIT licensed.
