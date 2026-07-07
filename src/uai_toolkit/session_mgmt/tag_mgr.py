#!/usr/bin/env python3
"""
tag_mgr.py — Unified tag management across todos, sessions, and briefs.

No args enters REPL mode. With args, runs as one-shot CLI.

Currently implemented backends:
- todos: .tag marker files in todo directories
- sessions: (stub — no tag column in session store yet)
- briefs: (stub — no structured tag metadata yet)
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

# Path setup
_SCRIPT_DIR = Path(__file__).resolve().parent
_AI_SCRIPTS = _SCRIPT_DIR.parent
for _p in (str(_AI_SCRIPTS), str(Path.home() / "bin/all_languages/python/src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from uai_toolkit.common_utils.standard_colors import c, bold, dim, heading, format_help, colors_enabled, set_color_mode
except ImportError:
    try:
        import importlib.util as _ilu
        _sc_path = _AI_SCRIPTS / "utils" / "standard_colors.py"
        if _sc_path.exists():
            _spec = _ilu.spec_from_file_location("standard_colors", str(_sc_path))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            c, bold, dim, heading = _mod.c, _mod.bold, _mod.dim, _mod.heading
            format_help, colors_enabled, set_color_mode = _mod.format_help, _mod.colors_enabled, _mod.set_color_mode
        else:
            raise ImportError
    except Exception:
        def c(text, *a, **k): return str(text)
        def bold(text): return str(text)
        def dim(text): return str(text)
        def heading(text): return str(text)
        def format_help(text): return str(text)
        def colors_enabled(): return False
        def set_color_mode(v): pass

VERSION = "1.0.0"

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
TODO_ROOT = Path(os.environ.get("TODO_ROOT", AI_ROOT / "ai_general/work/todos"))
HISTORY_FILE = Path.home() / ".tag_mgr_history"


# --- Todo Tag Backend ---

def _scan_todo_tags() -> dict[str, list[str]]:
    """Scan all todo dirs for .tag files. Returns {tag_name: [todo_ids]}."""
    tags: dict[str, list[str]] = {}
    if not TODO_ROOT.exists():
        return tags
    for todo_dir in sorted(TODO_ROOT.rglob("*.tag")):
        tag_name = todo_dir.stem
        todo_id = todo_dir.parent.name
        tags.setdefault(tag_name, []).append(todo_id)
    return tags


def _get_todo_tags(todo_id: str) -> list[str]:
    """Get tags for a specific todo."""
    todo_dir = _resolve_todo(todo_id)
    if not todo_dir:
        return []
    return sorted(f.stem for f in todo_dir.glob("*.tag"))


def _add_todo_tag(todo_id: str, tag_name: str) -> bool:
    """Add a tag to a todo. Returns True if new."""
    todo_dir = _resolve_todo(todo_id)
    if not todo_dir:
        return False
    tag_file = todo_dir / "{}.tag".format(tag_name)
    if tag_file.exists():
        return False
    tag_file.touch()
    return True


def _remove_todo_tag(todo_id: str, tag_name: str) -> bool:
    """Remove a tag from a todo. Returns True if removed."""
    todo_dir = _resolve_todo(todo_id)
    if not todo_dir:
        return False
    tag_file = todo_dir / "{}.tag".format(tag_name)
    if not tag_file.exists():
        return False
    tag_file.unlink()
    return True


def _resolve_todo(identifier: str) -> Optional[Path]:
    """Resolve a todo identifier to its directory."""
    # Direct name
    candidate = TODO_ROOT / identifier
    if candidate.is_dir():
        return candidate
    # Recursive search
    for d in TODO_ROOT.rglob(identifier):
        if d.is_dir():
            return d
    # Partial match
    for d in TODO_ROOT.iterdir():
        if d.is_dir() and identifier in d.name:
            return d
    return None


def _rename_todo_tag(old_name: str, new_name: str) -> int:
    """Rename a tag across all todos. Returns count of renames."""
    count = 0
    for tag_file in TODO_ROOT.rglob("{}.tag".format(old_name)):
        new_file = tag_file.parent / "{}.tag".format(new_name)
        tag_file.rename(new_file)
        count += 1
    return count


# --- Commands ---

def cmd_list(args: list[str]) -> str:
    """List all tags with usage counts."""
    tags = _scan_todo_tags()
    if not tags:
        return dim("No tags found.")

    sort_by = "name"
    for a in args:
        if a in ("--by-count", "-c"):
            sort_by = "count"

    if sort_by == "count":
        sorted_tags = sorted(tags.items(), key=lambda x: len(x[1]), reverse=True)
    else:
        sorted_tags = sorted(tags.items())

    lines = [c("Tags ({}):\n".format(len(sorted_tags)), "heading")]
    for tag_name, todo_ids in sorted_tags:
        lines.append("  {:<24s} {}".format(
            c(tag_name, "cyan"),
            c("{} todos".format(len(todo_ids)), "muted")))
    return "\n".join(lines)


def cmd_show(args: list[str]) -> str:
    """Show which todos have a specific tag."""
    if not args:
        return c("Usage: show <tag_name>", "error")
    tag_name = args[0]
    tags = _scan_todo_tags()
    if tag_name not in tags:
        return c("Tag not found: {}".format(tag_name), "error")

    todo_ids = tags[tag_name]
    lines = [c("Tag: {} ({} todos)\n".format(tag_name, len(todo_ids)), "heading")]
    for tid in sorted(todo_ids):
        lines.append("  {}".format(c(tid, "cyan")))
    return "\n".join(lines)


def cmd_tags_for(args: list[str]) -> str:
    """Show tags for a specific todo."""
    if not args:
        return c("Usage: tags-for <todo_id>", "error")
    todo_id = args[0]
    tags = _get_todo_tags(todo_id)
    if not tags:
        todo_dir = _resolve_todo(todo_id)
        if not todo_dir:
            return c("Todo not found: {}".format(todo_id), "error")
        return dim("No tags on {}".format(todo_id))

    lines = [c("Tags on {}:\n".format(todo_id), "heading")]
    for tag in tags:
        lines.append("  {}".format(c(tag, "cyan")))
    return "\n".join(lines)


def cmd_add(args: list[str]) -> str:
    """Add a tag to a todo."""
    if len(args) < 2:
        return c("Usage: add <todo_id> <tag_name>", "error")
    todo_id, tag_name = args[0], args[1]
    todo_dir = _resolve_todo(todo_id)
    if not todo_dir:
        return c("Todo not found: {}".format(todo_id), "error")
    if _add_todo_tag(todo_dir.name, tag_name):
        return c("+ {} on {}".format(tag_name, todo_dir.name), "success")
    return dim("Already tagged: {} on {}".format(tag_name, todo_dir.name))


def cmd_remove(args: list[str]) -> str:
    """Remove a tag from a todo."""
    if len(args) < 2:
        return c("Usage: remove <todo_id> <tag_name>", "error")
    todo_id, tag_name = args[0], args[1]
    todo_dir = _resolve_todo(todo_id)
    if not todo_dir:
        return c("Todo not found: {}".format(todo_id), "error")
    if _remove_todo_tag(todo_dir.name, tag_name):
        return c("- {} from {}".format(tag_name, todo_dir.name), "warning")
    return dim("Not tagged: {} on {}".format(tag_name, todo_dir.name))


def cmd_rename(args: list[str]) -> str:
    """Rename a tag across all todos."""
    if len(args) < 2:
        return c("Usage: rename <old_tag> <new_tag>", "error")
    old_name, new_name = args[0], args[1]
    count = _rename_todo_tag(old_name, new_name)
    if count:
        return c("Renamed '{}' -> '{}' on {} todos".format(old_name, new_name, count), "success")
    return dim("Tag '{}' not found on any todos".format(old_name))


def cmd_merge(args: list[str]) -> str:
    """Merge one tag into another (rename + deduplicate)."""
    if len(args) < 2:
        return c("Usage: merge <source_tag> <target_tag>", "error")
    source, target = args[0], args[1]
    tags = _scan_todo_tags()
    if source not in tags:
        return c("Source tag not found: {}".format(source), "error")

    count = 0
    for todo_id in tags[source]:
        todo_dir = _resolve_todo(todo_id)
        if not todo_dir:
            continue
        # Add target if not present
        target_file = todo_dir / "{}.tag".format(target)
        if not target_file.exists():
            target_file.touch()
        # Remove source
        source_file = todo_dir / "{}.tag".format(source)
        if source_file.exists():
            source_file.unlink()
            count += 1

    return c("Merged '{}' into '{}' ({} todos updated)".format(source, target, count), "success")


def cmd_status(args: list[str]) -> str:
    """Summary statistics."""
    tags = _scan_todo_tags()
    total_tags = len(tags)
    total_assignments = sum(len(ids) for ids in tags.values())

    # Find orphan tags (only on completed/trashed todos)
    lines = [
        c("Tag System Status:\n", "heading"),
        "  {}  {}".format(c("Unique tags:    ", "label"), c(str(total_tags), "bright_green")),
        "  {}  {}".format(c("Assignments:    ", "label"), c(str(total_assignments), "bright_green")),
        "  {}  {}".format(c("Source:         ", "label"), dim("todo .tag files ({})".format(TODO_ROOT))),
        "",
        dim("  Session/brief tag backends not yet implemented."),
    ]
    return "\n".join(lines)


def cmd_search(args: list[str]) -> str:
    """Search tags by substring."""
    if not args:
        return c("Usage: search <pattern>", "error")
    pattern = args[0].lower()
    tags = _scan_todo_tags()
    matches = {k: v for k, v in tags.items() if pattern in k.lower()}
    if not matches:
        return dim("No tags matching '{}'".format(pattern))
    lines = [c("Tags matching '{}' ({}):\n".format(pattern, len(matches)), "heading")]
    for tag_name, todo_ids in sorted(matches.items()):
        lines.append("  {:<24s} {}".format(
            c(tag_name, "cyan"), c("{} todos".format(len(todo_ids)), "muted")))
    return "\n".join(lines)


# --- Help ---

def _brief_help() -> str:
    def _cmd(name, desc):
        return "  {:<30} {}".format(c(name, "command"), c(desc, "muted"))

    lines = [c("Tag Manager REPL Commands:", "heading")]
    lines.append("")
    lines.append(c("Browse:", "subheading"))
    lines.append(_cmd("list [--by-count]", "All tags with usage counts"))
    lines.append(_cmd("show <tag>", "Todos with a specific tag"))
    lines.append(_cmd("tags-for <todo>", "Tags on a specific todo"))
    lines.append(_cmd("search <pattern>", "Search tags by substring"))
    lines.append(_cmd("status", "Summary statistics"))
    lines.append("")
    lines.append(c("Modify:", "subheading"))
    lines.append(_cmd("add <todo> <tag>", "Tag a todo"))
    lines.append(_cmd("remove <todo> <tag>", "Remove tag from todo"))
    lines.append(_cmd("rename <old> <new>", "Rename tag everywhere"))
    lines.append(_cmd("merge <source> <target>", "Merge source into target"))
    lines.append("")
    lines.append(_cmd("help", "This help"))
    lines.append(_cmd("quit / q", "Exit"))
    return "\n".join(lines)


_HELP_RAW = """\
tag_mgr -- Unified tag management (v{ver})

