"""
Guidance library — business logic for the Guidance MCP server.

Provides trait/role/skill/profile resolution, assembly, search, and reminders.
All functions are synchronous and return plain strings or dicts.
The MCP server.py is a thin wrapper that imports from here.
"""

import os
import re
import sqlite3
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# === Path configuration ===

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
AI_GENERAL = AI_ROOT / "ai_general"
TRAITS_DIR = AI_GENERAL / "ai_context_files"  # was the ai_traits symlink (now removed)
PROFILES_DIR = AI_GENERAL / "ai_profiles"
GLOBALS_DIR = AI_GENERAL / "ai_context_files" / "globals"
DB_PATH = AI_GENERAL / "data" / "context_files" / "context_files_registry.db"


# === Database access ===

def get_db() -> Optional[sqlite3.Connection]:
    """Get a fresh SQLite connection. Returns None if DB doesn't exist."""
    if not DB_PATH.exists():
        return None
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


def db_missing_msg() -> str:
    return (
        "Registry database not found. Run:\n"
        "  python3 scripts/context_files/scan_traits_registry.py --full\n"
        "from ai_general/ to build it."
    )


# === File reading ===

def read_file_content(path: Path) -> str:
    """Read a file, following symlinks."""
    try:
        resolved = path.resolve()
        if not resolved.exists():
            return f"[File not found: {path}]"
        return resolved.read_text()
    except Exception as e:
        return f"[Error reading {path}: {e}]"


def read_trait(rel_path: str) -> str:
    """Read a trait file by path relative to ai_general/."""
    text = str(rel_path or "").strip()
    if text.startswith("ai_traits/") or text.startswith("ai_context_files/"):
        return read_file_content(AI_GENERAL / text)

    normalized = normalize_trait_identifier(text)
    suffixes = (
        ".latest.condensed.yml",
        ".latest.yml",
        ".latest.md",
        ".condensed.yml",
        ".yml",
        ".yaml",
        ".md",
    )
    for suffix in suffixes:
        candidate = TRAITS_DIR / f"{normalized}{suffix}"
        if candidate.exists() or candidate.is_symlink():
            return read_file_content(candidate)

    candidate = TRAITS_DIR / normalized
    if candidate.exists() or candidate.is_symlink():
        return read_file_content(candidate)

    return f"[Trait not found: {rel_path}]"


def load_yaml_file(path: Path) -> dict:
    """Load a YAML file, returning empty dict on failure."""
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _trait_base_name(filename: str) -> str:
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


def normalize_trait_identifier(identifier: str) -> str:
    text = str(identifier or "").strip().replace("\\", "/")
    for _pfx in ("ai_context_files/", "ai_traits/"):
        if text.startswith(_pfx):
            text = text[len(_pfx):]
            break
    if text.startswith("/"):
        for _marker in ("/ai_context_files/", "/ai_traits/"):
            _parts = text.split(_marker, 1)
            if len(_parts) == 2:
                text = _parts[1]
                break
    if "/" not in text:
        return _trait_base_name(text)
    parts = text.split("/")
    category = "/".join(parts[:-1])
    return f"{category}/{_trait_base_name(parts[-1])}"


# === Resolution: id -> path ===

