"""
Guidance library — business logic for the Guidance MCP server.

Provides trait/role/skill/profile resolution, assembly, search, and reminders.
All functions are synchronous and return plain strings or dicts.
The MCP server.py is a thin wrapper that imports from here.

Backing index (todo_0319 migration)
------------------------------------
The delivery path now reads the authoritative typed graph index
``ai_general/data/context.db`` via ``context_mgr.ContextIndex`` — NOT the legacy
``context_files_registry.db``. ``get_db()`` returns a ``ContextIndex`` (the
``db``/``idx`` argument throughout is that instance). Files on disk are the
source of truth; context.db is a rebuildable index over them.

Edge rule (enforced): a **composition** (role/profile/skill/global) cascades to
what it composes (profile → role → file) — these are the outbound edges in
context.db. A **context file**'s references to other files are *see-also only*
and are NEVER cascade-loaded. context.db only builds edges for composition
kinds, so a leaf item has no outbound edges: ``ContextIndex.children()`` of a
leaf is empty, which enforces the rule structurally.
"""

import os
import re
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# context_mgr lives beside this file; make sure it is importable regardless of
# how guidance_lib is loaded.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files import context_mgr  # noqa: E402
from uai_toolkit.context_files.context_mgr import ContextIndex  # noqa: E402


# === Path configuration ===

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
AI_GENERAL = AI_ROOT / "ai_general"
TRAITS_DIR = AI_GENERAL / "ai_context_files"  # was the ai_traits symlink (now removed)
PROFILES_DIR = AI_GENERAL / "ai_profiles"
GLOBALS_DIR = AI_GENERAL / "ai_context_files" / "globals"

# The authoritative index. DB_PATH kept as an alias for any external referrer;
# it now points at context.db (NOT the legacy registry).
CONTEXT_DB_PATH = AI_GENERAL / "data" / "context.db"
DB_PATH = CONTEXT_DB_PATH

# Kinds that compose others vs. leaf content kinds (mirrors context_mgr).
COMPOSITION_KINDS = frozenset({"role", "profile", "skill", "global"})
ALL_KINDS = frozenset({"brief", "memory", "knowledge", "instruction",
                       "role", "profile", "skill", "global"})


# === Database access ===

def get_db() -> Optional[ContextIndex]:
    """Return a ``ContextIndex`` over context.db, or None if the DB is absent.

    Signature preserved for guidance_cli/server compatibility; the returned
    object is now a ContextIndex (not a raw sqlite3.Connection). ContextIndex
    opens/closes a connection per query, so callers do NOT close it.
    """
    if not CONTEXT_DB_PATH.exists():
        return None
    try:
        return ContextIndex()
    except Exception:
        return None


