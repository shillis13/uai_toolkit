#!/usr/bin/env python3
"""prompt_library.py — the prompt library (repository) CRUD/search logic.

Single source of truth for saved, reusable prompts. The UAI app's prompt box and
an MCP tool are both THIN WRAPPERS over this script (logic-in-scripts principle);
neither owns the data. A library prompt is pure CONTENT — it has no notion of
timing or delivery (that is a scheduled_prompt's concern, which may *wrap* one).

Store: ai_general/data/prompt_library/prompts.yml — human-readable YAML, one entry
per prompt, bodies as block scalars, git-tracked and hand-editable.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # ai_general/scripts
try:
    from uai_toolkit.common_utils.standard_colors import c, format_help, colors_enabled  # noqa: E402
except Exception:  # pragma: no cover — coloring is a nicety, never a hard dep
    def c(t, *_a):  # type: ignore
        return t
    def format_help(t):  # type: ignore
        return t
    def colors_enabled():  # type: ignore
        return False

try:
    import yaml
except ImportError:
    sys.stderr.write(f"[{datetime.now().isoformat(timespec='seconds')}] prompt_library ERROR: "
                     "PyYAML is required (pip install pyyaml)\n")
    sys.exit(2)

# Store at ai_general/data/prompt_library/prompts.yml, resolved relative to this
# script (scripts/prompts/prompt_library.py) so the caller's cwd never matters.
AI_GENERAL = Path(__file__).resolve().parents[2]
STORE = AI_GENERAL / "data" / "prompt_library" / "prompts.yml"

MODES = ("list", "get", "save", "update", "delete")


def _now_local() -> str:
    """Local-time ISO timestamp (no tz suffix) — the store is human-facing and the
    workspace convention is local time for authored/displayed files."""
    return datetime.now().isoformat(timespec="seconds")


def _fail(args, msg: str) -> int:
    """Two-channel failure: stderr evidence (timestamped) + JSON/plain surface. The
    nonzero exit (the indicator) is returned to main()."""
    sys.stderr.write(f"[{_now_local()}] prompt_library ERROR: {msg}\n")
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error": msg}))
    return 1


# Dump multi-line strings as `|` block scalars so bodies stay readable in the file.
def _str_representer(dumper: "yaml.Dumper", data: str):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_representer)


def load() -> list[dict]:
    if not STORE.exists():
        return []
    with STORE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    prompts = data.get("prompts") if isinstance(data, dict) else None
    return prompts if isinstance(prompts, list) else []


def save_all(prompts: list[dict]) -> None:
    # The script owns its store directory; create it on first save.
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", encoding="utf-8") as fh:
        fh.write("# Prompt library — reusable prompts (content only; no timing/delivery).\n")
        fh.write("# Managed by scripts/prompts/prompt_library.py; hand-editable.\n")
        yaml.dump({"prompts": prompts}, fh, allow_unicode=True, sort_keys=False, width=100)


def _gen_id() -> str:
    return "sp_" + uuid.uuid4().hex[:8]


def _read_body(args) -> str | None:
    if getattr(args, "body_file", None):
        if args.body_file == "-":
            return sys.stdin.read()
        return Path(args.body_file).read_text(encoding="utf-8")
    return getattr(args, "body", None)


def _order(prompts: list[dict]) -> list[dict]:
    """Newest first by created; stable for entries without a timestamp."""
    return sorted(prompts, key=lambda p: str(p.get("created", "")), reverse=True)


def _emit(args, payload: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload))
        return
    prompts = payload.get("prompts")
    if prompts is not None:
        if not prompts:
            print("(no saved prompts)")
        for p in prompts:
            tag = f"  [{p['tag']}]" if p.get("tag") else ""
            print(f"{p['id']}  {p.get('title', '(untitled)')}{tag}")
            print(f"    {' '.join(str(p.get('body', '')).split())[:80]}")
    elif payload.get("prompt"):
        p = payload["prompt"]
        print(f"{p['id']}  {p.get('title', '(untitled)')}" + (f"  [{p['tag']}]" if p.get("tag") else ""))
        print(p.get("body", ""))


def do_list(args) -> int:
    prompts = _order(load())
    if args.tag:
        prompts = [p for p in prompts if (p.get("tag") or "") == args.tag]
    if args.search:
        q = args.search.lower()
        prompts = [p for p in prompts
                   if q in (f"{p.get('title', '')} {p.get('body', '')} {p.get('tag') or ''}").lower()]
    _emit(args, {"ok": True, "prompts": prompts})
    return 0


def do_get(args) -> int:
    if not args.id:
        return _fail(args, "get needs an id")
    p = next((x for x in load() if x.get("id") == args.id), None)
    if not p:
        return _fail(args, f"no prompt with id {args.id}")
    _emit(args, {"ok": True, "prompt": p})
    return 0


def do_save(args) -> int:
    if not args.title or not args.title.strip():
        return _fail(args, "save needs --title")
    body = _read_body(args)
    if body is None or not body.strip():
        return _fail(args, "save needs a body (--body or --body-file)")
    prompts = load()
    entry = {"id": _gen_id(), "title": args.title.strip(), "created": _now_local(), "body": body}
    if args.tag:
        entry["tag"] = args.tag.strip()
    prompts.append(entry)
    save_all(prompts)
    _emit(args, {"ok": True, "prompts": _order(prompts), "saved": entry["id"]})
    return 0


def do_update(args) -> int:
    if not args.id:
        return _fail(args, "update needs an id")
    prompts = load()
    p = next((x for x in prompts if x.get("id") == args.id), None)
    if not p:
        return _fail(args, f"no prompt with id {args.id}")
    if args.title is not None:
        p["title"] = args.title.strip()
    body = _read_body(args)
    if body is not None:
        p["body"] = body
    if args.clear_tag:
        p.pop("tag", None)
    elif args.tag is not None:
        p["tag"] = args.tag.strip()
    p["updated"] = _now_local()
    save_all(prompts)
    _emit(args, {"ok": True, "prompts": _order(prompts), "updated": args.id})
    return 0


def do_delete(args) -> int:
    if not args.id:
        return _fail(args, "delete needs an id")
    prompts = load()
    remaining = [x for x in prompts if x.get("id") != args.id]
    if len(remaining) == len(prompts):
        return _fail(args, f"no prompt with id {args.id}")
    save_all(remaining)
    _emit(args, {"ok": True, "prompts": _order(remaining), "deleted": args.id})
    return 0


_DISPATCH = {"list": do_list, "get": do_get, "save": do_save, "update": do_update, "delete": do_delete}

_DESC = (
    "The prompt library — reusable prompts (content only; no timing/delivery). Store:\n"
    "ai_general/data/prompt_library/prompts.yml (human-readable, hand-editable).\n\n"
    "Modes (select with --mode; default list) — ALL flags documented here, there is no\n"
    "subcommand help and no REPL:\n"
    "  list     print prompts newest-first; narrow with --tag / --search\n"
    "  get      print one prompt by ID\n"
    "  save     add a prompt: --title (required), body via --body or --body-file, --tag\n"
    "  update   change a prompt by ID: any of --title/--body/--body-file/--tag/--clear-tag\n"
    "  delete   remove a prompt by ID"
)
_EPILOG = (
    "Examples:\n"
    "  prompt_library.py --mode list --json\n"
    "  prompt_library.py --mode list --search standup\n"
    "  prompt_library.py --mode save --title Standup --tag daily --body 'What did you ship?'\n"
    "  git log | prompt_library.py --mode save --title 'Log' --body-file -\n"
    "  prompt_library.py --mode get sp_1a2b3c4d\n"
    "  prompt_library.py --mode delete sp_1a2b3c4d"
)


class _ColorHelp(argparse.RawDescriptionHelpFormatter):
    """Reflows the OPTIONS block to the real terminal width (argparse default — width
    is NOT pinned) and colors the whole thing via the shared standard_colors helper."""
    def format_help(self) -> str:
        return format_help(super().format_help())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prompt_library.py", description=_DESC, epilog=_EPILOG, formatter_class=_ColorHelp,
    )
    p.add_argument("id", nargs="?", metavar="ID", help="prompt id (for get/update/delete)")
    p.add_argument("--mode", choices=MODES, default="list", help="operation (default: list)")
    p.add_argument("--title", help="prompt title (save/update)")
    p.add_argument("--body", help="prompt body text (save/update)")
    p.add_argument("--body-file", metavar="PATH", help="read body from a file, or - for stdin")
    p.add_argument("--tag", help="single free-text tag (save/update)")
    p.add_argument("--clear-tag", action="store_true", help="remove the tag (update)")
    p.add_argument("--search", metavar="Q", help="filter list by substring in title/body/tag")
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return _DISPATCH[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