def resolve_item(db: sqlite3.Connection, identifier: str) -> Optional[dict]:
    """Resolve an identifier to an item using the resolution order:
    1. Exact id
    2. Exact alias
    3. Exact path match (in content_files)
    4. Name match (case-insensitive)
    5. FTS-ranked match
    Returns dict with id, name, category, preferred path, or None.
    """
    # 1. Exact id
    row = db.execute("SELECT * FROM content_items WHERE id = ?", (identifier,)).fetchone()
    if row:
        pref = db.execute(
            "SELECT path FROM content_files WHERE item_id = ? ORDER BY is_preferred DESC LIMIT 1",
            (row["id"],)
        ).fetchone()
        return {**dict(row), "preferred_path": pref["path"] if pref else None}

    # 2. Exact alias
    alias_row = db.execute("SELECT item_id FROM item_aliases WHERE alias = ?", (identifier,)).fetchone()
    if alias_row:
        row = db.execute("SELECT * FROM content_items WHERE id = ?", (alias_row["item_id"],)).fetchone()
        if row:
            pref = db.execute(
                "SELECT path FROM content_files WHERE item_id = ? ORDER BY is_preferred DESC LIMIT 1",
                (row["id"],)
            ).fetchone()
            return {**dict(row), "preferred_path": pref["path"] if pref else None}

    # 3. Exact path match
    file_row = db.execute("SELECT item_id FROM content_files WHERE path = ?", (identifier,)).fetchone()
    if file_row:
        row = db.execute("SELECT * FROM content_items WHERE id = ?", (file_row["item_id"],)).fetchone()
        if row:
            return {**dict(row), "preferred_path": identifier}

    # 4. Name match (case-insensitive)
    row = db.execute("SELECT * FROM content_items WHERE LOWER(name) = LOWER(?)", (identifier,)).fetchone()
    if row:
        pref = db.execute(
            "SELECT path FROM content_files WHERE item_id = ? ORDER BY is_preferred DESC LIMIT 1",
            (row["id"],)
        ).fetchone()
        return {**dict(row), "preferred_path": pref["path"] if pref else None}

    # 5. FTS match
    try:
        fts_row = db.execute(
            "SELECT item_id FROM content_fts WHERE content_fts MATCH ? LIMIT 1",
            (identifier,)
        ).fetchone()
        if fts_row:
            row = db.execute("SELECT * FROM content_items WHERE id = ?", (fts_row["item_id"],)).fetchone()
            if row:
                pref = db.execute(
                    "SELECT path FROM content_files WHERE item_id = ? ORDER BY is_preferred DESC LIMIT 1",
                    (row["id"],)
                ).fetchone()
                return {**dict(row), "preferred_path": pref["path"] if pref else None}
    except Exception:
        pass  # FTS query syntax errors are non-fatal

    return None


def render_trait_content(identifier: str, db: Optional[sqlite3.Connection], include_header: bool = True) -> str:
    """Resolve and render a trait/knowledge item using the same logic as get_trait."""
    if db:
        item = resolve_item(db, identifier)
        if item and item.get("preferred_path"):
            content = read_trait(item["preferred_path"])
            if include_header:
                header = (
                    f"# {item['name']}\n"
                    f"**Category:** {item.get('category', '')} | "
                    f"**Status:** {item.get('status', '')} | "
                    f"**Version:** {item.get('version', '')}\n\n"
                )
                return header + content
            return content

    normalized = normalize_trait_identifier(identifier)
    if normalized:
        content = read_trait(normalized)
        if not content.startswith("["):
            return content
    return f"[Trait not found: {identifier}]"


# === Role/skill/profile assembly ===

def assemble_role(role_name: str, db: Optional[sqlite3.Connection] = None) -> str:
    """Assemble a role definition with its referenced trait content."""
    role_path = PROFILES_DIR / "roles" / f"{role_name}.yml"
    if not role_path.exists():
        return f"[Role not found: {role_name}]"

    role = load_yaml_file(role_path)
    lines = []

    lines.append(f"# Role: {role.get('name', role_name)}")
    lines.append("")
    desc = role.get("description", "")
    if desc:
        lines.append(desc.strip())
        lines.append("")

    resp = role.get("responsibilities", {})
    if resp:
        duties = resp.get("duties", [])
        if duties:
            lines.append("## Duties")
            for d in duties:
                if isinstance(d, dict):
                    lines.append(f"- **{d.get('name', '')}** ({d.get('schedule', '')}): {d.get('action', '')}")
                else:
                    lines.append(f"- {d}")
            lines.append("")

        ownership = resp.get("ownership", [])
        if ownership:
            lines.append("## Ownership")
            for o in ownership:
                lines.append(f"- {o}")
            lines.append("")

        not_own = resp.get("does_not_own", [])
        if not_own:
            lines.append("## Does Not Own")
            for n in not_own:
                lines.append(f"- {n}")
            lines.append("")

    # Referenced context files (key renamed traits -> context_files; accept both
    # during the todo_0319 transition).
    traits = role.get("context_files", role.get("traits", {}))
    if isinstance(traits, list):
        trait_paths = traits
    elif isinstance(traits, dict):
        trait_paths = []
        for category_list in traits.values():
            if isinstance(category_list, list):
                trait_paths.extend(category_list)
    else:
        trait_paths = []

    if trait_paths:
        lines.append("---")
        lines.append("## Referenced Traits")
        lines.append("")
        for tp in trait_paths:
            path_str = tp if isinstance(tp, str) else tp.get("path", str(tp)) if isinstance(tp, dict) else str(tp)
            lines.append(f"### {Path(path_str).stem}")
            lines.append("")
            lines.append(render_trait_content(path_str, db, include_header=False))
            lines.append("")

    return "\n".join(lines)


