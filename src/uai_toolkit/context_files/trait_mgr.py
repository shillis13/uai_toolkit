#!/usr/bin/env python3
"""
trait_mgr.py — CRUD for traits, roles, skills, profiles, platforms, and globals.

Manages the library of AI traits and profiles on disk. No session concept —
this edits the catalog that session_traits.py reads from.

No args enters REPL mode. With args, runs as one-shot CLI.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Optional

# Path setup — resolve through symlinks to get real script location
_SCRIPT_DIR = Path(__file__).resolve().parent
_AI_SCRIPTS = _SCRIPT_DIR.parent  # ai_general/scripts/
for _p in (str(_AI_SCRIPTS), str(Path.home() / "bin/all_languages/python/src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import standard_colors — try multiple paths
_sc_imported = False
try:
    from uai_toolkit.common_utils.standard_colors import c, bold, dim, heading, format_help, colors_enabled, set_color_mode
    _sc_imported = True
except ImportError:
    # Direct file import as last resort
    try:
        import importlib.util as _ilu
        _sc_path = _AI_SCRIPTS / "utils" / "standard_colors.py"
        if _sc_path.exists():
            _spec = _ilu.spec_from_file_location("standard_colors", str(_sc_path))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            c = _mod.c
            bold = _mod.bold
            dim = _mod.dim
            heading = _mod.heading
            format_help = _mod.format_help
            colors_enabled = _mod.colors_enabled
            set_color_mode = _mod.set_color_mode
            _sc_imported = True
    except Exception:
        pass

if not _sc_imported:
    def c(text, *args, **kw): return str(text)
    def bold(text): return str(text)
    def dim(text): return str(text)
    def heading(text): return str(text)
    def format_help(text): return str(text)
    def colors_enabled(): return False
    def set_color_mode(v): pass

VERSION = "1.0.0"

# Toolkit: no `utils` package-name collision here (the ~/bin shim isn't on path),
# so import the shared resolver normally (source uses an importlib-by-path
# workaround to dodge that collision in ai_general; unneeded + broken here).
from uai_toolkit.paths import AI_ROOT
AI_GENERAL = AI_ROOT / "ai_general"
TRAITS_DIR = AI_GENERAL / "ai_traits"
PROFILES_DIR = AI_GENERAL / "ai_profiles"
ROLES_DIR = PROFILES_DIR / "roles"
SKILLS_DIR = PROFILES_DIR / "skills"
PLATFORMS_DIR = PROFILES_DIR / "platforms"
GLOBALS_DIR = PROFILES_DIR / "globals"
HISTORY_FILE = Path.home() / ".trait_mgr_history"
TRAIT_RESOLUTION_SUFFIXES = (
    ".latest.condensed.yml",
    ".latest.yml",
    ".latest.md",
    ".condensed.yml",
    ".yml",
    ".yaml",
    ".md",
)
LIST_TARGET_ALIASES = {
    "trait": "traits",
    "traits": "traits",
    "role": "roles",
    "roles": "roles",
    "skill": "skills",
    "skills": "skills",
    "profile": "profiles",
    "profiles": "profiles",
    "platform": "platforms",
    "platforms": "platforms",
    "global": "globals",
    "globals": "globals",
    "category": "categories",
    "categories": "categories",
}
LIST_TARGETS = ("traits", "roles", "skills", "profiles", "platforms", "globals", "categories")
VIEW_TYPE_ALIASES = {
    "trait": "trait",
    "traits": "trait",
    "role": "role",
    "roles": "role",
    "skill": "skill",
    "skills": "skill",
    "profile": "profile",
    "profiles": "profile",
    "platform": "platform",
    "platforms": "platform",
    "global": "global",
    "globals": "global",
}
TREE_DIRECTIONS = {"up", "down", "both"}

def _discover_categories() -> list[str]:
    """Scan ai_traits/ for subdirectories (dynamic, not hardcoded)."""
    if not TRAITS_DIR.exists():
        return []
    return sorted(d.name for d in TRAITS_DIR.iterdir()
                  if d.is_dir() and not d.name.startswith((".", "_")))


def _trait_base_name(filename: str) -> str:
    """Extract logical trait name from a filename."""
    name = filename
    for ext in (".yml", ".yaml", ".md"):
        if name.endswith(ext):
            name = name[:-len(ext)]
            break
    if name.endswith(".condensed"):
        name = name[:-len(".condensed")]
    if name.endswith(".latest"):
        name = name[:-len(".latest")]
    return name


def _trait_resolution_priority(filename: str) -> int:
    """Lower number = more preferred file representation."""
    priority = len(TRAIT_RESOLUTION_SUFFIXES)
    for idx, suffix in enumerate(TRAIT_RESOLUTION_SUFFIXES):
        if filename.endswith(suffix):
            priority = idx
            break
    return priority


def _logical_trait_path(category: str, base_name: str) -> str:
    return "ai_traits/{}/{}".format(category, base_name)


def _normalize_trait_query(name: str) -> str:
    query = str(name or "").strip().replace("\\", "/")
    if query.startswith("~"):
        query = str(Path(query).expanduser())
    try:
        query_path = Path(query)
        if query_path.is_absolute():
            try:
                query = str(query_path.relative_to(AI_GENERAL))
            except ValueError:
                pass
    except Exception:
        pass
    if query.startswith("ai_traits/"):
        query = query[len("ai_traits/"):]
    return query.strip("/")


def _trait_slug_from_ref(trait_ref: str) -> str:
    normalized = _normalize_trait_query(trait_ref)
    if not normalized:
        return normalized
    parts = normalized.split("/")
    if len(parts) >= 2:
        return "{}/{}".format(parts[0], _trait_base_name(parts[-1]))
    return _trait_base_name(parts[0])


def _role_id_from_ref(role_ref: str) -> str:
    return Path(str(role_ref)).stem


def _normalize_role_query(role_input: str) -> str:
    query = str(role_input or "").strip().replace("\\", "/")
    if query.startswith("~"):
        query = str(Path(query).expanduser())
    try:
        query_path = Path(query)
        if query_path.is_absolute():
            try:
                query = str(query_path.relative_to(AI_GENERAL))
            except ValueError:
                pass
    except Exception:
        pass
    return query.strip("/")


def _resolve_role_ref_input(role_input: str) -> str | None:
    normalized = _normalize_role_query(role_input)
    role_ref = None

    candidate = AI_GENERAL / normalized
    if normalized and candidate.exists():
        role_ref = str(candidate.relative_to(AI_GENERAL))
    elif normalized.endswith(".yml"):
        candidate = ROLES_DIR / normalized
        if candidate.exists():
            role_ref = str(candidate.relative_to(AI_GENERAL))
    else:
        candidate = ROLES_DIR / "{}.yml".format(normalized)
        if candidate.exists():
            role_ref = str(candidate.relative_to(AI_GENERAL))

    return role_ref


# --- YAML helpers ---

def _read_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _write_yaml(path: Path, data: dict) -> None:
    import yaml
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


# --- Discovery ---

def list_traits() -> list[dict]:
    """List all traits with category, name, path."""
    results_by_slug = {}
    if not TRAITS_DIR.exists():
        return []
    for cat_dir in sorted(TRAITS_DIR.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith((".", "_")):
            continue
        for f in sorted(cat_dir.rglob("*")):
            if not f.is_file() and not f.is_symlink():
                continue
            if f.name.startswith("."):
                continue
            rel_parts = f.relative_to(cat_dir).parts
            parent_parts = rel_parts[:-1]
            if any(part.startswith((".", "_")) for part in parent_parts):
                continue
            if "versions" in parent_parts or "archive" in parent_parts:
                continue
            if len(rel_parts) > 2:
                continue
            if f.is_symlink() or (f.is_file() and f.suffix in (".yml", ".md", ".yaml")):
                base_name = _trait_base_name(f.name)
                slug = "{}/{}".format(cat_dir.name, base_name)
                candidate = {
                    "category": cat_dir.name,
                    "name": base_name,
                    "slug": slug,
                    "file": f.name,
                    "path": _logical_trait_path(cat_dir.name, base_name),
                    "ref_path": str(f.relative_to(AI_GENERAL)),
                    "abs_path": str(f),
                    "is_symlink": f.is_symlink(),
                }
                current = results_by_slug.get(slug)
                if current is None:
                    results_by_slug[slug] = candidate
                elif _trait_resolution_priority(candidate["file"]) < _trait_resolution_priority(current["file"]):
                    results_by_slug[slug] = candidate
    return [results_by_slug[key] for key in sorted(results_by_slug)]


def list_roles() -> list[dict]:
    """List all roles."""
    results = []
    if not ROLES_DIR.exists():
        return results
    for f in sorted(ROLES_DIR.iterdir()):
        if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
            data = _read_yaml(f)
            trait_refs = _extract_trait_refs(data)
            results.append({
                "id": f.stem,
                "name": data.get("name", f.stem),
                "description": (data.get("description") or "").strip()[:80],
                "traits": [_trait_slug_from_ref(ref) for ref in trait_refs],
                "trait_refs": trait_refs,
                "path": str(f.relative_to(AI_GENERAL)),
            })
    return results


def list_skills() -> list[dict]:
    """List all skills."""
    results = []
    if not SKILLS_DIR.exists():
        return results
    for f in sorted(SKILLS_DIR.iterdir()):
        if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
            data = _read_yaml(f)
            meta = data.get("metadata", {})
            trait_refs = _extract_trait_refs(data)
            results.append({
                "id": f.stem,
                "name": meta.get("name", f.stem),
                "description": (meta.get("description") or "").strip()[:80],
                "traits": [_trait_slug_from_ref(ref) for ref in trait_refs],
                "trait_refs": trait_refs,
                "path": str(f.relative_to(AI_GENERAL)),
            })
    return results


def list_profiles() -> list[dict]:
    """List all profiles (top-level yml in ai_profiles/)."""
    results = []
    if not PROFILES_DIR.exists():
        return results
    for f in sorted(PROFILES_DIR.iterdir()):
        if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
            data = _read_yaml(f)
            role_refs = data.get("roles", [])
            results.append({
                "id": f.stem,
                "name": data.get("name", f.stem),
                "description": (data.get("description") or "").strip()[:80],
                "roles": [_role_id_from_ref(role_ref) for role_ref in role_refs],
                "role_refs": role_refs,
                "path": str(f.relative_to(AI_GENERAL)),
            })
    return results


def list_platforms() -> list[dict]:
    """List all platforms."""
    results = []
    if not PLATFORMS_DIR.exists():
        return results
    for f in sorted(PLATFORMS_DIR.iterdir()):
        if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
            data = _read_yaml(f)
            trait_refs = _extract_trait_refs(data)
            results.append({
                "id": f.stem,
                "name": data.get("name", f.stem),
                "description": (data.get("description") or "").strip()[:80],
                "traits": [_trait_slug_from_ref(ref) for ref in trait_refs],
                "trait_refs": trait_refs,
                "path": str(f.relative_to(AI_GENERAL)),
            })
    return results


def list_globals() -> list[dict]:
    """List all globals."""
    results = []
    if not GLOBALS_DIR.exists():
        return results
    for f in sorted(GLOBALS_DIR.iterdir()):
        if f.is_file() and f.suffix == ".yml" and not f.name.startswith("."):
            data = _read_yaml(f)
            trait_refs = _extract_trait_refs(data)
            results.append({
                "id": f.stem,
                "name": data.get("name", f.stem),
                "description": (data.get("description") or "").strip()[:80],
                "traits": [_trait_slug_from_ref(ref) for ref in trait_refs],
                "trait_refs": trait_refs,
                "path": str(f.relative_to(AI_GENERAL)),
            })
    return results


def list_categories() -> list[dict]:
    """List categories with logical trait counts."""
    results = []
    traits = list_traits()
    for category in _discover_categories():
        count = len([trait for trait in traits if trait["category"] == category])
        results.append({
            "name": category,
            "traits": count,
        })
    return results


def library_status() -> dict:
    traits = list_traits()
    roles = list_roles()
    skills = list_skills()
    profiles = list_profiles()
    platforms = list_platforms()
    globals_ = list_globals()
    return {
        "traits": len(traits),
        "roles": len(roles),
        "skills": len(skills),
        "profiles": len(profiles),
        "platforms": len(platforms),
        "globals": len(globals_),
        "categories": len(list_categories()),
        "role_trait_links": sum(len(role["traits"]) for role in roles),
        "skill_trait_links": sum(len(skill["traits"]) for skill in skills),
        "profile_role_links": sum(len(profile["roles"]) for profile in profiles),
        "platform_trait_links": sum(len(platform["traits"]) for platform in platforms),
        "global_trait_links": sum(len(global_["traits"]) for global_ in globals_),
    }


def _resolve_trait_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    normalized = _normalize_trait_query(query)
    exact_matches = []
    name_matches = []
    partial_matches = []

    for trait in list_traits():
        ref_without_prefix = trait["ref_path"]
        if ref_without_prefix.startswith("ai_traits/"):
            ref_without_prefix = ref_without_prefix[len("ai_traits/"):]
        exact_candidates = {
            trait["slug"],
            trait["name"],
            trait["file"],
            trait["path"],
            trait["ref_path"],
            ref_without_prefix,
        }
        if normalized in exact_candidates or query in exact_candidates:
            exact_matches.append(trait)
        elif normalized == trait["name"]:
            name_matches.append(trait)
        elif normalized and (normalized in trait["slug"] or normalized in trait["name"]):
            partial_matches.append(trait)

    matches = exact_matches
    if not matches:
        matches = name_matches
    if not matches:
        matches = partial_matches

    if not matches:
        return None, "Trait not found: {}".format(query)

    if len(matches) > 1:
        options = ", ".join(match["slug"] for match in matches[:5])
        if len(matches) > 5:
            options = options + ", ..."
        return None, "Trait '{}' is ambiguous. Try one of: {}".format(query, options)

    return matches[0], None


def _public_trait_record(trait: dict) -> dict:
    return {
        "category": trait["category"],
        "name": trait["name"],
        "slug": trait["slug"],
        "path": trait["path"],
        "is_symlink": trait["is_symlink"],
    }


def _public_role_record(role: dict) -> dict:
    return {
        "id": role["id"],
        "name": role["name"],
        "description": role["description"],
        "traits": role["traits"],
        "path": role["path"],
    }


def _public_skill_record(skill: dict) -> dict:
    return {
        "id": skill["id"],
        "name": skill["name"],
        "description": skill["description"],
        "traits": skill["traits"],
        "path": skill["path"],
    }


def _public_profile_record(profile: dict) -> dict:
    return {
        "id": profile["id"],
        "name": profile["name"],
        "description": profile["description"],
        "roles": profile["roles"],
        "path": profile["path"],
    }


def _public_platform_record(platform: dict) -> dict:
    return {
        "id": platform["id"],
        "name": platform["name"],
        "description": platform["description"],
        "traits": platform["traits"],
        "path": platform["path"],
    }


def _public_global_record(global_record: dict) -> dict:
    return {
        "id": global_record["id"],
        "name": global_record["name"],
        "description": global_record["description"],
        "traits": global_record["traits"],
        "path": global_record["path"],
    }


def _resolve_trait_fs_path(trait_ref: str) -> Path | None:
    direct = Path(trait_ref) if str(trait_ref).startswith("/") else (AI_GENERAL / str(trait_ref))
    if direct.exists():
        return direct
    slug = _trait_slug_from_ref(trait_ref)
    for trait in list_traits():
        if trait["slug"] == slug:
            candidate = Path(trait["abs_path"])
            if candidate.exists():
                return candidate
    return None


def _resolve_role_fs_path(role_ref: str) -> Path | None:
    direct = Path(role_ref) if str(role_ref).startswith("/") else (AI_GENERAL / str(role_ref))
    if direct.exists():
        return direct
    resolved = _resolve_role_ref_input(role_ref)
    if resolved:
        candidate = AI_GENERAL / resolved
        if candidate.exists():
            return candidate
    return None


def _trait_ref_exists(trait_ref: str) -> bool:
    return _resolve_trait_fs_path(trait_ref) is not None


def _role_ref_exists(role_ref: str) -> bool:
    return _resolve_role_fs_path(role_ref) is not None


def _ref_exists(path_str: str) -> bool:
    text = str(path_str)
    if text.startswith("ai_traits/") or _trait_slug_from_ref(text) != _trait_base_name(text):
        return _trait_ref_exists(text)
    if text.startswith("ai_profiles/roles/") or text in {role["id"] for role in list_roles()}:
        return _role_ref_exists(text)
    path = Path(text) if text.startswith("/") else (AI_GENERAL / text)
    return path.exists()


def _missing_trait_refs(trait_refs: list[str]) -> list[str]:
    return [ref for ref in trait_refs if not _trait_ref_exists(ref)]


def _missing_role_refs(role_refs: list[str]) -> list[str]:
    return [ref for ref in role_refs if not _role_ref_exists(ref)]


def _trait_validation(trait: dict) -> dict:
    issues = []
    if not Path(trait["abs_path"]).exists():
        issues.append("broken path")
    return {"issues": issues}


def _role_validation(role: dict) -> dict:
    missing = _missing_trait_refs(role.get("trait_refs", []))
    return {"missing_traits": missing}


def _skill_validation(skill: dict) -> dict:
    missing = _missing_trait_refs(skill.get("trait_refs", []))
    return {"missing_traits": missing}


def _profile_validation(profile: dict) -> dict:
    missing = _missing_role_refs(profile.get("role_refs", []))
    return {"missing_roles": missing}


def _platform_validation(platform: dict) -> dict:
    missing = _missing_trait_refs(platform.get("trait_refs", []))
    return {"missing_traits": missing}


def _global_validation(global_record: dict) -> dict:
    missing = _missing_trait_refs(global_record.get("trait_refs", []))
    return {"missing_traits": missing}


def _resolve_named_record(records: list[dict], query: str, keys: tuple[str, ...], label: str) -> tuple[Optional[dict], Optional[str]]:
    normalized = _normalize_role_query(query).lower()
    exact = []
    partial = []
    for record in records:
        values = [str(record.get(key, "")).strip().lower() for key in keys]
        if normalized in values:
            exact.append(record)
        elif normalized and any(normalized in value for value in values):
            partial.append(record)

    matches = exact if exact else partial
    if not matches:
        return None, "{} not found: {}".format(label, query)
    if len(matches) > 1:
        options = ", ".join(match.get("id", match.get("slug", "?")) for match in matches[:5])
        if len(matches) > 5:
            options = options + ", ..."
        return None, "{} '{}' is ambiguous. Try one of: {}".format(label, query, options)
    return matches[0], None


def _resolve_role_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    return _resolve_named_record(list_roles(), query, ("id", "name", "path"), "Role")


def _resolve_skill_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    return _resolve_named_record(list_skills(), query, ("id", "name", "path"), "Skill")


def _resolve_profile_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    return _resolve_named_record(list_profiles(), query, ("id", "name", "path"), "Profile")


def _resolve_platform_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    return _resolve_named_record(list_platforms(), query, ("id", "name", "path"), "Platform")


def _resolve_global_record(query: str) -> tuple[Optional[dict], Optional[str]]:
    return _resolve_named_record(list_globals(), query, ("id", "name", "path"), "Global")


def _resolve_any_entity(query: str) -> tuple[Optional[str], Optional[dict], Optional[str]]:
    normalized = _normalize_role_query(query).lower()
    exact = []
    partial = []

    def add_matches(entity_type: str, record: dict, values: list[str]) -> None:
        lowered = [str(value).strip().lower() for value in values if str(value).strip()]
        entry = (entity_type, record)
        if normalized in lowered:
            exact.append(entry)
        elif normalized and any(normalized in value for value in lowered):
            partial.append(entry)

    for trait in list_traits():
        ref_without_prefix = trait["ref_path"]
        if ref_without_prefix.startswith("ai_traits/"):
            ref_without_prefix = ref_without_prefix[len("ai_traits/"):]
        add_matches("trait", trait, [trait["slug"], trait["name"], trait["path"], trait["ref_path"], ref_without_prefix, trait["file"]])
    for role in list_roles():
        add_matches("role", role, [role["id"], role["name"], role["path"]])
    for skill in list_skills():
        add_matches("skill", skill, [skill["id"], skill["name"], skill["path"]])
    for profile in list_profiles():
        add_matches("profile", profile, [profile["id"], profile["name"], profile["path"]])
    for platform in list_platforms():
        add_matches("platform", platform, [platform["id"], platform["name"], platform["path"]])
    for global_record in list_globals():
        add_matches("global", global_record, [global_record["id"], global_record["name"], global_record["path"]])

    matches = exact if exact else partial
    if not matches:
        return None, None, "No trait/role/skill/profile/platform/global found for '{}'.".format(query)
    if len(matches) > 1:
        options = ", ".join("{}:{}".format(entity_type, record.get("id", record.get("slug", "?"))) for entity_type, record in matches[:8])
        if len(matches) > 8:
            options = options + ", ..."
        return None, None, "Ambiguous identifier '{}'. Matches: {}".format(query, options)
    entity_type, record = matches[0]
    return entity_type, record, None


def _find_profiles_using_role(role_id: str) -> list[dict]:
    return [profile for profile in list_profiles() if role_id in profile.get("roles", [])]


def _find_roles_using_trait(trait_slug: str) -> list[dict]:
    return [role for role in list_roles() if trait_slug in role.get("traits", [])]


def _find_skills_using_trait(trait_slug: str) -> list[dict]:
    return [skill for skill in list_skills() if trait_slug in skill.get("traits", [])]


def _find_platforms_using_trait(trait_slug: str) -> list[dict]:
    return [platform for platform in list_platforms() if trait_slug in platform.get("traits", [])]


def _find_globals_using_trait(trait_slug: str) -> list[dict]:
    return [global_record for global_record in list_globals() if trait_slug in global_record.get("traits", [])]


def _resolve_trait_reference_context(query: str) -> tuple[Optional[dict], Optional[str]]:
    normalized = _trait_slug_from_ref(query)
    if not normalized or "/" not in normalized:
        return None, "Trait not found: {}".format(query)

    roles = _find_roles_using_trait(normalized)
    skills = _find_skills_using_trait(normalized)
    platforms = _find_platforms_using_trait(normalized)
    globals_ = _find_globals_using_trait(normalized)
    if not any((roles, skills, platforms, globals_)):
        return None, "Trait not found: {}".format(query)

    category, base_name = normalized.split("/", 1)
    return {
        "category": category,
        "name": base_name,
        "slug": normalized,
        "path": "ai_traits/{}".format(normalized),
        "ref_path": "ai_traits/{}".format(normalized),
        "abs_path": str(TRAITS_DIR / normalized),
        "is_symlink": False,
    }, None


def _format_trait_slug_display(slug: str) -> str:
    if "/" not in slug:
        return _styled_trait_name(slug)
    category, name = slug.split("/", 1)
    return "{}{}{}".format(
        c(category, "category"),
        c("/", "muted"),
        _styled_trait_name(name),
    )


def _format_missing_suffix(count: int, label: str = "missing") -> str:
    if count <= 0:
        return ""
    return " {}".format(c("({} {})".format(count, label), "error"))
def _extract_trait_refs(data: dict) -> list[str]:
    """Extract trait file references from a role/skill/platform YAML."""
    refs = []
    traits_section = data.get("traits", {})
    if isinstance(traits_section, dict):
        for category, paths in traits_section.items():
            if isinstance(paths, list):
                for item in paths:
                    if isinstance(item, str):
                        refs.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("path"), str):
                        refs.append(item["path"])
            elif isinstance(paths, str):
                refs.append(paths)
            elif isinstance(paths, dict) and isinstance(paths.get("path"), str):
                refs.append(paths["path"])
    elif isinstance(traits_section, list):
        for item in traits_section:
            if isinstance(item, str):
                refs.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                refs.append(item["path"])
    return refs


# --- View ---

def view_trait(name: str) -> str:
    """View a trait's content. Name can be category/stem or partial match."""
    trait, error_msg = _resolve_trait_record(name)
    if error_msg:
        return c(error_msg, "error")

    path = Path(trait["abs_path"])
    content = path.read_text()
    lines = [
        c("Trait: {}".format(trait["slug"]), "heading"),
        "  {} {}  {} {}".format(
            c("Category:", "label"), c(trait["category"], "category"),
            c("Name:", "label"), c(trait["name"], "trait")),
        "  {} {}".format(c("Path:", "label"), c(trait["path"], "path")),
        "",
        content[:2000],
    ]
    if len(content) > 2000:
        lines.append(c("\n... ({} chars total, showing first 2000)".format(len(content)), "muted"))
    return "\n".join(lines)


