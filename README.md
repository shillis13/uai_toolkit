# uai_toolkit

Unified AI toolkit — portable scaffolding and CLI-agent utilities with a largely AI-platform-agnostic design.

Package name: `ai_toolkit`.

## Install

```bash
pip install -e .
# or, later: pipx install ai-toolkit
```

For instance-specific state, point `AI_ROOT` at your writable instance and customize `config.toml`:

```bash
cp config.example.toml "$AI_ROOT/config.toml"
```

## Tools

- `read_jsonl` — read/filter/inspect Claude/Codex/Gemini session transcripts.

## Layout

- `src/ai_toolkit/` — portable package code.
- `$AI_ROOT/` — writable local instance: config, logs, overrides. Never overwritten on upgrade.

See `DESIGN.md` for architecture and the porting roadmap. Requires Python >= 3.10.