def assemble_skill(skill_name: str) -> str:
    """Load a skill definition and return formatted content."""
    skill_path = PROFILES_DIR / "skills" / f"{skill_name}.yml"
    if not skill_path.exists():
        skill_path = PROFILES_DIR / "skills" / f"{skill_name.replace('-', '_')}.yml"
    if not skill_path.exists():
        return f"[Skill not found: {skill_name}]"
    return read_file_content(skill_path)


# === Reminders ===

def resolve_reminders() -> str:
    """Load all reminder files and resolve dynamic variables."""
    reminders_dir = TRAITS_DIR / "reminders"
    if not reminders_dir.exists():
        return "No reminders configured."

    lines = []
    now = datetime.now(timezone.utc)

    for f in sorted(reminders_dir.glob("*.md")):
        content = f.read_text()
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()

        content = content.replace("{timestamp}", now.strftime("%Y-%m-%d %H:%M:%S UTC"))
        content = content.replace("{date}", now.strftime("%Y-%m-%d"))
        content = content.replace("{time}", now.strftime("%H:%M"))

        lines.append(content)
        lines.append("")

    return "\n".join(lines) if lines else "No reminders found."


# === Tool handler functions (called by server.py) ===

def handle_test(db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'test' tool."""
    if db:
        item_count = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
        file_count = db.execute("SELECT COUNT(*) FROM content_files").fetchone()[0]
        ref_count = db.execute("SELECT COUNT(*) FROM content_references").fetchone()[0]
        mcp_count = db.execute("SELECT COUNT(*) FROM mcps").fetchone()[0]
        meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM registry_meta")}
        db.close()
        return (
            f"Guidance MCP server OK.\n"
            f"Registry: {item_count} items, {file_count} files, {ref_count} refs, {mcp_count} MCPs\n"
            f"Last scan: {meta.get('generated_at', 'unknown')}\n"
            f"Git commit: {meta.get('git_commit', 'unknown')}\n"
            f"AI_ROOT: {AI_ROOT}"
        )
    return f"Guidance MCP server OK (no registry DB).\nAI_ROOT: {AI_ROOT}"


def handle_get_role(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_role' tool."""
    result = assemble_role(arguments.get("name", ""), db)
    if db:
        db.close()
    return result


def handle_get_skill(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_skill' tool."""
    result = assemble_skill(arguments.get("name", ""))
    if db:
        db.close()
    return result


def handle_get_trait(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_trait' tool."""
    identifier = arguments.get("identifier", arguments.get("path", ""))
    result = render_trait_content(identifier, db, include_header=True)
    if db:
        db.close()
    if result.startswith("[Trait not found:"):
        return f"{result}. Use get_knowledge_topics to browse."
    return result


def handle_get_profile(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_profile' tool."""
    profile_name = arguments.get("name", "")
    profile_path = PROFILES_DIR / f"{profile_name}.yml"
    if not profile_path.exists():
        if db:
            db.close()
        return f"[Profile not found: {profile_name}]"
    content = read_file_content(profile_path)
    if db:
        db.close()
    return content


def handle_get_knowledge_topics(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_knowledge_topics' tool."""
    if not db:
        return db_missing_msg()
    category_filter = arguments.get("category", "")
    status_filter = arguments.get("status", "active")

    query = "SELECT id, name, category, subcategory, description, status FROM content_items WHERE 1=1"
    params = []
    if category_filter:
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category_filter)
    if status_filter:
        query += " AND LOWER(status) = LOWER(?)"
        params.append(status_filter)
    query += " ORDER BY category, subcategory, name"

    rows = db.execute(query, params).fetchall()
    db.close()

    lines = [f"# Available Topics ({len(rows)} items)\n"]
    current_cat = ""
    for r in rows:
        cat = f"{r['category']}/{r['subcategory']}" if r["subcategory"] else (r["category"] or "uncategorized")
        if cat != current_cat:
            lines.append(f"\n## {cat}")
            current_cat = cat
        lines.append(f"- **{r['name']}** (`{r['id']}`): {r['description'] or ''}")
    return "\n".join(lines)


def handle_get_knowledge(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_knowledge' tool."""
    topic_names = arguments.get("topics", [])
    lines = []
    for requested in topic_names:
        if db:
            item = resolve_item(db, requested)
            if item and item.get("preferred_path"):
                lines.append(f"# {item['name']}")
                lines.append(f"Category: {item.get('category', '')} | ID: {item['id']}")
                lines.append("")
                lines.append(render_trait_content(item["preferred_path"], db, include_header=False))
                lines.append("\n---\n")
                continue

        # Fallback
        lines.append(f"# {requested}")
        lines.append("[Not found. Use get_knowledge_topics to browse.]")
        lines.append("")

    if db:
        db.close()
    return "\n".join(lines)


def handle_how_to(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'how_to' tool."""
    query = arguments.get("query", "")
    lines = []

    if db:
        # FTS search
        try:
            fts_rows = db.execute(
                "SELECT item_id, name, description, category FROM content_fts WHERE content_fts MATCH ? LIMIT 10",
                (query,)
            ).fetchall()
        except Exception:
            # FTS query syntax error -- fall back to LIKE
            words = query.lower().split()
            like_clauses = " OR ".join(["LOWER(name) LIKE ? OR LOWER(description) LIKE ?"] * len(words))
            like_params = []
            for w in words:
                like_params.extend([f"%{w}%", f"%{w}%"])
            fts_rows = db.execute(
                f"SELECT id as item_id, name, description, category FROM content_items WHERE {like_clauses} LIMIT 10",
                like_params
            ).fetchall()

        # Also check skills
        skill_rows = db.execute(
            "SELECT id, name, description FROM content_items WHERE item_type = 'skill'"
        ).fetchall()
        skill_matches = []
        for sr in skill_rows:
            text = f"{sr['name']} {sr['description'] or ''}".lower()
            score = sum(1 for w in query.lower().split() if w in text)
            if score > 0:
                skill_matches.append((score, sr))
        skill_matches.sort(key=lambda x: -x[0])

        if skill_matches:
            best = skill_matches[0][1]
            lines.append(f"## Relevant Skill: {best['name']}")
            lines.append("")
            lines.append(assemble_skill(best["id"]))
            lines.append("")

        if fts_rows:
            lines.append(f"## Relevant Knowledge ({len(fts_rows)} matches)")
            lines.append("")
            for r in fts_rows:
                lines.append(f"- **{r['name']}** ({r['category']}): {r['description'] or ''}")
            lines.append("")
            # Auto-load top match
            top = fts_rows[0]
            pref = db.execute(
                "SELECT path FROM content_files WHERE item_id = ? ORDER BY is_preferred DESC LIMIT 1",
                (top["item_id"],)
            ).fetchone()
            if pref:
                lines.append(f"### {top['name']}")
                lines.append("")
                lines.append(read_trait(pref["path"]))

        db.close()

    if not lines:
        lines.append(f"No matches found for: {query}")
        lines.append("Try: get_knowledge_topics to browse available content")

    return "\n".join(lines)


def handle_remind_me(db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'remind_me' tool."""
    if db:
        db.close()
    return resolve_reminders()


def handle_get_references(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_references' tool."""
    if not db:
        return db_missing_msg()
    item_id = arguments.get("id", "")

    outgoing = db.execute(
        "SELECT target_path, target_type, target_name, target_id FROM content_references WHERE source_id = ?",
        (item_id,)
    ).fetchall()

    incoming = db.execute(
        "SELECT source_id, target_type FROM content_references WHERE target_id = ?",
        (item_id,)
    ).fetchall()

    db.close()

    lines = [f"# References for: {item_id}\n"]
    lines.append(f"## Outgoing ({len(outgoing)})")
    for r in outgoing:
        resolved = f" -> `{r['target_id']}`" if r["target_id"] else " (unresolved)"
        lines.append(f"- [{r['target_type']}] `{r['target_path']}`{resolved}")

    lines.append(f"\n## Incoming ({len(incoming)})")
    for r in incoming:
        lines.append(f"- [{r['target_type']}] from `{r['source_id']}`")

    return "\n".join(lines)


def handle_get_stale(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'get_stale' tool."""
    if not db:
        return db_missing_msg()
    days = arguments.get("days", 90)
    category_filter = arguments.get("category", "")

    query = "SELECT id, name, category, status, updated FROM content_items WHERE updated < date('now', ?)"
    params = [f"-{days} days"]
    if category_filter:
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category_filter)
    query += " AND status = 'active' ORDER BY updated ASC"

    rows = db.execute(query, params).fetchall()
    db.close()

    lines = [f"# Stale Items (not updated in {days}+ days): {len(rows)}\n"]
    for r in rows:
        lines.append(f"- **{r['name']}** (`{r['id']}`) -- {r['category']} -- last updated: {r['updated']}")

    return "\n".join(lines)


def handle_search(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'search' tool."""
    if not db:
        return db_missing_msg()

    query_text = arguments.get("query", "")
    category_filter = arguments.get("category", "")
    status_filter = arguments.get("status", "")
    type_filter = arguments.get("item_type", "")

    if query_text:
        try:
            rows = db.execute(
                "SELECT item_id, name, description, category FROM content_fts WHERE content_fts MATCH ? LIMIT 20",
                (query_text,)
            ).fetchall()
        except Exception:
            words = query_text.lower().split()
            like_parts = []
            params = []
            for w in words:
                like_parts.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
                params.extend([f"%{w}%", f"%{w}%"])
            rows = db.execute(
                f"SELECT id as item_id, name, description, category FROM content_items WHERE {' AND '.join(like_parts)} LIMIT 20",
                params
            ).fetchall()
    else:
        sql = "SELECT id as item_id, name, description, category, status, item_type FROM content_items WHERE 1=1"
        params = []
        if category_filter:
            sql += " AND LOWER(category) = LOWER(?)"
            params.append(category_filter)
        if status_filter:
            sql += " AND LOWER(status) = LOWER(?)"
            params.append(status_filter)
        if type_filter:
            sql += " AND LOWER(item_type) = LOWER(?)"
            params.append(type_filter)
        sql += " ORDER BY name LIMIT 50"
        rows = db.execute(sql, params).fetchall()

    db.close()

    lines = [f"# Search Results ({len(rows)} items)\n"]
    for r in rows:
        lines.append(f"- **{r['name']}** (`{r['item_id']}`) [{r['category'] or ''}]: {r['description'] or ''}")

    return "\n".join(lines)


def handle_list_roles(db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'list_roles' tool."""
    if db:
        rows = db.execute(
            "SELECT id, name, description FROM content_items WHERE composition_type = 'role' ORDER BY name"
        ).fetchall()
        db.close()
        lines = ["# Available Roles\n"]
        for r in rows:
            lines.append(f"- **{r['name']}** (`{r['id']}`): {r['description'] or ''}")
    else:
        lines = ["# Available Roles\n"]
        for rp in sorted(PROFILES_DIR.glob("roles/*.yml")):
            role = load_yaml_file(rp)
            lines.append(f"- **{role.get('name', rp.stem)}** (`{rp.stem}`): {role.get('description', '').strip().split(chr(10))[0][:100]}")
    return "\n".join(lines)


def handle_list_skills(db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'list_skills' tool."""
    if db:
        rows = db.execute(
            "SELECT id, name, description FROM content_items WHERE composition_type = 'skill' ORDER BY name"
        ).fetchall()
        db.close()
        lines = ["# Available Skills\n"]
        for r in rows:
            lines.append(f"- **{r['name']}** (`{r['id']}`): {r['description'] or ''}")
    else:
        lines = ["# Available Skills\n"]
        for sp in sorted(PROFILES_DIR.glob("skills/*.yml")):
            skill = load_yaml_file(sp)
            meta = skill.get("metadata", {})
            lines.append(f"- **{meta.get('name', sp.stem)}**: {meta.get('description', '').strip().split(chr(10))[0][:100]}")
    return "\n".join(lines)


def handle_list_traits(db: Optional[sqlite3.Connection], category: Optional[str] = None) -> str:
    """Handle the 'list_traits' tool."""
    if db:
        # Traits are content_items with NULL composition_type (roles/skills/profiles have explicit types)
        if category:
            rows = db.execute(
                "SELECT id, name, category, description FROM content_items "
                "WHERE composition_type IS NULL AND category LIKE ? ORDER BY category, name",
                (f"%{category}%",)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, name, category, description FROM content_items "
                "WHERE composition_type IS NULL ORDER BY category, name"
            ).fetchall()
        db.close()
        lines = ["# Available Traits\n"]
        current_cat = None
        for r in rows:
            cat = r['category'] or 'uncategorized'
            if cat != current_cat:
                current_cat = cat
                lines.append(f"\n## {cat}")
            desc = (r['description'] or '').strip().split('\n')[0][:120]
            lines.append(f"- **{r['name']}** (`{r['id']}`): {desc}")
    else:
        lines = ["# Available Traits\n", "(No database — listing from filesystem not implemented for traits)"]
    return "\n".join(lines)


def handle_list_profiles(db: Optional[sqlite3.Connection]) -> str:
    """Handle the 'list_profiles' tool."""
    if db:
        rows = db.execute(
            "SELECT id, name, description FROM content_items WHERE composition_type = 'profile' ORDER BY name"
        ).fetchall()
        db.close()
        lines = ["# Available Profiles\n"]
        for r in rows:
            lines.append(f"- **{r['name']}** (`{r['id']}`): {r['description'] or ''}")
    else:
        lines = ["# Available Profiles\n"]
        for pp in sorted(PROFILES_DIR.glob("*.yml")):
            profile = load_yaml_file(pp)
            roles = profile.get("roles", [])
            role_names = [Path(r).stem for r in roles] if roles else []
            role_str = f" [{', '.join(role_names)}]" if role_names else ""
            lines.append(f"- **{profile.get('name', pp.stem)}** (`{pp.stem}`){role_str}: {profile.get('description', '').strip().split(chr(10))[0][:100]}")
    return "\n".join(lines)


# === Globals ===

_GLOBAL_SUFFIXES = (".md", ".yml", ".txt")


def _list_global_files() -> list[Path]:
    """Return sorted list of global context files."""
    if not GLOBALS_DIR.exists():
        return []
    return sorted(
        f for f in GLOBALS_DIR.iterdir()
        if f.is_file() and f.suffix in _GLOBAL_SUFFIXES and not f.name.startswith(".")
    )


def read_global(name: str) -> str:
    """Read a global context file by stem name."""
    for suffix in _GLOBAL_SUFFIXES:
        candidate = GLOBALS_DIR / (name + suffix)
        if candidate.exists():
            return read_file_content(candidate)
    candidate = GLOBALS_DIR / name
    if candidate.exists():
        return read_file_content(candidate)
    return f"[Global not found: {name}]"


def handle_list_globals(db: Optional[sqlite3.Connection]) -> str:
    """List available global context files."""
    files = _list_global_files()
    if not files:
        return "No global context files found in ai_context_files/globals/."
    lines = ["# Global Context Files\n"]
    for f in files:
        lines.append(f"- **{f.stem}** ({f.suffix})")
    return "\n".join(lines)


def handle_get_globals(arguments: dict, db: Optional[sqlite3.Connection]) -> str:
    """Load global context files. If a specific name is given, load that one; otherwise load all."""
    name = arguments.get("name")
    if name:
        content = read_global(name)
        return f"# Global: {name}\n\n{content}"

    files = _list_global_files()
    if not files:
        return "No global context files configured."
    parts = []
    for f in files:
        content = read_file_content(f)
        parts.append(f"# === globals/{f.stem} ===\n\n{content}")
    return "\n\n".join(parts)