def view_role(name: str) -> str:
    """View a role definition."""
    for r in list_roles():
        if r["id"] == name or name in r["id"]:
            path = AI_GENERAL / r["path"]
            data = _read_yaml(path)
            lines = [
                c("Role: {}".format(r["name"]), "heading"),
                "  {} {}".format(c("ID:", "label"), c(r["id"], "role")),
                "",
                c("Description:", "subheading"),
                "  {}".format(data.get("description", "(none)").strip()),
                "",
            ]
            resp = data.get("responsibilities", {})
            if resp.get("ownership"):
                lines.append(c("Owns:", "subheading"))
                for item in resp["ownership"]:
                    lines.append("  {} {}".format(c("-", "success"), item))
            if resp.get("does_not_own"):
                lines.append(c("Does not own:", "subheading"))
                for item in resp["does_not_own"]:
                    lines.append("  {} {}".format(c("-", "error"), item))
            trait_refs = _extract_trait_refs(data)
            if trait_refs:
                lines.append("")
                lines.append(c("Linked Traits:", "subheading"))
                for ref in trait_refs:
                    exists = _trait_ref_exists(ref)
                    status = c("ok", "ok") if exists else c("MISSING", "error")
                    lines.append("  {} [{}]".format(_format_trait_slug_display(_trait_slug_from_ref(ref)), status))
            return "\n".join(lines)
    return c("Role not found: {}".format(name), "error")