def db_missing_msg() -> str:
    return (
        "Context index not found. Run:\n"
        "  python3 scripts/context_files/context_mgr.py reindex\n"
        "from ai_general/ to build data/context.db."
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
    """Read a context file by path relative to ai_general/ (or a bare stem)."""
    text = str(rel_path or "").strip()
    # context.db paths are AI_ROOT-relative (start with 'ai_general/'); accept
    # those too by stripping the leading segment.
    if text.startswith("ai_general/"):
        text = text[len("ai_general/"):]
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
    for _pfx in ("ai_general/", ):
        if text.startswith(_pfx):
            text = text[len(_pfx):]
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


# === Resolution: id -> item (context.db) ===

def _basename_noext(s: str) -> str:
    base = (s or "").rstrip("/").split("/")[-1]
    return re.sub(r"\.(md|ya?ml|json)$", "", re.sub(r"\.condensed$", "", base))


def _strip_ai_general(path: Optional[str]) -> Optional[str]:
    if path and path.startswith("ai_general/"):
        return path[len("ai_general/"):]
    return path


def _ref_to_id(ref: str) -> Optional[str]:
    """Map a reference-style path (ai_context_files/..., ai_profiles/...) to a
    context.db item id ``kind:name``. Returns None if it doesn't match a known
    prefix."""
    r = re.sub(r"\.(md|ya?ml|json)$", "", (ref or "").strip().replace("\\", "/"))
    if r.startswith("ai_general/"):
        r = r[len("ai_general/"):]
    prefixes = (
        ("knowledge", "ai_context_files/knowledge/"),
        ("instruction", "ai_context_files/instructions/"),
        ("instruction", "ai_context_files/platforms/"),
        ("global", "ai_profiles/globals/"),
        ("skill", "ai_profiles/skills/"),
        ("role", "ai_profiles/roles/"),
    )
    for kind, pfx in prefixes:
        if r.startswith(pfx):
            name = r[len(pfx):]
            if kind == "skill":
                name = name.replace("-", "_")
            return f"{kind}:{name}"
    if r.startswith("ai_context_files/"):
        return f"instruction:{r.split('/', 2)[-1]}"
    if r.startswith("ai_profiles/"):
        return f"profile:{r[len('ai_profiles/'):]}"
    return None


def _item_to_legacy(row: dict) -> dict:
    """Convert a context.db item/row into the legacy-shaped dict the delivery
    code + guidance_cli consume.

    Keys:
      _ctx_id        : the context.db qualified id (kind:name) — INTERNAL, used
                       for graph ops (edges/dedup). Never surfaced to users.
      id             : bare id — compositions keep their flat name; leaves use
                       the basename (parity with the legacy registry ids).
      disk_name      : kind-relative, extension-less slug for on-disk lookups.
      composition_type: role/profile/skill/global, else None (leaf).
      name/category/status/version/description/preferred_path: legacy fields.
    """
    kind = row.get("kind")
    slug = row.get("name") or ""
    comp = kind if kind in COMPOSITION_KINDS else None
    category = slug.split("/", 1)[0] if "/" in slug else (kind or "")
    prov = row.get("provenance")
    version = ""
    if isinstance(prov, dict):
        version = prov.get("version", "") or ""
    bare = slug if comp else _basename_noext(slug)
    return {
        "_ctx_id": row.get("id"),
        "id": bare,
        "kind": kind,
        "disk_name": slug,
        "composition_type": comp,
        "name": row.get("title") or bare,
        "category": category,
        "status": row.get("status", "") or "",
        "version": version,
        "description": row.get("summary", "") or "",
        "preferred_path": _strip_ai_general(row.get("path")),
    }


def _match_by_name(idx: ContextIndex, ident: str) -> Optional[dict]:
    """Best-effort name match over active items: exact slug, then slug
    basename, then title. Returns a full get_item row or None."""
    low = ident.lower()
    stem = _basename_noext(ident).lower()
    rows = idx.list_items(status="active")
    for r in rows:  # exact full-slug name
        if (r.get("name") or "").lower() == low:
            return idx.get_item(r["id"])
    for r in rows:  # slug basename
        if _basename_noext(r.get("name") or "").lower() == stem:
            return idx.get_item(r["id"])
    for r in rows:  # display title
        if (r.get("title") or "").lower() == low:
            return idx.get_item(r["id"])
    return None


def resolve_item(idx: Optional[ContextIndex], identifier: str) -> Optional[dict]:
    """Resolve an identifier to a context.db item (legacy-shaped dict) or None.

    Resolution order (adapted from the legacy registry order):
      1. qualified id ``kind:name``
      2. reference-style path (ai_context_files/…, ai_profiles/…)
      3. bare name against composition then leaf kinds (exact id)
      4. name / basename / title match across active items
      5. FTS-ranked match
    """
    if not idx:
        return None
    ident = str(identifier or "").strip()
    if not ident:
        return None

    # 1. qualified id
    if ":" in ident and ident.split(":", 1)[0] in ALL_KINDS:
        row = idx.get_item(ident)
        if row:
            return _item_to_legacy(row)

    # 2. reference-style path
    rid = _ref_to_id(ident)
    if rid:
        row = idx.get_item(rid)
        if row:
            return _item_to_legacy(row)

    # 3. bare name -> try each kind (compositions first)
    stem = _basename_noext(ident)
    for kind in ("role", "profile", "skill", "global",
                 "instruction", "knowledge", "brief", "memory"):
        row = idx.get_item(f"{kind}:{stem}")
        if row:
            return _item_to_legacy(row)
        if kind == "skill" and "-" in stem:
            row = idx.get_item(f"skill:{stem.replace('-', '_')}")
            if row:
                return _item_to_legacy(row)

    # 4. name / basename / title match
    hit = _match_by_name(idx, ident)
    if hit:
        return _item_to_legacy(hit)

    # 5. FTS
    try:
        res = idx.search(ident, limit=1)
        if res:
            row = idx.get_item(res[0]["id"])
            if row:
                return _item_to_legacy(row)
    except Exception:
        pass

    return None


def _render_leaf(item: dict, include_header: bool = True) -> str:
    """Render a leaf context file's content from its resolved item dict."""
    content = read_trait(item.get("preferred_path") or item.get("_ctx_id") or item["id"])
    if include_header:
        header = (
            f"# {item['name']}\n"
            f"**Category:** {item.get('category', '')} | "
            f"**Status:** {item.get('status', '')} | "
            f"**Version:** {item.get('version', '')}\n\n"
        )
        return header + content
    return content


def render_trait_content(identifier: str, db: Optional[ContextIndex],
                         include_header: bool = True) -> str:
    """Resolve and render a context/knowledge item (same logic as get_trait)."""
    if db:
        item = resolve_item(db, identifier)
        if item and item.get("preferred_path"):
            return _render_leaf(item, include_header=include_header)

    normalized = normalize_trait_identifier(identifier)
    if normalized:
        content = read_trait(normalized)
        if not content.startswith("["):
            return content
    return f"[Trait not found: {identifier}]"


# === Role/skill/profile assembly ===

def assemble_role(role_name: str, db: Optional[ContextIndex] = None) -> str:
    """Assemble a role definition with its referenced context-file content."""
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

    # Referenced context files (key renamed traits -> context_files; accept both).
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
    # Tolerate a qualified context.db id.
    if skill_name.startswith("skill:"):
        skill_name = skill_name.split(":", 1)[1]
    skill_path = PROFILES_DIR / "skills" / f"{skill_name}.yml"
    if not skill_path.exists():
        skill_path = PROFILES_DIR / "skills" / f"{skill_name.replace('-', '_')}.yml"
    if not skill_path.exists():
        return f"[Skill not found: {skill_name}]"
    return read_file_content(skill_path)


# === Uniform context assembly (todo_0319) ===
# One depth-controlled walk over the context.db reference graph. Composition
# edges cascade; leaf items have no edges (see-also is not cascaded).

LOAD_NONE, LOAD_DIRECT, LOAD_RECURSIVE = "none", "direct", "recursive"
LOAD_LEVELS = (LOAD_NONE, LOAD_DIRECT, LOAD_RECURSIVE)


def _role_definition(role_name: str) -> str:
    """A role's OWN content (header/duties/ownership) WITHOUT inlining its context
    files — those are reached via the reference walk."""
    role_path = PROFILES_DIR / "roles" / f"{role_name}.yml"
    if not role_path.exists():
        return f"[Role not found: {role_name}]"
    role = load_yaml_file(role_path)
    lines = [f"# Role: {role.get('name', role_name)}", ""]
    if role.get("description"):
        lines += [role["description"].strip(), ""]
    resp = role.get("responsibilities", {}) or {}
    for key, title in (("duties", "## Duties"), ("ownership", "## Ownership"),
                       ("does_not_own", "## Does Not Own")):
        vals = resp.get(key, [])
        if vals:
            lines.append(title)
            for v in vals:
                if isinstance(v, dict):
                    lines.append(f"- **{v.get('name', '')}** ({v.get('schedule', '')}): {v.get('action', '')}")
                else:
                    lines.append(f"- {v}")
            lines.append("")
    return "\n".join(lines).rstrip()


def render_own_content(item: dict, db: Optional[ContextIndex]) -> str:
    """Render an item's OWN content only (no reference expansion)."""
    ct = (item.get("composition_type") or "").lower()
    disk = item.get("disk_name") or item.get("id")
    if ct == "role":
        return _role_definition(disk)
    if ct == "profile":
        p = PROFILES_DIR / f"{disk}.yml"
        return read_file_content(p) if p.exists() else f"[Profile not found: {disk}]"
    if ct == "skill":
        return assemble_skill(disk)
    if ct == "global":
        p = PROFILES_DIR / "globals" / f"{disk}.yml"
        return read_file_content(p) if p.exists() else ""
    # leaf content file
    return _render_leaf(item, include_header=True)


def _curated_refs(item: dict, db: ContextIndex) -> list:
    """The item's cascade targets — its direct outbound edges in context.db.

    For a composition this is what it composes (profile→roles, role→context
    files/skills), in edge order. For a leaf content file this is EMPTY
    (context.db builds no outbound edges for leaves), which enforces the rule
    that file→file references are see-also only and never cascade-loaded.
    """
    if not db:
        return []
    ctx_id = item.get("_ctx_id") or item.get("id")
    try:
        kids = db.children(ctx_id)
    except Exception:
        return []
    return [_item_to_legacy(k) for k in kids]


def assemble_context(ref: str, db: Optional[ContextIndex],
                     load: str = LOAD_RECURSIVE, _seen: Optional[set] = None) -> str:
    """Resolve ``ref`` and render its content, expanding references per ``load``:
      none      -> own content only
      direct    -> own content + directly composed items (one hop, own content)
      recursive -> own content + transitive composition closure (deduped, cycle-safe)
    Uniform across roles, profiles, skills, globals, and context files. Cascades
    follow composition edges only; leaf see-also refs are never expanded."""
    if load not in LOAD_LEVELS:
        load = LOAD_RECURSIVE
    if _seen is None:
        _seen = set()
    item = resolve_item(db, ref) if db else None
    if not item:
        return f"[Not found: {ref}]"
    iid = item["_ctx_id"]
    if iid in _seen:
        return ""
    _seen.add(iid)
    parts = [render_own_content(item, db)]
    if load == LOAD_NONE:
        return parts[0]
    for tgt in _curated_refs(item, db):
        if tgt["_ctx_id"] in _seen:
            continue
        if load == LOAD_RECURSIVE:
            sub = assemble_context(tgt["_ctx_id"], db, LOAD_RECURSIVE, _seen)
        else:  # direct: one hop, own content only
            _seen.add(tgt["_ctx_id"])
            sub = render_own_content(tgt, db)
        if sub and sub.strip():
            parts.append(sub)
    return "\n\n".join(p for p in parts if p and p.strip())


# === Reminders ===

def _reminder_files_from_index(idx: ContextIndex) -> list:
    """Return (name, body) for active reminder context files via context.db.

    Reminders are instruction items under ``reminders/`` (id
    ``instruction:reminders/<name>``). Falls back to a filesystem scan of
    ai_context_files/instructions/reminders/ if the index yields none.
    """
    out = []
    try:
        rows = [r for r in idx.list_items(kind="instruction", status="active")
                if (r.get("name") or "").startswith("reminders/")]
        rows.sort(key=lambda r: r.get("name") or "")
        for r in rows:
            payload = idx.content(r["id"]) or {}
            body = payload.get("content")
            if body is not None:
                out.append((r["id"], body))
    except Exception:
        out = []
    return out


def resolve_reminders(idx: Optional[ContextIndex] = None) -> str:
    """Load all reminder context files (via context.db) and resolve dynamic
    variables. Kept arg-optional so handle_remind_me can call it directly."""
    idx = idx or get_db()
    now = datetime.now(timezone.utc)

    pairs = _reminder_files_from_index(idx) if idx else []

    # Filesystem fallback: the correct on-disk location for reminder content.
    if not pairs:
        reminders_dir = TRAITS_DIR / "instructions" / "reminders"
        if reminders_dir.exists():
            for f in sorted(reminders_dir.glob("*.md")):
                pairs.append((f.stem, f.read_text()))

    if not pairs:
        return "No reminders configured."

    lines = []
    for _name, content in pairs:
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


# === Tool handler functions (called by server.py / guidance_cli.py) ===
# NOTE: ContextIndex opens/closes a connection per query — handlers must NOT
# attempt to close the passed idx (it is not a raw sqlite3 connection).

def _kind_counts(idx: ContextIndex) -> dict:
    counts = {}
    for r in idx.list_items(status=None):
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return counts


def handle_test(db: Optional[ContextIndex]) -> str:
    """Handle the 'test' tool."""
    if db:
        counts = _kind_counts(db)
        total = sum(counts.values())
        try:
            edge_n = len(db.graph().get("edges", []))
        except Exception:
            edge_n = "?"
        by_kind = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        return (
            f"Guidance MCP server OK (context.db).\n"
            f"Index: {total} items ({by_kind}), {edge_n} edges\n"
            f"DB: {CONTEXT_DB_PATH}\n"
            f"AI_ROOT: {AI_ROOT}"
        )
    return f"Guidance MCP server OK (no context index).\nAI_ROOT: {AI_ROOT}"


def handle_get_role(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_role' tool. Recursively assembles role + its context files."""
    return assemble_context(arguments.get("name", ""), db, LOAD_RECURSIVE)


def handle_get_skill(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_skill' tool."""
    name = arguments.get("name", "")
    if db:
        item = resolve_item(db, name)
        if item and item.get("composition_type") == "skill":
            return assemble_skill(item["disk_name"])
    return assemble_skill(name)


def handle_get_trait(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_trait' tool."""
    identifier = arguments.get("identifier", arguments.get("path", ""))
    result = render_trait_content(identifier, db, include_header=True)
    if result.startswith("[Trait not found:"):
        return f"{result}. Use get_knowledge_topics to browse."
    return result


def handle_get_profile(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_profile' tool. Recursively assembles profile -> roles -> context files."""
    return assemble_context(arguments.get("name", ""), db, LOAD_RECURSIVE)


def handle_get_knowledge_topics(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_knowledge_topics' tool — browse leaf content files."""
    if not db:
        return db_missing_msg()
    category_filter = (arguments.get("category", "") or "").lower()
    status_filter = arguments.get("status", "active") or "active"

    rows = []
    for kind in ("knowledge", "instruction"):
        rows.extend(db.list_items(kind=kind, status=status_filter))

    def cat_of(r):
        slug = r.get("name") or ""
        return slug.split("/", 1)[0] if "/" in slug else r.get("kind", "")

    if category_filter:
        rows = [r for r in rows if cat_of(r).lower() == category_filter]
    rows.sort(key=lambda r: (cat_of(r), r.get("name") or ""))

    lines = [f"# Available Topics ({len(rows)} items)\n"]
    current_cat = ""
    for r in rows:
        cat = cat_of(r)
        if cat != current_cat:
            lines.append(f"\n## {cat}")
            current_cat = cat
        bare = _basename_noext(r.get("name") or "")
        lines.append(f"- **{r.get('title') or bare}** (`{bare}`): {r.get('summary') or ''}")
    return "\n".join(lines)


def handle_get_knowledge(arguments: dict, db: Optional[ContextIndex]) -> str:
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
                lines.append(_render_leaf(item, include_header=False))
                lines.append("\n---\n")
                continue

        lines.append(f"# {requested}")
        lines.append("[Not found. Use get_knowledge_topics to browse.]")
        lines.append("")

    return "\n".join(lines)


def handle_how_to(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'how_to' tool."""
    query = arguments.get("query", "")
    lines = []

    if db:
        # Relevant skill (word-overlap over skill items).
        skill_matches = []
        for sr in db.list_items(kind="skill", status="active"):
            text = f"{sr.get('title') or sr.get('name')} {sr.get('summary') or ''}".lower()
            score = sum(1 for w in query.lower().split() if w in text)
            if score > 0:
                skill_matches.append((score, sr))
        skill_matches.sort(key=lambda x: -x[0])
        if skill_matches:
            best = skill_matches[0][1]
            best_name = _basename_noext(best.get("name") or "")
            lines.append(f"## Relevant Skill: {best.get('title') or best_name}")
            lines.append("")
            lines.append(assemble_skill(best["id"]))
            lines.append("")

        # Relevant knowledge/instruction via FTS.
        try:
            hits = [h for h in db.search(query, limit=10)
                    if h.get("kind") in ("knowledge", "instruction")]
        except Exception:
            hits = []
        if hits:
            lines.append(f"## Relevant Knowledge ({len(hits)} matches)")
            lines.append("")
            for h in hits:
                bare = _basename_noext(h.get("name") or "")
                cat = (h.get("name") or "").split("/", 1)[0] if "/" in (h.get("name") or "") else h.get("kind", "")
                lines.append(f"- **{h.get('title') or bare}** ({cat}): {h.get('summary') or ''}")
            lines.append("")
            # Auto-load the top match's body.
            top = hits[0]
            payload = db.content(top["id"]) or {}
            if payload.get("content"):
                lines.append(f"### {top.get('title') or _basename_noext(top.get('name') or '')}")
                lines.append("")
                lines.append(payload["content"])

    if not lines:
        lines.append(f"No matches found for: {query}")
        lines.append("Try: get_knowledge_topics to browse available content")

    return "\n".join(lines)


def handle_remind_me(db: Optional[ContextIndex]) -> str:
    """Handle the 'remind_me' tool."""
    return resolve_reminders(db)


def handle_get_references(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_references' tool."""
    if not db:
        return db_missing_msg()
    requested = arguments.get("id", "")
    item = resolve_item(db, requested)
    ctx_id = item["_ctx_id"] if item else requested

    try:
        outgoing = db.refs(ctx_id, direction="out")
        incoming = db.refs(ctx_id, direction="in")
    except Exception:
        outgoing, incoming = [], []

    lines = [f"# References for: {ctx_id}\n"]
    lines.append(f"## Outgoing ({len(outgoing)})")
    for r in outgoing:
        marker = "" if r.get("resolved") else " (unresolved)"
        lines.append(f"- [{r['edge_type']}] `{r['dst_id']}`{marker}")

    lines.append(f"\n## Incoming ({len(incoming)})")
    for r in incoming:
        lines.append(f"- [{r['edge_type']}] from `{r['src_id']}`")

    return "\n".join(lines)


def handle_get_stale(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'get_stale' tool."""
    if not db:
        return db_missing_msg()
    days = arguments.get("days", 90) or 90
    category_filter = (arguments.get("category", "") or "").lower()
    cutoff = datetime.now().timestamp() - int(days) * 86400

    rows = db.list_items(status="active")

    def cat_of(r):
        slug = r.get("name") or ""
        return slug.split("/", 1)[0] if "/" in slug else r.get("kind", "")

    stale = []
    for r in rows:
        upd = r.get("updated_at")
        if not upd:
            continue
        try:
            ts = datetime.fromisoformat(upd).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            continue
        if category_filter and cat_of(r).lower() != category_filter:
            continue
        stale.append(r)
    stale.sort(key=lambda r: r.get("updated_at") or "")

    lines = [f"# Stale Items (not updated in {days}+ days): {len(stale)}\n"]
    for r in stale:
        bare = _basename_noext(r.get("name") or "")
        lines.append(f"- **{r.get('title') or bare}** (`{bare}`) -- {cat_of(r)} -- last updated: {r.get('updated_at')}")

    return "\n".join(lines)


def handle_search(arguments: dict, db: Optional[ContextIndex]) -> str:
    """Handle the 'search' tool."""
    if not db:
        return db_missing_msg()

    query_text = arguments.get("query", "")
    category_filter = (arguments.get("category", "") or "").lower()
    status_filter = arguments.get("status", "")
    type_filter = (arguments.get("item_type", "") or "").lower() or None

    def cat_of(r):
        slug = r.get("name") or ""
        return slug.split("/", 1)[0] if "/" in slug else r.get("kind", "")

    if query_text:
        try:
            rows = db.search(query_text, kind=type_filter, limit=20)
        except Exception:
            rows = []
    else:
        rows = db.list_items(kind=type_filter, status=(status_filter or "active"), limit=50)

    if category_filter:
        rows = [r for r in rows if cat_of(r).lower() == category_filter]

    lines = [f"# Search Results ({len(rows)} items)\n"]
    for r in rows:
        bare = _basename_noext(r.get("name") or "")
        lines.append(f"- **{r.get('title') or bare}** (`{bare}`) [{cat_of(r)}]: {r.get('summary') or ''}")

    return "\n".join(lines)


def _list_compositions(db: Optional[ContextIndex], kind: str, fs_glob: str,
                       fs_render, heading: str) -> str:
    if db:
        rows = db.list_items(kind=kind, status="active")
        lines = [f"# {heading}\n"]
        for r in rows:
            bare = _basename_noext(r.get("name") or "")
            lines.append(f"- **{r.get('title') or bare}** (`{bare}`): {r.get('summary') or ''}")
        return "\n".join(lines)
    lines = [f"# {heading}\n"]
    for p in sorted(fs_glob):
        lines.append(fs_render(p))
    return "\n".join(lines)


def handle_list_roles(db: Optional[ContextIndex]) -> str:
    """Handle the 'list_roles' tool."""
    if db:
        return _list_compositions(db, "role", [], None, "Available Roles")
    lines = ["# Available Roles\n"]
    for rp in sorted(PROFILES_DIR.glob("roles/*.yml")):
        role = load_yaml_file(rp)
        lines.append(f"- **{role.get('name', rp.stem)}** (`{rp.stem}`): {role.get('description', '').strip().split(chr(10))[0][:100]}")
    return "\n".join(lines)


def handle_list_skills(db: Optional[ContextIndex]) -> str:
    """Handle the 'list_skills' tool."""
    if db:
        return _list_compositions(db, "skill", [], None, "Available Skills")
    lines = ["# Available Skills\n"]
    for sp in sorted(PROFILES_DIR.glob("skills/*.yml")):
        skill = load_yaml_file(sp)
        meta = skill.get("metadata", {})
        lines.append(f"- **{meta.get('name', sp.stem)}**: {meta.get('description', '').strip().split(chr(10))[0][:100]}")
    return "\n".join(lines)


def handle_list_traits(db: Optional[ContextIndex], category: Optional[str] = None) -> str:
    """Handle the 'list_traits' tool — leaf content files (knowledge/instruction)."""
    if db:
        rows = []
        for kind in ("knowledge", "instruction"):
            rows.extend(db.list_items(kind=kind, status="active"))

        def cat_of(r):
            slug = r.get("name") or ""
            return slug.split("/", 1)[0] if "/" in slug else r.get("kind", "")

        if category:
            cl = category.lower()
            rows = [r for r in rows if cl in cat_of(r).lower()]
        rows.sort(key=lambda r: (cat_of(r), r.get("name") or ""))

        lines = ["# Available Traits\n"]
        current_cat = None
        for r in rows:
            cat = cat_of(r) or "uncategorized"
            if cat != current_cat:
                current_cat = cat
                lines.append(f"\n## {cat}")
            bare = _basename_noext(r.get("name") or "")
            desc = (r.get("summary") or "").strip().split("\n")[0][:120]
            lines.append(f"- **{r.get('title') or bare}** (`{bare}`): {desc}")
        return "\n".join(lines)
    return "# Available Traits\n\n(No index — listing from filesystem not implemented for traits)"


def handle_list_profiles(db: Optional[ContextIndex]) -> str:
    """Handle the 'list_profiles' tool."""
    if db:
        return _list_compositions(db, "profile", [], None, "Available Profiles")
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


def _list_global_files() -> list:
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


def handle_list_globals(db: Optional[ContextIndex]) -> str:
    """List available global context files."""
    files = _list_global_files()
    if not files:
        return "No global context files found in ai_context_files/globals/."
    lines = ["# Global Context Files\n"]
    for f in files:
        lines.append(f"- **{f.stem}** ({f.suffix})")
    return "\n".join(lines)


def handle_get_globals(arguments: dict, db: Optional[ContextIndex]) -> str:
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
