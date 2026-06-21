# ai-toolkit

Portable AI tooling — jsonl readers, hooks, and platform-agnostic helpers.
Runs on macOS, Linux, and **Windows 11 with native Python (no WSL)**.

## Install

```bash
pipx install ai-toolkit          # or: pip install ai-toolkit
# then point AI_ROOT at your instance and customize config.toml:
cp config.example.toml "$AI_ROOT/config.toml"
```

This installs real per-OS launchers for each tool (e.g. `read_jsonl`) — no
symlinks, no PATH setup, no admin rights.

## Tools

- **`read_jsonl`** — read/filter/inspect Claude/Codex/Gemini session transcripts.

## Layout

- `src/ai_toolkit/` — the package (read-only, upgradeable).
- `$AI_ROOT/` — your writable instance: `config.toml`, logs, overrides. Never overwritten on upgrade.

See `DESIGN.md` for architecture and the porting roadmap. Requires Python ≥ 3.10.