def view_profile(name: str) -> str:
    """View a profile definition."""
    for p in list_profiles():
        if p["id"] == name or name in p["id"]:
            role_refs = p.get("role_refs", [])
            lines = [
                c("Profile: {}".format(p["name"]), "heading"),
                "  {} {}".format(c("ID:", "label"), c(p["id"], "profile")),
                "",
                c("Description:", "subheading"),
                "  {}".format(p["description"] or c("(none)", "muted")),
                "",
                c("Linked Roles:", "subheading"),
            ]
            for role_ref in role_refs:
                exists = _role_ref_exists(role_ref)
                status = c("ok", "ok") if exists else c("MISSING", "error")
                lines.append("  {} [{}]".format(c(_role_id_from_ref(role_ref), "role"), status))
            return "\n".join(lines)
    return c("Profile not found: {}".format(name), "error")


def _view_trait_linked_entity(entity_label: str, entity_style: str, item_id: str, item_name: str,
                              description: str, trait_refs: list[str]) -> str:
    lines = [
        c("{}: {}".format(entity_label, item_name), "heading"),
        "  {} {}".format(c("ID:", "label"), c(item_id, entity_style)),
        "",
        c("Description:", "subheading"),
        "  {}".format(description or c("(none)", "muted")),
    ]
    lines.append("")
    lines.append(c("Linked Traits:", "subheading"))
    if trait_refs:
        for ref in trait_refs:
            status = c("ok", "ok") if _ref_exists(ref) else c("MISSING", "error")
            lines.append("  {} [{}]".format(_format_trait_slug_display(_trait_slug_from_ref(ref)), status))
    else:
        lines.append(c("  (no traits linked)", "muted"))
    return "\n".join(lines)


