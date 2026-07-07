#!/usr/bin/env python3
"""Scan ai_context_files/ and ai_profiles/ to build/update the context-files registry SQLite database.

Usage:
    python -m uai_toolkit.guidance.scan_registry --full          # Rebuild from scratch
    python -m uai_toolkit.guidance.scan_registry --incremental   # Only changed files (by content hash)
    python -m uai_toolkit.guidance.scan_registry --check         # Report issues, no writes
    python -m uai_toolkit.guidance.scan_registry --inventory     # Inventory of files and variant groups
    python -m uai_toolkit.guidance.scan_registry --stats         # Print registry statistics

The registry lives at: $AI_ROOT/ai_general/data/context_files/context_files_registry.db

Portability notes (uai_toolkit port of ~/bin/ai/context_files/scan_traits_registry.py):
  - The SQLite schema ships INSIDE the package (schema.sql next to this module),
    so a freshly-provisioned AI_ROOT that has content copied in but no
    scripts/context_files/schema.sql can still build its registry. Override with
    the AI_REGISTRY_SCHEMA env var if you must point at an external schema.
  - The MCP scan (apps/mcps/) degrades to an empty known_mcps set if that dir is
    absent in a fresh instance.
  - The git-commit metadata capture degrades to "" if git is missing / not a repo.
  - Corpus dirs (ai_context_files/, ai_profiles/, data/) stay AI_ROOT-relative:
    those ARE present in an instance after `init` copies shipped content in.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# === Path resolution ===
AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
AI_GENERAL = AI_ROOT / "ai_general"
# The corpus dir. Was the ai_traits symlink; now points at the real dir so the
# scanner no longer depends on the symlink (todo_0319 removes it).
TRAITS_DIR = AI_GENERAL / "ai_context_files"
PROFILES_DIR = AI_GENERAL / "ai_profiles"
MCPS_DIR = AI_GENERAL / "apps" / "mcps"
DB_PATH = AI_GENERAL / "data" / "context_files" / "context_files_registry.db"
# PORTED: schema ships with the package (not AI_ROOT-relative), so a fresh
# instance without scripts/context_files/schema.sql can still build. Env override
# for anyone who wants to point at an external schema.
SCHEMA_PATH = Path(
    os.environ.get("AI_REGISTRY_SCHEMA", str(Path(__file__).resolve().parent / "schema.sql"))
)
LOCK_PATH = AI_GENERAL / "data" / "context_files" / ".scan.lock"

# === Constants ===
INCLUDE_EXTENSIONS = {".md", ".yml", ".yaml"}
EXCLUDE_FILES = {".DS_Store", ".gitkeep", "README.md", "package.json", "package-lock.json", "catalog.yml"}
EXCLUDE_DIRS = {"versions", ".obsidian", ".claude", "__pycache__", "node_modules", ".venv",
                ".drafts", "roles-to-migrate"}
# Dirs whose NAME begins with any of these prefixes are also excluded (scratch /
# archived content that is not live corpus, e.g. _archive_condensation/).
EXCLUDE_DIR_PREFIXES = ("_archive",)

CATEGORY_MAP = {
    "perspective": "perspective",
    "knowledge": "knowledge",
    "processes": "processes",
    "procedures": "procedures",
    "methods": "methods",
    "templates": "templates",
    "reminders": "reminders",
    "_drafts": None,  # status-based, not category
}

VARIANT_MAP = {
    ".condensed.yml": "condensed_yml",
    ".yml": "source_yml",
    ".yaml": "source_yml",
    ".md": "source_md",
}

VARIANT_PREFERENCE = ["condensed_yml", "source_yml", "source_md"]


# === Helpers ===

def compute_hash(path: Path) -> str:
    """SHA-256 of file content."""
    try:
        return hashlib.sha256(path.resolve().read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token)."""
    return len(text) // 4


