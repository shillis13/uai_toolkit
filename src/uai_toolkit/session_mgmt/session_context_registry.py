#!/usr/bin/env python3
"""
session_context_registry.py — Track what context items a session has loaded.

Discovers available context (traits, roles, skills, profiles, briefs, memory slots)
from both the filesystem and the traits registry DB. Tracks per-session load state.

No args enters REPL mode. With args, runs as one-shot CLI.
Cross-session: use 'as <id>' in REPL or --session on CLI.

Legacy name: session_traits.py (symlink preserved for backward compat).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

# --- Paths ---

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
AI_GENERAL = AI_ROOT / "ai_general"
TRAITS_DIR = AI_GENERAL / "ai_traits"
PROFILES_DIR = AI_GENERAL / "ai_profiles"
ROLES_DIR = PROFILES_DIR / "roles"
SKILLS_DIR = PROFILES_DIR / "skills"
BRIEFS_DIR = AI_GENERAL / "data" / "session_briefs"
GLOBALS_DIR = AI_GENERAL / "ai_context_files" / "globals"
MANIFEST_PATH = AI_ROOT / "ai_memories" / "80_working_memory" / "manifest.yml"
SESSION_MGR = AI_GENERAL / "scripts" / "session_mgmt" / "session_mgr.py"
HISTORY_FILE = Path.home() / ".session_traits_history"

_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

_SM = AI_GENERAL / "scripts" / "session_mgmt"
if str(_SM) not in sys.path:
    sys.path.insert(0, str(_SM))

# Shared color library
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bin", "ai"))
from uai_toolkit.common_utils.standard_colors import c as _sc, bold, dim, heading, format_help, colors_enabled, set_color_mode

VERSION = "2.1.0"

# State keys
KEY_LOADED_TRAITS = "loaded.traits"
KEY_LOADED_ROLES = "loaded.roles"
KEY_LOADED_MSLOTS = "loaded.mslots"
KEY_LOADED_PROFILES = "loaded.profiles"

VALID_TYPES = ("traits", "mslots", "roles", "profiles", "briefs", "globals")
# Manifest uses singular; display uses plural. Map between them.
_PLURAL_TO_SINGULAR = {"traits": "trait", "roles": "role", "mslots": "mslot", "profiles": "profile", "briefs": "brief", "globals": "global"}
_SINGULAR_TO_PLURAL = {v: k for k, v in _PLURAL_TO_SINGULAR.items()}
TYPE_KEYS = {"traits": KEY_LOADED_TRAITS, "roles": KEY_LOADED_ROLES, "mslots": KEY_LOADED_MSLOTS, "profiles": KEY_LOADED_PROFILES}


def _manifest_types_for(item_type: str) -> tuple[str, ...]:
    """Return manifest type names that should be treated as this logical type.

    Includes backward-compat aliases for historical bad writes and the special
    case where skills are surfaced through the roles catalog as `skill:<name>`.
    """
    singular = _PLURAL_TO_SINGULAR.get(item_type, item_type)
    aliases = {singular}
    if item_type in _PLURAL_TO_SINGULAR:
        aliases.add(item_type)
    if singular == "role":
        aliases.add("skill")
    return tuple(sorted(aliases))


# --- Color helpers (thin wrappers over standard_colors) ---

_USE_COLOR = sys.stdout.isatty()


def _c(style_or_code, text):
    """Apply a named style from standard_colors. style_or_code is a style name."""
    return _sc(str(text), style_or_code)


# Style aliases used in session_traits display logic
_BOLD   = "bold"
_DIM    = "dim"
_CYAN   = "cyan"
_GREEN  = "green"
_YELLOW = "yellow"
_MAGENTA = "magenta"
_RED    = "red"
_BRIGHT_YELLOW = "bright_yellow"
_BRIGHT_GREEN  = "bright_green"


# --- Session Store ---

_store = None
_store_loaded = False


def _load_store():
    global _store, _store_loaded
    if _store_loaded:
        return _store
    _store_loaded = True
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        _store = SessionStore()
    except Exception:
        pass
    return _store


def _resolve_session(ref: str) -> str:
    """Resolve any identifier to a tracking ID. Returns as-is if unresolvable."""
    store = _load_store()
    if store is None:
        return ref
    try:
        session = store.resolve(ref)
        if session:
            return session.get("tracking_id", ref)
    except Exception:
        pass
    return ref


def _get_display_name(tracking_id: str) -> Optional[str]:
    store = _load_store()
    if store is None:
        return None
    try:
        session = store.get(tracking_id)
        if session:
            return session.get("display_name")
    except Exception:
        return None


def _session_label(tracking_id: str) -> str:
    name = _get_display_name(tracking_id)
    if name:
        return "{} ({})".format(name, tracking_id)
    return tracking_id


# --- Session State Interface ---

def _run_session_mgr(session_id: str, subcommand: str, args: list[str] | None = None) -> str:
    if not session_id:
        return ""
    cmd = [sys.executable, str(SESSION_MGR), subcommand, session_id]
    session_dir = os.environ.get("AI_SESSION_DIR", "")
    if session_dir:
        cmd += ["--data-dir", session_dir]
    if args:
        cmd += args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


# --- Manifest Storage (loaded.manifest) ---

def _get_manifest(session_id: str) -> list[dict]:
    """Get the full loaded manifest for a session."""
    raw = _run_session_mgr(session_id, "state_get", ["loaded.manifest"])
    if not raw:
        return []
    try:
        data = json.loads(raw)
        value = data.get("value")
        if not value:
            return []
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, list):
            return value
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def _set_manifest(session_id: str, manifest: list[dict]) -> None:
    """Write the full loaded manifest for a session."""
    _run_session_mgr(session_id, "state_set", ["loaded.manifest", json.dumps(manifest, default=str)])


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def get_loaded(session_id: str, item_type: str) -> list[str]:
    """Get names of loaded items of a type (backwards-compat convenience).

    item_type can be plural (traits) or singular (trait) — both work.
    """
    manifest = _get_manifest(session_id)
    manifest_types = _manifest_types_for(item_type)
    return [e["name"] for e in manifest if e.get("type") in manifest_types]


def get_loaded_with_src(session_id: str, item_type: str | None = None) -> list[dict]:
    """Get loaded items with full src info. If type is None, return all."""
    manifest = _get_manifest(session_id)
    if item_type:
        manifest_types = _manifest_types_for(item_type)
        return [e for e in manifest if e.get("type") in manifest_types]
    return manifest


def load_item(session_id: str, item_type: str, name: str, src: str) -> dict:
    """Record a loaded item. Returns {new: bool, entry: dict}.

    src is a free-form string: "cmd", "startup", "role:assistant",
    "profile:developer_teammate", "hook:prompt_submit", etc.
    """
    manifest = _get_manifest(session_id)
    manifest_type = _PLURAL_TO_SINGULAR.get(item_type, item_type)
    existing = [e for e in manifest if e.get("type") == manifest_type and e.get("name") == name]
    if existing:
        return {"new": False, "entry": existing[0]}
    entry = {"type": manifest_type, "name": name, "src": src, "at": _now_iso()}
    manifest.append(entry)
    _set_manifest(session_id, manifest)
    return {"new": True, "entry": entry}


# --- Pending Context Load (pending_context_load) ---

def _get_pending(session_id: str) -> list[dict]:
    """Get pending context load items for a session."""
    raw = _run_session_mgr(session_id, "state_get", ["pending_context_load"])
    if not raw:
        return []
    try:
        data = json.loads(raw)
        value = data.get("value")
        if not value:
            return []
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, list):
            return value
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def _set_pending(session_id: str, pending: list[dict]) -> None:
    """Write the pending context load list for a session."""
    _run_session_mgr(session_id, "state_set", ["pending_context_load", json.dumps(pending, default=str)])


def pend_items(session_id: str, items: list[dict]) -> list[dict]:
    """Add items to pending_context_load. Each item: {type, name, path}.
    Returns the items that were newly added."""
    pending = _get_pending(session_id)
    existing_keys = {(e["type"], e["name"]) for e in pending}
    added = []
    for item in items:
        key = (item["type"], item["name"])
        if key not in existing_keys:
            pending.append(item)
            existing_keys.add(key)
            added.append(item)
    if added:
        _set_pending(session_id, pending)
    return added


def unpend_items(session_id: str, items: list[dict]) -> int:
    """Remove items from pending_context_load. Each item: {type, name}.
    Returns count removed."""
    pending = _get_pending(session_id)
    remove_keys = {(i["type"], i["name"]) for i in items}
    new_pending = [e for e in pending if (e["type"], e["name"]) not in remove_keys]
    removed = len(pending) - len(new_pending)
    if removed:
        _set_pending(session_id, new_pending)
    return removed


def get_pending_names(session_id: str) -> set[str]:
    """Get set of 'type::name' keys for pending items (for quick UI lookups)."""
    return {"{}::{}".format(e["type"], e["name"]) for e in _get_pending(session_id)}


def clear_loaded(session_id: str, item_type: str | None = None) -> dict[str, int]:
    """Clear loaded state. Returns counts of what was cleared."""
    manifest = _get_manifest(session_id)
    if item_type:
        manifest_types = _manifest_types_for(item_type)
        removed = [e for e in manifest if e.get("type") in manifest_types]
        manifest = [e for e in manifest if e.get("type") not in manifest_types]
        cleared = {item_type: len(removed)}
    else:
        cleared = {}
        for t in VALID_TYPES:
            manifest_types = _manifest_types_for(t)
            cleared[t] = len([e for e in manifest if e.get("type") in manifest_types])
        manifest = []
    _set_manifest(session_id, manifest)
    return cleared


def adopt(session_id: str, name: str, src: str) -> list[dict]:
    """Adopt a profile or role by name. Cascades: profile->roles->traits.

    Returns list of all entries added (including cascaded).
    """
    added = []

    # Check if it's a profile
    profile_file = PROFILES_DIR / "{}.yml".format(name)
    if profile_file.exists():
        result = load_item(session_id, "profile", name, src)
        if result["new"]:
            added.append(result["entry"])
        # Load each role in the profile
        import yaml
        data = yaml.safe_load(profile_file.read_text()) or {}
        for role_ref in data.get("roles", []):
            role_name = Path(role_ref).stem
            role_added = _adopt_role(session_id, role_name, "profile:{}".format(name))
            added.extend(role_added)
        return added

    # Check if it's a role
    role_added = _adopt_role(session_id, name, src)
    if role_added:
        return role_added

    # Check if it's a skill
    skill_file = SKILLS_DIR / "{}.yml".format(name)
    if skill_file.exists():
        return _adopt_skill(session_id, name, src)

    return []  # not found


def _adopt_role(session_id: str, name: str, src: str) -> list[dict]:
    """Load a role and its traits. Returns entries added."""
    role_file = ROLES_DIR / "{}.yml".format(name)
    if not role_file.exists():
        return []
    added = []
    result = load_item(session_id, "role", name, src)
    if result["new"]:
        added.append(result["entry"])
    # Load traits referenced by this role
    import yaml
    data = yaml.safe_load(role_file.read_text()) or {}
    traits_section = data.get("traits", {})
    trait_refs = []
    if isinstance(traits_section, dict):
        for cat_paths in traits_section.values():
            if isinstance(cat_paths, list):
                trait_refs.extend(cat_paths)
    elif isinstance(traits_section, list):
        trait_refs = traits_section
    for ref in trait_refs:
        # Normalize: ai_traits/perspective/foo.latest.condensed.yml -> perspective/foo
        ref_path = ref
        if ref_path.startswith("ai_traits/"):
            ref_path = ref_path[len("ai_traits/"):]
        parts = ref_path.split("/")
        if len(parts) >= 2:
            category = "/".join(parts[:-1])
            base = _trait_base_name(parts[-1])
            trait_name = "{}/{}".format(category, base)
        else:
            trait_name = _trait_base_name(parts[0])
        # Only record if the trait file actually exists
        if _resolve_trait_path(trait_name) is None:
            continue
        r = load_item(session_id, "trait", trait_name, "role:{}".format(name))
        if r["new"]:
            added.append(r["entry"])
    return added


def _adopt_skill(session_id: str, name: str, src: str) -> list[dict]:
    """Load a skill and its traits. Returns entries added."""
    skill_file = SKILLS_DIR / "{}.yml".format(name)
    if not skill_file.exists():
        return []
    added = []
    result = load_item(session_id, "skill", "skill:{}".format(name), src)
    if result["new"]:
        added.append(result["entry"])
    import yaml
    data = yaml.safe_load(skill_file.read_text()) or {}
    traits_section = data.get("traits", {})
    trait_refs = []
    if isinstance(traits_section, dict):
        for cat_paths in traits_section.values():
            if isinstance(cat_paths, list):
                trait_refs.extend(cat_paths)
    for ref in trait_refs:
        ref_path = ref
        if ref_path.startswith("ai_traits/"):
            ref_path = ref_path[len("ai_traits/"):]
        parts = ref_path.split("/")
        if len(parts) >= 2:
            category = "/".join(parts[:-1])
            base = _trait_base_name(parts[-1])
            trait_name = "{}/{}".format(category, base)
        else:
            trait_name = _trait_base_name(parts[0])
        if _resolve_trait_path(trait_name) is None:
            continue
        r = load_item(session_id, "trait", trait_name, "skill:{}".format(name))
        if r["new"]:
            added.append(r["entry"])
    return added


# --- Discovery ---

def _trait_base_name(filename: str) -> str:
    """Extract the logical trait name from a filename.

    architectural_thinking.latest.md → architectural_thinking
    instr_development.latest.condensed.yml → instr_development
    instr_audit_system.md → instr_audit_system
    download_chat_registry_data_claude.md → download_chat_registry_data_claude
    """
    name = filename
    # Strip file extension
    for ext in (".yml", ".yaml", ".md"):
        if name.endswith(ext):
            name = name[:-len(ext)]
            break
    # Strip .condensed suffix
    if name.endswith(".condensed"):
        name = name[:-len(".condensed")]
    # Strip .latest suffix
    if name.endswith(".latest"):
        name = name[:-len(".latest")]
    return name


def discover_traits() -> list[str]:
    """Discover logical trait names (category/base_name). Deduplicates variants."""
    traits = []
    seen = set()
    if not TRAITS_DIR.exists():
        return traits
    for subdir in sorted(TRAITS_DIR.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith((".", "_")):
            for f in sorted(subdir.iterdir()):
                if f.is_symlink() or (f.is_file() and f.suffix in (".yml", ".md")):
                    if not f.name.startswith("."):
                        base = _trait_base_name(f.name)
                        key = f"{subdir.name}/{base}"
                        if key not in seen:
                            seen.add(key)
                            traits.append(key)
    return traits


def discover_roles() -> list[str]:
    roles = []
    if ROLES_DIR.exists():
        for f in sorted(ROLES_DIR.iterdir()):
            if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
                roles.append(f.stem)
    if SKILLS_DIR.exists():
        for f in sorted(SKILLS_DIR.iterdir()):
            if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
                roles.append(f"skill:{f.stem}")
    return roles


def discover_mslots() -> list[str]:
    slots = []
    if not MANIFEST_PATH.exists():
        return slots
    try:
        import yaml
        data = yaml.safe_load(MANIFEST_PATH.read_text())
        slot_structure = data.get("slot_structure", {})
        for slot_num, info in sorted(slot_structure.items(), key=lambda x: int(x[0])):
            name = info.get("name", f"slot_{slot_num}")
            slots.append(f"{int(slot_num):02d}:{name}")
    except Exception:
        slot_dir = MANIFEST_PATH.parent
        for f in sorted(slot_dir.glob("[0-9][0-9].yml")):
            slots.append(f"{f.stem}:unknown")
    return slots


def discover_profiles() -> list[str]:
    """Discover profile definitions in ai_profiles/ (top-level .yml files)."""
    profiles = []
    if PROFILES_DIR.exists():
        for f in sorted(PROFILES_DIR.iterdir()):
            if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
                profiles.append(f.stem)
    return profiles


def discover_briefs() -> list[str]:
    """Discover session briefs in data/session_briefs/ (recursive)."""
    briefs = []
    if not BRIEFS_DIR.exists():
        return briefs
    for f in sorted(BRIEFS_DIR.rglob("*.yml")):
        if f.name.startswith("."):
            continue
        rel = f.relative_to(BRIEFS_DIR)
        # Use parent/stem for subdirs, just stem for top-level
        if len(rel.parts) > 1:
            briefs.append(f"{rel.parent}/{f.stem}")
        else:
            briefs.append(f.stem)
    return briefs


def discover_globals() -> list[str]:
    """Discover global context files in ai_context_files/globals/."""
    if not GLOBALS_DIR.exists():
        return []
    return sorted(
        f.stem for f in GLOBALS_DIR.iterdir()
        if f.is_file() and f.suffix in (".md", ".yml", ".txt") and not f.name.startswith(".")
    )


def _discover_from_registry() -> dict[str, list[str]]:
    """Query the traits registry DB for all indexed items.

    Returns items grouped by VALID_TYPES. Items are keyed the same way
    filesystem discovery keys them:
      traits: "category/base_name" (e.g., "knowledge/instr_operating_principles")
      roles: role id (e.g., "dev") or "skill:name"
      profiles: profile id (e.g., "individual_developer")
    """
    db_path = AI_GENERAL / "data" / "context_files" / "context_files_registry.db"
    if not db_path.exists():
        return {}

    import sqlite3
    try:
        db = sqlite3.connect(str(db_path))
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, category, composition_type, status FROM content_items WHERE status = 'active' OR status IS NULL"
        ).fetchall()
        db.close()
    except (sqlite3.Error, OSError):
        return {}

    result = {"traits": [], "roles": [], "profiles": []}
    for row in rows:
        comp = (row["composition_type"] or "").lower()
        item_id = row["id"]
        category = row["category"] or ""

        if comp == "role":
            result["roles"].append(item_id)
        elif comp == "skill":
            result["roles"].append(f"skill:{item_id}")
        elif comp == "profile":
            result["profiles"].append(item_id)
        elif comp in ("global", "platform"):
            result["profiles"].append(item_id)
        else:
            # Traits/knowledge — use category/id format
            key = f"{category}/{item_id}" if category else item_id
            result["traits"].append(key)

    return result


def discover_all() -> dict[str, list[str]]:
    """Discover all available context items from filesystem + registry DB.

    Filesystem discovery is authoritative for mslots and briefs (not indexed).
    Registry DB supplements traits, roles, and profiles with items that the
    filesystem scanner might miss (e.g., deeply nested knowledge topics).
    """
    fs_result = {
        "traits": discover_traits(),
        "roles": discover_roles(),
        "mslots": discover_mslots(),
        "profiles": discover_profiles(),
        "briefs": discover_briefs(),
        "globals": discover_globals(),
    }

    db_result = _discover_from_registry()
    for item_type, items in db_result.items():
        existing = set(fs_result.get(item_type, []))
        for item in items:
            if item not in existing:
                fs_result.setdefault(item_type, []).append(item)
                existing.add(item)

    return fs_result


# --- Content Resolution ---

def _resolve_trait_path(name: str) -> Path | None:
    """Resolve a trait name (category/base_name) to best file on disk.

    Preference: .latest.condensed.yml > .latest.yml > .latest.md > .yml > .md
    Also handles names that already include .latest or full filename.
    """
    # If name contains a category prefix, use it directly
    # Try resolution order: condensed yml, yml, md, then bare name
    suffixes = [
        ".latest.condensed.yml",
        ".latest.yml",
        ".latest.md",
        ".condensed.yml",
        ".yml",
        ".md",
    ]
    for suffix in suffixes:
        candidate = TRAITS_DIR / (name + suffix)
        if candidate.exists() or candidate.is_symlink():
            return candidate
    # Try as-is (already has extension or is exact path)
    candidate = TRAITS_DIR / name
    if candidate.exists() or candidate.is_symlink():
        return candidate
    return None


def _resolve_role_path(name: str) -> Path | None:
    if name.startswith("skill:"):
        candidate = SKILLS_DIR / (name[6:] + ".yml")
    else:
        candidate = ROLES_DIR / (name + ".yml")
    return candidate if candidate.exists() else None


def _resolve_mslot_path(name: str) -> Path | None:
    slot_num = name.split(":")[0] if ":" in name else name
    candidate = MANIFEST_PATH.parent / f"{slot_num}.yml"
    return candidate if candidate.exists() else None


def _resolve_profile_path(name: str) -> Path | None:
    candidate = PROFILES_DIR / (name + ".yml")
    return candidate if candidate.exists() else None


def _resolve_brief_path(name: str) -> Path | None:
    candidate = BRIEFS_DIR / (name + ".yml")
    return candidate if candidate.exists() else None


def _resolve_global_path(name: str) -> Path | None:
    for suffix in (".md", ".yml", ".txt"):
        candidate = GLOBALS_DIR / (name + suffix)
        if candidate.exists():
            return candidate
    candidate = GLOBALS_DIR / name
    if candidate.exists():
        return candidate
    return None


def _read_content(item_type: str, name: str) -> str | None:
    if item_type == "traits":
        path = _resolve_trait_path(name)
    elif item_type == "roles":
        path = _resolve_role_path(name)
    elif item_type == "mslots":
        path = _resolve_mslot_path(name)
    elif item_type == "profiles":
        path = _resolve_profile_path(name)
    elif item_type == "briefs":
        path = _resolve_brief_path(name)
    elif item_type == "globals":
        path = _resolve_global_path(name)
    else:
        return None
    if path and path.exists():
        return path.read_text()
    return None


# --- Help ---

def _brief_help(has_session: bool = True) -> str:
    def _cmd(name, desc):
        return "  {:<34} {}".format(_c(_CYAN, name), _c(_DIM, desc))

    lines = [_c(_BOLD, "Session Traits REPL Commands:")]

    lines.append("")
    lines.append(_c(_BOLD, "Identity:"))
    lines.append(_cmd("whoami", "Show current session identity"))
    lines.append(_cmd("as <id_or_name>", "Switch session scope"))
    lines.append(_cmd("as none", "Clear session scope"))

    lines.append("")
    lines.append(_c(_BOLD, "Browse:"))
    default_list_desc = "List loaded items in the session" if has_session else "List all available items"
    lines.append(_cmd("list [type]", default_list_desc))
    lines.append(_cmd("types", "Show valid types with counts"))

    if has_session:
        lines.append(_cmd("list --loaded [type]", "Only items loaded (with src)"))
        lines.append(_cmd("list --available [type]", "Only available items (ignore session state)"))
        lines.append(_cmd("list --not-loaded [type]", "Only items not yet loaded"))
        lines.append(_cmd("list --all [type]", "All items with loaded markers + src"))
        lines.append("")
        lines.append(_c(_BOLD, "Session State:"))
        lines.append(_cmd("adopt <profile|role|skill>", "Load with cascade (profile->roles->traits)"))
        lines.append(_cmd("load <type> <name...>", "Load individual items (src=cmd)"))
        lines.append(_cmd("clear [type]", "Clear tracked loaded-state bookkeeping for this session"))
        lines.append(_cmd("status", "Summary counts (loaded vs available)"))
    else:
        lines.append("")
        lines.append(_c(_DIM, "  Set a session with 'as <name>' to see loaded state."))

    lines.append("")
    lines.append(_cmd("help", "This help"))
    lines.append(_cmd("quit / q / Ctrl-D", "Exit"))
    return "\n".join(lines)


def _cli_help() -> str:
    """Colorized --help for CLI mode."""
    raw = """\