def view_skill(name: str) -> str:
    """View a skill definition."""
    skill, error_msg = _resolve_skill_record(name)
    if error_msg:
        return c(error_msg, "error")
    return _view_trait_linked_entity(
        "Skill",
        "skill",
        skill["id"],
        skill["name"],
        skill["description"],
        skill.get("trait_refs", []),
    )


def view_platform(name: str) -> str:
    """View a platform definition."""
    platform, error_msg = _resolve_platform_record(name)
    if error_msg:
        return c(error_msg, "error")
    return _view_trait_linked_entity(
        "Platform",
        "platform",
        platform["id"],
        platform["name"],
        platform["description"],
        platform.get("trait_refs", []),
    )


def view_global(name: str) -> str:
    """View a global definition."""
    global_record, error_msg = _resolve_global_record(name)
    if error_msg:
        return c(error_msg, "error")
    return _view_trait_linked_entity(
        "Global",
        "global",
        global_record["id"],
        global_record["name"],
        global_record["description"],
        global_record.get("trait_refs", []),
    )


def _view_any(name: str) -> str:
    entity_type, record, error_msg = _resolve_any_entity(name)
    if error_msg:
        return c(error_msg, "error")
    if entity_type == "trait":
        return view_trait(record["slug"])
    if entity_type == "role":
        return view_role(record["id"])
    if entity_type == "skill":
        return view_skill(record["id"])
    if entity_type == "profile":
        return view_profile(record["id"])
    if entity_type == "platform":
        return view_platform(record["id"])
    if entity_type == "global":
        return view_global(record["id"])
    return c("Unsupported view type: {}".format(entity_type), "error")


# --- Link management ---

def link_trait_to_role(trait_path: str, role_id: str) -> str:
    """Add a trait reference to a role."""
    role_file = ROLES_DIR / "{}.yml".format(role_id)
    if not role_file.exists():
        return c("Role not found: {}".format(role_id), "error")

    trait_record, error_msg = _resolve_trait_record(trait_path)
    if error_msg:
        return c(error_msg, "error")

    data = _read_yaml(role_file)
    existing = _extract_trait_refs(data)
    target_ref = trait_record["ref_path"]
    target_slug = trait_record["slug"]
    existing_slugs = [_trait_slug_from_ref(ref) for ref in existing]
    if target_slug in existing_slugs:
        return c("Already linked: {} -> {}".format(target_slug, role_id), "muted")

    category = trait_record["category"]

    traits_section = data.get("traits", {})
    if not isinstance(traits_section, dict):
        traits_section = {}
    if category not in traits_section:
        traits_section[category] = []
    traits_section[category].append(target_ref)
    data["traits"] = traits_section
    _write_yaml(role_file, data)
    return "{} {} {} {} {}".format(
        c("+", "success"), c("linked", "success"),
        _format_trait_slug_display(target_slug), c("->", "muted"), c("role:" + role_id, "role"))


def link_role_to_profile(role_path: str, profile_id: str) -> str:
    """Add a role reference to a profile."""
    profile_file = PROFILES_DIR / "{}.yml".format(profile_id)
    if not profile_file.exists():
        return c("Profile not found: {}".format(profile_id), "error")

    resolved_role_ref = _resolve_role_ref_input(role_path)
    if not resolved_role_ref:
        return c("Role not found: {}".format(role_path), "error")

    data = _read_yaml(profile_file)
    roles = data.get("roles", [])
    role_id = _role_id_from_ref(resolved_role_ref)
    existing_role_ids = [_role_id_from_ref(role_ref) for role_ref in roles]
    if role_id in existing_role_ids:
        return c("Already linked: {} -> {}".format(role_id, profile_id), "muted")
    roles.append(resolved_role_ref)
    data["roles"] = roles
    _write_yaml(profile_file, data)
    return "{} {} {} {} {}".format(
        c("+", "success"), c("linked", "success"),
        c(role_id, "role"), c("->", "muted"), c("profile:" + profile_id, "profile"))


def unlink_trait_from_role(trait_path: str, role_id: str) -> str:
    """Remove a trait reference from a role."""
    role_file = ROLES_DIR / "{}.yml".format(role_id)
    if not role_file.exists():
        return c("Role not found: {}".format(role_id), "error")

    trait_record, error_msg = _resolve_trait_record(trait_path)
    if error_msg:
        return c(error_msg, "error")

    data = _read_yaml(role_file)
    traits_section = data.get("traits", {})
    found = False
    if isinstance(traits_section, dict):
        for cat, paths in traits_section.items():
            if isinstance(paths, list):
                retained = []
                for path in paths:
                    if _trait_slug_from_ref(path) == trait_record["slug"]:
                        found = True
                    else:
                        retained.append(path)
                traits_section[cat] = retained
    if found:
        data["traits"] = traits_section
        _write_yaml(role_file, data)
        return "{} {} {} {} {}".format(
            c("-", "warning"), c("unlinked", "warning"),
            _format_trait_slug_display(trait_record["slug"]), c("from", "muted"), c("role:" + role_id, "role"))
    return c("Not linked: {} in role:{}".format(trait_path, role_id), "muted")


def unlink_role_from_profile(role_path: str, profile_id: str) -> str:
    """Remove a role reference from a profile."""
    profile_file = PROFILES_DIR / "{}.yml".format(profile_id)
    if not profile_file.exists():
        return c("Profile not found: {}".format(profile_id), "error")

    resolved_role_ref = _resolve_role_ref_input(role_path)
    if not resolved_role_ref:
        return c("Role not found: {}".format(role_path), "error")

    data = _read_yaml(profile_file)
    roles = data.get("roles", [])
    role_id = _role_id_from_ref(resolved_role_ref)
    if role_id in [_role_id_from_ref(role_ref) for role_ref in roles]:
        roles = [role_ref for role_ref in roles if _role_id_from_ref(role_ref) != role_id]
        data["roles"] = roles
        _write_yaml(profile_file, data)
        return "{} {} {} {} {}".format(
            c("-", "warning"), c("unlinked", "warning"),
            c(role_id, "role"), c("from", "muted"), c("profile:" + profile_id, "profile"))
    return c("Not linked: {} in profile:{}".format(role_path, profile_id), "muted")


def _format_trait_ref_detail(trait_ref: str) -> str:
    slug = _trait_slug_from_ref(trait_ref)
    declared = str(trait_ref)
    canonical = "ai_traits/{}".format(slug)
    if declared not in (slug, canonical):
        return "{} {} {}{}".format(
            _format_trait_slug_display(slug),
            c("[declared:", "muted"),
            c(declared, "path"),
            c("]", "muted"),
        )
    return _format_trait_slug_display(slug)


def _format_role_ref_detail(role_ref: str) -> str:
    role_id = _role_id_from_ref(role_ref)
    declared = str(role_ref)
    canonical = "ai_profiles/roles/{}.yml".format(role_id)
    if declared not in (role_id, canonical):
        return "{} {} {}{}".format(
            c(role_id, "role"),
            c("[declared:", "muted"),
            c(declared, "path"),
            c("]", "muted"),
        )
    return c(role_id, "role")


def validate_targets(targets: list[str] | None = None) -> dict:
    selected = list(targets or ("traits", "roles", "skills", "profiles", "platforms", "globals"))
    results = {}

    if "traits" in selected:
        items = []
        for trait in list_traits():
            validation = _trait_validation(trait)
            if validation["issues"]:
                items.append({"id": trait["slug"], "issues": validation["issues"], "path": trait["path"]})
        results["traits"] = items

    if "roles" in selected:
        items = []
        for role in list_roles():
            validation = _role_validation(role)
            if validation["missing_traits"]:
                items.append({"id": role["id"], "missing_traits": validation["missing_traits"]})
        results["roles"] = items

    if "skills" in selected:
        items = []
        for skill in list_skills():
            validation = _skill_validation(skill)
            if validation["missing_traits"]:
                items.append({"id": skill["id"], "missing_traits": validation["missing_traits"]})
        results["skills"] = items

    if "profiles" in selected:
        items = []
        for profile in list_profiles():
            validation = _profile_validation(profile)
            if validation["missing_roles"]:
                items.append({"id": profile["id"], "missing_roles": validation["missing_roles"]})
        results["profiles"] = items

    if "platforms" in selected:
        items = []
        for platform in list_platforms():
            validation = _platform_validation(platform)
            if validation["missing_traits"]:
                items.append({"id": platform["id"], "missing_traits": validation["missing_traits"]})
        results["platforms"] = items

    if "globals" in selected:
        items = []
        for global_record in list_globals():
            validation = _global_validation(global_record)
            if validation["missing_traits"]:
                items.append({"id": global_record["id"], "missing_traits": validation["missing_traits"]})
        results["globals"] = items

    return results


def _validate_summary_count(results: dict) -> tuple[int, int]:
    item_count = 0
    issue_count = 0
    for section_items in results.values():
        item_count += len(section_items)
        for item in section_items:
            for key, value in item.items():
                if key.startswith("missing_") and isinstance(value, list):
                    issue_count += len(value)
                elif key == "issues" and isinstance(value, list):
                    issue_count += len(value)
    return item_count, issue_count


