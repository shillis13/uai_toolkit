#!/usr/bin/env python3
"""
CLI for the guidance/traits system.

Unified get/list commands with color output.

Usage:
    guidance_cli get_context dev                          # auto-resolves: role
    guidance_cli get_context instr_development             # auto-resolves: trait
    guidance_cli get_context ai-comms "operating principles"  # multiple refs
    guidance_cli list_context                              # list all
    guidance_cli list_context --type roles                 # list roles only
    guidance_cli list_context --type traits --category methods
    guidance_cli search "commit conventions" --category knowledge
    guidance_cli how_to "how to delegate work"
    guidance_cli references instr_development
    guidance_cli stale --days 60
    guidance_cli test
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# --- sys.path setup ---
_SCRIPT_DIR = Path(__file__).resolve().parent
AI_ROOT = Path(os.environ.get("AI_ROOT", _SCRIPT_DIR.parents[2]))
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(_SCRIPT_DIR.parent))
from uai_toolkit.paths import AI_SCRIPTS  # noqa: E402
sys.path.insert(0, str(AI_SCRIPTS / "context_files"))
sys.path.insert(0, str(AI_SCRIPTS))

from uai_toolkit.guidance import guidance_lib  # noqa: E402

SESSION_TRAITS = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_traits.py"
BRIEFS_DIR = AI_ROOT / "ai_general" / "data" / "session_briefs"

# --- Color support ---
try:
    from uai_toolkit.common_utils.standard_colors import c, bold, dim, heading
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    def c(text, *_styles):
        return str(text)
    def bold(text):
        return str(text)
    def dim(text):
        return str(text)
    def heading(text):
        return str(text)


def _get_db():
    return guidance_lib.get_db()


def _active_tracking_id():
    return os.environ.get("AI_TRACKING_ID", "").strip()


def _track_session_adopt(name):
    tracking_id = _active_tracking_id()
    if not tracking_id or not SESSION_TRAITS.exists():
        return
    subprocess.run(
        [sys.executable, str(SESSION_TRAITS), "--session", tracking_id, "--json", "adopt", name],
        capture_output=True, text=True, timeout=15,
    )


def _track_session_load(item_type, name):
    tracking_id = _active_tracking_id()
    if not tracking_id or not SESSION_TRAITS.exists():
        return
    subprocess.run(
        [sys.executable, str(SESSION_TRAITS), "--session", tracking_id, "--json", "load", item_type, name],
        capture_output=True, text=True, timeout=15,
    )
    # Clear from pending_context_load — content has been delivered via MCP
    subprocess.run(
        [sys.executable, str(SESSION_TRAITS), "--session", tracking_id, "--json", "unpend", item_type, name],
        capture_output=True, text=True, timeout=10,
    )


def _resolve_brief(ref):
    """Resolve a brief reference to (path, content).

    Briefs are file-based per-session artifacts under data/session_briefs/ — they
    are deliberately NOT in the guidance DB, so get_context resolves them here on
    a registry miss (or when explicitly qualified as 'briefs/<name>'). This is the
    loader avenue: a raw read of a .ref pointer can't see the brief; only this
    resolver turns the name into content.

    Returns (Path, str) or (None, None).
    """
    name = ref.split("/", 1)[1] if ref.startswith(("briefs/", "brief/")) else ref
    if not name or not BRIEFS_DIR.exists():
        return None, None
    matches = list(BRIEFS_DIR.rglob("{}.yml".format(name)))
    if not matches:
        return None, None
    # Deterministic precedence: auto_briefs/ first, then shallowest path.
    matches.sort(key=lambda p: (0 if "auto_briefs" in p.parts else 1, len(p.parts), str(p)))
    path = matches[0]
    try:
        return path, path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None


def _emit_brief(ref, outputs):
    """Resolve+emit a brief, with load tracking. Returns True if found."""
    path, content = _resolve_brief(ref)
    if content is None:
        return False
    outputs.append("# Brief: {}\n\n{}".format(path.stem, content))
    _track_session_load("briefs", path.stem)
    return True


def _normalize_trait_name(identifier, db):
    if db:
        item = guidance_lib.resolve_item(db, identifier)
        if item and item.get("category") and item.get("name"):
            return "{}/{}".format(item["category"], item["name"])
    return guidance_lib.normalize_trait_identifier(identifier)


def _track_knowledge_request(topic, db):
    if not db:
        return
    item = guidance_lib.resolve_item(db, topic)
    if not item:
        return
    composition_type = (item.get("composition_type") or "").lower()
    if composition_type in ("role", "skill", "profile"):
        _track_session_adopt(item["id"])
    elif item.get("category") and item.get("name"):
        _track_session_load("traits", "{}/{}".format(item["category"], item["name"]))


# ── Color formatting helpers ─────────────────────────────────────────

def _colorize_get_output(text, item_type):
    """Add color to get output — titles in heading color, content in default."""
    if not HAS_COLOR or not text:
        return text
    lines = text.split('\n')
    result = []
    for line in lines:
        if line.startswith('# '):
            result.append(c(line, 'heading'))
        elif line.startswith('## '):
            result.append(c(line, 'subheading'))
        elif line.startswith('### '):
            result.append(bold(line))
        elif line.startswith('- **') and '**' in line[4:]:
            # Bold name in list items: - **Name** (id): description
            parts = line.split('**')
            if len(parts) >= 3:
                result.append(parts[0] + c(parts[1], 'cyan') + dim(line[line.index('**', 4) + 2:]))
            else:
                result.append(line)
        elif line.startswith('---'):
            result.append(dim(line))
        elif line.startswith('| ') or line.startswith('|-'):
            result.append(dim(line))
        elif line.startswith('```'):
            result.append(c(line, 'muted'))
        elif line.startswith('> '):
            result.append(c(line, 'yellow'))
        elif line.startswith('**') and line.endswith('**'):
            result.append(bold(line.strip('*')))
        else:
            result.append(line)
    return '\n'.join(result)


def _colorize_list_output(text):
    """Color list output — names in cyan, descriptions dimmed."""
    if not HAS_COLOR or not text:
        return text
    lines = text.split('\n')
    result = []
    for line in lines:
        if line.startswith('# '):
            result.append(c(line, 'heading'))
        elif line.startswith('## '):
            result.append(c(line, 'subheading'))
        elif line.startswith('- **') and '**' in line[4:]:
            parts = line.split('**')
            if len(parts) >= 3:
                name = parts[1]
                rest = line[line.index('**', 4) + 2:]
                # Extract (id) part
                if rest.startswith(' (`') and '`)' in rest:
                    id_end = rest.index('`)') + 2
                    id_part = rest[:id_end]
                    desc = rest[id_end:]
                    result.append('- ' + c(name, 'cyan') + ' ' + dim(id_part) + dim(desc))
                else:
                    result.append('- ' + c(name, 'cyan') + dim(rest))
            else:
                result.append(line)
        else:
            result.append(line)
    return '\n'.join(result)


# ── Unified get_context command ──────────────────────────────────────

def cmd_get_context(args):
    """Load one or more context references. Auto-resolves type via registry.
    The --load level controls reference expansion uniformly for any item type."""
    db = _get_db()
    load = getattr(args, 'load', None) or guidance_lib.LOAD_RECURSIVE
    refs = args.references if hasattr(args, 'references') else [args.name] if hasattr(args, 'name') else []
    seen = set()  # shared across refs so a shared context file loads once
    outputs = []
    for ref in refs:
        # Globals: "globals" loads all, "globals/<name>" loads one
        if ref == "globals" or ref.startswith("globals/"):
            name = ref.split("/", 1)[1] if "/" in ref else None
            result = guidance_lib.handle_get_globals({"name": name}, guidance_lib.get_db())
            outputs.append(result)
            # Track each loaded global
            if name:
                _track_session_load("globals", name)
            else:
                for gf in guidance_lib._list_global_files():
                    _track_session_load("globals", gf.stem)
            continue

        # Briefs: explicit "briefs/<name>" (or "brief/<name>") — file-based,
        # resolved outside the guidance DB.
        if ref.startswith(("briefs/", "brief/")):
            if not _emit_brief(ref, outputs):
                outputs.append("[Not found: {}]".format(ref))
            continue

        _track_knowledge_request(ref, db)
        # Uniform: resolve + walk the reference graph to the requested depth.
        item = guidance_lib.resolve_item(db, ref) if db else None
        if item and item.get("kind") == "brief":
            # Briefs are file-based artifacts. The registry now INDEXES them
            # (kind='brief'), so a bare brief name HITS the registry — but their
            # content lives on disk and must be loaded by the brief resolver, not
            # the composition/graph walker (assemble_context can't read a brief
            # .yml and reports "Trait not found"). Route registry-hit briefs to
            # the same file loader a registry-miss uses. Applies to briefs at the
            # session_briefs/ root as well as auto_briefs/.
            if not _emit_brief(item.get("name") or ref, outputs):
                outputs.append("[Not found: {}]".format(ref))
        elif item:
            outputs.append(guidance_lib.assemble_context(ref, db, load, _seen=seen))
        else:
            # Registry miss — try a file-based brief by name, else knowledge search
            if not _emit_brief(ref, outputs):
                outputs.append(guidance_lib.handle_get_knowledge({"topics": [ref]}, guidance_lib.get_db()))
    print(_colorize_get_output("\n".join(outputs), "context"))


# ── Unified list_context command ─────────────────────────────────────

def cmd_list_context(args):
    """List available context items, optionally filtered by type and category."""
    list_type = getattr(args, 'type', 'all') or 'all'
    category = getattr(args, 'category', None)
    status = getattr(args, 'status', None)

    topic_args = {}
    if category:
        topic_args["category"] = category
    if status:
        topic_args["status"] = status

    # Each handler closes the connection it is given (get_db() returns a *fresh*
    # connection by contract), so every handler call gets its OWN get_db().
    # Sharing one across handlers makes the first handler's close() break the
    # rest with "Cannot operate on a closed database" — which is exactly the bug
    # that left list_context (and the 'all' view) returning partial/empty output.
    if list_type == 'all':
        sections = [
            guidance_lib.handle_list_globals(guidance_lib.get_db()),
            guidance_lib.handle_list_roles(guidance_lib.get_db()),
            guidance_lib.handle_list_skills(guidance_lib.get_db()),
            guidance_lib.handle_list_profiles(guidance_lib.get_db()),
            guidance_lib.handle_list_traits(guidance_lib.get_db(), category=category),
            guidance_lib.handle_get_knowledge_topics(topic_args, guidance_lib.get_db()),
        ]
        output = "\n\n".join(s for s in sections if s.strip())
    elif list_type == 'globals':
        output = guidance_lib.handle_list_globals(guidance_lib.get_db())
    elif list_type == 'roles':
        output = guidance_lib.handle_list_roles(guidance_lib.get_db())
    elif list_type == 'skills':
        output = guidance_lib.handle_list_skills(guidance_lib.get_db())
    elif list_type == 'profiles':
        output = guidance_lib.handle_list_profiles(guidance_lib.get_db())
    elif list_type == 'traits':
        output = guidance_lib.handle_list_traits(guidance_lib.get_db(), category=category)
    elif list_type == 'topics':
        output = guidance_lib.handle_get_knowledge_topics(topic_args, guidance_lib.get_db())
    else:
        print(c("Unknown type: {}. Use: globals, roles, skills, traits, profiles, topics, all".format(list_type), 'error'))
        return

    print(_colorize_list_output(output))


# ── Legacy get/list commands (backward compat) ───────────────────────

def cmd_get(args):
    """Legacy: get <type> <name> — redirects to get_context."""
    args.references = [args.name]
    cmd_get_context(args)


def cmd_list(args):
    """Legacy: list <type> — redirects to list_context."""
    item_type = args.type
    # Map plural list type to list_context type
    type_map = {'roles': 'roles', 'skills': 'skills', 'profiles': 'profiles',
                'traits': 'traits', 'topics': 'topics'}
    args.type = type_map.get(item_type, item_type)
    cmd_list_context(args)


# ── Other commands ───────────────────────────────────────────────────

def cmd_search(args):
    db = _get_db()
    arguments = {}
    if args.query:
        arguments["query"] = args.query
    if args.category:
        arguments["category"] = args.category
    if args.status:
        arguments["status"] = args.status
    if args.item_type:
        arguments["item_type"] = args.item_type
    output = guidance_lib.handle_search(arguments, db)
    print(_colorize_list_output(output))


def cmd_how_to(args):
    db = _get_db()
    output = guidance_lib.handle_how_to({"query": args.query}, db)
    print(_colorize_get_output(output, "knowledge"))


def cmd_references(args):
    db = _get_db()
    output = guidance_lib.handle_get_references({"id": args.id}, db)
    print(_colorize_get_output(output, "references"))


def cmd_stale(args):
    db = _get_db()
    arguments = {}
    if args.days is not None:
        arguments["days"] = args.days
    if args.category:
        arguments["category"] = args.category
    output = guidance_lib.handle_get_stale(arguments, db)
    print(_colorize_list_output(output))


def cmd_remind_me(_args):
    db = _get_db()
    output = guidance_lib.handle_remind_me(db)
    print(_colorize_get_output(output, "reminders"))


def cmd_test(_args):
    db = _get_db()
    print(guidance_lib.handle_test(db))


# ── Legacy subcommand aliases (for MCP compatibility) ────────────────
# The MCP tools call these by the old names via _NAME_MAP in knowledge_guidance.py

def cmd_get_role(args):
    args.type = 'role'
    args.name = args.name
    cmd_get(args)

def cmd_get_skill(args):
    args.type = 'skill'
    cmd_get(args)

def cmd_get_context_file(args):
    args.type = 'context_file'
    args.name = args.identifier
    cmd_get(args)

# Back-compat alias: get_trait -> get_context_file
cmd_get_trait = cmd_get_context_file

def cmd_get_profile(args):
    args.type = 'profile'
    cmd_get(args)

def cmd_get_knowledge_topics(args):
    args.type = 'topics'
    args.status = getattr(args, 'status', '')
    cmd_list(args)

def cmd_get_knowledge(args):
    db = _get_db()
    for topic in args.topics:
        _track_knowledge_request(topic, db)
    output = guidance_lib.handle_get_knowledge({"topics": args.topics}, db)
    print(_colorize_get_output(output, "knowledge"))

def cmd_list_roles(_args):
    _args.type = 'roles'
    _args.category = None
    _args.status = None
    cmd_list(_args)

def cmd_list_skills(_args):
    _args.type = 'skills'
    _args.category = None
    _args.status = None
    cmd_list(_args)

def cmd_list_profiles(_args):
    _args.type = 'profiles'
    _args.category = None
    _args.status = None
    cmd_list(_args)

def cmd_list_traits(args):
    args.type = 'traits'
    args.status = None
    cmd_list(args)


# ── Argument parser ──────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="guidance_cli",
        description="Query traits, roles, skills, profiles, and knowledge.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── get_context <ref> [<ref> ...] ───────────────────────────────
    p = sub.add_parser("get_context", help="Load context by reference (auto-resolves type).")
    p.add_argument("references", nargs="+", help="Context references to load")
    p.add_argument("--load", choices=["none", "direct", "recursive"], default="recursive",
                   help="Reference expansion: none=item only, direct=+one hop, recursive=+full closure (default)")

    # ── list_context [--type TYPE] [--category CAT] ─────────────────
    p = sub.add_parser("list_context", help="List available context items.")
    p.add_argument("--type", default="all",
                   choices=["globals", "roles", "skills", "traits", "profiles", "topics", "all"],
                   help="What to list (default: all)")
    p.add_argument("--category", default=None, help="Filter by category")
    p.add_argument("--status", default=None, help="Filter by status")

    # ── Legacy: get <type> <name> (hidden) ───────────────────────────
    p = sub.add_parser("get", help=argparse.SUPPRESS)
    p.add_argument("type", choices=["role", "skill", "trait", "profile", "knowledge"],
                   help="Item type")
    p.add_argument("name", help="Item name, id, or identifier")

    # ── Legacy: list <type> (hidden) ─────────────────────────────────
    p = sub.add_parser("list", help=argparse.SUPPRESS)
    p.add_argument("type", choices=["globals", "roles", "skills", "traits", "profiles", "topics"],
                   help="What to list")
    p.add_argument("--category", default=None, help="Filter by category")
    p.add_argument("--status", default=None, help="Filter by status")

    # ── search ───────────────────────────────────────────────────────
    p = sub.add_parser("search", help="Search across all items.")
    p.add_argument("query", nargs="?", default="", help="Search text")
    p.add_argument("--category", default="", help="Filter by category")
    p.add_argument("--status", default="", help="Filter by status")
    p.add_argument("--item-type", dest="item_type", default="", help="Filter by type")

    # ── how_to ───────────────────────────────────────────────────────
    p = sub.add_parser("how_to", help="Natural language search.")
    p.add_argument("query", help="Natural language question")

    # ── references ───────────────────────────────────────────────────
    p = sub.add_parser("references", help="Show what an item references and what references it.")
    p.add_argument("id", help="Item id")

    # ── stale ────────────────────────────────────────────────────────
    p = sub.add_parser("stale", help="Find items not updated in N days.")
    p.add_argument("--days", type=int, default=None, help="Days since last update")
    p.add_argument("--category", default="", help="Category filter")

    # ── remind_me ────────────────────────────────────────────────────
    sub.add_parser("remind_me", help="Get configured reminders.")

    # ── test ─────────────────────────────────────────────────────────
    sub.add_parser("test", help="Test connectivity and show registry stats.")

    # ── Legacy subcommands (hidden, for MCP backward compat) ─────────
    p = sub.add_parser("get_role", help=argparse.SUPPRESS)
    p.add_argument("name")
    p = sub.add_parser("get_skill", help=argparse.SUPPRESS)
    p.add_argument("name")
    p = sub.add_parser("get_context_file", help=argparse.SUPPRESS)
    p.add_argument("identifier")
    p = sub.add_parser("get_trait", help=argparse.SUPPRESS)  # back-compat alias
    p.add_argument("identifier")
    p = sub.add_parser("get_profile", help=argparse.SUPPRESS)
    p.add_argument("name")
    p = sub.add_parser("get_knowledge_topics", help=argparse.SUPPRESS)
    p.add_argument("--category", default="")
    p.add_argument("--status", default="")
    p = sub.add_parser("get_knowledge", help=argparse.SUPPRESS)
    p.add_argument("topics", nargs="+")
    sub.add_parser("list_roles", help=argparse.SUPPRESS)
    sub.add_parser("list_skills", help=argparse.SUPPRESS)
    sub.add_parser("list_profiles", help=argparse.SUPPRESS)
    p = sub.add_parser("list_traits", help=argparse.SUPPRESS)
    p.add_argument("--category", default=None)
    p = sub.add_parser("get_references", help=argparse.SUPPRESS)
    p.add_argument("id")
    p = sub.add_parser("get_stale", help=argparse.SUPPRESS)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--category", default="")

    return parser


# ── Dispatch ─────────────────────────────────────────────────────────

_DISPATCH = {
    "get_context": cmd_get_context,
    "list_context": cmd_list_context,
    "get": cmd_get,
    "list": cmd_list,
    "search": cmd_search,
    "how_to": cmd_how_to,
    "references": cmd_references,
    "stale": cmd_stale,
    "remind_me": cmd_remind_me,
    "test": cmd_test,
    # Legacy subcommands (MCP backward compat)
    "get_role": cmd_get_role,
    "get_skill": cmd_get_skill,
    "get_context_file": cmd_get_context_file,
    "get_trait": cmd_get_trait,  # back-compat alias
    "get_profile": cmd_get_profile,
    "get_knowledge_topics": cmd_get_knowledge_topics,
    "get_knowledge": cmd_get_knowledge,
    "get_references": cmd_references,
    "get_stale": cmd_stale,
    "list_roles": cmd_list_roles,
    "list_skills": cmd_list_skills,
    "list_profiles": cmd_list_profiles,
    "list_traits": cmd_list_traits,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    handler = _DISPATCH.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)
    try:
        handler(args)
    except Exception as e:
        print(c("Error: {}".format(e), 'error'), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