def infer_item_id(filename: str) -> str:
    """Strip .latest, .condensed, extensions to get logical item ID.

    IMPORTANT: Match longest/most-specific suffixes first to avoid
    leaving .latest in the ID (e.g., foo.latest.condensed.yml → foo, not foo.latest).
    """
    name = filename
    for suffix in [".latest.condensed.yml", ".latest.yaml", ".latest.yml",
                   ".latest.md", ".condensed.yml", ".yaml", ".yml", ".md"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name


def infer_variant(filename: str) -> str:
    """Determine file variant from filename."""
    if ".condensed.yml" in filename:
        return "condensed_yml"
    if filename.endswith(".yml") or filename.endswith(".yaml"):
        return "source_yml"
    return "source_md"


def infer_category(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Infer category and subcategory from file path."""
    rel = str(path.relative_to(AI_GENERAL))
    parts = rel.split("/")

    # ai_traits/{category}/...  (ai_traits is a symlink to ai_context_files)
    if len(parts) >= 2 and parts[0] in ("ai_traits", "ai_context_files"):
        cat_dir = parts[1]
        if cat_dir == "_drafts":
            # Check for retired
            if len(parts) >= 3 and parts[2] == "retired":
                return None, None  # status=retired, no category
            return None, None  # status=draft
        # Two-bucket nesting (todo_0319): instructions/<subtype>[/<group>]/<file>
        # or knowledge/<subtype>[/<group>]/<file>. Category = the subtype; a
        # non-file 4th segment (protocols/playbooks/mcp_usage) is the subcategory.
        if cat_dir in ("instructions", "knowledge") and len(parts) >= 3:
            subtype = parts[2]
            subgroup = None
            if len(parts) >= 4 and not parts[3].endswith((".md", ".yml", ".yaml", ".json")):
                subgroup = parts[3]
            return subtype, subgroup
        category = CATEGORY_MAP.get(cat_dir, cat_dir)
        subcategory = parts[2] if len(parts) >= 3 and re.match(r"\d+_", parts[2]) else None
        return category, subcategory

    # ai_profiles/{type}/...
    if len(parts) >= 2 and parts[0] == "ai_profiles":
        return None, None  # compositions don't have ontology categories

    return None, None


def infer_status(path: Path) -> str:
    """Infer status from path."""
    rel = str(path.relative_to(AI_GENERAL))
    if "_drafts/retired" in rel:
        return "retired"
    if "_drafts" in rel:
        return "draft"
    return "active"


def infer_item_type(path: Path) -> str:
    """Determine if context_file or composition type."""
    rel = str(path.relative_to(AI_GENERAL))
    if rel.startswith("ai_traits/") or rel.startswith("ai_context_files/"):
        return "context_file"
    if rel.startswith("ai_profiles/roles/"):
        return "role"
    if rel.startswith("ai_profiles/skills/"):
        return "skill"
    if rel.startswith("ai_profiles/globals/"):
        return "global"
    if rel.startswith("ai_profiles/platforms/"):
        return "platform"
    if rel.startswith("ai_profiles/") and "/" not in rel[len("ai_profiles/"):]:
        return "profile"
    return "context_file"


def infer_name(item_id: str) -> str:
    """Generate human-readable name from ID."""
    name = item_id
    for prefix in ["instr_", "spec_", "schema_", "protocol_", "playbook.", "playbook_",
                    "arch_", "architecture_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").replace("-", " ").title()


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter from markdown file."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def parse_registry_block(content: str) -> dict:
    """Extract _registry: block from YAML file."""
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict) and "_registry" in data:
            return data["_registry"]
    except Exception:
        pass
    return {}


def parse_meta_line(content: str) -> dict:
    """Extract meta: {v: X, updated: Y} inline from condensed YAML."""
    m = re.search(r'^meta:\s*\{(.+?)\}', content, re.MULTILINE)
    if not m:
        return {}
    result = {}
    for pair in m.group(1).split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k == "v":
                result["version"] = v
            elif k == "updated":
                result["updated"] = v
            elif k == "status":
                result["status"] = v
    return result


def extract_metadata(path: Path, content: str) -> dict:
    """Extract metadata from file using format-appropriate method."""
    filename = path.name
    meta = {}

    if filename.endswith(".md"):
        meta = parse_frontmatter(content)
    elif filename.endswith(".yml") or filename.endswith(".yaml"):
        meta = parse_registry_block(content)
        if not meta:
            meta = parse_meta_line(content)
        # Also check for metadata: block
        if not meta:
            try:
                import yaml
                data = yaml.safe_load(content)
                if isinstance(data, dict) and "metadata" in data:
                    md = data["metadata"]
                    if isinstance(md, dict):
                        meta = {
                            "version": str(md.get("version", "")),
                            "updated": str(md.get("updated", md.get("last_updated", ""))),
                            "status": md.get("status", ""),
                            "name": md.get("name", md.get("title", "")),
                        }
            except Exception:
                pass

    return {k: v for k, v in meta.items() if v}


def extract_description(content: str, filename: str) -> str:
    """Extract a one-line description from file content."""
    # Check frontmatter/metadata first
    meta = {}
    if filename.endswith(".md"):
        meta = parse_frontmatter(content)
    if meta.get("description"):
        return str(meta["description"]).strip().split("\n")[0][:200]

    # Check for purpose/summary/description keys in YAML
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            for key in ["description", "purpose", "summary"]:
                val = data.get(key)
                if val:
                    if isinstance(val, list):
                        val = val[0] if val else ""
                    return str(val).strip().split("\n")[0][:200]
    except Exception:
        pass

    # Fallback: first non-empty, non-heading line
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith("---") and not line.startswith("meta:"):
            return line[:200]
    return ""


# === Reference extraction ===

def extract_references(content: str, known_mcps: set[str]) -> list[dict]:
    """Extract references using layered approach."""
    refs = []
    seen = set()

    def add_ref(target_path: str, target_type: str, target_name: str = ""):
        if target_path not in seen:
            seen.add(target_path)
            refs.append({"target_path": target_path, "target_type": target_type, "target_name": target_name})

    # Layer 1: Structured YAML parsing
    try:
        import yaml
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            # context_files: list or dict of lists (back-compat: also read legacy "traits" key).
            # These refs are extensionless stems (e.g. ai_context_files/.../operational_handoff),
            # so the Layer 2 path regex (which requires an extension) does NOT catch them — this
            # structured pass is the only thing that records role/skill -> context_file links.
            context_files_val = data.get("context_files", data.get("traits", {}))
            if isinstance(context_files_val, list):
                for t in context_files_val:
                    p = t if isinstance(t, str) else (t.get("path", "") if isinstance(t, dict) else "")
                    if p:
                        add_ref(p, "item")
            elif isinstance(context_files_val, dict):
                for cat_list in context_files_val.values():
                    if isinstance(cat_list, list):
                        for t in cat_list:
                            p = t if isinstance(t, str) else (t.get("path", "") if isinstance(t, dict) else "")
                            if p:
                                add_ref(p, "item")

            # roles: list
            for r in data.get("roles", []):
                if isinstance(r, str):
                    add_ref(r, "item")

            # required_mcps
            for m in data.get("required_mcps", []):
                if isinstance(m, str):
                    add_ref(m, "mcp", m)
    except Exception:
        pass

    # Layer 2: Path regex (ai_traits/ legacy + ai_context_files/ current)
    for m in re.finditer(r'(?:ai_traits|ai_context_files)/[\w/.-]+\.[\w.]+', content):
        add_ref(m.group(), "item")
    for m in re.finditer(r'ai_profiles/[\w/.-]+\.[\w.]+', content):
        add_ref(m.group(), "item")
    for m in re.finditer(r'~/bin/ai/[\w/.-]+\.\w+', content):
        add_ref(m.group(), "script")
    for m in re.finditer(r'\$AI_ROOT/[\w/.-]+\.\w+', content):
        add_ref(m.group(), "item")

    # Layer 3: MCP tool references (backtick-wrapped or known server names)
    for m in re.finditer(r'`(\w+):(\w+)`', content):
        server, tool = m.group(1), m.group(2)
        if server in known_mcps:
            add_ref(f"{server}:{tool}", "tool", f"{server}:{tool}")
    # Also check non-backtick with known server names
    for m in re.finditer(r'\b(\w+):(\w+)\b', content):
        server, tool = m.group(1), m.group(2)
        if server in known_mcps and tool not in ("//", ""):
            key = f"{server}:{tool}"
            if key not in seen:
                add_ref(key, "tool", key)

    return refs


# === MCP scanning ===

def scan_mcps(db: sqlite3.Connection):
    """Scan apps/mcps/ for server.py files and extract tool info.

    PORTED: degrades gracefully if MCPS_DIR is absent (fresh instance may not
    have apps/mcps/ populated) — leaves the mcps/mcp_tools tables empty rather
    than crashing.
    """
    if not MCPS_DIR.exists():
        return

    now = datetime.now(timezone.utc).isoformat()

    for server_dir in MCPS_DIR.iterdir():
        if not server_dir.is_dir():
            continue
        server_py = server_dir / "server.py"
        if not server_py.exists():
            continue

        name = server_dir.name
        content = server_py.read_text(encoding="utf-8")

        # Extract tool names
        tools = re.findall(r'name="(\w+)"', content)
        tools = [t for t in tools if t != "test"]
        description_match = re.search(r'"""(.+?)"""', content, re.DOTALL)
        description = ""
        if description_match:
            first_line = description_match.group(1).strip().split("\n")[0]
            description = first_line[:200]

        db.execute(
            "INSERT OR REPLACE INTO mcps (name, description, tool_count, server_path, scanned_at) VALUES (?,?,?,?,?)",
            (name, description, len(tools), str(server_py.relative_to(AI_GENERAL)), now)
        )

        # Tool details
        db.execute("DELETE FROM mcp_tools WHERE mcp_name = ?", (name,))
        for tool_name in tools:
            db.execute(
                "INSERT OR IGNORE INTO mcp_tools (mcp_name, tool_name) VALUES (?,?)",
                (name, tool_name)
            )


# === File scanning ===

def collect_files(base_dir: Path, item_type_default: str = "context_file") -> list[dict]:
    """Walk a directory and collect scannable files, grouped by logical item."""
    files = []
    for root, dirs, filenames in os.walk(base_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(AI_GENERAL)

        # Exclude dirs (exact names + prefix matches like _archive*)
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS
                   and not d.startswith(EXCLUDE_DIR_PREFIXES)]

        for fname in filenames:
            if fname in EXCLUDE_FILES:
                continue
            ext = "." + fname.split(".", 1)[1] if "." in fname else ""
            # Check extension — handle .condensed.yml specially
            if fname.endswith(".condensed.yml"):
                pass  # include
            elif not any(fname.endswith(e) for e in INCLUDE_EXTENSIONS):
                continue

            fpath = root_path / fname
            # Skip back-compat shim symlinks (todo_0319 reorg). A REAL item symlink
            # (.latest) targets its own "versions/<stem>_v<ver>.*" file. The reorg
            # leaves a shim at each moved item's OLD path pointing at its new home
            # (e.g. "../instructions/.../X.md" or "reference/X.latest.md"). So: any
            # symlink whose target is NOT "versions/..." is a shim → skip it, which
            # prevents counting the same item at both its old and new paths and works
            # for plain-.md items and any move direction.
            if fpath.is_symlink() and not os.readlink(fpath).startswith("versions/"):
                continue
            files.append({
                "path": fpath,
                "rel_path": str(fpath.relative_to(AI_GENERAL)),
                "filename": fname,
                "item_id": infer_item_id(fname),
                "variant": infer_variant(fname),
                "item_type": infer_item_type(fpath),
            })

    return files


def _get_parent_key(path: Path) -> str:
    """Get the immediate parent directory name for grouping disambiguation."""
    try:
        rel = path.relative_to(AI_GENERAL)
        parts = list(rel.parts)
        # Return the immediate parent dir (not the file itself)
        if len(parts) >= 2:
            return parts[-2]
    except Exception:
        pass
    return ""


def group_by_item(files: list[dict]) -> dict[str, list[dict]]:
    """Group files by logical item ID, disambiguating collisions.

    Collisions are detected at two levels:
    1. Same stem, different categories → prefix with category
    2. Same stem, same category, different subdirectories → prefix with subdir
    """
    groups: dict[str, list[dict]] = {}
    for f in files:
        item_id = f["item_id"]
        groups.setdefault(item_id, []).append(f)

    final: dict[str, list[dict]] = {}
    for item_id, file_list in groups.items():
        # Check for cross-parent collisions (different subdirectories)
        parent_dirs = set()
        for f in file_list:
            parent_dirs.add(_get_parent_key(f["path"]))

        if len(parent_dirs) > 1:
            # Collision — files with same stem in different dirs
            for f in file_list:
                parent = _get_parent_key(f["path"])
                prefixed_id = f"{parent}/{item_id}" if parent else item_id
                f["item_id"] = prefixed_id
                final.setdefault(prefixed_id, []).append(f)
        else:
            final[item_id] = file_list

    return final


def scan_items(db: sqlite3.Connection, base_dir: Path, errors: list[dict], known_mcps: set[str]):
    """Scan a directory tree and populate content_items + content_files."""
    now = datetime.now(timezone.utc).isoformat()
    files = collect_files(base_dir)
    groups = group_by_item(files)

    for item_id, file_list in groups.items():
        # Use the canonical source (prefer .md) for metadata
        canonical = None
        for variant_pref in ["source_md", "source_yml", "condensed_yml"]:
            for f in file_list:
                if f["variant"] == variant_pref:
                    canonical = f
                    break
            if canonical:
                break
        if not canonical:
            canonical = file_list[0]

        try:
            content = canonical["path"].resolve().read_text(encoding="utf-8")
        except Exception as e:
            errors.append({"path": canonical["rel_path"], "phase": "read", "error_type": "io", "message": str(e)})
            continue

        meta = extract_metadata(canonical["path"], content)
        category, subcategory = infer_category(canonical["path"])
        status = meta.get("status") or infer_status(canonical["path"])
        item_type = canonical["item_type"]
        composition_type = item_type if item_type != "context_file" else None
        name = meta.get("name") or infer_name(item_id)
        description = meta.get("description") or extract_description(content, canonical["filename"])
        version = meta.get("version", "")
        created = meta.get("created", "")
        updated = meta.get("updated", "")

        # Upsert content_item
        db.execute("""
            INSERT INTO content_items (id, item_type, category, subcategory, composition_type,
                name, status, version, description, created, updated, scanned_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                item_type=excluded.item_type, category=excluded.category,
                subcategory=excluded.subcategory, composition_type=excluded.composition_type,
                name=excluded.name, status=excluded.status, version=excluded.version,
                description=excluded.description, created=excluded.created,
                updated=excluded.updated, scanned_at=excluded.scanned_at
        """, (item_id, item_type, category, subcategory, composition_type,
              name, status, version, description, str(created), str(updated), now))

        # Nature tags
        natures = meta.get("nature", [])
        if isinstance(natures, str):
            natures = [natures]
        if natures:
            db.execute("DELETE FROM item_natures WHERE item_id = ?", (item_id,))
            for n in natures:
                db.execute("INSERT OR IGNORE INTO item_natures (item_id, nature) VALUES (?,?)", (item_id, n))

        # Content files
        for f in file_list:
            try:
                fpath = f["path"].resolve()
                file_content = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
                chash = compute_hash(f["path"])
                tokens = estimate_tokens(file_content)
                fsize = fpath.stat().st_size if fpath.exists() else 0
                symtarget = str(os.readlink(f["path"])) if f["path"].is_symlink() else None
                is_preferred = 1 if f["variant"] == VARIANT_PREFERENCE[0] else 0
                # If no condensed, prefer yml, then md
                if not any(ff["variant"] == "condensed_yml" for ff in file_list):
                    if f["variant"] == "source_yml":
                        is_preferred = 1
                    elif f["variant"] == "source_md" and not any(ff["variant"] == "source_yml" for ff in file_list):
                        is_preferred = 1

                db.execute("""
                    INSERT INTO content_files (item_id, path, variant, is_preferred, content_hash,
                        token_estimate, file_size, symlink_target, scanned_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET
                        item_id=excluded.item_id, variant=excluded.variant,
                        is_preferred=excluded.is_preferred, content_hash=excluded.content_hash,
                        token_estimate=excluded.token_estimate, file_size=excluded.file_size,
                        symlink_target=excluded.symlink_target, scanned_at=excluded.scanned_at
                """, (item_id, f["rel_path"], f["variant"], is_preferred, chash,
                      tokens, fsize, symtarget, now))
            except Exception as e:
                errors.append({"path": f["rel_path"], "phase": "file", "error_type": "io", "message": str(e)})

        # References (from canonical file)
        try:
            refs = extract_references(content, known_mcps)
            for ref in refs:
                db.execute("""
                    INSERT OR IGNORE INTO content_references (source_id, target_path, target_type, target_name)
                    VALUES (?,?,?,?)
                """, (item_id, ref["target_path"], ref["target_type"], ref.get("target_name", "")))
        except Exception as e:
            errors.append({"path": canonical["rel_path"], "phase": "reference", "error_type": "parse", "message": str(e)})


def resolve_references(db: sqlite3.Connection):
    """Resolve target_path to target_id where possible."""
    rows = db.execute("SELECT rowid, target_path FROM content_references WHERE target_id IS NULL").fetchall()
    for rowid, target_path in rows:
        # Try direct path match
        match = db.execute("SELECT item_id FROM content_files WHERE path = ?", (target_path,)).fetchone()
        if match:
            db.execute("UPDATE content_references SET target_id = ? WHERE rowid = ?", (match[0], rowid))
            continue
        # Try item id match
        match = db.execute("SELECT id FROM content_items WHERE id = ?", (target_path,)).fetchone()
        if match:
            db.execute("UPDATE content_references SET target_id = ? WHERE rowid = ?", (match[0], rowid))


def rebuild_fts(db: sqlite3.Connection):
    """Rebuild the FTS index from content_items."""
    db.execute("DELETE FROM content_fts")
    rows = db.execute("SELECT id, name, description, category FROM content_items").fetchall()
    for row in rows:
        db.execute("INSERT INTO content_fts (item_id, name, description, category) VALUES (?,?,?,?)", row)


# === Lock management ===

def acquire_lock() -> bool:
    """Acquire scan lock. Returns True if acquired.

    Clears a STALE lock so a crashed scan can't block scans forever: stale =
    the holder PID is no longer alive, OR the lock is > 5 min old. (A dead scan
    used to leave a lock that blocked re-scans for 5 min while the DB sat broken.)
    """
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        holder_alive = True
        try:
            pid = int(LOCK_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)  # signal 0 = liveness probe; raises if dead
        except (ValueError, OSError):
            holder_alive = False  # bad PID or dead process -> stale
        if holder_alive and age < 300:
            return False
        LOCK_PATH.unlink()  # stale: dead holder or >5 min old
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock():
    """Release scan lock."""
    try:
        LOCK_PATH.unlink()
    except Exception:
        pass


# === Main operations ===

def init_db() -> sqlite3.Connection:
    """Initialize database from schema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    db.executescript(schema)
    return db


def full_scan():
    """Rebuild registry from scratch."""
    if not acquire_lock():
        print("Another scan is in progress. Exiting.", file=sys.stderr)
        return 1

    try:
        print(f"Full scan starting... ({datetime.now().strftime('%H:%M:%S')})")
        db = init_db()
        errors: list[dict] = []

        # Clear existing data
        for table in ["content_fts", "content_references", "item_natures", "item_aliases",
                       "content_files", "content_items", "mcp_tools", "mcps"]:
            db.execute(f"DELETE FROM {table}")
        # ATOMIC REBUILD: do NOT commit here, nor between the steps below. The
        # truncate + full repopulate is one transaction, committed only at the very
        # end (step 7). A crash mid-scan therefore rolls back to the prior registry
        # instead of leaving an empty, committed DB. (Same-connection reads still
        # see these uncommitted writes, so step ordering is unaffected.)

        # 1. MCPs first (needed for reference resolution)
        print("  Scanning MCPs...")
        scan_mcps(db)
        known_mcps = {row[0] for row in db.execute("SELECT name FROM mcps").fetchall()}

        # 2. Context files
        print("  Scanning ai_context_files/...")
        scan_items(db, TRAITS_DIR, errors, known_mcps)

        # 3. Profiles
        print("  Scanning ai_profiles/...")
        scan_items(db, PROFILES_DIR, errors, known_mcps)

        # 4. Resolve references
        print("  Resolving references...")
        resolve_references(db)

        # 5. Rebuild FTS
        print("  Building FTS index...")
        rebuild_fts(db)

        # 6. Registry metadata
        now = datetime.now(timezone.utc).isoformat()
        # PORTED: degrade gracefully if git is absent / AI_GENERAL is not a repo
        # (fresh box / WSL / Windows). Never let a missing git break the scan.
        git_commit = ""
        try:
            git_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                cwd=str(AI_GENERAL), timeout=5
            ).stdout.strip()[:12]
        except Exception:
            git_commit = ""

        for k, v in [("schema_version", "1.0.0"), ("scanner_version", "1.0.0"),
                      ("generated_at", now), ("source_root", str(AI_GENERAL)),
                      ("git_commit", git_commit)]:
            db.execute("INSERT OR REPLACE INTO registry_meta (key, value) VALUES (?,?)", (k, v))

        # 7. Log
        item_count = db.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
        file_count = db.execute("SELECT COUNT(*) FROM content_files").fetchone()[0]
        ref_count = db.execute("SELECT COUNT(*) FROM content_references").fetchone()[0]
        mcp_count = db.execute("SELECT COUNT(*) FROM mcps").fetchone()[0]

        db.execute("""
            INSERT INTO scan_log (timestamp, mode, files_scanned, items_added, items_updated, items_removed, errors)
            VALUES (?, 'full', ?, ?, 0, 0, ?)
        """, (now, file_count, item_count, json.dumps([e["message"] for e in errors[:20]])))

        # Log errors
        if errors:
            scan_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            for e in errors:
                db.execute("""
                    INSERT INTO scan_errors (scan_id, path, phase, error_type, message)
                    VALUES (?,?,?,?,?)
                """, (scan_id, e.get("path"), e.get("phase"), e.get("error_type"), e.get("message")))

        db.commit()
        db.close()

        print(f"\nRegistry built:")
        print(f"  Items:      {item_count}")
        print(f"  Files:      {file_count}")
        print(f"  References: {ref_count}")
        print(f"  MCPs:       {mcp_count}")
        if errors:
            print(f"  Errors:     {len(errors)}")
            for e in errors[:5]:
                print(f"    {e['phase']}: {e['path']} — {e['message'][:80]}")
        print(f"  DB:         {DB_PATH}")
        return 0

    finally:
        release_lock()


def check_mode():
    """Report issues without writing."""
    print("Inventory/check mode...")
    files = collect_files(TRAITS_DIR) + collect_files(PROFILES_DIR)
    groups = group_by_item(files)

    print(f"\nFiles found: {len(files)}")
    print(f"Logical items: {len(groups)}")

    # Variant breakdown
    variants = {}
    for f in files:
        v = f["variant"]
        variants[v] = variants.get(v, 0) + 1
    print(f"Variants: {variants}")

    # Items with multiple variants
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Items with multiple variants: {len(multi)}")

    # Check for collisions that got prefixed
    prefixed = [k for k in groups if "/" in k and not k.startswith("ai_")]
    if prefixed:
        print(f"\nID collisions (category-prefixed): {len(prefixed)}")
        for p in prefixed[:10]:
            print(f"  {p}")

    return 0


def stats_mode():
    """Print registry statistics."""
    if not DB_PATH.exists():
        print("No registry database found. Run --full first.")
        return 1

    db = sqlite3.connect(str(DB_PATH))
    print("=== Traits Registry Statistics ===\n")

    # Meta
    for row in db.execute("SELECT key, value FROM registry_meta ORDER BY key"):
        print(f"  {row[0]}: {row[1]}")
    print()

    # Items by type
    print("Items by type:")
    for row in db.execute("SELECT item_type, COUNT(*) FROM content_items GROUP BY item_type ORDER BY item_type"):
        print(f"  {row[0]}: {row[1]}")
    print()

    # Items by category
    print("Items by category:")
    for row in db.execute("SELECT category, COUNT(*) FROM content_items WHERE category IS NOT NULL GROUP BY category ORDER BY category"):
        print(f"  {row[0]}: {row[1]}")
    print()

    # Items by status
    print("Items by status:")
    for row in db.execute("SELECT status, COUNT(*) FROM content_items GROUP BY status ORDER BY status"):
        print(f"  {row[0]}: {row[1]}")
    print()

    # Files by variant
    print("Files by variant:")
    for row in db.execute("SELECT variant, COUNT(*) FROM content_files GROUP BY variant ORDER BY variant"):
        print(f"  {row[0]}: {row[1]}")
    print()

    # References
    ref_count = db.execute("SELECT COUNT(*) FROM content_references").fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM content_references WHERE target_id IS NOT NULL").fetchone()[0]
    print(f"References: {ref_count} total, {resolved} resolved, {ref_count - resolved} unresolved")

    # MCPs
    mcp_count = db.execute("SELECT COUNT(*) FROM mcps").fetchone()[0]
    tool_count = db.execute("SELECT COUNT(*) FROM mcp_tools").fetchone()[0]
    print(f"MCPs: {mcp_count} servers, {tool_count} tools")

    # Recent scan
    row = db.execute("SELECT timestamp, mode, files_scanned, items_added FROM scan_log ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        print(f"\nLast scan: {row[0]} ({row[1]}, {row[2]} files, {row[3]} items)")

    db.close()
    return 0


def inventory_mode(as_json: bool = False):
    """Detailed inventory of files and variant groups."""
    files = collect_files(TRAITS_DIR) + collect_files(PROFILES_DIR)
    groups = group_by_item(files)

    if as_json:
        output = {
            "total_files": len(files),
            "total_items": len(groups),
            "items": {}
        }
        for item_id, file_list in sorted(groups.items()):
            output["items"][item_id] = {
                "variants": [{"path": f["rel_path"], "variant": f["variant"]} for f in file_list],
                "category": infer_category(file_list[0]["path"])[0],
                "status": infer_status(file_list[0]["path"]),
            }
        print(json.dumps(output, indent=2))
    else:
        check_mode()

    return 0


def main():
    parser = argparse.ArgumentParser(description="Scan and build the traits registry")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Full rebuild from scratch")
    group.add_argument("--incremental", action="store_true", help="Only update changed files")
    group.add_argument("--check", action="store_true", help="Report issues, no writes")
    group.add_argument("--stats", action="store_true", help="Print registry statistics")
    group.add_argument("--inventory", action="store_true", help="Detailed file inventory")
    parser.add_argument("--json", action="store_true", help="JSON output (with --inventory)")

    args = parser.parse_args()

    if args.full:
        return full_scan()
    elif args.incremental:
        # For now, incremental == full. Optimize later with hash comparison.
        return full_scan()
    elif args.check:
        return check_mode()
    elif args.stats:
        return stats_mode()
    elif args.inventory:
        return inventory_mode(args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