def render_validation(results: dict) -> str:
    lines = [c("Validation Report:", "heading"), ""]
    any_issues = False

    for section in ("traits", "roles", "skills", "profiles", "platforms", "globals"):
        items = results.get(section, [])
        if not items:
            continue
        any_issues = True
        lines.append(c("{}:".format(section.upper()), "subheading"))
        for item in items:
            lines.append("  {}".format(c(item["id"], section[:-1] if section != "globals" else "global")))
            if section == "traits":
                for issue in item.get("issues", []):
                    lines.append("    {} {}".format(c("-", "error"), c(issue, "error")))
            else:
                for trait_ref in item.get("missing_traits", []):
                    lines.append("    {} missing trait: {}".format(c("-", "error"), _format_trait_ref_detail(trait_ref)))
                for role_ref in item.get("missing_roles", []):
                    lines.append("    {} missing role: {}".format(c("-", "error"), _format_role_ref_detail(role_ref)))
        lines.append("")

    if not any_issues:
        lines.append(c("No missing links found.", "ok"))
    else:
        item_count, issue_count = _validate_summary_count(results)
        lines.append("{} {} across {} items".format(
            c("Summary:", "label"),
            c("{} issues".format(issue_count), "error"),
            c(str(item_count), "value"),
        ))
    return "\n".join(lines).rstrip()


def _tree_default_direction(entity_type: str) -> str:
    defaults = {
        "trait": "up",
        "role": "both",
        "skill": "down",
        "profile": "down",
        "platform": "down",
        "global": "down",
    }
    return defaults.get(entity_type, "both")


def _resolve_tree_args(args: list[str]) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
    if not args:
        return None, None, "both", "Usage: tree [<type>] <identifier> [up|down|both]"

    parsed = list(args)
    direction = None
    if parsed and parsed[-1].lower() in TREE_DIRECTIONS:
        direction = parsed.pop().lower()

    entity_type = None
    if parsed and VIEW_TYPE_ALIASES.get(parsed[0].lower()):
        entity_type = VIEW_TYPE_ALIASES.get(parsed.pop(0).lower())

    if not parsed:
        return None, None, "both", "Usage: tree [<type>] <identifier> [up|down|both]"

    identifier = " ".join(parsed)
    return entity_type, identifier, direction or "", None


def _render_profile_tree(profile: dict) -> list[str]:
    lines = [c("Profile: {}".format(profile["id"]), "heading")]
    role_refs = profile.get("role_refs", [])
    if not role_refs:
        lines.append(c("  (no roles linked)", "muted"))
        return lines
    for role_ref in role_refs:
        exists = _ref_exists(role_ref)
        role_id = _role_id_from_ref(role_ref)
        lines.append("  {} [{}]".format(c(role_id, "role"), c("ok", "ok") if exists else c("MISSING", "error")))
        if exists:
            role_record, _ = _resolve_role_record(role_id)
            if role_record:
                for trait_ref in role_record.get("trait_refs", []):
                    lines.append("    {} [{}]".format(
                        _format_trait_ref_detail(trait_ref),
                        c("ok", "ok") if _ref_exists(trait_ref) else c("MISSING", "error")))
    return lines


def _render_role_tree(role: dict, direction: str) -> list[str]:
    lines = [c("Role: {}".format(role["id"]), "heading")]
    if direction in ("down", "both"):
        lines.append(c("  Traits:", "subheading"))
        if role.get("trait_refs"):
            for trait_ref in role["trait_refs"]:
                lines.append("    {} [{}]".format(
                    _format_trait_ref_detail(trait_ref),
                    c("ok", "ok") if _ref_exists(trait_ref) else c("MISSING", "error")))
        else:
            lines.append(c("    (none)", "muted"))
    if direction in ("up", "both"):
        lines.append(c("  Profiles:", "subheading"))
        profiles = _find_profiles_using_role(role["id"])
        if profiles:
            for profile in profiles:
                lines.append("    {}".format(c(profile["id"], "profile")))
        else:
            lines.append(c("    (none)", "muted"))
    return lines


def _render_trait_tree(trait: dict) -> list[str]:
    lines = [c("Trait: {}".format(trait["slug"]), "heading")]
    exists = _ref_exists(trait.get("ref_path", trait.get("path", ""))) or Path(trait.get("abs_path", "")).exists()
    lines.append("  {} {}".format(c("Status:", "label"), c("ok", "ok") if exists else c("MISSING on disk", "error")))
    roles = _find_roles_using_trait(trait["slug"])
    skills = _find_skills_using_trait(trait["slug"])
    platforms = _find_platforms_using_trait(trait["slug"])
    globals_ = _find_globals_using_trait(trait["slug"])

    lines.append(c("  Roles:", "subheading"))
    if roles:
        for role in roles:
            missing_here = trait["slug"] in [_trait_slug_from_ref(ref) for ref in _role_validation(role)["missing_traits"]]
            status = c("MISSING", "error") if missing_here else c("ok", "ok")
            lines.append("    {} [{}]".format(c(role["id"], "role"), status))
            profiles = _find_profiles_using_role(role["id"])
            for profile in profiles:
                lines.append("      {} {}".format(c("↳", "muted"), c(profile["id"], "profile")))
    else:
        lines.append(c("    (none)", "muted"))

    for label, style, items, validator in (
        ("Skills", "skill", skills, _skill_validation),
        ("Platforms", "platform", platforms, _platform_validation),
        ("Globals", "global", globals_, _global_validation),
    ):
        lines.append(c("  {}:".format(label), "subheading"))
        if items:
            for item in items:
                missing_here = trait["slug"] in [_trait_slug_from_ref(ref) for ref in validator(item)["missing_traits"]]
                status = c("MISSING", "error") if missing_here else c("ok", "ok")
                lines.append("    {} [{}]".format(c(item["id"], style), status))
        else:
            lines.append(c("    (none)", "muted"))
    return lines


def _render_trait_linked_tree(entity_label: str, entity_style: str, item: dict) -> list[str]:
    lines = [c("{}: {}".format(entity_label, item["id"]), "heading")]
    lines.append(c("  Traits:", "subheading"))
    if item.get("trait_refs"):
        for trait_ref in item["trait_refs"]:
            lines.append("    {} [{}]".format(
                _format_trait_ref_detail(trait_ref),
                c("ok", "ok") if _ref_exists(trait_ref) else c("MISSING", "error")))
    else:
        lines.append(c("    (none)", "muted"))
    return lines


def render_tree(entity_type: str, record: dict, direction: str) -> str:
    effective_direction = direction or _tree_default_direction(entity_type)
    if entity_type == "profile":
        lines = _render_profile_tree(record)
    elif entity_type == "role":
        lines = _render_role_tree(record, effective_direction)
    elif entity_type == "trait":
        lines = _render_trait_tree(record)
    elif entity_type == "skill":
        lines = _render_trait_linked_tree("Skill", "skill", record)
    elif entity_type == "platform":
        lines = _render_trait_linked_tree("Platform", "platform", record)
    elif entity_type == "global":
        lines = _render_trait_linked_tree("Global", "global", record)
    else:
        return c("Unsupported tree type: {}".format(entity_type), "error")
    return "\n".join(lines)


# --- Help ---

_HELP_RAW = """\
trait_mgr -- inspect and manage AI traits, roles, skills, profiles, platforms, and globals (v{ver})

Usage:
    trait_mgr                          Interactive REPL mode
    trait_mgr <command> [args...]      One-shot CLI mode

Commands -- list:
    list [section...]       List traits/roles/skills/profiles/platforms/globals/categories
    ls [section...]         Alias for list

Commands -- status:
    status                  Summary counts

Commands -- view:
    view <identifier>       View a uniquely-matching trait/role/skill/profile/platform/global
    view trait <identifier> View trait details
    view role <identifier>  View role details
    view skill <identifier> View skill details
    view profile <identifier> View profile details
    view platform <identifier> View platform details
    view global <identifier> View global details

Commands -- link:
    link trait <slug_or_path> role <id>     Add trait to role
    link role <id_or_path> profile <id>     Add role to profile
    unlink trait <slug_or_path> role <id>   Remove trait from role
    unlink role <id_or_path> profile <id>   Remove role from profile

Commands -- graph / validation:
    tree [<type>] <identifier> [up|down|both]  Show linked dependency tree
    refs [<type>] <identifier> [up|down|both]  Alias for tree
    validate [section...]                      Show missing links / broken references

Options:
    --json            Structured JSON output
    --no-color        Disable colors

Categories:
    knowledge, perspective, methods, procedures, processes, reminders, templates

Trait references:
    Traits can be referenced as <category>/<slug> or ai_traits/<category>/<slug>.
    The manager resolves .latest / .latest.condensed variants automatically.

Identifiers:
    Use the value shown in list output:
    - trait: <category>/<slug>
    - role/skill/profile/platform/global: the short id shown in the first column
""".format(ver=VERSION)