Usage:
    tag_mgr                          Interactive REPL mode
    tag_mgr <command> [args...]      One-shot CLI mode

Commands -- browse:
    list [--by-count]       All tags with usage counts
    show <tag>              Todos with a specific tag
    tags-for <todo>         Tags on a specific todo
    search <pattern>        Search tags by substring
    status                  Summary statistics

Commands -- modify:
    add <todo> <tag>        Tag a todo
    remove <todo> <tag>     Remove tag from todo
    rename <old> <new>      Rename tag across all todos
    merge <source> <target> Merge source tag into target

Options:
    --json            Structured JSON output
    --no-color        Disable colors

Backends:
    Currently: todo .tag files
    Planned: session tags, brief tags
""".format(ver=VERSION)


# --- Command Dispatch ---

def run_command(line: str, interactive: bool = True) -> str | None:
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return c("Parse error: {}".format(e), "error")

    if not parts:
        return None

    cmd = parts[0].lower()
    args = parts[1:]

    ALIASES = {"ls": "list", "l": "list", "s": "status", "find": "search"}
    cmd = ALIASES.get(cmd, cmd)

    if cmd == "list":
        return cmd_list(args)
    elif cmd == "show":
        return cmd_show(args)
    elif cmd in ("tags-for", "tags_for", "tagsfor"):
        return cmd_tags_for(args)
    elif cmd == "search":
        return cmd_search(args)
    elif cmd == "status":
        return cmd_status(args)
    elif cmd == "add":
        return cmd_add(args)
    elif cmd in ("remove", "rm"):
        return cmd_remove(args)
    elif cmd == "rename":
        return cmd_rename(args)
    elif cmd == "merge":
        return cmd_merge(args)
    elif cmd == "help":
        return _brief_help()
    elif cmd in ("quit", "exit", "q") and interactive:
        return None
    else:
        return c("Unknown command: {}. Try 'help'.".format(cmd), "warning")


# --- REPL ---

def repl() -> None:
    from uai_toolkit.common_utils.lib_readline import setup_readline
    setup_readline(history_file=HISTORY_FILE, history_length=200)

    print("{} -- type 'help' for commands, 'q' to quit".format(bold("Tag Manager REPL")))
    print(run_command("status"))
    print()

    while True:
        try:
            prompt = "{}{}{}> ".format(dim("tag"), c(":", "cyan"), dim(""))
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break

        result = run_command(line, interactive=True)
        if result:
            print(result)


# --- JSON Mode ---

def run_json_command(args: list[str]) -> None:
    if not args:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    cmd = args[0].lower()
    cmd_args = args[1:]

    try:
        if cmd == "list":
            tags = _scan_todo_tags()
            result = {"tags": {k: len(v) for k, v in sorted(tags.items())}, "count": len(tags)}
        elif cmd == "show":
            tag_name = cmd_args[0] if cmd_args else ""
            tags = _scan_todo_tags()
            todos = tags.get(tag_name, [])
            result = {"tag": tag_name, "todos": sorted(todos), "count": len(todos)}
        elif cmd in ("tags-for", "tags_for"):
            todo_id = cmd_args[0] if cmd_args else ""
            result = {"todo": todo_id, "tags": _get_todo_tags(todo_id)}
        elif cmd == "search":
            pattern = (cmd_args[0] if cmd_args else "").lower()
            tags = _scan_todo_tags()
            matches = {k: len(v) for k, v in tags.items() if pattern in k.lower()}
            result = {"pattern": pattern, "matches": matches, "count": len(matches)}
        elif cmd == "status":
            tags = _scan_todo_tags()
            result = {"unique_tags": len(tags), "total_assignments": sum(len(v) for v in tags.values())}
        elif cmd == "add":
            if len(cmd_args) < 2:
                result = {"error": "Usage: add <todo> <tag>"}
            else:
                added = _add_todo_tag(cmd_args[0], cmd_args[1])
                result = {"success": True, "new": added, "todo": cmd_args[0], "tag": cmd_args[1]}
        elif cmd in ("remove", "rm"):
            if len(cmd_args) < 2:
                result = {"error": "Usage: remove <todo> <tag>"}
            else:
                removed = _remove_todo_tag(cmd_args[0], cmd_args[1])
                result = {"success": True, "removed": removed, "todo": cmd_args[0], "tag": cmd_args[1]}
        elif cmd == "rename":
            if len(cmd_args) < 2:
                result = {"error": "Usage: rename <old> <new>"}
            else:
                count = _rename_todo_tag(cmd_args[0], cmd_args[1])
                result = {"success": True, "old": cmd_args[0], "new": cmd_args[1], "count": count}
        elif cmd == "merge":
            if len(cmd_args) < 2:
                result = {"error": "Usage: merge <source> <target>"}
            else:
                # Inline merge for JSON mode
                tags = _scan_todo_tags()
                count = 0
                if cmd_args[0] in tags:
                    for tid in tags[cmd_args[0]]:
                        td = _resolve_todo(tid)
                        if td:
                            (td / "{}.tag".format(cmd_args[1])).touch()
                            sf = td / "{}.tag".format(cmd_args[0])
                            if sf.exists():
                                sf.unlink()
                                count += 1
                result = {"success": True, "source": cmd_args[0], "target": cmd_args[1], "count": count}
        else:
            result = {"error": "Unknown command: {}".format(cmd)}

        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


# --- Main ---

def main() -> None:
    args = sys.argv[1:]
    json_mode = False

    i = 0
    while i < len(args):
        if args[i] == "--json":
            json_mode = True
            args = args[:i] + args[i+1:]
        elif args[i] == "--no-color":
            set_color_mode(False)
            args = args[:i] + args[i+1:]
        elif args[i] in ("--help", "-h"):
            print(format_help(_HELP_RAW))
            sys.exit(0)
        elif args[i] == "--version":
            print("tag_mgr v{}".format(VERSION))
            sys.exit(0)
        else:
            i += 1

    if json_mode:
        set_color_mode(False)
        run_json_command(args)
        return

    if not args:
        repl()
        return

    command_line = " ".join(shlex.quote(a) for a in args)
    result = run_command(command_line, interactive=False)
    if result:
        print(result)


if __name__ == "__main__":
    main()