session_traits -- Track loaded traits, roles, and memory slots (v{ver})

Usage:
    session_traits                              Interactive REPL mode
    session_traits <command> [args...]          One-shot CLI mode

Global flags:
    --session <id>       Target session (tracking ID, CLI UUID, terminal name, display name)
    --session-id <id>    Alias for --session (explicit AI session selector)
    --json               Structured JSON output
    --no-color           Disable colors

Commands:
    list [type]                 Session-scoped: list loaded items. Unscoped: list available items.
    list --loaded [type]        Only items loaded in the session
    list --available [type]     Only available items (ignore session state)
    list --not-loaded [type]    Only items not yet loaded
    list --all [type]           All items with loaded markers
    types                       Show valid types with counts
    load <type> <name...>       Record a trait/role/mslot as loaded
    clear [type]                Clear tracked loaded-state bookkeeping for the session
    status                      Summary counts (loaded vs available)

Types:
    traits    Files in ai_traits/ (knowledge, perspective, methods, etc.)
    roles     Roles + skills in ai_profiles/roles/ and skills/
    mslots    Working memory slots from manifest.yml
    profiles  Profile definitions in ai_profiles/ (top-level .yml files)

Clear:
    Clears only session_traits bookkeeping in loaded.manifest for the target
    session. It does not remove content from the session's context window
    (that's not possible). Use when tracked loaded-state has drifted from
    reality and needs a fresh start.

Load:
    Records that a trait/role/mslot is loaded in the target session. Verifies
    the item exists on disk. Does not deliver content -- bootstrap and guidance
    MCP handle actual loading. This is bookkeeping for cross-session visibility.

Session resolution:
    --session / --session-id accepts: tracking ID, CLI UUID, terminal session
    name, UUID prefix (8+ hex chars), or display name. Defaults to
    $AI_TRACKING_ID.
""".format(ver=VERSION)
    return format_help(raw)


# --- REPL Commands ---

def cmd_list(args: list[str], session_id: str | None) -> str:
    """Unified list: ls [--loaded|--available|--not-loaded|--all] [type]

    --loaded: only items loaded in the session (requires session scope)
    --available: only available items (ignore session scope)
    --not-loaded: only items NOT loaded (requires session scope)
    --all: all items, with loaded markers (requires session scope)
    (no flag): loaded items when session-scoped, otherwise all available items
    """
    # Parse flags
    filter_mode = None  # None = choose default by scope
    item_type = None
    for a in args:
        al = a.lower()
        if al in ("--loaded", "-l"):
            filter_mode = "loaded"
        elif al == "--available":
            filter_mode = "available"
        elif al in ("--not-loaded", "--unloaded", "-n"):
            filter_mode = "not-loaded"
        elif al in ("--all", "-a"):
            filter_mode = "all"
        elif al in VALID_TYPES or al == "all":
            item_type = al
        # ignore unknown flags

    if item_type and item_type != "all" and item_type not in VALID_TYPES:
        return _c(_RED, "Unknown type: {}. Use 'types' to see valid types.".format(item_type))

    if filter_mode is None:
        filter_mode = "loaded" if session_id else "available"

    available = discover_all()
    types = VALID_TYPES if not item_type or item_type == "all" else (item_type,)

    need_session = filter_mode in ("loaded", "not-loaded", "all")
    if need_session and not session_id:
        return _c(_RED, "Session scope required for --loaded/--not-loaded/--all. Use 'as <name>' first.")

    loaded_sets = {}
    if need_session and session_id:
        for t in types:
            loaded_sets[t] = set(get_loaded(session_id, t))

    lines = []
    for t in types:
        avail = available.get(t, [])
        loaded = loaded_sets.get(t, set())

        if filter_mode == "loaded":
            show = [i for i in avail if i in loaded]
            label = "{} loaded".format(len(show))
        elif filter_mode == "available":
            show = avail
            label = "{} available".format(len(avail))
        elif filter_mode == "not-loaded":
            show = [i for i in avail if i not in loaded]
            label = "{} not loaded".format(len(show))
        elif filter_mode == "all":
            show = avail
            label = "{} total, {} loaded".format(len(avail), len(loaded))
        else:
            show = avail
            label = "{} available".format(len(avail))

        lines.append(_c(_BOLD, "\n{} ({}):".format(t.upper(), label)))
        # Build src lookup for loaded items
        src_map = {}
        if need_session and session_id:
            for entry in get_loaded_with_src(session_id, t):
                src_map[entry["name"]] = entry.get("src", "unk")

        for item in show:
            if filter_mode in ("all",) and item in loaded:
                src = src_map.get(item, "unk")
                lines.append("  {} {} {}".format(
                    _c(_GREEN, item), _c(_DIM, "[loaded]"), _c(_YELLOW, "src=" + src)))
            elif filter_mode in ("all",):
                lines.append("  {}".format(_c(_CYAN, item)))
            elif filter_mode == "loaded":
                src = src_map.get(item, "unk")
                lines.append("  {} {}".format(_c(_GREEN, item), _c(_YELLOW, "src=" + src)))
            else:
                lines.append("  {}".format(_c(_CYAN, item)))
        if not show:
            lines.append(_c(_DIM, "  (none)"))

    return "\n".join(lines)


def cmd_types(args: list[str]) -> str:
    """Show valid types."""
    lines = [_c(_BOLD, "Valid types:"), ""]
    for t in VALID_TYPES:
        desc = {"traits": "Files in ai_traits/ (knowledge, perspective, methods, etc.)",
                "roles": "Roles + skills in ai_profiles/roles/ and skills/",
                "mslots": "Working memory slots from manifest.yml",
                "profiles": "Profile definitions in ai_profiles/ (top-level .yml files)",
                "briefs": "Session briefs in data/session_briefs/"}.get(t, "")
        count = len(discover_all().get(t, []))
        lines.append("  {:<10s} {} {}".format(
            _c(_CYAN, t), _c(_GREEN, str(count)), _c(_DIM, desc)))
    return "\n".join(lines)


def cmd_load(args: list[str], session_id: str) -> str:
    if len(args) < 2:
        return _c(_RED, "Usage: load <type> <name...>")
    item_type = args[0]
    if item_type not in VALID_TYPES:
        return _c(_RED, "Unknown type: {}. Use 'types' to see valid types.".format(item_type))
    results = []
    for name in args[1:]:
        content = _read_content(item_type, name)
        if content is None:
            results.append(_c(_RED, "  ! {} (not found)".format(name)))
            continue
        r = load_item(session_id, item_type, name, src="cmd")
        if r["new"]:
            results.append("{} {}".format(
                _c(_GREEN, "  + " + name), _c(_DIM, "({} chars, src=cmd)".format(len(content)))))
        else:
            results.append(_c(_DIM, "  = {} (already loaded, src={})".format(name, r["entry"].get("src", "?"))))
    return "\n".join(results)


def cmd_adopt(args: list[str], session_id: str) -> str:
    """Adopt a profile or role — cascades to load all referenced items."""
    if not args:
        return _c(_RED, "Usage: adopt <profile_or_role_name>")
    name = args[0]
    added = adopt(session_id, name, src="cmd")
    if not added:
        return _c(_RED, "Not found as profile, role, or skill: {}".format(name))
    lines = [_c(_BOLD, "Adopted {} ({} items loaded):".format(name, len(added))), ""]
    for entry in added:
        lines.append("  {} {} {} {}".format(
            _c(_GREEN, "+"),
            _c(_CYAN, entry["type"] + ":" + entry["name"]),
            _c(_DIM, "src="),
            _c(_YELLOW, entry["src"]),
        ))
    return "\n".join(lines)


def cmd_clear(args: list[str], session_id: str) -> str:
    item_type = args[0] if args else None
    if item_type and item_type not in VALID_TYPES:
        return _c(_RED,"Unknown type: {}. Valid: {}".format(item_type, ", ".join(VALID_TYPES)))
    cleared = clear_loaded(session_id, item_type)
    lines = [
        _c(_DIM, "Clears only session_traits bookkeeping in loaded.manifest; it does not unload content already present in the AI session.")
    ]
    for t, count in cleared.items():
        if count:
            lines.append(_c(_YELLOW,"  Cleared {} {}".format(count, t)))
        else:
            lines.append(_c(_DIM,"  {}: already empty".format(t)))
    return "\n".join(lines)


def cmd_status(session_id: str | None) -> str:
    available = discover_all()
    if not session_id:
        lines = [_c(_DIM,"\nNo session targeted (discovery only)"), ""]
        for t in VALID_TYPES:
            avail = available.get(t, [])
            lines.append("  {:8s}  {} / {:3d} available".format(t, _c(_DIM,"  -"), len(avail)))
        lines.append(_c(_DIM,"\n  Use 'as <name>' to see loaded state."))
        return "\n".join(lines)
    lines = [_c(_DIM,"\nSession: {}".format(_session_label(session_id))), ""]
    for t in VALID_TYPES:
        avail = available.get(t, [])
        loaded = get_loaded(session_id, t)
        bar = "{} / {:3d}".format(_c(_GREEN,"{:3d}".format(len(loaded))), len(avail))
        lines.append("  {:8s}  {}".format(t, bar))
    return "\n".join(lines)


def cmd_whoami(session_id: str | None) -> str:
    if not session_id:
        return _c(_DIM,"  (no session scope set)")
    store = _load_store()
    if store:
        info = store.resolve(session_id)
        if info:
            lines = []
            lines.append("  {} {}".format(_c(_DIM,"Tracking ID:  "), _c(_BRIGHT_YELLOW,info.get("tracking_id", ""))))
            lines.append("  {} {}".format(_c(_DIM,"CLI UUID:     "), _c(_CYAN,info.get("cli_session_id", "") or "(none)")))
            lines.append("  {} {}".format(_c(_DIM,"Terminal:     "), _c(_CYAN,info.get("terminal_session", "") or "(none)")))
            lines.append("  {} {}".format(_c(_DIM,"Display Name: "), _c(_BRIGHT_GREEN,info.get("display_name", "") or "(none)")))
            lines.append("  {} {}".format(_c(_DIM,"Platform:     "), _c(_CYAN,info.get("platform", "") or "(none)")))
            return "\n".join(lines)
    return "  {} {}".format(_c(_DIM,"session:"), _c(_BRIGHT_YELLOW,session_id))


# --- Command Dispatch ---

def run_command(line: str, session_id: str | None, interactive: bool = True) -> str | None:
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return _c(_RED,"Parse error: {}".format(e))

    if not parts:
        return None

    cmd = parts[0].lower()
    args = parts[1:]

    ALIASES = {"ls": "list", "l": "list", "avail": "list", "available": "list",
               "loaded": "list", "s": "status", "mark": "load"}

    # Aliases that imply a specific filter mode inject the matching flag
    if parts[0].lower() == "loaded":
        args = ["--loaded"] + args
    elif parts[0].lower() in ("available", "avail"):
        args = ["--available"] + args

    cmd = ALIASES.get(cmd, cmd)

    _NO_SESSION_CMDS = {"list", "types", "status", "help", "whoami", "as", "quit", "exit", "q"}

    if cmd not in _NO_SESSION_CMDS and not session_id:
        return _c(_YELLOW, "No session scope. Use 'as <name>' first.")

    if cmd == "list":
        return cmd_list(args, session_id)
    elif cmd == "types":
        return cmd_types(args)
    elif cmd == "adopt":
        return cmd_adopt(args, session_id)
    elif cmd == "load":
        return cmd_load(args, session_id)
    elif cmd == "clear":
        return cmd_clear(args, session_id)
    elif cmd == "status":
        return cmd_status(session_id)
    elif cmd == "whoami":
        return cmd_whoami(session_id)
    elif cmd == "help":
        return _brief_help(has_session=bool(session_id))
    elif cmd in ("quit", "exit", "q") and interactive:
        return None
    else:
        return _c(_YELLOW,"Unknown command: {}. Try 'help'.".format(cmd))


# --- REPL ---

def repl(session_id: str | None) -> None:
    from uai_toolkit.common_utils.lib_readline import setup_readline, make_session_completer
    setup_readline(history_file=HISTORY_FILE, history_length=200,
                   completer=make_session_completer())

    current_session = session_id or ""

    def prompt_str() -> str:
        if not colors_enabled():
            if not current_session:
                return "traits:*> "
            name = _get_display_name(current_session)
            label = name if name else current_session
            if len(label) > 30:
                label = label[:27] + "..."
            return "traits:{}> ".format(label)

        if not current_session:
            return "{dim_traits}{sep}".format(
                dim_traits=_sc("traits", "dim") + _sc(":*>", "bright_yellow"),
                sep=" ",
            )

        name = _get_display_name(current_session)
        label = name if name else current_session
        if len(label) > 30:
            label = label[:27] + "..."
        return "{prefix}{label}{suffix} ".format(
            prefix=_sc("traits:", "dim"),
            label=_sc(label, "bright_yellow", "bold"),
            suffix=_sc(">", "dim"),
        )

    # Welcome
    print("{} -- type 'help' for commands, 'q' to quit".format(_c(_BOLD,"Session Traits REPL")))
    if current_session:
        print("{} {}".format(_c(_DIM,"Identity:"), _c(_BRIGHT_GREEN,_session_label(current_session))))
    else:
        print("{} {}".format(_c(_DIM,"Identity:"), _c(_YELLOW,"(none) -- use 'as <name>' to set")))

    print(run_command("status", current_session or None))
    print()

    while True:
        try:
            line = input(prompt_str()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        try:
            tokens = shlex.split(line)
        except ValueError as e:
            print("  {}".format(_c(_RED,"Parse error: {}".format(e))))
            continue

        if not tokens:
            continue

        cmd = tokens[0].lower()
        rest = tokens[1:]

        if cmd in ("quit", "exit", "q"):
            break

        elif cmd == "as":
            if not rest:
                print("  {} {}".format(_c(_DIM,"Usage:"), _c(_CYAN,"as <tracking_id_or_name>")))
                continue
            ref = " ".join(rest)
            if ref.lower() in ("none", "all", "*"):
                current_session = ""
                print("  {}".format(_c(_YELLOW,"Session scope cleared.")))
            else:
                resolved = _resolve_session(ref)
                current_session = resolved
                print("  {} {}".format(_c(_DIM,"Now acting as:"), _c(_BRIGHT_GREEN,_session_label(current_session))))

        else:
            result = run_command(line, current_session or None, interactive=True)
            if result:
                print(result)


# --- JSON Mode ---

def run_json_command(args: list[str], session_id: str | None) -> None:
    if not args:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    cmd = args[0].lower()
    cmd_args = args[1:]

    try:
        if cmd in ("list", "ls", "available", "loaded"):
            item_type = None
            filter_mode = None
            for a in cmd_args:
                if a in ("--loaded", "-l"):
                    filter_mode = "loaded"
                elif a == "--available":
                    filter_mode = "available"
                elif a in ("--not-loaded", "-n"):
                    filter_mode = "not-loaded"
                elif a in ("--all", "-a"):
                    filter_mode = "all"
                elif a in VALID_TYPES:
                    item_type = a
            if cmd == "loaded":
                filter_mode = "loaded"
            elif cmd == "available":
                filter_mode = "available"
            if filter_mode is None:
                filter_mode = "loaded" if session_id else "available"
            available = discover_all()
            types = VALID_TYPES if not item_type else (item_type,)
            result = {}
            for t in types:
                avail = available.get(t, [])
                loaded = set(get_loaded(session_id, t)) if session_id else set()
                if filter_mode == "loaded":
                    result[t] = [i for i in avail if i in loaded]
                elif filter_mode == "not-loaded":
                    result[t] = [i for i in avail if i not in loaded]
                elif filter_mode == "available":
                    result[t] = avail
                else:
                    result[t] = avail
        elif cmd == "types":
            available = discover_all()
            result = {t: len(available.get(t, [])) for t in VALID_TYPES}
        elif cmd in ("load", "mark"):
            if len(cmd_args) < 2:
                result = {"error": "Usage: load <type> <name>"}
            else:
                item_type = cmd_args[0]
                loaded_items = []
                for name in cmd_args[1:]:
                    content = _read_content(item_type, name)
                    if content is None:
                        loaded_items.append({"name": name, "new": False, "found": False, "error": "not found"})
                    else:
                        r = load_item(session_id, item_type, name, src="cmd")
                        loaded_items.append({"name": name, "new": r["new"], "found": True,
                                             "size": len(content), "src": r["entry"].get("src", "cmd")})
                result = {"success": True, "type": item_type, "items": loaded_items}
        elif cmd == "adopt":
            if not cmd_args:
                result = {"error": "Usage: adopt <profile_or_role_name>"}
            else:
                added = adopt(session_id, cmd_args[0], src="cmd")
                result = {"success": len(added) > 0, "adopted": cmd_args[0], "items": added}
        elif cmd == "clear":
            item_type = cmd_args[0] if cmd_args else None
            cleared = clear_loaded(session_id, item_type)
            result = {
                "success": True,
                "cleared": cleared,
                "note": "Clears only session_traits bookkeeping in loaded.manifest; does not unload actual AI context.",
            }
        elif cmd == "pend":
            if len(cmd_args) < 2:
                result = {"error": "Usage: pend <type> <name...>"}
            else:
                item_type = cmd_args[0]
                items_to_pend = []
                for name in cmd_args[1:]:
                    path = _read_content(item_type, name)
                    if path is not None:
                        resolve_fn = {"traits": _resolve_trait_path, "roles": _resolve_role_path,
                                      "mslots": _resolve_mslot_path, "profiles": _resolve_profile_path,
                                      "briefs": _resolve_brief_path}.get(item_type)
                        resolved = str(resolve_fn(name)) if resolve_fn else ""
                        items_to_pend.append({"type": item_type, "name": name, "path": resolved})
                added = pend_items(session_id, items_to_pend)
                # Stage .ref files into context_to_load/ for hook delivery
                staged = 0
                if added and session_id:
                    session_dir = os.environ.get("AI_SESSION_DIR", "")
                    if not session_dir:
                        store = _load_store()
                        if store:
                            entry = store.resolve(session_id) or store.get(session_id)
                            if entry:
                                session_dir = entry.get("session_dir", "")
                    if session_dir:
                        _cli_dir = AI_GENERAL / "scripts" / "cli"
                        if str(_cli_dir) not in sys.path:
                            sys.path.insert(0, str(_cli_dir))
                        from uai_toolkit.cli.stage_context import stage_ref
                        for item in added:
                            name_staged, err = stage_ref(session_dir, item["type"], item["name"], path=item.get("path"))
                            if not err:
                                staged += 1
                result = {"success": True, "added": len(added), "staged": staged, "items": added}
        elif cmd == "unpend":
            if len(cmd_args) < 2:
                result = {"error": "Usage: unpend <type> <name...>"}
            else:
                item_type = cmd_args[0]
                items_to_unpend = [{"type": item_type, "name": n} for n in cmd_args[1:]]
                removed = unpend_items(session_id, items_to_unpend)
                result = {"success": True, "removed": removed}
        elif cmd == "pending":
            pending = _get_pending(session_id)
            if cmd_args and cmd_args[0] == "clear":
                _set_pending(session_id, [])
                result = {"success": True, "cleared": len(pending)}
            else:
                result = {"items": pending, "count": len(pending)}
        elif cmd == "status":
            available = discover_all()
            result = {}
            for t in VALID_TYPES:
                loaded = get_loaded(session_id, t)
                result[t] = {"loaded": len(loaded), "available": len(available.get(t, []))}
        else:
            result = {"error": "Unknown command: {}".format(cmd)}

        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


# --- Main ---

def main() -> None:
    args = sys.argv[1:]

    session_id = os.environ.get("AI_TRACKING_ID", "")
    json_mode = False

    i = 0
    while i < len(args):
        if args[i] in ("--session", "--session-id", "-s", "--as"):
            if i + 1 < len(args):
                session_id = args[i + 1]
                args = args[:i] + args[i+2:]
            else:
                print(_c(_RED,"Missing value for --session/--session-id"), file=sys.stderr)
                sys.exit(1)
        elif args[i] == "--json":
            json_mode = True
            args = args[:i] + args[i+1:]
        elif args[i] == "--no-color":
            set_color_mode(False)
            args = args[:i] + args[i+1:]
        elif args[i] in ("--help", "-h"):
            print(_cli_help())
            sys.exit(0)
        elif args[i] == "--version":
            print("session_traits v{}".format(VERSION))
            sys.exit(0)
        else:
            i += 1

    # Resolve session ID if provided
    if session_id:
        session_id = _resolve_session(session_id)

    if json_mode:
        set_color_mode(False)
        run_json_command(args, session_id or None)
        return

    if not args:
        repl(session_id or None)
        return

    command_line = " ".join(shlex.quote(a) for a in args)
    result = run_command(command_line, session_id or None, interactive=False)
    if result:
        print(result)


if __name__ == "__main__":
    main()