def _brief_help() -> str:
    def _cmd(name, desc):
        return "  {:<36} {}".format(c(name, "command"), c(desc, "muted"))

    lines = [c("Trait Manager REPL Commands:", "heading")]

    lines.append("")
    lines.append(c("List:", "subheading"))
    lines.append(_cmd("list [section...]", "List traits/roles/skills/profiles/platforms/globals/categories"))
    lines.append(_cmd("ls [section...]", "Alias for list"))

    lines.append("")
    lines.append(c("Status:", "subheading"))
    lines.append(_cmd("status", "Summary counts"))

    lines.append("")
    lines.append(c("View:", "subheading"))
    lines.append(_cmd("view <identifier>", "View a uniquely-matching item"))
    lines.append(_cmd("view trait <identifier>", "View trait details"))
    lines.append(_cmd("view role <identifier>", "View role details"))
    lines.append(_cmd("view skill <identifier>", "View skill details"))
    lines.append(_cmd("view profile <identifier>", "View profile details"))
    lines.append(_cmd("view platform <identifier>", "View platform details"))
    lines.append(_cmd("view global <identifier>", "View global details"))

    lines.append("")
    lines.append(c("Link:", "subheading"))
    lines.append(_cmd("link trait <slug_or_path> role <id>", "Add trait to role"))
    lines.append(_cmd("link role <id_or_path> profile <id>", "Add role to profile"))
    lines.append(_cmd("unlink trait <slug_or_path> role <id>", "Remove trait from role"))
    lines.append(_cmd("unlink role <id_or_path> profile <id>", "Remove role from profile"))

    lines.append("")
    lines.append(c("Graph / Validation:", "subheading"))
    lines.append(_cmd("tree [<type>] <identifier> [dir]", "Show linked dependency tree"))
    lines.append(_cmd("refs [<type>] <identifier> [dir]", "Alias for tree"))
    lines.append(_cmd("validate [section...]", "Show missing links / broken references"))
    lines.append(_cmd("help", "This help"))
    lines.append(_cmd("quit / q", "Exit"))
    return "\n".join(lines)


# --- Commands ---

def _render_list_target(target: str, target_args: list[str]) -> str:
    if target == "traits":
        return cmd_traits(target_args)
    if target == "roles":
        return cmd_roles(target_args)
    if target == "skills":
        return cmd_skills(target_args)
    if target == "profiles":
        return cmd_profiles(target_args)
    if target == "platforms":
        return cmd_platforms(target_args)
    if target == "globals":
        return cmd_globals(target_args)
    if target == "categories":
        return cmd_categories(target_args)
    return c("Unknown list target: {}".format(target), "error")


def _trait_family(name: str) -> str:
    lowered = name.lower()
    known_prefixes = (
        "instr_",
        "protocol_",
        "playbook.",
        "workflow_",
        "spec_",
        "schema_",
        "know_",
        "arch_",
        "task_",
        "cli_",
    )
    for prefix in known_prefixes:
        if lowered.startswith(prefix):
            return prefix.rstrip("_.")
    return "other"


def _trait_family_style(family: str) -> str:
    return {
        "instr": "family_instr",
        "protocol": "family_protocol",
        "playbook": "family_playbook",
        "workflow": "family_workflow",
        "spec": "family_spec",
        "schema": "family_schema",
        "know": "family_know",
        "arch": "family_arch",
        "task": "family_task",
        "cli": "family_cli",
        "other": "family_other",
    }.get(family, "trait")


def _styled_trait_name(name: str) -> str:
    family = _trait_family(name)
    family_style = _trait_family_style(family)
    if family == "other":
        return c(name, family_style)

    if name.startswith(family + "_"):
        separator = "_"
    elif name.startswith(family + "."):
        separator = "."
    else:
        separator = ""

    prefix_len = len(family) + len(separator)
    remainder = name[prefix_len:]
    if not remainder:
        return c(name, family_style)

    return "{}{}{}".format(
        c(family, family_style),
        c(separator, "muted"),
        c(remainder, "value"),
    )


def cmd_list(args: list[str]) -> str:
    if not args:
        sections = [_render_list_target(target, []) for target in LIST_TARGETS]
        return "\n\n".join(sections)

    if args[0].lower() == "status":
        return c("Use 'status' as a separate command.", "error")

    first_target = LIST_TARGET_ALIASES.get(args[0].lower())
    if not first_target:
        valid = ", ".join(LIST_TARGETS)
        return c("Unknown list target: {}. Valid: {}".format(args[0], valid), "error")

    remaining_are_targets = True
    for arg in args[1:]:
        if not LIST_TARGET_ALIASES.get(arg.lower()):
            remaining_are_targets = False
            break

    if len(args) == 1 or not remaining_are_targets:
        return _render_list_target(first_target, args[1:])

    targets = []
    for arg in args:
        normalized = LIST_TARGET_ALIASES.get(arg.lower())
        if normalized and normalized not in targets:
            targets.append(normalized)
    sections = [_render_list_target(target, []) for target in targets]
    return "\n\n".join(sections)

def cmd_traits(args: list[str]) -> str:
    category = args[0] if args else None
    traits = list_traits()
    if category:
        traits = [t for t in traits if t["category"] == category]
        if not traits:
            return c("No traits in category '{}'. Valid: {}".format(category, ", ".join(_discover_categories())), "error")
    lines = []
    current_cat = None
    grouped: dict[str, dict[str, list[dict]]] = {}
    for trait in traits:
        grouped.setdefault(trait["category"], {}).setdefault(_trait_family(trait["name"]), []).append(trait)

    for cat in sorted(grouped):
        if cat != current_cat:
            current_cat = cat
            lines.append(c("\n{}:".format(current_cat.upper()), "heading"))
        family_groups = grouped[cat]
        family_order = sorted(family_groups, key=lambda family: (family == "other", family))
        for family in family_order:
            family_items = sorted(family_groups[family], key=lambda trait: trait["name"])
            if len(family_order) > 1 or family != "other":
                lines.append("  {} {}".format(c(family, _trait_family_style(family), "bold"), c("({})".format(len(family_items)), "muted")))
            for trait in family_items:
                sym = c(" @", "muted") if trait["is_symlink"] else ""
                validation = _trait_validation(trait)
                broken = ""
                if validation["issues"]:
                    broken = " " + c("(broken)", "error")
                indent = "    " if len(family_order) > 1 or family != "other" else "  "
                lines.append("{}{} {}{}{}".format(
                    indent,
                    c("•", "muted"),
                    _styled_trait_name(trait["name"]),
                    sym,
                    broken,
                ))
    lines.append(c("\n{} traits total".format(len(traits)), "muted"))
    return "\n".join(lines)


def cmd_roles(args: list[str]) -> str:
    if args:
        return c("Usage: list roles", "error")
    roles = list_roles()
    lines = [c("Roles ({}):\n".format(len(roles)), "heading")]
    for r in roles:
        trait_count = len(r["traits"])
        tc_color = "success" if trait_count > 0 else "muted"
        missing_count = len(_role_validation(r)["missing_traits"])
        lines.append("  {:<18s} {}  {}".format(
            c(r["id"], "role"),
            c("{} traits".format(trait_count), tc_color) + _format_missing_suffix(missing_count),
            c(r["description"][:50], "muted") if r["description"] else "",
        ))
    return "\n".join(lines)


def cmd_skills(args: list[str]) -> str:
    if args:
        return c("Usage: list skills", "error")
    skills = list_skills()
    lines = [c("Skills ({}):\n".format(len(skills)), "heading")]
    for s in skills:
        trait_count = len(s["traits"])
        tc_color = "success" if trait_count > 0 else "muted"
        missing_count = len(_skill_validation(s)["missing_traits"])
        lines.append("  {:<18s} {}  {}".format(
            c(s["id"], "skill"),
            c("{} traits".format(trait_count), tc_color) + _format_missing_suffix(missing_count),
            c(s["description"][:50], "muted") if s["description"] else "",
        ))
    return "\n".join(lines)


def cmd_profiles(args: list[str]) -> str:
    if args:
        return c("Usage: list profiles", "error")
    profiles = list_profiles()
    lines = [c("Profiles ({}):\n".format(len(profiles)), "heading")]
    for p in profiles:
        role_count = len(p["roles"])
        rc_color = "success" if role_count > 0 else "muted"
        missing_count = len(_profile_validation(p)["missing_roles"])
        lines.append("  {:<24s} {}  {}".format(
            c(p["id"], "profile"),
            c("{} roles".format(role_count), rc_color) + _format_missing_suffix(missing_count),
            c(p["description"][:50], "muted") if p["description"] else "",
        ))
    return "\n".join(lines)


def cmd_platforms(args: list[str]) -> str:
    if args:
        return c("Usage: list platforms", "error")
    platforms = list_platforms()
    lines = [c("Platforms ({}):\n".format(len(platforms)), "heading")]
    for platform in platforms:
        trait_count = len(platform["traits"])
        tc_color = "success" if trait_count > 0 else "muted"
        missing_count = len(_platform_validation(platform)["missing_traits"])
        lines.append("  {:<18s} {}  {}".format(
            c(platform["id"], "platform"),
            c("{} traits".format(trait_count), tc_color) + _format_missing_suffix(missing_count),
            c(platform["description"][:50], "muted") if platform["description"] else "",
        ))
    return "\n".join(lines)


