"""`ai-toolkit` command — install/configure the toolkit instance.

Subcommands:
  init   Create the AI_ROOT instance, write config.toml, and wire the
         file_access anti-clobber hooks into Claude Code settings.json.

No native installer needed: `pipx install ai-toolkit` puts the tools on PATH,
then `ai-toolkit init` makes them live. Idempotent and --dry-run-able.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ai_toolkit import __version__, paths

# Desired Claude Code hook wiring: (event, matcher, command).
HOOK_WIRING = [
    ("PreToolUse", "Edit|Write|MultiEdit", "ai-fa-check-write"),
    ("PostToolUse", "Read", "ai-fa-track-read"),
    ("PostToolUse", "Edit|Write|MultiEdit", "ai-fa-track-write"),
]

INSTANCE_SUBDIRS = ["data", "data/file_access", "logs"]


# ---------------------------------------------------------------------------
# settings.json hook merge (idempotent)
# ---------------------------------------------------------------------------

def _hook_present(entries: list, matcher: str, command: str) -> bool:
    for entry in entries:
        if entry.get("matcher") != matcher:
            continue
        for h in entry.get("hooks", []):
            if h.get("command") == command:
                return True
    return False


def merge_hooks(settings: dict) -> tuple[dict, list[str]]:
    """Add our hook wiring to a settings dict if absent. Returns (settings, added)."""
    hooks = settings.setdefault("hooks", {})
    added = []
    for event, matcher, command in HOOK_WIRING:
        entries = hooks.setdefault(event, [])
        if _hook_present(entries, matcher, command):
            continue
        entries.append({
            "matcher": matcher,
            "hooks": [{"type": "command", "command": command}],
        })
        added.append(f"{event}[{matcher}] -> {command}")
    return settings, added


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    dry = args.dry_run
    root = Path(args.ai_root).expanduser() if args.ai_root else paths.ai_root()
    settings_path = (
        Path(args.settings).expanduser() if args.settings
        else Path.home() / ".claude" / "settings.json"
    )
    tag = "[dry-run] would " if dry else ""

    print(f"ai-toolkit {__version__} init")
    print(f"  AI_ROOT:  {root}")
    print(f"  settings: {settings_path}")

    # 1) instance dirs
    for sub in [""] + INSTANCE_SUBDIRS:
        d = root / sub if sub else root
        if d.is_dir():
            continue
        print(f"  {tag}create dir: {d}")
        if not dry:
            d.mkdir(parents=True, exist_ok=True)

    # 2) config.toml from packaged example (never overwrite an existing one)
    cfg = root / "config.toml"
    if cfg.exists():
        print(f"  config.toml exists — leaving as-is: {cfg}")
    else:
        example = _packaged_example()
        if example and example.is_file():
            print(f"  {tag}write config.toml from example")
            if not dry:
                shutil.copyfile(example, cfg)
        else:
            print("  ! packaged config.example.toml not found; skipping config")

    # 3) hook wiring (idempotent merge)
    settings = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text() or "{}")
        except json.JSONDecodeError:
            print(f"  ! {settings_path} is not valid JSON — refusing to touch it")
            return 1
    settings, added = merge_hooks(settings)
    if not added:
        print("  hooks already wired — nothing to add")
    else:
        for a in added:
            print(f"  {tag}wire hook: {a}")
        if not dry:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    print("done." if not dry else "dry-run complete (no changes written).")
    return 0


def _packaged_example() -> Path | None:
    """Locate config.example.toml shipped alongside the package, if present."""
    # repo layout: <root>/config.example.toml, two parents up from this file's package
    for cand in (
        Path(__file__).resolve().parents[2] / "config.example.toml",  # src/ layout
        Path(__file__).resolve().parent / "config.example.toml",
    ):
        if cand.is_file():
            return cand
    return None


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-toolkit", description=__doc__)
    parser.add_argument("--version", action="version", version=f"ai-toolkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create AI_ROOT instance + wire hooks")
    p_init.add_argument("--ai-root", help="Instance root (default: $AI_ROOT / discovery)")
    p_init.add_argument("--settings", help="Claude settings.json (default: ~/.claude/settings.json)")
    p_init.add_argument("--dry-run", action="store_true", help="Show actions without writing")
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