def cmd_globals(args: list[str]) -> str:
    if args:
        return c("Usage: list globals", "error")
    globals_ = list_globals()
    lines = [c("Globals ({}):\n".format(len(globals_)), "heading")]
    for global_record in globals_:
        trait_count = len(global_record["traits"])
        tc_color = "success" if trait_count > 0 else "muted"
        missing_count = len(_global_validation(global_record)["missing_traits"])
        lines.append("  {:<18s} {}  {}".format(
            c(global_record["id"], "global"),
            c("{} traits".format(trait_count), tc_color) + _format_missing_suffix(missing_count),
            c(global_record["description"][:50], "muted") if global_record["description"] else "",
        ))
    return "\n".join(lines)


def cmd_categories(args: list[str]) -> str:
    if args:
        return c("Usage: list categories", "error")
    lines = [c("Trait Categories:\n", "heading")]
    for category in list_categories():
        count_color = "success" if category["traits"] > 0 else "muted"
        lines.append("  {:<16s} {}".format(
            c(category["name"], "category"),
            c("{} items".format(category["traits"]), count_color)))
    return "\n".join(lines)


def cmd_status(args: list[str]) -> str:
    if args:
        return c("Usage: status", "error")

    summary = library_status()

    lines = [
        c("Trait/Profile Library Status:\n", "heading"),
        "  {}  {}".format(c("Traits:    ", "label"), c(str(summary["traits"]), "trait")),
        "  {}  {}".format(c("Roles:     ", "label"), c(str(summary["roles"]), "role")),
        "  {}  {}".format(c("Skills:    ", "label"), c(str(summary["skills"]), "skill")),
        "  {}  {}".format(c("Profiles:  ", "label"), c(str(summary["profiles"]), "profile")),
        "  {}  {}".format(c("Platforms: ", "label"), c(str(summary["platforms"]), "platform")),
        "  {}  {}".format(c("Globals:   ", "label"), c(str(summary["globals"]), "global")),
        "  {}  {}".format(c("Categories:", "label"), c(str(summary["categories"]), "category")),
        "",
        "  {}  {}".format(c("Role->Traits links:    ", "muted"), c(str(summary["role_trait_links"]), "value")),
        "  {}  {}".format(c("Skill->Traits links:   ", "muted"), c(str(summary["skill_trait_links"]), "value")),
        "  {}  {}".format(c("Profile->Roles links:  ", "muted"), c(str(summary["profile_role_links"]), "value")),
        "  {}  {}".format(c("Platform->Traits links:", "muted"), c(str(summary["platform_trait_links"]), "value")),
        "  {}  {}".format(c("Global->Traits links:  ", "muted"), c(str(summary["global_trait_links"]), "value")),
    ]
    return "\n".join(lines)


def cmd_tree(args: list[str]) -> str:
    entity_type, identifier, direction, usage_error = _resolve_tree_args(args)
    if usage_error:
        return c(usage_error, "error")

    if entity_type is None:
        entity_type, record, error_msg = _resolve_any_entity(identifier)
        if error_msg:
            trait_record, trait_error = _resolve_trait_reference_context(identifier)
            if trait_record:
                entity_type = "trait"
                record = trait_record
                error_msg = None
    else:
        record = None
        error_msg = None
        if entity_type == "trait":
            record, error_msg = _resolve_trait_record(identifier)
            if error_msg:
                record, fallback_error = _resolve_trait_reference_context(identifier)
                if record:
                    error_msg = None
        elif entity_type == "role":
            record, error_msg = _resolve_role_record(identifier)
        elif entity_type == "skill":
            record, error_msg = _resolve_skill_record(identifier)
        elif entity_type == "profile":
            record, error_msg = _resolve_profile_record(identifier)
        elif entity_type == "platform":
            record, error_msg = _resolve_platform_record(identifier)
        elif entity_type == "global":
            record, error_msg = _resolve_global_record(identifier)
        else:
            error_msg = "Unsupported tree type: {}".format(entity_type)

    if error_msg:
        return c(error_msg, "error")
    return render_tree(entity_type, record, direction)


def cmd_refs(args: list[str]) -> str:
    """Alias for tree."""
    return cmd_tree(args)


def cmd_validate(args: list[str]) -> str:
    if not args:
        targets = ["traits", "roles", "skills", "profiles", "platforms", "globals"]
    else:
        targets = []
        for arg in args:
            normalized = LIST_TARGET_ALIASES.get(arg.lower(), arg.lower())
            if normalized not in ("traits", "roles", "skills", "profiles", "platforms", "globals"):
                return c("Unknown validate target: {}. Valid: traits, roles, skills, profiles, platforms, globals".format(arg), "error")
            if normalized not in targets:
                targets.append(normalized)
    return render_validation(validate_targets(targets))


def _completion_identifiers(entity_type: str | None = None) -> list[str]:
    if entity_type == "trait":
        return [trait["slug"] for trait in list_traits()]
    if entity_type == "role":
        return [role["id"] for role in list_roles()]
    if entity_type == "skill":
        return [skill["id"] for skill in list_skills()]
    if entity_type == "profile":
        return [profile["id"] for profile in list_profiles()]
    if entity_type == "platform":
        return [platform["id"] for platform in list_platforms()]
    if entity_type == "global":
        return [global_record["id"] for global_record in list_globals()]

    items = []
    items.extend(_completion_identifiers("trait"))
    items.extend(_completion_identifiers("role"))
    items.extend(_completion_identifiers("skill"))
    items.extend(_completion_identifiers("profile"))
    items.extend(_completion_identifiers("platform"))
    items.extend(_completion_identifiers("global"))
    return sorted(set(items))


def make_trait_mgr_completer():
    import readline

    commands = [
        "list", "ls", "status", "view", "link", "unlink",
        "tree", "refs", "validate", "help", "quit", "exit", "q",
    ]
    legacy_aliases = ["traits", "roles", "skills", "profiles", "platforms", "globals", "categories"]
    view_types = sorted(set(VIEW_TYPE_ALIASES))
    link_types = ["trait", "role", "profile"]
    validate_targets = ["traits", "roles", "skills", "profiles", "platforms", "globals"]

    def _matches(options: list[str], text: str) -> list[str]:
        seen = []
        for option in options:
            if option.startswith(text) and option not in seen:
                seen.append(option)
        return seen

    def completer(text: str, state: int) -> str | None:
        line = readline.get_line_buffer()
        begidx = readline.get_begidx()
        before = line[:begidx]
        try:
            tokens = shlex.split(before)
        except ValueError:
            tokens = before.split()

        suggestions: list[str] = []
        cmd = tokens[0].lower() if tokens else ""

        if begidx == 0:
            suggestions = _matches(commands + legacy_aliases, text)
        elif cmd in ("list", "ls", *legacy_aliases):
            if cmd in legacy_aliases:
                suggestions = _matches([], text)
            else:
                suggestions = _matches(list(LIST_TARGETS), text)
        elif cmd == "validate":
            suggestions = _matches(validate_targets, text)
        elif cmd == "view":
            if len(tokens) <= 1:
                suggestions = _matches(view_types + _completion_identifiers(), text)
            else:
                entity_type = VIEW_TYPE_ALIASES.get(tokens[1].lower())
                suggestions = _matches(_completion_identifiers(entity_type), text)
        elif cmd in ("tree", "refs"):
            if len(tokens) <= 1:
                suggestions = _matches(view_types + _completion_identifiers() + sorted(TREE_DIRECTIONS), text)
            elif len(tokens) == 2:
                entity_type = VIEW_TYPE_ALIASES.get(tokens[1].lower())
                if entity_type:
                    suggestions = _matches(_completion_identifiers(entity_type), text)
                else:
                    suggestions = _matches(_completion_identifiers() + sorted(TREE_DIRECTIONS), text)
            else:
                entity_type = VIEW_TYPE_ALIASES.get(tokens[1].lower())
                suggestions = _matches(sorted(TREE_DIRECTIONS) if entity_type else _completion_identifiers() + sorted(TREE_DIRECTIONS), text)
        elif cmd in ("link", "unlink"):
            if len(tokens) <= 1:
                suggestions = _matches(link_types, text)
            elif tokens[1] == "trait":
                if len(tokens) == 2:
                    suggestions = _matches(_completion_identifiers("trait"), text)
                elif len(tokens) == 3:
                    suggestions = _matches(["role"], text)
                else:
                    suggestions = _matches(_completion_identifiers("role"), text)
            elif tokens[1] == "role":
                if len(tokens) == 2:
                    suggestions = _matches(_completion_identifiers("role"), text)
                elif len(tokens) == 3:
                    suggestions = _matches(["profile"], text)
                else:
                    suggestions = _matches(_completion_identifiers("profile"), text)
        else:
            suggestions = _matches(commands + legacy_aliases, text)

        return suggestions[state] if state < len(suggestions) else None

    return completer


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
    cmd_aliases = {
        "ls": "list",
        "traits": "list",
        "roles": "list",
        "skills": "list",
        "profiles": "list",
        "platforms": "list",
        "globals": "list",
        "categories": "list",
    }
    cmd = cmd_aliases.get(cmd, cmd)

    if cmd == "list":
        if parts[0].lower() != "list" and parts[0].lower() != "ls":
            return cmd_list([parts[0].lower()] + args)
        return cmd_list(args)
    elif cmd == "status":
        return cmd_status(args)
    elif cmd == "view":
        if not args:
            return c("Usage: view [<type>] <identifier>", "error")
        first = VIEW_TYPE_ALIASES.get(args[0].lower())
        if first:
            if len(args) < 2:
                return c("Usage: view {} <identifier>".format(args[0].lower()), "error")
            vname = " ".join(args[1:])
            if first == "trait":
                return view_trait(vname)
            if first == "role":
                return view_role(vname)
            if first == "skill":
                return view_skill(vname)
            if first == "profile":
                return view_profile(vname)
            if first == "platform":
                return view_platform(vname)
            if first == "global":
                return view_global(vname)
        return _view_any(" ".join(args))
    elif cmd == "link":
        # link trait <path> role <id>  OR  link role <path> profile <id>
        if len(args) >= 4 and args[0] == "trait" and args[2] == "role":
            return link_trait_to_role(args[1], args[3])
        elif len(args) >= 4 and args[0] == "role" and args[2] == "profile":
            return link_role_to_profile(args[1], args[3])
        return c("Usage: link trait <slug_or_path> role <id>  OR  link role <id_or_path> profile <id>", "error")
    elif cmd == "unlink":
        if len(args) >= 4 and args[0] == "trait" and args[2] == "role":
            return unlink_trait_from_role(args[1], args[3])
        elif len(args) >= 4 and args[0] == "role" and args[2] == "profile":
            return unlink_role_from_profile(args[1], args[3])
        return c("Usage: unlink trait <slug_or_path> role <id>  OR  unlink role <id_or_path> profile <id>", "error")
    elif cmd == "refs":
        return cmd_refs(args)
    elif cmd == "tree":
        return cmd_tree(args)
    elif cmd == "validate":
        return cmd_validate(args)
    elif cmd == "help":
        return _brief_help()
    elif cmd in ("quit", "exit", "q") and interactive:
        return None
    else:
        return c("Unknown command: {}. Try 'help'.".format(cmd), "warning")


# --- REPL ---

def repl() -> None:
    from uai_toolkit.common_utils.lib_readline import setup_readline
    setup_readline(
        history_file=HISTORY_FILE,
        history_length=200,
        completer=make_trait_mgr_completer(),
    )

    print("{} -- type 'help' for commands, 'q' to quit".format(bold("Trait Manager REPL")))
    print(run_command("status"))
    print()

    while True:
        try:
            prompt = "{}{}{} ".format(c("trait", "trait"), c(":", "muted"), c(">", "muted"))
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
    legacy_list_aliases = {"traits", "roles", "skills", "profiles", "platforms", "globals", "categories"}

    try:
        if cmd in legacy_list_aliases:
            cmd_args = [cmd] + cmd_args
            cmd = "list"

        if cmd in ("list", "ls"):
            if not cmd_args:
                result = {
                    "traits": [_public_trait_record(trait) for trait in list_traits()],
                    "roles": [_public_role_record(role) for role in list_roles()],
                    "skills": [_public_skill_record(skill) for skill in list_skills()],
                    "profiles": [_public_profile_record(profile) for profile in list_profiles()],
                    "platforms": [_public_platform_record(platform) for platform in list_platforms()],
                    "globals": [_public_global_record(global_record) for global_record in list_globals()],
                    "categories": list_categories(),
                }
            elif cmd_args[0].lower() == "status":
                result = {"error": "Use status as a separate command."}
            else:
                target = LIST_TARGET_ALIASES.get(cmd_args[0].lower())
                if target == "traits":
                    category = cmd_args[1] if len(cmd_args) > 1 else None
                    traits = list_traits()
                    if category:
                        traits = [trait for trait in traits if trait["category"] == category]
                    result = {"traits": [_public_trait_record(trait) for trait in traits], "count": len(traits)}
                elif target == "roles":
                    roles = list_roles()
                    result = {"roles": [_public_role_record(role) for role in roles], "count": len(roles)}
                elif target == "skills":
                    skills = list_skills()
                    result = {"skills": [_public_skill_record(skill) for skill in skills], "count": len(skills)}
                elif target == "profiles":
                    profiles = list_profiles()
                    result = {"profiles": [_public_profile_record(profile) for profile in profiles], "count": len(profiles)}
                elif target == "platforms":
                    platforms = list_platforms()
                    result = {"platforms": [_public_platform_record(platform) for platform in platforms], "count": len(platforms)}
                elif target == "globals":
                    globals_ = list_globals()
                    result = {"globals": [_public_global_record(global_record) for global_record in globals_], "count": len(globals_)}
                elif target == "categories":
                    categories = list_categories()
                    result = {"categories": categories, "count": len(categories)}
                else:
                    result = {"error": "Unknown list target: {}".format(cmd_args[0])}
        elif cmd == "status":
            result = library_status()
        elif cmd in ("validate",):
            targets = []
            for arg in cmd_args:
                normalized = LIST_TARGET_ALIASES.get(arg.lower(), arg.lower())
                if normalized not in ("traits", "roles", "skills", "profiles", "platforms", "globals"):
                    result = {"error": "Unknown validate target: {}".format(arg)}
                    break
                if normalized not in targets:
                    targets.append(normalized)
            else:
                result = validate_targets(targets or None)
        elif cmd in ("tree", "refs"):
            entity_type, identifier, direction, usage_error = _resolve_tree_args(cmd_args)
            if usage_error:
                result = {"error": usage_error}
            else:
                if entity_type is None:
                    entity_type, record, error_msg = _resolve_any_entity(identifier)
                    if error_msg:
                        trait_record, trait_error = _resolve_trait_reference_context(identifier)
                        if trait_record:
                            entity_type = "trait"
                            record = trait_record
                            error_msg = None
                else:
                    resolver_map = {
                        "trait": _resolve_trait_record,
                        "role": _resolve_role_record,
                        "skill": _resolve_skill_record,
                        "profile": _resolve_profile_record,
                        "platform": _resolve_platform_record,
                        "global": _resolve_global_record,
                    }
                    record, error_msg = resolver_map[entity_type](identifier)
                    if entity_type == "trait" and error_msg:
                        record, fallback_error = _resolve_trait_reference_context(identifier)
                        if record:
                            error_msg = None
                if error_msg:
                    result = {"error": error_msg}
                else:
                    result = {
                        "type": entity_type,
                        "identifier": record.get("id", record.get("slug")),
                        "direction": direction or _tree_default_direction(entity_type),
                        "tree": render_tree(entity_type, record, direction),
                    }
        elif cmd == "view":
            if not cmd_args:
                result = {"error": "Usage: view <identifier>"}
            else:
                # Optional typed view: view trait <id>, view role <id>, etc.
                view_type = None
                identifier = cmd_args[0]
                if len(cmd_args) >= 2 and cmd_args[0] in ("trait", "role", "skill", "profile", "platform", "global"):
                    view_type = cmd_args[0]
                    identifier = cmd_args[1]

                entity_type, record, error_msg = (None, None, None)
                if view_type:
                    resolver_map = {
                        "trait": _resolve_trait_record,
                        "role": _resolve_role_record,
                        "skill": _resolve_skill_record,
                        "profile": _resolve_profile_record,
                        "platform": _resolve_platform_record,
                        "global": _resolve_global_record,
                    }
                    record, error_msg = resolver_map[view_type](identifier)
                    entity_type = view_type
                    if entity_type == "trait" and error_msg:
                        record, fallback_error = _resolve_trait_reference_context(identifier)
                        if record:
                            error_msg = None
                else:
                    entity_type, record, error_msg = _resolve_any_entity(identifier)

                if error_msg:
                    result = {"error": error_msg}
                else:
                    file_path = record.get("abs_path") or record.get("path", "")
                    # Resolve relative paths against AI_GENERAL
                    resolved = Path(file_path)
                    if not resolved.is_absolute():
                        resolved = AI_GENERAL / file_path
                    content = ""
                    if resolved.exists():
                        try:
                            content = resolved.read_text()
                        except Exception:
                            content = "(file not readable)"
                    file_path = str(resolved)
                    result = {
                        "type": entity_type,
                        "identifier": record.get("id", record.get("slug", identifier)),
                        "path": file_path,
                        "content": content,
                    }
        elif cmd == "link" and len(cmd_args) >= 4:
            if cmd_args[0] == "trait" and cmd_args[2] == "role":
                msg = link_trait_to_role(cmd_args[1], cmd_args[3])
                result = {"success": True, "message": msg}
            elif cmd_args[0] == "role" and cmd_args[2] == "profile":
                msg = link_role_to_profile(cmd_args[1], cmd_args[3])
                result = {"success": True, "message": msg}
            else:
                result = {"error": "Usage: link trait <slug_or_path> role <id>"}
        elif cmd == "unlink" and len(cmd_args) >= 4:
            if cmd_args[0] == "trait" and cmd_args[2] == "role":
                msg = unlink_trait_from_role(cmd_args[1], cmd_args[3])
                result = {"success": True, "message": msg}
            elif cmd_args[0] == "role" and cmd_args[2] == "profile":
                msg = unlink_role_from_profile(cmd_args[1], cmd_args[3])
                result = {"success": True, "message": msg}
            else:
                result = {"error": "Usage: unlink trait <slug_or_path> role <id>"}
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
            print("trait_mgr v{}".format(VERSION))
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
