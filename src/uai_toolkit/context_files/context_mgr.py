#!/usr/bin/env python3
"""
context_mgr.py — SQLite-backed index for UAI's Context Mgr.

Phase 1 of the Context Mgr overhaul (todo_0331). This module owns the SQLite
index + schema and the read-only query CLI. Files on disk are the source of
truth; this database (``ai_general/data/context.db``) is a rebuildable index
over them. The class stays ``ContextIndex`` (it remains the index); the DB
filename ``data/context.db`` is unchanged.

Domain model
------------
- **Context files** (leaf content): kinds ``brief``, ``memory``, ``knowledge``,
  ``instruction``.
- **Composition** (bundles that reference others): kinds ``role``, ``profile``,
  ``skill``, ``global``.
- A **reference graph**: composition items reference context files and each
  other via rows in ``edges``.

Library usage::

    from uai_toolkit.context_files.context_mgr import ContextIndex
    idx = ContextIndex()                 # uses default DB_PATH under AI_ROOT
    idx = ContextIndex(db_path=tmp)      # override for tests

Database location: {AI_ROOT}/ai_general/data/context.db
Schema version tracked in the ``context_meta`` table for forward migration.

Conventions follow the sibling store
``ai_general/scripts/session_mgmt/session_store.py``: module-level DDL,
``_init_db()`` with CREATE TABLE IF NOT EXISTS, DB_PATH resolved from AI_ROOT
but overridable via the constructor, ``PRAGMA journal_mode=WAL`` +
``foreign_keys=ON``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is available in the workspace
    yaml = None

# AI_ROOT resolution (via the shared path resolver).
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402

SCHEMA_VERSION = 1

DB_PATH = AI_ROOT / "ai_general" / "data" / "context.db"

# Kinds that bundle/compose other items (vs. leaf content kinds).
COMPOSITION_KINDS = frozenset({"role", "profile", "skill", "global"})
LEAF_KINDS = frozenset({"brief", "memory", "knowledge", "instruction"})

# Derived ``loader`` per kind — how a bundle is delivered into a session.
# Bundles differ only by doorway: role via MCP (``knowledge_get_*``), skill via
# a /command, global always-on; a profile is an MCP-loaded bundle of roles, so
# it shares ``mcp``. Leaf content kinds have no loader (a bundle pulls them in),
# so they map to None. Computed from ``kind`` — NOT a schema column.
_LOADER_BY_KIND = {
    "role": "mcp",
    "profile": "mcp",
    "skill": "command",
    "global": "auto",
}
# Reverse map for the ``--loader`` list filter: loader -> kinds that carry it.
_KINDS_BY_LOADER: Dict[str, List[str]] = {}
for _k, _l in _LOADER_BY_KIND.items():
    _KINDS_BY_LOADER.setdefault(_l, []).append(_k)


def _loader_for_kind(kind: Optional[str]) -> Optional[str]:
    """Return the derived loader (mcp/command/auto) for a kind; None for leaves."""
    return _LOADER_BY_KIND.get(kind)


# Orphan severity by kind: briefs/memories are orphan-by-nature (no inbound
# edges expected), so the UI can de-emphasize them; knowledge/instruction
# orphans are likely real defects worth surfacing.
_ORPHAN_SEVERITY = {
    "brief": "low",
    "memory": "low",
    "knowledge": "warn",
    "instruction": "warn",
}


def _orphan_severity(kind: Optional[str]) -> str:
    """Return the orphan severity (low|warn) for a leaf kind (default warn)."""
    return _ORPHAN_SEVERITY.get(kind, "warn")

# Content-file extensions we index (excludes .json/.txt/.DS_Store noise).
_CONTENT_EXTS = frozenset({".md", ".yml", ".yaml"})

# Source layout: (kind, path relative to ai_general). Reference strings in
# composition files use these same prefixes (extension-less), so the same
# table resolves both on-disk files and references. Order matters: more
# specific prefixes (e.g. ai_profiles/globals) must precede ai_profiles.
_REF_PREFIXES = (
    ("knowledge", "ai_context_files/knowledge"),
    ("instruction", "ai_context_files/instructions"),
    # platforms map to instruction by default (no platform leaf-kind yet).
    ("instruction", "ai_context_files/platforms"),
    ("global", "ai_profiles/globals"),
    ("skill", "ai_profiles/skills"),
    ("role", "ai_profiles/roles"),
)


# =============================================================================
# Schema
# =============================================================================

# Core schema (everything except the FTS table, which needs build-dependent
# handling for the fts5 module).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,                 -- stable id, e.g. <kind>:<name> or a hash
  kind TEXT NOT NULL,                  -- brief|memory|knowledge|instruction|role|profile|skill|global
  name TEXT NOT NULL,
  path TEXT NOT NULL,                  -- file path relative to AI_ROOT
  title TEXT, summary TEXT,
  status TEXT NOT NULL DEFAULT 'active', -- active|archived
  scope TEXT,                          -- e.g. 'global' when applied to all (derived from globals membership)
  created_at TEXT, updated_at TEXT,
  size_bytes INTEGER, content_hash TEXT,
  provenance_json TEXT                 -- briefs: {generated_by, source, generated_at}; nullable
);
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind, status);
CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
CREATE TABLE IF NOT EXISTS edges (
  src_id TEXT NOT NULL,                -- referencing item
  dst_id TEXT NOT NULL,                -- referenced item (may be unresolved name if dangling)
  edge_type TEXT NOT NULL DEFAULT 'references', -- references|composes
  order_idx INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (src_id, dst_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
CREATE TABLE IF NOT EXISTS changelog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id TEXT NOT NULL, op TEXT NOT NULL, field TEXT,
  old_value TEXT, new_value TEXT, changed_by TEXT, changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changelog_item ON changelog(item_id);
CREATE TABLE IF NOT EXISTS context_meta (key TEXT PRIMARY KEY, value TEXT);
"""

# FTS table — fts5 is preferred. On sqlite builds without fts5 we fall back to a
# plain table with the same columns.
FTS_SQL_FTS5 = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts "
    "USING fts5(id UNINDEXED, title, summary, content);"
)
FTS_SQL_FALLBACK = (
    "CREATE TABLE IF NOT EXISTS items_fts "
    "(id TEXT, title TEXT, summary TEXT, content TEXT);"
)


class ContextIndex:
    """SQLite-backed index for the Context Mgr.

    Files are the source of truth; this DB is a rebuildable index. This class
    owns schema creation only (Phase 1). Reads return plain values — no ORM.

    Attributes:
        db_path: Path to the SQLite database.
        fts5_available: True if the items_fts table uses the fts5 module;
            False if the plain-table fallback was used.
    """

    def __init__(
        self,
        db_path: Optional[Union[Path, str]] = None,
        ai_root: Optional[Union[Path, str]] = None,
    ):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # The on-disk context tree to scan. Defaults to the live AI_ROOT but is
        # overridable so reindex can run against a fixture tree in tests.
        self.ai_root = Path(ai_root) if ai_root else AI_ROOT
        self.fts5_available = False
        self._init_db()

    # -- scan roots (relative to self.ai_root) -------------------------------

    @property
    def _ai_general(self) -> Path:
        return self.ai_root / "ai_general"

    @property
    def _working_memory_dir(self) -> Path:
        return self.ai_root / "ai_memories" / "80_working_memory"

    def _init_db(self) -> None:
        """Create tables/indexes if absent; record schema_version once."""
        # WAL mode must be set outside a transaction.
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()

        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

            # FTS table: prefer fts5, fall back to a plain table if unavailable.
            try:
                conn.execute(FTS_SQL_FTS5)
                self.fts5_available = True
            except sqlite3.OperationalError:
                conn.execute(FTS_SQL_FALLBACK)
                self.fts5_available = False

            # Record schema_version if absent (idempotent).
            conn.execute(
                "INSERT OR IGNORE INTO context_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # Reindex — scan the on-disk tree, classify items, build the edge graph.
    # =========================================================================

    def reindex(self, *, dry_run: bool = False) -> dict:
        """Scan the context tree, upsert ``items``, rebuild ``edges``.

        Files are the source of truth; this rebuilds the index to match them.
        Each item gets id ``<kind>:<name>``. Composition items (role/profile/
        skill/global) contribute edges to the items they reference — 'composes'
        when the target is another bundle, 'references' for leaf content. A
        reference whose target file does not exist still produces an edge (with
        a best-effort dst id) so dangling links are detectable.

        Items directly referenced by a ``global`` get ``scope='global'``.

        Args:
            dry_run: If True, compute and return counts without writing.

        Returns:
            ``{"items_by_kind": {kind: n, ...}, "edges": n, "unresolved": n}``.
        """
        items = self._scan_items()
        edges = self._build_edges(items)

        item_ids = set(items)
        # Apply global scope: anything a global directly references.
        for src_id, dst_id, _etype, _oidx in edges:
            src = items.get(src_id)
            if src is not None and src["kind"] == "global" and dst_id in items:
                items[dst_id]["scope"] = "global"

        unresolved = sum(1 for (_s, dst, _t, _o) in edges if dst not in item_ids)
        counts = {
            "items_by_kind": dict(Counter(it["kind"] for it in items.values())),
            "edges": len(edges),
            "unresolved": unresolved,
        }

        if dry_run:
            return counts

        self._write(items, edges)
        return counts

    # -- scanning ------------------------------------------------------------

    def _scan_items(self) -> Dict[str, dict]:
        """Walk all sources and return ``{id: item_dict}``."""
        items: Dict[str, dict] = {}
        manifest = self._load_memory_manifest()

        # Leaf + composition files discovered by walking known directories.
        dirs = [
            (self._ai_general / "ai_context_files" / "knowledge", True),
            (self._ai_general / "ai_context_files" / "instructions", True),
            (self._ai_general / "ai_context_files" / "platforms", True),
            (self._ai_general / "ai_profiles" / "globals", True),
            (self._ai_general / "ai_profiles" / "skills", True),
            (self._ai_general / "ai_profiles" / "roles", True),
            (self._ai_general / "data" / "session_briefs", True),
        ]
        for base, recursive in dirs:
            if not base.exists():
                continue
            walker = base.rglob("*") if recursive else base.iterdir()
            for f in walker:
                if not f.is_file() or f.suffix.lower() not in _CONTENT_EXTS:
                    continue
                # Skip anything under a directory starting with '.' or '_'
                # (e.g. _archive, .git). Archived items are NOT indexed.
                if any(p.startswith((".", "_")) for p in f.relative_to(base).parts[:-1]):
                    continue
                self._add_item(items, f, manifest)

        # Profiles: top-level *.yml in ai_profiles (subdirs are roles/skills/
        # globals handled separately). Archived (_archive/) profiles are NOT
        # indexed.
        prof_dir = self._ai_general / "ai_profiles"
        if prof_dir.exists():
            for f in sorted(prof_dir.glob("*.yml")):
                if f.is_file():
                    self._add_item(items, f, manifest)

        # Working-memory slots (numeric NN.yml; manifest.yml excluded).
        # Archived slots (_archive/) are NOT indexed.
        wm = self._working_memory_dir
        if wm.exists():
            for f in sorted(wm.glob("*.yml")):
                if f.name == "manifest.yml":
                    continue
                self._add_item(items, f, manifest)

        return items

    def _add_item(self, items: dict, path: Path, manifest: dict) -> None:
        kn = self._kind_name_for_file(path)
        if kn is None:
            return
        kind, name = kn
        item_id = "{}:{}".format(kind, name)

        try:
            raw = path.read_bytes()
        except OSError:
            return
        text = raw.decode("utf-8", errors="replace")
        content_hash = hashlib.sha256(raw).hexdigest()

        title, summary, provenance = self._extract_meta(path, kind, text, name, manifest)

        try:
            st = path.stat()
            created = datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_ctime)).isoformat(timespec="seconds")
            updated = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
            size = st.st_size
        except OSError:
            created = updated = None
            size = len(raw)

        status = "archived" if "_archive" in path.parts else "active"

        items[item_id] = {
            "id": item_id,
            "kind": kind,
            "name": name,
            "path": self._rel_to_ai_root(path),
            "title": title,
            "summary": summary,
            "status": status,
            "scope": None,
            "created_at": created,
            "updated_at": updated,
            "size_bytes": size,
            "content_hash": content_hash,
            "provenance_json": provenance,
            "content": text,
        }

    # -- classification ------------------------------------------------------

    def _classify(self, path: Path) -> Optional[str]:
        """Return the kind for an on-disk file path, or None if not indexable."""
        kn = self._kind_name_for_file(path)
        return kn[0] if kn else None

    def _kind_name_for_file(self, path: Path) -> Optional[Tuple[str, str]]:
        """Map an on-disk file to ``(kind, name)`` or None.

        ``name`` is the path relative to the kind's base directory, without
        extension — the same value a reference string resolves to.
        """
        # Working-memory slots live outside ai_general. The name is the
        # wm-relative, extension-less path so an archived slot keeps its
        # ``_archive/`` segment (id ``memory:_archive/99``) — distinct from the
        # active ``memory:99`` and reclassified as archived by reindex.
        try:
            wm_rel = path.resolve().relative_to(self._working_memory_dir.resolve())
            if path.name != "manifest.yml":
                return ("memory", _strip_ext(wm_rel.as_posix()))
            return None
        except ValueError:
            pass

        try:
            rel = path.resolve().relative_to(self._ai_general.resolve())
        except ValueError:
            return None
        rel_posix = rel.as_posix()

        # Briefs (data/session_briefs/**.yml).
        if rel_posix.startswith("data/session_briefs/"):
            name = rel_posix[len("data/session_briefs/"):]
            return ("brief", _strip_ext(name))

        for kind, prefix in _REF_PREFIXES:
            pfx = prefix + "/"
            if rel_posix.startswith(pfx):
                return (kind, _strip_ext(rel_posix[len(pfx):]))

        # Top-level ai_profiles/*.yml → profile (subdirs roles/skills/globals/
        # platforms are excluded above). The ``_archive/`` subtree of
        # ai_profiles holds archived profiles: keep the ``_archive/`` segment in
        # the name (id ``profile:_archive/solo``) so reindex reclassifies it as
        # archived rather than losing it.
        if rel.suffix == ".yml":
            parent = rel.parent.as_posix()
            if parent == "ai_profiles":
                if rel.stem.lower() == "readme":
                    return None
                return ("profile", rel.stem)
            if parent.startswith("ai_profiles/{}".format(self._ARCHIVE_SEG)):
                name = rel_posix[len("ai_profiles/"):]
                return ("profile", _strip_ext(name))

        return None

    def _resolve_ref(self, ref: str) -> Optional[Tuple[str, str]]:
        """Resolve a reference string to ``(kind, name)``.

        References are extension-less paths relative to ai_general (e.g.
        ``ai_context_files/knowledge/x`` or ``ai_profiles/roles/dev``) or bare
        skill names (``peer-review``). Returns None for unrecognizable refs.
        """
        ref = (ref or "").strip()
        if not ref:
            return None

        for kind, prefix in _REF_PREFIXES:
            pfx = prefix + "/"
            if ref.startswith(pfx):
                name = _strip_ext(ref[len(pfx):])
                if kind == "skill":
                    name = name.replace("-", "_")
                return (kind, name)

        if ref.startswith("ai_context_files/"):
            # Unknown context subdir → treat as instruction (best effort).
            tail = ref.split("/", 2)[-1]
            return ("instruction", _strip_ext(tail))

        if ref.startswith("ai_profiles/"):
            # Top-level profile reference.
            return ("profile", _strip_ext(ref[len("ai_profiles/"):]))

        if "/" not in ref:
            # Bare name in a role's `skills:` list.
            return ("skill", _strip_ext(ref).replace("-", "_"))

        return None

    # -- references ----------------------------------------------------------

    def _parse_refs(self, path: Path, kind: str) -> List[Tuple[str, str]]:
        """Return ordered ``[(dst_id, edge_type), ...]`` for a composition file.

        Walks `roles`, `skills`, and `context_files` keys in document order.
        edge_type is 'composes' when the target is another bundle kind, else
        'references'. Unresolvable-but-shaped refs still yield a best-effort id.
        """
        refs, _ok = self._parse_refs_checked(path, kind)
        return refs

    def _parse_refs_checked(
        self, path: Path, kind: str
    ) -> Tuple[List[Tuple[str, str]], bool]:
        """Like :meth:`_parse_refs` but report parse success separately.

        Returns ``(refs, ok)``: ``ok`` is False ONLY when the file could not be
        read or its YAML failed to parse (so a caller — e.g. ``_refresh_edges``
        — can preserve existing edges instead of erasing them on a transient
        parse failure). A file that parses to a non-dict / has no refs is a
        successful parse with an empty ref list (``ok=True``).
        """
        if yaml is None:
            return [], True
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], False
        try:
            data = yaml.safe_load(text)
        except Exception:
            return [], False
        if not isinstance(data, dict):
            return [], True

        out: List[Tuple[str, str]] = []
        for ref in _iter_ref_strings(data):
            resolved = self._resolve_ref(ref)
            if resolved is None:
                continue
            dst_kind, dst_name = resolved
            dst_id = "{}:{}".format(dst_kind, dst_name)
            etype = "composes" if dst_kind in COMPOSITION_KINDS else "references"
            out.append((dst_id, etype))
        return out, True

    def _build_edges(self, items: Dict[str, dict]) -> List[Tuple[str, str, str, int]]:
        edges: List[Tuple[str, str, str, int]] = []
        seen = set()
        for item in items.values():
            if item["kind"] not in COMPOSITION_KINDS:
                continue
            src_id = item["id"]
            order_idx = 0
            for dst_id, etype in self._parse_refs(self.ai_root / item["path"], item["kind"]):
                key = (src_id, dst_id, etype)
                if key in seen:
                    continue
                seen.add(key)
                edges.append((src_id, dst_id, etype, order_idx))
                order_idx += 1
        return edges

    # -- metadata extraction -------------------------------------------------

    def _extract_meta(self, path, kind, text, name, manifest):
        """Best-effort ``(title, summary, provenance_json)`` for an item."""
        title = summary = provenance = None
        # Document version comes ONLY from frontmatter now (filename versioning is
        # deprecated). Surfaced via provenance_json so the UI's version chip lights.
        version = None
        try:
            if kind == "brief":
                data = (yaml.safe_load(text) or {}) if yaml else {}
                bm = data.get("brief_meta", {}) or {}
                meta = data.get("meta", {}) or {}
                title = bm.get("name") or path.stem
                summary = bm.get("description") or meta.get("topic") or meta.get("objective")
                prov = {k: bm.get(k) for k in ("sources", "condenser_session", "created", "status") if k in bm}
                provenance = json.dumps(prov, default=str) if prov else None
            elif kind == "memory":
                slot = manifest.get(_slot_key(name))
                if slot:
                    title = slot.get("name")
                    summary = slot.get("purpose")
                if not title:
                    title = name
            elif path.suffix.lower() in (".yml", ".yaml"):
                data = (yaml.safe_load(text) or {}) if yaml else {}
                if isinstance(data, dict):
                    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                    title = data.get("name") or meta.get("name") or meta.get("title") or path.stem
                    summary = data.get("description") or meta.get("description") or meta.get("purpose")
                    version = data.get("version") or meta.get("version")
                else:
                    title = path.stem
            else:  # markdown
                fm, body = _split_frontmatter(text)
                if isinstance(fm, dict):
                    title = fm.get("title") or fm.get("name") or fm.get("id")
                    summary = fm.get("summary") or fm.get("description")
                    version = fm.get("version")
                if not title:
                    title = _first_heading(body) or path.stem
                if not summary:
                    summary = _first_paragraph(body)
        except Exception:
            title = title or path.stem

        if title:
            title = " ".join(str(title).split())[:200]
        if summary:
            summary = " ".join(str(summary).split())[:500]
        if version not in (None, ""):
            # Merge version into provenance_json (the UI reads provenance.version).
            try:
                prov_obj = json.loads(provenance) if provenance else {}
                if not isinstance(prov_obj, dict):
                    prov_obj = {}
            except Exception:
                prov_obj = {}
            prov_obj["version"] = str(version).strip()
            provenance = json.dumps(prov_obj, default=str)
        return title, summary, provenance

    def _load_memory_manifest(self) -> dict:
        """Return ``{slot_key: {name, purpose}}`` from the working-memory manifest."""
        mf = self._working_memory_dir / "manifest.yml"
        if not mf.exists() or yaml is None:
            return {}
        try:
            data = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        out = {}
        for slot, info in (data.get("slot_structure") or {}).items():
            if isinstance(info, dict):
                out[_slot_key(str(slot))] = info
        return out

    # -- persistence ---------------------------------------------------------

    def _rel_to_ai_root(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.ai_root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _write(self, items: Dict[str, dict], edges) -> None:
        with self._connect() as conn:
            for it in items.values():
                conn.execute(
                    """
                    INSERT INTO items
                      (id, kind, name, path, title, summary, status, scope,
                       created_at, updated_at, size_bytes, content_hash, provenance_json)
                    VALUES (:id, :kind, :name, :path, :title, :summary, :status, :scope,
                            :created_at, :updated_at, :size_bytes, :content_hash, :provenance_json)
                    ON CONFLICT(id) DO UPDATE SET
                      kind=excluded.kind, name=excluded.name, path=excluded.path,
                      title=excluded.title, summary=excluded.summary,
                      status=excluded.status, scope=excluded.scope,
                      updated_at=excluded.updated_at, size_bytes=excluded.size_bytes,
                      content_hash=excluded.content_hash,
                      provenance_json=excluded.provenance_json
                    """,
                    {k: it[k] for k in (
                        "id", "kind", "name", "path", "title", "summary", "status",
                        "scope", "created_at", "updated_at", "size_bytes",
                        "content_hash", "provenance_json")},
                )

            # Prune items that no longer exist on disk (rebuildable index).
            ids = list(items)
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    "DELETE FROM items WHERE id NOT IN ({})".format(placeholders), ids
                )
            else:
                conn.execute("DELETE FROM items")

            # Rebuild edges from scratch.
            conn.execute("DELETE FROM edges")
            for src_id, dst_id, etype, order_idx in edges:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (src_id, dst_id, edge_type, order_idx) "
                    "VALUES (?, ?, ?, ?)",
                    (src_id, dst_id, etype, order_idx),
                )

            # Rebuild the FTS index.
            conn.execute("DELETE FROM items_fts")
            for it in items.values():
                conn.execute(
                    "INSERT INTO items_fts (id, title, summary, content) VALUES (?, ?, ?, ?)",
                    (it["id"], it["title"] or "", it["summary"] or "", it["content"] or ""),
                )

    # =========================================================================
    # Read API — the query surface UI + sessions consume. Read-only: these
    # methods never mutate items/edges (writes arrive in Phase 2). Files are
    # the source of truth; this DB is the index they are read through.
    # =========================================================================

    # Columns selected for the lightweight "row" shape. ``provenance_json`` is
    # the raw TEXT column; :meth:`_finalize_item_row` converts it into the
    # parsed ``provenance`` object|null before the row is returned to a caller.
    _LIST_COLS = (
        "id", "kind", "name", "title", "summary",
        "status", "scope", "path", "size_bytes", "updated_at",
        "provenance_json",
    )

    def list_items(
        self,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = "active",
        scope: Optional[str] = None,
        loader: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[dict]:
        """Return item rows, optionally filtered/paged.

        Args:
            kind: restrict to a single kind (e.g. ``role``); None = all kinds.
            status: restrict to a status (default ``active``); None or ``all``
                disables the filter.
            scope: restrict to a scope (e.g. ``global``); None = all scopes.
            loader: restrict to a derived loader (``mcp``/``command``/``auto``);
                translated to the bundle kinds that carry it. None = all.
            limit: max rows (None = unbounded); offset: rows to skip.

        Returns:
            List of ``{id,kind,name,title,summary,status,scope,path,
            size_bytes,updated_at,loader,provenance}`` dicts, ordered by
            (kind, name). ``loader`` is a derived field (mcp/command/auto for
            bundles, None for leaf content kinds). ``provenance`` is the parsed
            provenance object, or None (never a raw JSON string).
        """
        where, params = [], []
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if status and status != "all":
            where.append("status = ?")
            params.append(status)
        if scope:
            where.append("scope = ?")
            params.append(scope)
        if loader:
            kinds = _KINDS_BY_LOADER.get(loader, [])
            if not kinds:
                return []  # unknown loader -> no rows carry it
            placeholders = ",".join("?" * len(kinds))
            where.append("kind IN ({})".format(placeholders))
            params.extend(kinds)
        sql = "SELECT {} FROM items".format(", ".join(self._LIST_COLS))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY kind, name"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        elif offset:
            sql += " LIMIT -1 OFFSET ?"
            params.append(int(offset))
        with self._connect() as conn:
            return [self._finalize_item_row(dict(r)) for r in conn.execute(sql, params).fetchall()]

    @staticmethod
    def _finalize_item_row(row: dict) -> dict:
        """Normalize a raw item row for API output (in place).

        Applies the two cross-cutting transforms every read path shares so the
        returned shape is uniform:

        - attach the derived ``loader`` field (mcp/command/auto for bundles,
          None for leaf content kinds);
        - expose provenance as a parsed object (or None) under ``provenance``,
          dropping the raw ``provenance_json`` TEXT column. This guarantees the
          field is ``provenance`` = object|null everywhere it appears — never a
          raw JSON string in one method and a parsed object in another. The DB
          column name (``provenance_json``) is unchanged; only the API output
          is normalized.
        """
        row["loader"] = _loader_for_kind(row.get("kind"))
        row["provenance"] = _parse_json(row.pop("provenance_json", None))
        return row

    def children(self, item_id: str) -> List[dict]:
        """Return item rows for ``item_id``'s direct children.

        Children are the items ``item_id`` directly references — its
        outbound-edge targets — returned in edge (``order_idx``) order. Each row
        has the same lightweight shape as :meth:`list_items`. Only resolved
        targets (present in ``items``) are returned; dangling refs are omitted
        (use :meth:`refs` to inspect those).
        """
        cols = ", ".join(self._LIST_COLS)
        with self._connect() as conn:
            edge_rows = conn.execute(
                "SELECT dst_id FROM edges WHERE src_id = ? ORDER BY order_idx",
                (item_id,),
            ).fetchall()
            out: List[dict] = []
            for e in edge_rows:
                row = conn.execute(
                    "SELECT {} FROM items WHERE id = ?".format(cols), (e["dst_id"],)
                ).fetchone()
                if row is not None:
                    out.append(self._finalize_item_row(dict(row)))
        return out

    def get_item(self, item_id: str) -> Optional[dict]:
        """Return the full item row for ``item_id`` (or None if absent).

        Provenance is exposed as a parsed object (or None) under ``provenance``
        — never the raw ``provenance_json`` TEXT column — a derived ``loader``
        field is attached, and a ``counts`` key carries ``{outbound, inbound}``
        edge degrees.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            out_n = conn.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE src_id = ?", (item_id,)
            ).fetchone()["n"]
            in_n = conn.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE dst_id = ?", (item_id,)
            ).fetchone()["n"]
        self._finalize_item_row(item)
        item["counts"] = {"outbound": out_n, "inbound": in_n}
        return item

    def content(self, item_id: str) -> Optional[dict]:
        """Return an item's on-disk file text (the Content tab's payload).

        ``get_item`` returns metadata only; this returns the actual file body.
        Files are the source of truth, so the text is read from disk via the
        item's recorded (AI_ROOT-relative) path.

        Returns ``{id, kind, path, content}`` (``content`` is None if the file
        can't be read), or None if no such item exists.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind, path FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "path": row["path"],
            "content": self._read_body(row["path"]),
        }

    def _read_body(self, rel_path: str) -> Optional[str]:
        """Read a file (path relative to ``ai_root``) as UTF-8 text, or None."""
        if not rel_path:
            return None
        try:
            return (self.ai_root / rel_path).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return None

    def search(
        self, query: str, *, kind: Optional[str] = None, limit: int = 50
    ) -> List[dict]:
        """Full-text search over ``items_fts`` joined to ``items``.

        Returns rows ``{id,kind,name,title,summary,path,snippet}``. Uses the
        fts5 ``snippet()`` highlighter when available; falls back to a LIKE
        scan (no snippet) on sqlite builds without fts5.
        """
        q = (query or "").strip()
        if not q:
            return []
        with self._connect() as conn:
            if self.fts5_available:
                sql = (
                    "SELECT i.id, i.kind, i.name, i.title, i.summary, i.path, "
                    "snippet(items_fts, 3, '[', ']', '…', 12) AS snippet "
                    "FROM items_fts f JOIN items i ON i.id = f.id "
                    "WHERE items_fts MATCH ?"
                )
                params: list = [_fts_query(q)]
                if kind:
                    sql += " AND i.kind = ?"
                    params.append(kind)
                sql += " LIMIT ?"
                params.append(int(limit))
                try:
                    return [dict(r) for r in conn.execute(sql, params).fetchall()]
                except sqlite3.OperationalError:
                    pass  # malformed MATCH expression -> fall through to LIKE
            # Fallback: LIKE over title/summary/content.
            like = "%{}%".format(q)
            sql = (
                "SELECT i.id, i.kind, i.name, i.title, i.summary, i.path, "
                "NULL AS snippet "
                "FROM items_fts f JOIN items i ON i.id = f.id "
                "WHERE (f.title LIKE ? OR f.summary LIKE ? OR f.content LIKE ?)"
            )
            params = [like, like, like]
            if kind:
                sql += " AND i.kind = ?"
                params.append(kind)
            sql += " LIMIT ?"
            params.append(int(limit))
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def refs(self, item_id: str, *, direction: str = "out") -> List[dict]:
        """Return edge rows touching ``item_id``.

        direction ``out`` = edges where ``item_id`` is the source (items it
        references); ``in`` = edges where it is the destination (what
        references it); ``both`` = the union. Each row is
        ``{src_id,dst_id,edge_type,order_idx,resolved}`` where ``resolved``
        reports whether ``dst_id`` exists in ``items``.
        """
        if direction not in ("out", "in", "both"):
            raise ValueError("direction must be one of out|in|both")
        with self._connect() as conn:
            rows = []
            if direction in ("out", "both"):
                rows += conn.execute(
                    "SELECT * FROM edges WHERE src_id = ? ORDER BY order_idx",
                    (item_id,),
                ).fetchall()
            if direction in ("in", "both"):
                rows += conn.execute(
                    "SELECT * FROM edges WHERE dst_id = ? ORDER BY src_id",
                    (item_id,),
                ).fetchall()
            ids = {r["id"] for r in conn.execute("SELECT id FROM items").fetchall()}
        out = []
        for r in rows:
            out.append({
                "src_id": r["src_id"],
                "dst_id": r["dst_id"],
                "edge_type": r["edge_type"],
                "order_idx": r["order_idx"],
                "resolved": r["dst_id"] in ids,
            })
        return out

    def tree(self, item_id: str, *, max_depth: int = 10) -> dict:
        """Recursively expand outbound edges into a nested tree.

        Children follow ``composes``+``references`` edges in ``order_idx``
        order. Nodes are ``{id,kind,title,children:[...]}``; unresolved targets
        are marked ``unresolved=True``, repeat ancestors ``cycle=True``, and
        depth-capped nodes ``truncated=True`` (with empty ``children``).
        """
        items, adj = self._load_graph()

        def build(node_id: str, depth: int, ancestors: frozenset) -> dict:
            it = items.get(node_id)
            node: dict = {
                "id": node_id,
                "kind": it["kind"] if it else None,
                "title": it["title"] if it else None,
                "children": [],
            }
            if it is None:
                node["unresolved"] = True
                return node
            if node_id in ancestors:
                node["cycle"] = True
                return node
            if depth >= max_depth:
                if adj.get(node_id):
                    node["truncated"] = True
                return node
            nxt = ancestors | {node_id}
            for dst_id, _etype, _oidx in adj.get(node_id, []):
                node["children"].append(build(dst_id, depth + 1, nxt))
            return node

        return build(item_id, 0, frozenset())

    def resolve(self, item_id: str) -> dict:
        """Flatten a composition into its ordered, de-duplicated leaf files.

        Walks ``composes``/``references`` edges transitively (first-seen order
        preserved, deduped by id). Composition kinds are expanded; leaf content
        items are collected. Targets missing from ``items`` are reported under
        ``unresolved``.

        Each leaf carries the **composition chains** that pull it in under
        ``via`` (a list of ordered bundle-id paths from the start down to the
        leaf's parent), plus ``count`` when more than one distinct chain
        contributes it (powering the Loads ×N badge + hover). A leaf reached
        directly (no bundle) has ``via=[[]]``.

        Returns ``{id, resolved:[{id,kind,name,path,via,[count]}],
        unresolved:[dst_id...], total_size_bytes}``.
        """
        items, adj = self._load_graph()
        resolved: List[dict] = []
        resolved_by_id: Dict[str, dict] = {}
        unresolved: List[str] = []
        unresolved_seen: set = set()

        def walk(node_id: str, stack: frozenset, path: List[str]) -> None:
            if node_id in stack:
                return  # cycle guard
            it = items.get(node_id)
            if it is None:
                if node_id not in unresolved_seen:
                    unresolved_seen.add(node_id)
                    unresolved.append(node_id)
                return
            if it["kind"] in COMPOSITION_KINDS:
                nxt = stack | {node_id}
                child_path = path + [node_id]
                for dst_id, _etype, _oidx in adj.get(node_id, []):
                    walk(dst_id, nxt, child_path)
            else:  # leaf content file
                leaf = resolved_by_id.get(node_id)
                if leaf is None:
                    leaf = {
                        "id": it["id"], "kind": it["kind"],
                        "name": it["name"], "path": it["path"],
                        "via": [],
                    }
                    resolved_by_id[node_id] = leaf
                    resolved.append(leaf)
                chain = list(path)
                if chain not in leaf["via"]:
                    leaf["via"].append(chain)

        start = items.get(item_id)
        if start is not None and start["kind"] in COMPOSITION_KINDS:
            for dst_id, _etype, _oidx in adj.get(item_id, []):
                walk(dst_id, frozenset({item_id}), [item_id])
        else:
            walk(item_id, frozenset(), [])

        # Annotate multi-path leaves with a count (>1 distinct contributing chains).
        for leaf in resolved:
            if len(leaf["via"]) > 1:
                leaf["count"] = len(leaf["via"])

        total = sum(
            (items[r["id"]].get("size_bytes") or 0) for r in resolved
        )
        return {
            "id": item_id,
            "resolved": resolved,
            "unresolved": unresolved,
            "total_size_bytes": total,
        }

    def validate(self) -> dict:
        """Return integrity issues over the current index.

        ``dangling``: edges whose ``dst_id`` is absent from ``items``.
        ``orphans``: leaf items (kind in knowledge/instruction/brief) with zero
        inbound edges that are not global-scoped. Both queries count only edges
        whose SOURCE is an active item — an edge from an archived bundle neither
        counts as a real dangling defect nor keeps an active leaf from being
        reported as orphaned. Each orphan entry is
        ``{id, kind, severity}`` where ``severity`` is ``low`` for
        orphan-by-nature kinds (brief/memory) and ``warn`` for knowledge/
        instruction — so the UI can de-emphasize the expected briefs.
        """
        with self._connect() as conn:
            dangling = [
                {"src_id": r["src_id"], "dst_id": r["dst_id"]}
                for r in conn.execute(
                    "SELECT e.src_id, e.dst_id FROM edges e "
                    "JOIN items s ON s.id = e.src_id AND s.status = 'active' "
                    "LEFT JOIN items i ON i.id = e.dst_id "
                    "WHERE i.id IS NULL "
                    "ORDER BY e.src_id, e.dst_id"
                ).fetchall()
            ]
            orphans = [
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "severity": _orphan_severity(r["kind"]),
                }
                for r in conn.execute(
                    "SELECT i.id, i.kind FROM items i "
                    "WHERE i.kind IN ('knowledge','instruction','brief') "
                    "AND (i.scope IS NULL OR i.scope != 'global') "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM edges e "
                    "  JOIN items s ON s.id = e.src_id AND s.status = 'active' "
                    "  WHERE e.dst_id = i.id) "
                    "ORDER BY i.id"
                ).fetchall()
            ]
        return {"dangling": dangling, "orphans": orphans}

    def graph(self) -> dict:
        """Return the WHOLE reference graph in one shot for client-side use.

        Built so a UI (the Link Matrix) can fetch once and compute connectivity
        client-side — highlighting an item's transitively-connected set across
        columns without N per-item ``refs`` calls.

        ``items`` are the **active** items as lightweight rows
        ``{id, kind, name, title, loader, scope, status, provenance}``
        (``loader`` derived per kind: mcp/command/auto for bundles, None for
        leaves; ``provenance`` the parsed provenance object|null). ``edges`` is
        every edge ``{src_id, dst_id, edge_type}`` **whose source is an active
        item**, in ``order_idx`` order — including ones with a dangling
        ``dst_id`` (absent from ``items``) so the UI can flag dangling targets.
        Edges from archived sources are EXCLUDED (graph items are active-only, so
        such an edge would originate from a node the UI never renders). Item
        count equals the active-item total; edge count equals ``reindex``'s
        ``edges`` count when no archived bundle contributes edges.

        Returns ``{items:[...], edges:[...]}``.
        """
        with self._connect() as conn:
            items = [
                self._finalize_item_row({
                    "id": r["id"],
                    "kind": r["kind"],
                    "name": r["name"],
                    "title": r["title"],
                    "scope": r["scope"],
                    "status": r["status"],
                    "provenance_json": r["provenance_json"],
                })
                for r in conn.execute(
                    "SELECT id, kind, name, title, scope, status, provenance_json "
                    "FROM items WHERE status = 'active' ORDER BY kind, name"
                ).fetchall()
            ]
            edges = [
                {
                    "src_id": r["src_id"],
                    "dst_id": r["dst_id"],
                    "edge_type": r["edge_type"],
                }
                for r in conn.execute(
                    "SELECT e.src_id, e.dst_id, e.edge_type FROM edges e "
                    "JOIN items s ON s.id = e.src_id AND s.status = 'active' "
                    "ORDER BY e.src_id, e.order_idx"
                ).fetchall()
            ]
        return {"items": items, "edges": edges}

    def history(self, item_id: str, *, limit: int = 50) -> List[dict]:
        """Return changelog rows for ``item_id`` (newest first).

        Empty until Phase-2 writes populate the changelog, but the verb works.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM changelog WHERE item_id = ? "
                "ORDER BY changed_at DESC, id DESC LIMIT ?",
                (item_id, int(limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    # =========================================================================
    # Write API — AUTHORING path (Phase 2, Task 1). Context files only
    # (kinds knowledge|instruction: the .md-with-frontmatter case). Bundles and
    # link/move/delete are SEPARATE later tasks.
    #
    # SINGLE WRITE PATH: every mutation (file write + index upsert) routes
    # through :meth:`_record_change`, which records exactly one ``changelog``
    # row per mutation (item_id, op, field, old_value, new_value, changed_by,
    # changed_at). ``changed_by`` comes from the ``by`` param, defaulting to
    # ``$AI_TRACKING_ID`` then ``"unknown"``. Files are the source of truth; the
    # index is rebuilt from disk after each write so the row matches the file.
    # =========================================================================

    # Context-file kinds the authoring write path handles. Bundles
    # (role/profile/skill/global) and other leaves (brief/memory) are out of
    # scope for create/update_content.
    _AUTHORING_KINDS = frozenset({"knowledge", "instruction"})

    # Base directory (relative to ai_general) per authoring kind.
    _AUTHORING_BASE = {
        "knowledge": "ai_context_files/knowledge",
        "instruction": "ai_context_files/instructions",
    }

    def _resolve_by(self, by: Optional[str]) -> str:
        """Resolve the ``changed_by`` actor: explicit ``by`` > env > 'unknown'."""
        if by:
            return by
        return os.environ.get("AI_TRACKING_ID") or "unknown"

    def create(
        self,
        kind: str,
        title: str,
        category: str,
        *,
        name: Optional[str] = None,
        by: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """Create a context-file stub (knowledge|instruction) and index it.

        Derives a ``name`` slug from ``title`` when not given, computes the path
        under the kind's category dir (relative to ``ai_root``), and — unless it
        would collide with an existing file or item id — writes a minimal stub
        (YAML frontmatter with ``title`` + a body heading), inserts the item
        row, and records a ``changelog`` op="create" row through the single
        write path.

        Validates inputs: ``kind`` in {knowledge, instruction}; ``title``
        non-empty; ``category`` and derived ``name`` are safe slugs (no path
        traversal / absolute paths).

        Args:
            kind: ``knowledge`` or ``instruction``.
            title: human title; non-empty.
            category: category sub-directory (a safe slug).
            name: optional explicit slug (overrides the title-derived slug).
            by: actor for the changelog (defaults to $AI_TRACKING_ID/unknown).
            dry_run: compute + return the planned id/path WITHOUT writing the
                file or the row.

        Returns:
            ``{ok: True, id, path, dry_run}`` on success, else
            ``{ok: False, error, dry_run}``.
        """
        if kind not in self._AUTHORING_KINDS:
            return {
                "ok": False,
                "error": "kind must be one of {} (got {!r})".format(
                    sorted(self._AUTHORING_KINDS), kind
                ),
                "dry_run": dry_run,
            }
        title = (title or "").strip()
        if not title:
            return {"ok": False, "error": "title must be non-empty", "dry_run": dry_run}

        if not _is_safe_slug(category):
            return {
                "ok": False,
                "error": "category {!r} is not a safe slug".format(category),
                "dry_run": dry_run,
            }

        slug = name if name is not None else _slugify(title)
        if not _is_safe_slug(slug):
            return {
                "ok": False,
                "error": "name {!r} is not a safe slug".format(slug),
                "dry_run": dry_run,
            }

        rel_name = "{}/{}".format(category, slug)
        item_id = "{}:{}".format(kind, rel_name)
        rel_path = "{}/{}/{}.md".format(self._AUTHORING_BASE[kind], category, slug)
        rel_to_root = "ai_general/{}".format(rel_path)
        abs_path = self.ai_root / rel_to_root

        # Reject collisions (don't overwrite): existing file OR existing item id.
        if abs_path.exists():
            return {
                "ok": False,
                "error": "a file already exists at {}".format(rel_to_root),
                "dry_run": dry_run,
            }
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if existing is not None:
            return {
                "ok": False,
                "error": "an item with id {} already exists".format(item_id),
                "dry_run": dry_run,
            }

        if dry_run:
            return {"ok": True, "id": item_id, "path": rel_to_root, "dry_run": True}

        # YAML-safe frontmatter: a title with ':' '#' quotes or a leading '-'
        # would produce invalid/misparsed YAML if written raw, so serialize the
        # title line through yaml (plain scalars stay unquoted, special-char
        # titles get correctly quoted/escaped). The body heading is markdown,
        # so the raw title is fine there.
        title_line = _yaml_title_line(title)
        stub = "---\n{}\n---\n\n# {}\n".format(title_line, title)
        # Atomic exclusive create: never clobber a file that appeared between the
        # collision check above and now (TOCTOU-safe).
        try:
            _atomic_write(abs_path, stub, exclusive=True)
        except FileExistsError:
            return {
                "ok": False,
                "error": "a file already exists at {}".format(rel_to_root),
                "dry_run": False,
            }

        # Index from disk (files are the source of truth) + audit the create.
        self.reindex()
        self._record_change(
            item_id=item_id, op="create", field=None,
            old_value=None, new_value=rel_to_root, by=by,
        )
        return {"ok": True, "id": item_id, "path": rel_to_root, "dry_run": False}

    def update_content(
        self, item_id: str, content: str, *, by: Optional[str] = None
    ) -> dict:
        """Replace the BODY of an existing context-file item (frontmatter kept).

        Preserves the file's YAML frontmatter block (everything up to and
        including the closing ``---``) and replaces the body beneath it with
        ``content``. Reindexes the item (size/hash/summary refresh) and records
        a ``changelog`` op="update" field="content" row through the single write
        path. Rejects a missing item or a non-context-file kind.

        Returns ``{ok: True, id, path}`` or ``{ok: False, error}``.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind, path FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "no such item: {}".format(item_id)}
        if row["kind"] not in self._AUTHORING_KINDS:
            return {
                "ok": False,
                "error": "update_content only handles context files {} (got {})".format(
                    sorted(self._AUTHORING_KINDS), row["kind"]
                ),
            }

        rel_path = row["path"]
        abs_path = self.ai_root / rel_path
        try:
            current = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"ok": False, "error": "cannot read {}: {}".format(rel_path, e)}

        fm_block = _frontmatter_block(current)
        body = content if content.endswith("\n") else content + "\n"
        # Blank line between the frontmatter fence and the body (matches the
        # create-stub format and standard markdown).
        new_text = (fm_block + "\n\n" + body) if fm_block else body
        _atomic_write(abs_path, new_text)

        # Index from disk + audit the update.
        self.reindex()
        self._record_change(
            item_id=item_id, op="update", field="content",
            old_value=None, new_value=None, by=by,
        )
        return {"ok": True, "id": item_id, "path": rel_path}

    def edit_command(self, item_id: str) -> dict:
        """Resolve the editor + on-disk path for ``item_id`` (does NOT launch).

        The CLI ``edit`` verb launches the editor; this method only resolves so
        it is safely unit-testable. ``editor`` is ``$EDITOR`` or ``vi``.

        Also returns ``content_hash`` — the file's current SHA-256 — so the CLI
        can hand it to :meth:`apply_edit` after the editor exits to detect
        whether the human actually changed anything (and reindex + audit only
        then). ``None`` if the file can't be read.

        Returns ``{ok: True, path, editor, content_hash}`` (``path`` absolute) or
        ``{ok: False, error}``.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, path FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "no such item: {}".format(item_id)}
        abs_path = (self.ai_root / row["path"]).resolve()
        editor = os.environ.get("EDITOR") or "vi"
        return {
            "ok": True,
            "path": str(abs_path),
            "editor": editor,
            "content_hash": _sha256_file(abs_path),
        }

    def apply_edit(
        self, item_id: str, *, before_hash: Optional[str] = None,
        by: Optional[str] = None,
    ) -> dict:
        """Reconcile an interactive ``$EDITOR`` edit: reindex + audit if changed.

        The interactive launch lives in the CLI (not unit-testable); this method
        is the testable reconciliation run AFTER the editor exits. It compares
        the file's current hash against ``before_hash`` (captured by
        :meth:`edit_command` before launch). On a real change it reindexes from
        disk (files are the source of truth — size/hash/summary/edges refresh)
        and records ONE ``changelog`` op="update" field="content" row through the
        single write path. On a no-op (hash unchanged) it does nothing and
        records nothing.

        Returns ``{ok: True, id, changed: bool}`` or ``{ok: False, error}``.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, path FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "no such item: {}".format(item_id)}

        abs_path = (self.ai_root / row["path"]).resolve()
        after_hash = _sha256_file(abs_path)
        if after_hash is None:
            return {"ok": False,
                    "error": "cannot read {} after edit".format(row["path"])}

        if after_hash == before_hash:
            return {"ok": True, "id": item_id, "changed": False}

        # Index from disk + audit the edit (one row, single write path).
        self.reindex()
        self._record_change(
            item_id=item_id, op="update", field="content",
            old_value=before_hash, new_value=after_hash, by=by,
        )
        return {"ok": True, "id": item_id, "changed": True}

    def _record_change(
        self, *, item_id: str, op: str, field: Optional[str],
        old_value, new_value, by: Optional[str],
    ) -> None:
        """Record a single ``changelog`` row — the audit point of every write.

        ALL authoring mutations funnel here so each disk write is paired with
        exactly one changelog row (item_id, op, field, old/new value, the
        resolved ``changed_by`` actor, and an ISO ``changed_at`` timestamp).
        """
        changed_by = self._resolve_by(by)
        changed_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO changelog "
                "(item_id, op, field, old_value, new_value, changed_by, changed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, op, field,
                 None if old_value is None else str(old_value),
                 None if new_value is None else str(new_value),
                 changed_by, changed_at),
            )

    # =========================================================================
    # Write API — REFERENCE-GRAPH path (Phase 2, Task 2). link/unlink edit a
    # *bundle's* YAML (role/profile/skill/global) to add/remove a reference
    # edge, then INCREMENTALLY refresh only that bundle's outbound edges in the
    # index (not a full reindex — addresses the scaling concern) and record a
    # changelog row through the single write point.
    #
    # CORRECTNESS INVARIANT: the ref string written into the YAML must be
    # exactly what :meth:`reindex` parses back. We derive the ref from the dst
    # item's recorded ``path`` (ai_general-relative, extension-less) — the same
    # value ``_resolve_ref`` maps back to the dst id — so link-then-reindex is a
    # no-op on the edge set (proved by the round-trip tests).
    # =========================================================================

    def link(
        self, src_id: str, dst_id: str, *,
        by: Optional[str] = None, dry_run: bool = False,
    ) -> dict:
        """Add a reference edge from a bundle ``src`` to ``dst``.

        Validates: ``src`` exists and is a bundle (role/profile/skill/global);
        ``dst`` exists; ``src != dst``; adding the edge does not create a cycle
        (walks existing edges); ``dst`` is not already referenced by ``src``
        (idempotent — reports ``already_linked`` with no dup). On success, edits
        ``src``'s YAML to add the ref in the location :meth:`reindex` reads (a
        leaf dst under ``context_files`` in the dst's category bucket; a bundle
        dst into the ``roles``/``skills`` list), re-parses ONLY ``src``'s refs to
        replace its outbound edges incrementally, and records a ``changelog``
        op="link" row.

        ``dry_run`` returns the planned change (``file`` + ``ref``) WITHOUT
        writing the file, the edges, or the changelog row.

        Returns ``{ok: True, src_id, dst_id, ref, file, dry_run[, already_linked]}``
        or ``{ok: False, error}``.
        """
        items, adj = self._load_graph()
        err = self._validate_link(src_id, dst_id, items, adj)
        if err is not None:
            return {"ok": False, "error": err, "dry_run": dry_run}

        src = items[src_id]
        dst = items[dst_id]
        ref = self._ref_for_dst(dst)
        rel_file = src["path"]
        abs_file = self.ai_root / rel_file

        # Idempotent: already referenced -> report, no write, no dup.
        if self._has_outbound_edge(src_id, dst_id, adj):
            return {
                "ok": True, "src_id": src_id, "dst_id": dst_id, "ref": ref,
                "file": rel_file, "already_linked": True, "dry_run": dry_run,
            }

        if dry_run:
            return {
                "ok": True, "src_id": src_id, "dst_id": dst_id, "ref": ref,
                "file": rel_file, "dry_run": True,
            }

        try:
            current = abs_file.read_text(encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": "cannot read {}: {}".format(rel_file, e),
                    "dry_run": False}

        if dst["kind"] in COMPOSITION_KINDS:
            list_key = "skills" if dst["kind"] == "skill" else "roles"
            new_text = _yaml_add_to_list(current, list_key, ref)
        else:
            category = _ref_category(dst["name"])
            new_text = _yaml_add_to_context_files(current, category, ref)

        _atomic_write(abs_file, new_text)
        warning = self._refresh_edges(src_id)
        self._record_change(
            item_id=src_id, op="link", field="references",
            old_value=None, new_value=dst_id, by=by,
        )
        result = {
            "ok": True, "src_id": src_id, "dst_id": dst_id, "ref": ref,
            "file": rel_file, "dry_run": False,
        }
        # Surface a parse-failure warning so a caller (CLI/UI) is not told the
        # link succeeded cleanly when the index could not be incrementally
        # refreshed (existing edges preserved; a full reindex would reconcile).
        if warning:
            result["warning"] = warning
        return result

    def unlink(
        self, src_id: str, dst_id: str, *,
        by: Optional[str] = None, dry_run: bool = False,
    ) -> dict:
        """Remove the reference edge from a bundle ``src`` to ``dst``.

        Rejects when ``src`` is not a bundle, ``src`` does not exist, or the edge
        is not currently present. On success, drops the ref entry from ``src``'s
        YAML (tidying a now-empty ``roles``/``skills`` list or ``context_files``
        bucket), re-parses ``src``'s refs to refresh its outbound edges
        incrementally, and records a ``changelog`` op="unlink" row.

        ``dry_run`` returns the planned change WITHOUT writing.

        Returns ``{ok: True, src_id, dst_id, ref, file, dry_run}`` or
        ``{ok: False, error}``.
        """
        items, adj = self._load_graph()
        src = items.get(src_id)
        if src is None:
            return {"ok": False, "error": "no such item: {}".format(src_id),
                    "dry_run": dry_run}
        if src["kind"] not in COMPOSITION_KINDS:
            return {
                "ok": False,
                "error": "src {} is not a bundle (kind {})".format(
                    src_id, src["kind"]),
                "dry_run": dry_run,
            }
        if not self._has_outbound_edge(src_id, dst_id, adj):
            return {
                "ok": False,
                "error": "{} does not reference {}".format(src_id, dst_id),
                "dry_run": dry_run,
            }

        rel_file = src["path"]
        abs_file = self.ai_root / rel_file
        # The ref string to drop.
        dst = items.get(dst_id)
        if dst is not None:
            ref = self._ref_for_dst(dst)
        else:
            # Dangling dst: its id may NOT round-trip to the on-disk ref path —
            # e.g. a ref into a `_`-skipped dir (`_drafts/`) whose segment the id
            # normalization drops, so a reconstructed ref would miss the real
            # YAML line. Find the ACTUAL declared ref whose resolved id == dst_id.
            ref = self._ref_for_dst_id(dst_id)  # fallback if not found on disk
            try:
                _data = yaml.safe_load(abs_file.read_text(encoding="utf-8")) if yaml else None
            except Exception:
                _data = None
            if isinstance(_data, dict):
                for _ref_str in _iter_ref_strings(_data):
                    _resolved = self._resolve_ref(_ref_str)
                    if _resolved and "{}:{}".format(*_resolved) == dst_id:
                        ref = _ref_str
                        break

        if dry_run:
            return {
                "ok": True, "src_id": src_id, "dst_id": dst_id, "ref": ref,
                "file": rel_file, "dry_run": True,
            }

        try:
            current = abs_file.read_text(encoding="utf-8")
        except OSError as e:
            return {"ok": False, "error": "cannot read {}: {}".format(rel_file, e),
                    "dry_run": False}

        new_text = _yaml_remove_ref(current, ref)
        _atomic_write(abs_file, new_text)
        warning = self._refresh_edges(src_id)
        self._record_change(
            item_id=src_id, op="unlink", field="references",
            old_value=dst_id, new_value=None, by=by,
        )
        result = {
            "ok": True, "src_id": src_id, "dst_id": dst_id, "ref": ref,
            "file": rel_file, "dry_run": False,
        }
        if warning:
            result["warning"] = warning
        return result

    # =========================================================================
    # Write API — MOVE / RENAME path (Phase 2, Task 3) with REFERENTIAL
    # INTEGRITY. ``move`` renames (``new_name``) and/or relocates
    # (``new_category``) an item, then repoints EVERY inbound reference so no
    # dangling ref is introduced and every previously-resolving inbound ref
    # still resolves — now to the new location.
    #
    # ORDERING (apply) — COPY-FIRST so a crash never leaves a dangling ref:
    # (1) read+stage every inbound bundle's repointed YAML in memory AND verify
    # the postcondition (old ref id gone, new ref id present) BEFORE any write —
    # a no-op/failed repoint aborts here with nothing written; (2) COPY the item
    # file to the new path (the OLD file stays in place for now); (3) write all
    # referrer YAML edits (now pointing at a file that already exists); (4) update
    # the index in one transaction — rename the item row id old→new and rewrite
    # every edge src/dst that referenced the old id; (5) remove the OLD file
    # LAST, then repoint any ``*_latest`` symlink (relative target) to the new
    # location; (6) record a changelog op="move" (plus one row per repointed
    # referrer). A referrer-write or index-update failure restores the written
    # referrers and drops the new copy (old file untouched). Because the old file
    # is removed only after the copy+referrers+index all succeed, a crash leaves
    # refs pointing at either the old file (still present) or the new file
    # (already present) — NEVER at a path with no file. A subsequent ``reindex``
    # (files are the source of truth) reconciles the index to disk.
    # =========================================================================

    # Base directory (relative to ai_general) per movable kind. Leaf kinds and
    # bundle kinds both live under a single base dir keyed by kind; profiles are
    # the special case (top-level ai_profiles/*.yml) handled inline.
    _MOVE_BASE = {
        "knowledge": "ai_context_files/knowledge",
        "instruction": "ai_context_files/instructions",
        "role": "ai_profiles/roles",
        "skill": "ai_profiles/skills",
        "global": "ai_profiles/globals",
    }
    # Fallback file extension per kind (leaves are .md; bundles are .yml), used
    # ONLY when the source extension can't be determined — a rename normally
    # PRESERVES the source file's own extension (see _move_target).
    _MOVE_EXT = {
        "knowledge": ".md", "instruction": ".md",
        "role": ".yml", "skill": ".yml", "global": ".yml", "profile": ".yml",
    }

    def _move_target(
        self, kind: str, old_name: str,
        new_category: Optional[str], new_name: Optional[str],
        old_path: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Compute ``(new_name, rel_to_root_path)`` for a move.

        ``new_name`` (when given) replaces the whole name; ``new_category``
        replaces only the leading category segment (a leaf's first path
        segment). Either or both may be supplied. Returns the resolved name and
        the new AI_ROOT-relative file path.

        The new file keeps the SOURCE file's extension (a rename must not change
        format — e.g. a ``.yml`` rule must not become ``.md``); the per-kind
        ``_MOVE_EXT`` is only a fallback when the source extension is unknown.
        """
        name = new_name if new_name is not None else old_name
        if new_category is not None:
            # Replace the leading category segment of the (resolved) name.
            tail = name.split("/", 1)[1] if "/" in name else name
            name = "{}/{}".format(new_category, tail)

        ext = None
        if old_path:
            src_ext = Path(old_path).suffix
            if src_ext.lower() in _CONTENT_EXTS:
                ext = src_ext
        if ext is None:
            ext = self._MOVE_EXT.get(kind, ".md")
        if kind == "profile":
            rel_path = "ai_general/ai_profiles/{}{}".format(name, ext)
        else:
            base = self._MOVE_BASE[kind]
            rel_path = "ai_general/{}/{}{}".format(base, name, ext)
        return name, rel_path

    def move(
        self, item_id: str, *,
        new_category: Optional[str] = None, new_name: Optional[str] = None,
        by: Optional[str] = None, dry_run: bool = False,
    ) -> dict:
        """Rename and/or relocate an item, repointing ALL inbound references.

        Computes the new path + id (``id = kind:new_name`` when the name
        changes; the file path changes with category/name for a leaf, and a name
        change moves the .yml for a bundle), rejects a target-path or new-id
        collision, finds every inbound edge (each item whose YAML references this
        one), and repoints those refs to the new location.

        ``dry_run=True`` returns a PLAN ``{ok, from:{id,path}, to:{id,path},
        inbound:[{src_id, ref_old, ref_new}], dry_run:true}`` and writes NOTHING.

        Apply (not dry_run): writes every inbound bundle's repointed YAML, moves
        the file (and any ``*_latest`` symlink pointing at it), updates the index
        (rename the item row id old→new + rewrite every edge src/dst that
        referenced the old id), and records a changelog op="move" (plus one row
        per repointed referrer). Integrity gate: after apply there are ZERO
        dangling refs and every previously-resolving inbound ref still resolves.

        Returns the plan/result dict, or ``{ok: False, error, dry_run}``.
        """
        if new_category is None and new_name is None:
            return {
                "ok": False,
                "error": "move requires new_name and/or new_category",
                "dry_run": dry_run,
            }
        if new_category is not None and not _is_safe_slug(new_category):
            return {
                "ok": False,
                "error": "new_category {!r} is not a safe slug".format(new_category),
                "dry_run": dry_run,
            }
        if new_name is not None and not _is_safe_move_name(new_name):
            return {
                "ok": False,
                "error": "new_name {!r} is not a safe name".format(new_name),
                "dry_run": dry_run,
            }

        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind, name, path FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "no such item: {}".format(item_id),
                    "dry_run": dry_run}

        kind = row["kind"]
        if kind not in self._MOVE_BASE and kind != "profile":
            return {
                "ok": False,
                "error": "move does not handle kind {!r}".format(kind),
                "dry_run": dry_run,
            }

        old_name = row["name"]
        old_path = row["path"]
        new_name_resolved, new_path = self._move_target(
            kind, old_name, new_category, new_name, old_path
        )
        new_id = "{}:{}".format(kind, new_name_resolved)

        # No-op: nothing actually changes.
        if new_id == item_id and new_path == old_path:
            return {
                "ok": False,
                "error": "move is a no-op (resolved id/path unchanged)",
                "dry_run": dry_run,
            }

        abs_old = self.ai_root / old_path
        abs_new = self.ai_root / new_path

        # Collision: target path exists, or the new id is already taken.
        if abs_new.exists() or abs_new.is_symlink():
            return {
                "ok": False,
                "error": "target path already exists: {}".format(new_path),
                "dry_run": dry_run,
            }
        if new_id != item_id:
            with self._connect() as conn:
                clash = conn.execute(
                    "SELECT 1 FROM items WHERE id = ?", (new_id,)
                ).fetchone()
            if clash is not None:
                return {
                    "ok": False,
                    "error": "an item with id {} already exists".format(new_id),
                    "dry_run": dry_run,
                }

        # Ref strings: derive from the old/new ai_general-relative ext-less path
        # (the same value reindex/_resolve_ref maps back to the id).
        ref_old = self._ref_for_path(old_path)
        ref_new = self._ref_for_path(new_path)

        # Inbound referrers: every edge whose dst is this item.
        with self._connect() as conn:
            inbound_rows = conn.execute(
                "SELECT DISTINCT src_id FROM edges WHERE dst_id = ? ORDER BY src_id",
                (item_id,),
            ).fetchall()
            src_paths = {}
            for r in inbound_rows:
                pr = conn.execute(
                    "SELECT path FROM items WHERE id = ?", (r["src_id"],)
                ).fetchone()
                if pr is not None:
                    src_paths[r["src_id"]] = pr["path"]

        inbound_plan = [
            {"src_id": sid, "ref_old": ref_old, "ref_new": ref_new}
            for sid in src_paths
        ]

        if dry_run:
            return {
                "ok": True,
                "from": {"id": item_id, "path": old_path},
                "to": {"id": new_id, "path": new_path},
                "inbound": inbound_plan,
                "dry_run": True,
            }

        # ---- APPLY -----------------------------------------------------------
        # CRASH-SAFE ORDERING: copy the target to the NEW path FIRST (old stays),
        # then repoint referrers (pointing at a file that already exists), update
        # the index, and remove the OLD file LAST. A crash at any point leaves
        # either refs->old(exists) or refs->new(exists) — never a ref to a path
        # with no file (the old "write referrers then rename" order could leave
        # danglers if it crashed between the two steps).

        # (1) Stage every referrer's repointed YAML in memory + VERIFY the
        #     postcondition (old ref id gone, new ref id present) BEFORE writing.
        #     A no-op/failed replacement is caught here and aborts the whole move.
        staged = []  # list of (abs_path, original_text, new_text)
        for sid, rel_file in src_paths.items():
            abs_file = self.ai_root / rel_file
            try:
                original = abs_file.read_text(encoding="utf-8")
            except OSError as e:
                return {
                    "ok": False,
                    "error": "cannot read referrer {}: {}".format(rel_file, e),
                    "dry_run": False,
                }
            new_text = _yaml_replace_ref(original, ref_old, ref_new)
            with self._connect() as conn:
                kr = conn.execute(
                    "SELECT kind FROM items WHERE id = ?", (sid,)
                ).fetchone()
            src_kind = kr["kind"] if kr is not None else None
            post_ids = self._ids_in_yaml_text(new_text, src_kind)
            if post_ids is None:
                return {
                    "ok": False,
                    "error": "could not parse staged referrer {} after repoint; "
                             "aborted move".format(rel_file),
                    "dry_run": False,
                }
            if item_id in post_ids or new_id not in post_ids:
                return {
                    "ok": False,
                    "error": "referrer {} did not repoint {} -> {} (no-op or wrong "
                             "match); aborted move".format(rel_file, item_id, new_id),
                    "dry_run": False,
                }
            staged.append((abs_file, original, new_text))

        # (2) Copy the file to the new path (old remains for now).
        try:
            abs_new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(abs_old), str(abs_new))
        except OSError as e:
            return {
                "ok": False,
                "error": "failed copying {} -> {}: {}".format(old_path, new_path, e),
                "dry_run": False,
            }

        def _rollback_new_copy():
            try:
                if abs_new.exists():
                    abs_new.unlink()
            except OSError:
                pass

        # (3) Write all referrer YAML edits; on failure restore + drop the copy.
        written = []  # (abs_path, original_text) already written
        try:
            for abs_file, original, new_text in staged:
                _atomic_write(abs_file, new_text)
                written.append((abs_file, original))
        except OSError as e:
            for abs_file, original in written:
                try:
                    _atomic_write(abs_file, original)
                except OSError:
                    pass
            _rollback_new_copy()
            return {
                "ok": False,
                "error": "failed writing referrer YAML, restored prior edits: {}".format(e),
                "dry_run": False,
            }

        # (4) Update the index in one transaction: rename the item row id and
        #     rewrite every edge src/dst that referenced the old id. On failure,
        #     restore referrers + drop the new copy (old file untouched).
        try:
            self._move_update_index(item_id, new_id, new_name_resolved, new_path)
        except sqlite3.Error as e:
            for abs_file, original in written:
                try:
                    _atomic_write(abs_file, original)
                except OSError:
                    pass
            _rollback_new_copy()
            return {
                "ok": False,
                "error": "failed updating index, restored disk state: {}".format(e),
                "dry_run": False,
            }

        # (5) Remove the OLD file LAST, then repoint any *_latest symlink to new.
        old_removed = True
        try:
            abs_old.unlink()
        except OSError:
            old_removed = False
        self._repoint_latest_symlink(abs_old, abs_new)

        return self._move_finish(
            item_id, new_id, old_path, new_path, ref_old, ref_new,
            src_paths, by, old_removed,
        )

    def _move_update_index(self, item_id, new_id, new_name_resolved, new_path):
        """Rename the item row id + rewrite edges/FTS in one transaction."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE items SET id = ?, name = ?, path = ? WHERE id = ?",
                (new_id, new_name_resolved, new_path, item_id),
            )
            if new_id != item_id:
                conn.execute(
                    "UPDATE edges SET src_id = ? WHERE src_id = ?", (new_id, item_id)
                )
                conn.execute(
                    "UPDATE edges SET dst_id = ? WHERE dst_id = ?", (new_id, item_id)
                )
                conn.execute(
                    "UPDATE items_fts SET id = ? WHERE id = ?", (new_id, item_id)
                )

    def _move_finish(
        self, item_id, new_id, old_path, new_path, ref_old, ref_new,
        src_paths, by, old_removed,
    ) -> dict:
        """Audit a completed move and build its result dict.

        Records one op="move" row (keyed by the new id) plus one per repointed
        referrer. ``old_removed=False`` (the old file could not be unlinked after
        a successful copy+index update) surfaces a recovery ``warning`` — the
        move is committed but a stale duplicate file remains; a reindex will
        re-surface it, so the caller is told to remove it manually.
        """
        self._record_change(
            item_id=new_id, op="move", field="path",
            old_value=old_path, new_value=new_path, by=by,
        )
        for sid in src_paths:
            self._record_change(
                item_id=sid, op="move", field="references",
                old_value=ref_old, new_value=ref_new, by=by,
            )

        result = {
            "ok": True,
            "from": {"id": item_id, "path": old_path},
            "to": {"id": new_id, "path": new_path},
            "inbound": [
                {"src_id": sid, "ref_old": ref_old, "ref_new": ref_new}
                for sid in src_paths
            ],
            "dry_run": False,
        }
        if not old_removed:
            result["warning"] = (
                "moved, but the old file {} could not be removed; remove it "
                "manually and reindex".format(old_path)
            )
        return result

    def _ref_for_path(self, rel_to_root: str) -> str:
        """ai_general-relative, extension-less ref for an AI_ROOT-relative path.

        Mirrors :meth:`_ref_for_dst` but works from a raw path string (so it can
        be computed for the *new* path before any item row exists for it).
        """
        path = rel_to_root or ""
        if path.startswith("ai_general/"):
            path = path[len("ai_general/"):]
        return _strip_ext(path)

    @staticmethod
    def _repoint_latest_symlink(abs_old: Path, abs_new: Path) -> None:
        """Repoint a sibling ``*_latest`` symlink that targeted the moved file.

        Looks for ``<stem>_latest<ext>`` next to the old file; if it is a
        symlink resolving to the moved file, recreate it pointing at the new
        filename (preserving relative-link style). Best-effort — failures here
        do not abort the move (the file itself has already moved).
        """
        old_dir = abs_old.parent
        latest = old_dir / "{}_latest{}".format(abs_old.stem, abs_old.suffix)
        if not latest.is_symlink():
            return
        try:
            target = os.readlink(str(latest))
        except OSError:
            return
        # Resolve relative to the symlink's directory for the comparison.
        resolved = (old_dir / target) if not os.path.isabs(target) else Path(target)
        try:
            same = resolved.resolve() == abs_old.resolve() or os.path.basename(target) == abs_old.name
        except OSError:
            same = os.path.basename(target) == abs_old.name
        if not same:
            return
        # Policy: the symlink STAYS in its original directory and is repointed to
        # the new file location. For a relative symlink that must be a path
        # RELATIVE TO the symlink's own directory — using just ``abs_new.name``
        # is wrong for a cross-directory move (it would resolve back in old_dir).
        if os.path.isabs(target):
            new_target = str(abs_new)
        else:
            new_target = os.path.relpath(str(abs_new), str(latest.parent))
        try:
            latest.unlink()
            latest.symlink_to(new_target)
        except OSError:
            pass

    # =========================================================================
    # Write API — DELETE / ARCHIVE path (Phase 2, Task 4). ``delete`` is a
    # SOFT-DELETE: it never hard-deletes a file by default. The item's file is
    # moved into the kind base's ``_archive/`` subtree — the SAME convention
    # ``reindex`` already classifies as ``status='archived'`` (see
    # ``_add_item``: ``"_archive" in path.parts`` -> archived). So the archive
    # is FILE-BACKED and survives a reindex-from-scratch: the item stays
    # archived and drops out of the default (active) listings, never silently
    # resurrected as active.
    #
    # INBOUND-REF GUARD: if any item references this one and NOT ``force``,
    # delete is REJECTED (don't create danglers silently). With ``force=True``
    # we proceed and the now-dangling refs are surfaced by ``validate`` (we do
    # NOT repoint/strip the referrers — that is ``move``'s/``unlink``'s job).
    #
    # ID CHANGE: moving under ``_archive/`` changes the derived name (and thus
    # the id) to ``<kind>:_archive/<old_name>`` — exactly what reindex derives
    # for the new path. After the file move we run a full ``reindex()`` (like
    # create/update_content) so the index matches disk: the archived row appears
    # under the new id and the old active row is pruned. This is what makes the
    # round-trip gate pass.
    # =========================================================================

    # Marker segment prepended to a name to archive it; reindex treats any path
    # containing this part as archived (``"_archive" in path.parts``).
    _ARCHIVE_SEG = "_archive"

    def delete(
        self, item_id: str, *,
        force: bool = False, by: Optional[str] = None, dry_run: bool = False,
    ) -> dict:
        """Soft-delete (archive) an item: move its file into ``_archive/``.

        Finds the item, computes its archived path/id (the file relocated under
        the kind base's ``_archive/`` subtree, which reindex classifies as
        ``status='archived'``), checks the inbound-ref guard, and — unless
        ``dry_run`` — moves the file, reindexes from disk (so the archived row
        matches the file + the old active row is pruned), and records a
        changelog op="delete" row.

        Inbound-ref guard: if any item references ``item_id`` and not ``force``,
        REJECT with ``{ok:False, error:'referenced', referrers:[src_id,...]}``
        (don't create danglers silently). With ``force=True`` the archive
        proceeds and the result carries ``referrers`` (now-dangling refs that
        ``validate`` will report). Both carry a repair-ready ``repair`` list
        ``[{src_id, old_ref, old_dst_id}, ...]`` — enough to repoint/strip each
        dangling ref (the bare id list alone is not).

        ``dry_run=True`` returns the PLAN ``{ok, from:{id,path}, to:{id,path},
        referrers:[...], dry_run:true}`` and writes NOTHING.

        Returns the result/plan dict, or ``{ok: False, error, dry_run}``.

        DESTRUCTIVE-OP FRESHNESS: the inbound-ref guard reads the ``edges``
        table, which can go stale after raw YAML edits / parse failures. Before
        a destructive decision we reindex from disk (files are the source of
        truth) so the guard — and the dry-run plan — reflect on-disk reality and
        we never archive a still-referenced item without ``force``. Refreshing
        the rebuildable index is not a user-visible mutation, so it is safe even
        on the ``dry_run`` path.
        """
        # Refresh the index from disk so the inbound-ref guard is not fooled by a
        # stale edge table (a referrer added/removed on disk since last reindex).
        self.reindex()

        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, kind, name, path, status FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            return {"ok": False, "error": "no such item: {}".format(item_id),
                    "dry_run": dry_run}

        if row["status"] == "archived" or self._ARCHIVE_SEG in Path(row["path"]).parts:
            return {"ok": False, "error": "already archived: {}".format(item_id),
                    "dry_run": dry_run}

        old_name = row["name"]
        old_path = row["path"]
        new_name = "{}/{}".format(self._ARCHIVE_SEG, old_name)
        new_id = "{}:{}".format(row["kind"], new_name)
        new_path = self._archive_path(old_path)

        # Inbound referrers: every item whose YAML references this one.
        with self._connect() as conn:
            referrers = [
                r["src_id"] for r in conn.execute(
                    "SELECT DISTINCT src_id FROM edges WHERE dst_id = ? ORDER BY src_id",
                    (item_id,),
                ).fetchall()
            ]
        # Repair-ready detail: each referrer plus the ref it used and the id it
        # pointed at, so a repair tool can repoint/strip the now-dangling refs a
        # --force archive leaves (the bare ``referrers`` id list alone is not
        # enough to reconstruct the edit). ``old_ref`` is the deleted item's
        # pre-archive ref string (same for all referrers).
        old_ref = self._ref_for_path(old_path)
        repair = [
            {"src_id": sid, "old_ref": old_ref, "old_dst_id": item_id}
            for sid in referrers
        ]

        # Guard: reject (don't dangle silently) unless forced.
        if referrers and not force and not dry_run:
            return {"ok": False, "error": "referenced",
                    "referrers": referrers, "repair": repair, "dry_run": False}

        if dry_run:
            return {
                "ok": True,
                "from": {"id": item_id, "path": old_path},
                "to": {"id": new_id, "path": new_path},
                "referrers": referrers,
                "repair": repair,
                "dry_run": True,
            }

        # Collision guard on the archive target.
        abs_old = self.ai_root / old_path
        abs_new = self.ai_root / new_path
        if abs_new.exists() or abs_new.is_symlink():
            return {"ok": False,
                    "error": "archive target already exists: {}".format(new_path),
                    "dry_run": False}

        try:
            abs_new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(str(abs_old), str(abs_new))
        except OSError as e:
            return {"ok": False,
                    "error": "failed archiving {} -> {}: {}".format(
                        old_path, new_path, e),
                    "dry_run": False}

        # Index from disk (files are the source of truth): the archived row
        # appears under the new id with status='archived' and the old active
        # row is pruned. ``force`` leaves the referrers' refs untouched, so
        # ``validate`` now reports them as dangling.
        self.reindex()
        self._record_change(
            item_id=new_id, op="delete", field="status",
            old_value=old_path, new_value=new_path, by=by,
        )

        result = {
            "ok": True,
            "from": {"id": item_id, "path": old_path},
            "to": {"id": new_id, "path": new_path},
            "id": new_id,
            "dry_run": False,
        }
        if referrers:
            # Surface the now-dangling refs created by --force, with repair detail.
            result["referrers"] = referrers
            result["repair"] = repair
        return result

    def _archive_path(self, rel_to_root: str) -> str:
        """Insert ``_archive/`` after the kind base dir of an AI_ROOT-rel path.

        ``ai_general/ai_context_files/knowledge/reference/x.md`` ->
        ``ai_general/ai_context_files/knowledge/_archive/reference/x.md`` so the
        moved file is the kind's name with an ``_archive/`` prefix — exactly the
        path reindex derives the archived id + status from.
        """
        base = self._archive_base_for_path(rel_to_root)
        if base is None:
            # Fall back: prepend _archive/ before the filename.
            p = Path(rel_to_root)
            return (p.parent / self._ARCHIVE_SEG / p.name).as_posix()
        tail = rel_to_root[len(base) + 1:]  # strip "base/"
        return "{}/{}/{}".format(base, self._ARCHIVE_SEG, tail)

    def _unarchive_path(self, rel_to_root: str) -> str:
        """Inverse of :meth:`_archive_path`: drop the ``_archive/`` segment."""
        parts = [p for p in Path(rel_to_root).parts if p != self._ARCHIVE_SEG]
        return Path(*parts).as_posix() if parts else rel_to_root

    def _strip_archive_seg(self, name: str) -> str:
        """Drop the ``_archive/`` segment from an item name."""
        parts = [p for p in name.split("/") if p != self._ARCHIVE_SEG]
        return "/".join(parts)

    def _archive_base_for_path(self, rel_to_root: str) -> Optional[str]:
        """The kind base dir prefix (ai_general-rooted) of an AI_ROOT-rel path.

        Returns e.g. ``ai_general/ai_context_files/knowledge`` so ``_archive/``
        can be inserted right after it, mirroring the kind-base convention.
        """
        path = rel_to_root or ""
        if path.startswith("ai_general/"):
            tail = path[len("ai_general/"):]
        else:
            return None
        for _kind, prefix in _REF_PREFIXES:
            pfx = prefix + "/"
            if tail.startswith(pfx):
                return "ai_general/" + prefix
        if tail.startswith("data/session_briefs/"):
            return "ai_general/data/session_briefs"
        return None

    # -- link/unlink helpers -------------------------------------------------

    def _validate_link(self, src_id, dst_id, items, adj) -> Optional[str]:
        """Return an error string if a link src->dst is invalid, else None."""
        src = items.get(src_id)
        if src is None:
            return "no such item: {}".format(src_id)
        if src["kind"] not in COMPOSITION_KINDS:
            return "src {} is not a bundle (kind {})".format(src_id, src["kind"])
        if dst_id not in items:
            return "no such item: {}".format(dst_id)
        # brief/memory are NOT validly linkable as bundle refs: their files live
        # outside the ref-prefix tree (data/session_briefs, ai_memories/...), so
        # reindex's _resolve_ref cannot map such a ref back to an edge — the link
        # would not round-trip. Reject cleanly rather than write a dead ref.
        dst_kind = items[dst_id].get("kind")
        if dst_kind in ("brief", "memory"):
            return (
                "dst {} (kind {}) is not linkable: brief/memory items are not "
                "valid bundle references (they would not round-trip through "
                "reindex)".format(dst_id, dst_kind)
            )
        if src_id == dst_id:
            return "cannot link an item to itself: {}".format(src_id)
        # Cycle check: dst must not already reach src through existing edges.
        if self._reaches(dst_id, src_id, adj):
            return (
                "linking {} -> {} would create a cycle "
                "({} already reaches {})".format(src_id, dst_id, dst_id, src_id)
            )
        return None

    @staticmethod
    def _has_outbound_edge(src_id, dst_id, adj) -> bool:
        return any(d == dst_id for (d, _t, _o) in adj.get(src_id, []))

    @staticmethod
    def _reaches(start: str, target: str, adj) -> bool:
        """True if ``target`` is reachable from ``start`` over outbound edges."""
        stack = [start]
        seen = set()
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            for dst_id, _etype, _oidx in adj.get(node, []):
                stack.append(dst_id)
        return False

    def _ref_for_dst(self, dst: dict) -> str:
        """The ref string to write for a dst item: its ai_general-relative,
        extension-less path — exactly what ``_resolve_ref`` maps back to the id.
        """
        path = dst.get("path") or ""
        if path.startswith("ai_general/"):
            path = path[len("ai_general/"):]
        return _strip_ext(path)

    def _ref_for_dst_id(self, dst_id: str) -> str:
        """Best-effort ref for a dangling dst id (``kind:name``) -> path form."""
        kind, _sep, name = dst_id.partition(":")
        for k, prefix in _REF_PREFIXES:
            if k == kind:
                return "{}/{}".format(prefix, name)
        return name

    def _refresh_edges(self, src_id: str) -> Optional[str]:
        """Re-parse ``src``'s file refs and replace ONLY its outbound edges.

        Incremental: deletes the rows where ``src_id`` is the source and inserts
        the freshly-parsed set (no global reindex). The file is the source of
        truth, so the edges always match what was just written.

        DATA-LOSS GUARD: if the file fails to PARSE (malformed YAML / unreadable)
        we PRESERVE the item's existing edges (skip the delete+rebuild) and
        return a warning string instead of silently erasing them. Returns None
        on a clean refresh.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT kind, path FROM items WHERE id = ?", (src_id,)
            ).fetchone()
            if row is None:
                return None
            refs, ok = self._parse_refs_checked(
                self.ai_root / row["path"], row["kind"]
            )
            if not ok:
                # Parse failure: do NOT touch existing edges. Surface a warning.
                return (
                    "could not parse {} ({}); preserved existing edges".format(
                        row["path"], src_id
                    )
                )
            conn.execute("DELETE FROM edges WHERE src_id = ?", (src_id,))
            seen = set()
            order_idx = 0
            for dst_id, etype in refs:
                key = (src_id, dst_id, etype)
                if key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    "INSERT OR IGNORE INTO edges (src_id, dst_id, edge_type, order_idx) "
                    "VALUES (?, ?, ?, ?)",
                    (src_id, dst_id, etype, order_idx),
                )
                order_idx += 1

    def _ids_in_yaml_text(self, text: str, kind: str) -> Optional[set]:
        """Resolve the reference ids in a composition's YAML TEXT (not a file).

        Used for move's staged-YAML postcondition: after computing a referrer's
        repointed text we verify, BEFORE writing anything, that the old ref id is
        gone and the new one present. Returns the set of resolved dst ids, or
        ``None`` if the text could not be parsed (a postcondition failure — we do
        not write a referrer we cannot verify).
        """
        if yaml is None:
            return None
        try:
            data = yaml.safe_load(text)
        except Exception:
            return None
        if not isinstance(data, dict):
            return set()
        ids = set()
        for ref in _iter_ref_strings(data):
            resolved = self._resolve_ref(ref)
            if resolved is not None:
                ids.add("{}:{}".format(*resolved))
        return ids

    def _load_graph(self) -> Tuple[Dict[str, dict], Dict[str, list]]:
        """Load (items_by_id, outbound_adjacency) for graph traversal.

        adjacency[src_id] = ordered list of (dst_id, edge_type, order_idx).
        """
        with self._connect() as conn:
            items = {
                r["id"]: dict(r)
                for r in conn.execute("SELECT * FROM items").fetchall()
            }
            adj: Dict[str, list] = {}
            for r in conn.execute(
                "SELECT src_id, dst_id, edge_type, order_idx FROM edges "
                "ORDER BY src_id, order_idx"
            ).fetchall():
                adj.setdefault(r["src_id"], []).append(
                    (r["dst_id"], r["edge_type"], r["order_idx"])
                )
        return items, adj


# =============================================================================
# Module-level parsing helpers
# =============================================================================

def _atomic_write(path, text: str, *, exclusive: bool = False) -> None:
    """Write ``text`` to ``path`` atomically and durably.

    Writes to a temp file in the TARGET's directory (so the final step is an
    atomic same-filesystem rename), flushes + ``fsync``s the data before the
    rename, and best-effort ``fsync``s the directory entry. A crash therefore
    leaves either the old file or the complete new one — never a torn partial.

    Symlink-follow is preserved: when ``path`` is a symlink (e.g. a ``*_latest``
    alias) the real target is replaced, so the symlink is not clobbered into a
    regular file. (The engine's indexed write paths already resolve to real
    files, but this keeps the helper safe for any caller.)

    ``exclusive=True`` requires the target NOT already exist (atomic create):
    the new file is linked into place with ``os.link``, which raises
    ``FileExistsError`` if the path exists, so an existing file is never
    clobbered.
    """
    path = Path(path)
    target = path
    if not exclusive and path.is_symlink():
        target = Path(os.path.realpath(str(path)))
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)

    data = text.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        dir=str(directory), prefix=".cmtmp_", suffix=target.suffix or ".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if exclusive:
            # Atomic create: os.link fails with FileExistsError if path exists.
            os.link(str(tmp), str(target))
            tmp.unlink()
        else:
            os.replace(str(tmp), str(target))
    except BaseException:
        # Never leave a temp turd behind on any failure path.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise

    # Best-effort durability of the rename/create in the directory entry.
    try:
        dfd = os.open(str(directory), os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except (OSError, AttributeError):
        pass


def _sha256_file(abs_path) -> Optional[str]:
    """Return a file's SHA-256 hex digest, or None if it can't be read.

    Matches the digest ``reindex`` records (sha256 of the raw bytes), so a
    hash captured here is directly comparable to a re-read after an edit.
    """
    try:
        return hashlib.sha256(Path(abs_path).read_bytes()).hexdigest()
    except OSError:
        return None


def _parse_json(value):
    """Parse a JSON string into an object; pass through None / non-strings."""
    if not value or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _fts_query(q: str) -> str:
    """Build a safe fts5 MATCH expression from free text.

    Each whitespace-separated term is double-quoted (so punctuation and the
    fts5 operators don't break the parse) and combined with implicit AND.
    """
    terms = [t for t in q.replace('"', " ").split() if t]
    if not terms:
        return '""'
    return " ".join('"{}"'.format(t) for t in terms)

def _yaml_title_line(title: str) -> str:
    """Serialize ``title`` as a YAML-safe ``title: <value>`` frontmatter line.

    Uses ``yaml.safe_dump`` so a plain title stays unquoted (human-readable)
    while a title containing YAML-special characters (``:`` ``#`` quotes, a
    leading ``-``, braces, ...) is correctly quoted/escaped — guaranteeing the
    written frontmatter parses back to the exact title. Falls back to a manual
    double-quote escape if yaml is unavailable.
    """
    if yaml is not None:
        # default_flow_style=False keeps block style; strip the trailing newline
        # safe_dump appends so we return a single clean line.
        return yaml.safe_dump(
            {"title": title}, default_flow_style=False, allow_unicode=True
        ).rstrip("\n")
    escaped = str(title).replace("\\", "\\\\").replace('"', '\\"')
    return 'title: "{}"'.format(escaped)


def _strip_ext(name: str) -> str:
    for ext in (".md", ".yml", ".yaml"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


# Authoring slug charset: lowercase letters, digits, underscore, hyphen.
_SLUG_SAFE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


def _slugify(title: str) -> str:
    """Derive a filesystem-safe slug from a title.

    Lowercases, maps any run of unsafe characters (spaces, punctuation) to a
    single underscore, and trims leading/trailing separators. Hyphens and
    underscores already present are preserved.
    """
    out = []
    prev_sep = False
    for ch in (title or "").strip().lower():
        if ch in _SLUG_SAFE_CHARS and ch not in "_-":
            out.append(ch)
            prev_sep = False
        elif ch in "_-":
            out.append(ch)
            prev_sep = False
        else:
            if not prev_sep:
                out.append("_")
                prev_sep = True
    return "".join(out).strip("_-")


def _is_safe_slug(value: str) -> bool:
    """True if ``value`` is a safe single-segment slug (no traversal/abs path).

    Rejects empties, absolute paths, ``.``/``..`` traversal segments, and any
    character outside the slug charset. A ``category`` may itself be a slug; we
    forbid embedded ``/`` so it stays a single directory segment.
    """
    if not value or not isinstance(value, str):
        return False
    if value in (".", ".."):
        return False
    if "/" in value or "\\" in value or value.startswith("."):
        return False
    if ".." in value:
        return False
    return all(ch in _SLUG_SAFE_CHARS for ch in value)


def _is_safe_move_name(value: str) -> bool:
    """True if ``value`` is a safe move name (each ``/``-segment a slug).

    A leaf name may carry a category prefix (``reference/lexicon``), so unlike a
    single-segment slug we allow embedded ``/`` but require every segment to be
    a safe slug (no traversal / absolute paths / empty segments).
    """
    if not value or not isinstance(value, str):
        return False
    if value.startswith("/") or "\\" in value:
        return False
    segments = value.split("/")
    return all(_is_safe_slug(seg) for seg in segments)


def _yaml_replace_ref(text: str, ref_old: str, ref_new: str) -> str:
    """Replace a list-item ref ``ref_old`` with ``ref_new`` in place.

    Targeted, formatting-preserving edit (mirrors the link/unlink machinery):
    finds the list-item line whose resolved value matches ``ref_old`` (by FULL
    normalized ref path, so a same-basename ref in a different category is NOT
    a false match; a hyphen/underscore-variant or ``path:`` entry still matches)
    and substitutes the value, leaving indentation, ``- ``/``path:`` style and
    the rest of the file byte-for-byte unchanged. No match -> the text is
    returned unchanged (defensive; the caller derived the ref from the edge).
    """
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        val = _line_ref_value(stripped)
        if val is None or not _refs_match(val, ref_old):
            continue
        # Substitute only the value token, preserving the line's prefix shape.
        indent = ln[: len(ln) - len(ln.lstrip())]
        if stripped[1:].strip().startswith("path:"):
            lines[i] = "{}- path: {}".format(indent, ref_new)
        else:
            lines[i] = "{}- {}".format(indent, ref_new)
        break
    return "\n".join(lines)


def _frontmatter_block(text: str) -> Optional[str]:
    """Return the leading ``---`` … ``---`` frontmatter block (no trailing body).

    Returns the block as text *including* both ``---`` fences, or None when the
    text has no leading frontmatter. Used by ``update_content`` to preserve
    frontmatter while replacing the body beneath it.
    """
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[: i + 1])
    return None


def _slot_key(name: str) -> str:
    """Normalize a slot identifier so '03', '3', 3 all collide."""
    s = str(name).strip()
    return str(int(s)) if s.isdigit() else s


def _iter_list_entries(entries):
    """Yield ref strings from a YAML list of ``str`` or ``{path: ...}`` items."""
    if not isinstance(entries, list):
        return
    for entry in entries:
        if isinstance(entry, str):
            yield entry
        elif isinstance(entry, dict) and "path" in entry:
            yield entry["path"]


def _iter_ref_strings(data: dict):
    """Yield reference strings from a composition dict in document order.

    Handles `roles` / `skills` (lists) and `context_files` in BOTH shapes it
    appears in the wild:
      - a dict of category → list  (``context_files: {procedures: [...]}``)
      - a FLAT list                (``context_files: [ref, ref, ...]``) — used
        by roles like ``condenser`` that don't bucket by category.
    Entries may be bare strings or ``{path: ..., purpose: ...}`` maps.
    """
    for key, value in data.items():
        if key in ("roles", "skills"):
            yield from _iter_list_entries(value)
        elif key == "context_files":
            if isinstance(value, dict):
                for _category, entries in value.items():
                    yield from _iter_list_entries(entries)
            elif isinstance(value, list):
                yield from _iter_list_entries(value)


def _ref_category(name: str) -> str:
    """Category bucket for a leaf dst name (first path segment; else 'misc').

    A leaf item ``name`` looks like ``reference/glossary`` or
    ``how_tos/instr_x``; the leading segment is its category, used as the
    ``context_files`` bucket key when a link is added. Reindex reads ALL buckets
    regardless of key, so this only affects where the ref is filed, not whether
    it round-trips.
    """
    name = (name or "").strip().strip("/")
    if "/" in name:
        return name.split("/", 1)[0]
    return "misc"


# ---------------------------------------------------------------------------
# Targeted YAML editors for link/unlink. ruamel.yaml (round-trip,
# comment-preserving) is unavailable in this environment, so rather than
# round-trip the whole file through PyYAML (which would drop comments and
# reflow), we edit the relevant block textually — appending/removing a single
# list entry and tidying a now-empty list/bucket — leaving the rest of the file
# byte-for-byte unchanged. The dump fallback (``_yaml_dump_edit``) is used only
# when the structural anchor is absent and we must materialize a new top-level
# key. Indentation is inferred from sibling lines so the result re-parses.
# ---------------------------------------------------------------------------

def _detect_indent(lines, header_idx: int) -> Tuple[int, int]:
    """Infer (key_indent, item_indent) for the block under ``lines[header_idx]``.

    ``key_indent`` is the indentation of the header key line; ``item_indent`` is
    the indentation of its child list items (first ``-`` found), defaulting to
    key_indent (PyYAML accepts list items at the parent key's indent).
    """
    key_indent = len(lines[header_idx]) - len(lines[header_idx].lstrip())
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind <= key_indent:
            break
        if ln.lstrip().startswith("-"):
            return key_indent, ind
    return key_indent, key_indent


def _block_bounds(lines, header_idx: int) -> int:
    """Index one past the last line belonging to the block at ``header_idx``.

    Handles the compact block-sequence style where a key's ``- `` list items sit
    at the SAME indent as the key (``perspective:`` then ``- path: …`` both at
    indent 2): those same-indent dash lines (and their deeper continuations)
    belong to the block. A same-indent NON-dash line is a sibling key and ends
    the block; a shallower line is a dedent.
    """
    key_indent = len(lines[header_idx]) - len(lines[header_idx].lstrip())
    end = header_idx + 1
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            end = j + 1
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind < key_indent:
            break
        if ind == key_indent and not ln.lstrip().startswith("-"):
            break  # sibling mapping key at the same indent
        end = j + 1
    return end


def _find_top_key(lines, key: str) -> Optional[int]:
    """Index of a top-level (column-0) ``key:`` line, or None."""
    for i, ln in enumerate(lines):
        if ln.startswith(key + ":") and (ln.rstrip() == key + ":" or
                                         ln[len(key) + 1:].strip() == ""):
            return i
    return None


def _yaml_add_to_list(text: str, list_key: str, ref: str) -> str:
    """Add ``- ref`` to the top-level ``list_key`` list, creating it if absent."""
    nl = "\n" if not text or text.endswith("\n") else ""
    lines = text.split("\n")
    # Drop a trailing empty element from a final newline so indices are clean.
    trailing_blank = lines and lines[-1] == ""
    if trailing_blank:
        lines = lines[:-1]

    hdr = _find_top_key(lines, list_key)
    if hdr is None:
        # Append a fresh top-level block.
        block = ["", "{}:".format(list_key), "  - {}".format(ref)]
        lines = lines + block
        return "\n".join(lines) + ("\n" if trailing_blank or nl == "" else nl)

    _key_indent, item_indent = _detect_indent(lines, hdr)
    end = _block_bounds(lines, hdr)
    # Insert before any trailing blank lines inside the block.
    insert_at = end
    while insert_at - 1 > hdr and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    new_line = "{}- {}".format(" " * item_indent, ref)
    lines.insert(insert_at, new_line)
    return "\n".join(lines) + ("\n" if trailing_blank or nl == "" else nl)


def _ref_parent_dir(ref: str) -> str:
    """Directory portion of a ref path (extension-less), for bucket matching."""
    ref = _strip_ext((ref or "").strip().strip("'\""))
    return ref.rsplit("/", 1)[0] if "/" in ref else ""


def _cf_category_headers(lines, cf: int, cf_end: int, cf_indent: int):
    """Yield ``(header_idx, key)`` for each category sub-key under context_files.

    A category header is the first indent level under ``context_files`` whose
    line is a bare ``key:`` (a mapping key, not a ``- `` list item).
    """
    child_indent = None
    for j in range(cf + 1, cf_end):
        ln = lines[j]
        if not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind <= cf_indent:
            break
        if child_indent is None:
            child_indent = ind
        if ind == child_indent and not ln.lstrip().startswith("-"):
            key = ln.strip()
            if key.endswith(":"):
                yield j, key[:-1].strip()


def _bucket_uses_path_form(lines, cat_hdr: int) -> bool:
    """True if the category bucket's list entries use the ``- path:`` map form."""
    cat_end = _block_bounds(lines, cat_hdr)
    for j in range(cat_hdr + 1, cat_end):
        s = lines[j].strip()
        if s.startswith("- path:") or s.startswith("-path:"):
            return True
        if s.startswith("-"):
            return False
    return False


def _bucket_entry_dirs(lines, cat_hdr: int):
    """Parent dirs of every ref in a category bucket (for same-dir matching)."""
    cat_end = _block_bounds(lines, cat_hdr)
    dirs = set()
    for j in range(cat_hdr + 1, cat_end):
        val = _line_ref_value(lines[j].strip())
        if val:
            dirs.add(_ref_parent_dir(val))
    return dirs


def _yaml_add_to_context_files(text: str, category: str, ref: str) -> str:
    """Add ``ref`` under ``context_files:``, in the RIGHT bucket + RIGHT shape.

    Bucket choice (so we don't spawn near-duplicate buckets like ``perspective``
    vs ``perspectives``): prefer an existing bucket that already holds a ref from
    the SAME directory as ``ref``; else a bucket whose key == ``category``; else
    create a new ``category:`` bucket. Entry shape matches the chosen bucket's
    siblings — ``- path: ref`` when they use the map form (``{path, purpose}``),
    else a bare ``- ref`` — so a file's existing convention is preserved.
    """
    nl_trailing = text.endswith("\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    cf = _find_top_key(lines, "context_files")
    if cf is None:
        block = ["", "context_files:",
                 "  {}:".format(category),
                 "    - {}".format(ref)]
        return "\n".join(lines + block) + ("\n" if nl_trailing else "")

    cf_indent = len(lines[cf]) - len(lines[cf].lstrip())
    cf_end = _block_bounds(lines, cf)
    ref_dir = _ref_parent_dir(ref)

    # Choose the target bucket: same-directory match wins, then category name.
    headers = list(_cf_category_headers(lines, cf, cf_end, cf_indent))
    cat_hdr = None
    for hdr, key in headers:
        if ref_dir and ref_dir in _bucket_entry_dirs(lines, hdr):
            cat_hdr = hdr
            break
    if cat_hdr is None:
        for hdr, key in headers:
            if key == category:
                cat_hdr = hdr
                break

    if cat_hdr is None:
        # Create the category sub-bucket at the first child indent of cf.
        child_indent = cf_indent + 2
        for j in range(cf + 1, cf_end):
            if lines[j].strip():
                child_indent = len(lines[j]) - len(lines[j].lstrip())
                break
        block = ["{}{}:".format(" " * child_indent, category),
                 "{}- {}".format(" " * (child_indent + 2), ref)]
        # Insert before trailing blanks within the context_files block.
        insert_at = cf_end
        while insert_at - 1 > cf and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        for off, bl in enumerate(block):
            lines.insert(insert_at + off, bl)
        return "\n".join(lines) + ("\n" if nl_trailing else "")

    # Bucket found: append the item, matching the bucket's existing entry shape.
    _ki, item_indent = _detect_indent(lines, cat_hdr)
    entry = "path: {}".format(ref) if _bucket_uses_path_form(lines, cat_hdr) else ref
    cat_end = _block_bounds(lines, cat_hdr)
    insert_at = cat_end
    while insert_at - 1 > cat_hdr and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines.insert(insert_at, "{}- {}".format(" " * item_indent, entry))
    return "\n".join(lines) + ("\n" if nl_trailing else "")


def _line_ref_value(stripped: str) -> Optional[str]:
    """Extract the ref from a list-item line (``- x`` or ``- path: x``)."""
    if not stripped.startswith("-"):
        return None
    rest = stripped[1:].strip()
    if rest.startswith("path:"):
        rest = rest[len("path:"):].strip()
    # Strip an inline comment and surrounding quotes.
    if " #" in rest:
        rest = rest.split(" #", 1)[0].strip()
    rest = rest.strip().strip("'\"")
    return rest or None


def _yaml_remove_ref(text: str, ref: str) -> str:
    """Remove the list entry matching ``ref`` and tidy a now-empty list/bucket.

    Matches by FULL normalized ref path so same-basename refs in different
    categories do NOT collide. A bare-name skill ref still matches: the on-disk
    entry may be ``peer-review`` while ``ref`` is
    ``ai_profiles/skills/peer_review``; :func:`_refs_match` falls back to a
    basename comparison only when the on-disk value has no path segment.
    """
    nl_trailing = text.endswith("\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    target = None
    for i, ln in enumerate(lines):
        val = _line_ref_value(ln.strip())
        if val is not None and _refs_match(val, ref):
            target = i
            break
    if target is None:
        # Nothing matched (defensive — caller validated linkage). Return as-is.
        return text

    # Remove the WHOLE list item, not just its first line. A map entry spans
    # several lines — ``- path: x`` followed by more-indented sibling keys
    # (``purpose:`` etc.). Deleting only the ``- path:`` line would orphan those
    # continuation lines and produce invalid YAML (a mapping key sitting where a
    # list item is expected). So consume every following line indented deeper
    # than the ``-`` marker, stopping at the next sibling item / dedent / blank.
    dash_indent = len(lines[target]) - len(lines[target].lstrip())
    end = target + 1
    while end < len(lines):
        ln = lines[end]
        if not ln.strip():
            break  # blank line: a block separator — leave it in place
        ind = len(ln) - len(ln.lstrip())
        if ind <= dash_indent:
            break  # next sibling ``-`` item or a dedented key
        end += 1
    del lines[target:end]
    _tidy_empty_blocks(lines)
    return "\n".join(lines) + ("\n" if nl_trailing else "")


def _norm_tail(ref: str) -> str:
    """Normalized comparison key for a ref: basename, hyphens->underscores.

    Retained for the bare-name case (a skill listed by basename only). For
    matching FULL refs use :func:`_refs_match`, which compares the whole
    extension-less path to avoid same-basename collisions across categories.
    """
    ref = _strip_ext((ref or "").strip().strip("'\""))
    tail = ref.rsplit("/", 1)[-1]
    return tail.replace("-", "_")


def _norm_ref(ref: str) -> str:
    """Full normalized comparison key for a ref: the WHOLE extension-less path,
    hyphens->underscores, quotes/whitespace stripped.

    Unlike :func:`_norm_tail` (basename only) this preserves the category path,
    so ``knowledge/a/glossary`` and ``knowledge/b/glossary`` are distinct.
    """
    ref = _strip_ext((ref or "").strip().strip("'\""))
    return ref.replace("-", "_")


def _refs_match(on_disk_val: str, target_ref: str) -> bool:
    """True if a list-item value ``on_disk_val`` refers to the same item as
    ``target_ref``.

    Compares the FULL normalized ref path (so same-basename refs in different
    categories do NOT collide). The one exception is a bare on-disk name (no
    ``/`` — e.g. a skill listed as ``peer-review`` rather than its full
    ``ai_profiles/skills/peer_review`` ref): there is no category to compare, so
    we fall back to a basename match for that case only.
    """
    if on_disk_val is None:
        return False
    od = _norm_ref(on_disk_val)
    tgt = _norm_ref(target_ref)
    if od == tgt:
        return True
    # Bare on-disk name (skill listed by basename) -> compare basenames only.
    if "/" not in od:
        return od == _norm_tail(target_ref)
    return False


def _tidy_empty_blocks(lines) -> None:
    """Remove now-empty mapping keys/list headers left after a deletion.

    A header line ``key:`` whose block has no remaining child content (only
    blank lines until a sibling/dedent) is removed. Applied repeatedly so an
    emptied ``context_files: <category>:`` collapses both levels.
    """
    changed = True
    while changed:
        changed = False
        for i, ln in enumerate(lines):
            stripped = ln.strip()
            if not stripped.endswith(":") or stripped.startswith("-"):
                continue
            indent = len(ln) - len(ln.lstrip())
            # Scan for the header's first non-blank following line to decide if
            # its block still has content. A child is either (a) any line indented
            # DEEPER than the header, or (b) a ``- `` list item at the SAME indent
            # — the compact block-sequence style where the sequence is the key's
            # value (``perspective:`` then ``- path: …`` both at indent 2). A
            # non-dash line at the same indent is a sibling key (not a child); a
            # shallower line is a dedent.
            has_child = False
            j = i + 1
            while j < len(lines):
                cl = lines[j]
                if not cl.strip():
                    j += 1
                    continue
                cind = len(cl) - len(cl.lstrip())
                if cind < indent:
                    break
                if cind == indent:
                    if cl.lstrip().startswith("-"):
                        has_child = True  # compact-style sequence value
                    break
                has_child = True  # deeper-indented child
                break
            if not has_child:
                del lines[i]
                # Drop an immediately-preceding blank-line separator we own.
                if i - 1 >= 0 and i - 1 < len(lines) and lines[i - 1].strip() == "":
                    del lines[i - 1]
                changed = True
                break


def _split_frontmatter(text: str):
    """Split a leading ``---`` YAML frontmatter block; return (dict|None, body)."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            if yaml is None:
                return None, body
            try:
                fm = yaml.safe_load(block)
            except Exception:
                return None, body
            return (fm if isinstance(fm, dict) else None), body
    return None, text


def _first_heading(text: str) -> Optional[str]:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return None


def _first_paragraph(text: str) -> Optional[str]:
    para = []
    started = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            if started:
                break
            continue
        if not s:
            if started:
                break
            continue
        started = True
        para.append(s)
    return " ".join(para) if para else None


# =============================================================================
# CLI — JSON query surface over the index. Read-only verbs only (Phase 1).
# =============================================================================

# Documented enum choices, surfaced via argparse ``choices=`` so they appear in
# ``--help`` and bad values are rejected before any work runs.
_KIND_CHOICES = [
    "brief", "memory", "knowledge", "instruction",
    "role", "profile", "skill", "global",
]
_STATUS_CHOICES = ["active", "archived", "all"]
_SCOPE_CHOICES = ["global"]
_LOADER_CHOICES = ["mcp", "command", "auto"]


# Top-level walkthrough printed by ``--help-examples``. Concise, copy-pasteable.
HELP_EXAMPLES = """\
context_mgr — common use cases
================================
The index is read-only; files on disk are the source of truth. Output is
human-readable by default; add --oneline for one line per item, or --json for
the stable machine shape a UI/tool consumes.

  # See all roles you can adopt
  context_mgr list --kind role

  # See exactly what a profile loads (flat, ordered, de-duplicated leaf files)
  context_mgr resolve profile:architect_developer

  # See a node's DIRECT children (the items it directly references)
  context_mgr list role:architect

  # See what references a knowledge file (who pulls it in)
  context_mgr refs knowledge:reference/glossary --in

  # See the full nested expansion of an item's reference graph
  context_mgr tree profile:architect_developer

  # Show an item's actual file text (the Content tab payload)
  context_mgr content knowledge:reference/glossary

  # Full-text search across titles, summaries and content
  context_mgr search "git guardian"

  # Integrity check: dangling refs (to missing items) and orphan items
  context_mgr validate

  # Dump the WHOLE reference graph (active items + all edges) for a UI/tool
  context_mgr graph --json

  # Rebuild the index from the source tree (the one safe write)
  context_mgr reindex

Tips:
  - Filter listings: --kind {brief,memory,knowledge,instruction,role,profile,
    skill,global}, --status {active,archived,all}, --scope global,
    --loader {mcp,command,auto} (how a bundle is delivered).
  - 'resolve' (alias 'preview') reports `resolved` = the leaf files an item
    loads, and `unresolved` = references whose target item is missing.
"""

_RESOLVE_DESC = (
    "Expand a composition item (role/profile/global) into the FLAT, ordered, "
    "de-duplicated list of leaf context-files it ultimately loads. `resolved` "
    "= the leaf files; `unresolved` = references whose target item does not "
    "exist (dangling). Alias: `preview`."
)


def _add_format_args(sp):
    """Add the mutually-exclusive output-format flags to a subparser.

    Default (neither flag) is human-readable. ``--json`` emits the stable
    machine shape (unchanged from prior releases); ``--oneline`` emits one
    compact line per item.
    """
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON (stable shape for tooling/UI).",
    )
    grp.add_argument(
        "--oneline", action="store_true",
        help="emit one compact line per item (id + title).",
    )


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        prog="context_mgr",
        description=(
            "Read-only query CLI over the Context Mgr index. Files on disk are "
            "the source of truth; this DB is a rebuildable index over them. "
            "Output is human-readable by default (use --oneline or --json)."
        ),
    )
    p.add_argument("--db", help="override the SQLite DB path (for tests/ops).")
    p.add_argument(
        "--help-examples", action="store_true",
        help="print a walkthrough of common use cases and exit.",
    )
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser(
        "list",
        help="list items, or (with an id) a node's direct children.",
        description=(
            "Without an id: list items, filterable by --kind/--status/--scope "
            "and pageable with --limit/--offset. With an id: list that node's "
            "DIRECT children — the items it directly references (its "
            "outbound-edge targets) — as item rows in reference order."
        ),
    )
    sp.add_argument(
        "id", nargs="?", default=None,
        help="optional item id (e.g. role:architect); lists its direct children.",
    )
    sp.add_argument(
        "--kind", choices=_KIND_CHOICES,
        help="filter to a single item kind.",
    )
    sp.add_argument(
        "--status", choices=_STATUS_CHOICES, default="active",
        help="filter by lifecycle status (default: active; 'all' disables the "
             "filter, returning active + archived).",
    )
    sp.add_argument(
        "--scope", choices=_SCOPE_CHOICES,
        help="filter to items applied to all sessions via the globals "
             "composition.",
    )
    sp.add_argument(
        "--loader", choices=_LOADER_CHOICES,
        help="filter bundles by derived loader: mcp (role/profile), command "
             "(skill), or auto (global).",
    )
    sp.add_argument("--limit", type=int, help="max rows to return (default: all).")
    sp.add_argument("--offset", type=int, default=0, help="rows to skip (default: 0).")
    _add_format_args(sp)

    sp = sub.add_parser(
        "get", help="full item row + edge counts.",
        description="Show the full record for one item, including its inbound/"
                    "outbound edge counts.",
    )
    sp.add_argument("id", help="item id, e.g. role:architect.")
    _add_format_args(sp)

    sp = sub.add_parser(
        "content", help="an item's actual on-disk file text.",
        description="Return an item's file text (the Content tab payload). "
                    "Unlike `get` (metadata only), this reads the file body "
                    "from disk via the item's recorded path.",
    )
    sp.add_argument("id", help="item id, e.g. knowledge:reference/glossary.")
    _add_format_args(sp)

    sp = sub.add_parser(
        "search", help="full-text search items.",
        description="Full-text search over item titles, summaries and content.",
    )
    sp.add_argument("query", help="free-text query.")
    sp.add_argument("--kind", choices=_KIND_CHOICES, help="restrict to one kind.")
    sp.add_argument("--limit", type=int, default=50, help="max hits (default: 50).")
    _add_format_args(sp)

    sp = sub.add_parser(
        "refs", help="raw reference-graph edges into/out of an item.",
        description="Raw reference-graph edges into/out of an item. --out: what "
                    "this item references; --in: what references it; --both: "
                    "the union. Each edge reports whether its target resolves.",
    )
    sp.add_argument("id", help="item id.")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--out", action="store_const", const="out", dest="direction",
                     help="edges where this item is the source (default).")
    grp.add_argument("--in", action="store_const", const="in", dest="direction",
                     help="edges where this item is the destination.")
    grp.add_argument("--both", action="store_const", const="both", dest="direction",
                     help="both directions.")
    sp.set_defaults(direction="out")
    _add_format_args(sp)

    sp = sub.add_parser(
        "tree", help="recursive nested expansion of an item's references.",
        description="Recursive nested expansion of an item's references "
                    "(outbound edges), rendered as an indented outline. Marks "
                    "unresolved targets, cycles and depth-capped nodes.",
    )
    sp.add_argument("id", help="item id to expand.")
    sp.add_argument("--max-depth", type=int, default=10,
                    help="maximum recursion depth (default: 10).")
    _add_format_args(sp)

    for verb in ("resolve", "preview"):
        sp = sub.add_parser(
            verb, help="flatten a composition into its leaf context-files.",
            description=_RESOLVE_DESC,
        )
        sp.add_argument("id", help="composition id, e.g. profile:architect_developer.")
        _add_format_args(sp)

    sp = sub.add_parser(
        "validate", help="report dangling edges + orphan items.",
        description="Report dangling edges (a reference to a missing item) and "
                    "orphan items (leaf files nothing references).",
    )
    _add_format_args(sp)

    sp = sub.add_parser(
        "graph",
        help="the whole reference graph (active items + all edges).",
        description="Return the entire reference graph in one shot: every "
                    "active item (lightweight row) plus every edge. Lets a UI "
                    "build the adjacency map once and explore connectivity "
                    "client-side without per-item calls. Read-only.",
    )
    _add_format_args(sp)

    sp = sub.add_parser(
        "history", help="changelog rows for an item.",
        description="Show changelog rows for an item, newest first.",
    )
    sp.add_argument("id", help="item id.")
    sp.add_argument("--limit", type=int, default=50, help="max rows (default: 50).")
    _add_format_args(sp)

    sp = sub.add_parser(
        "reindex",
        help="(re)build the index from the source tree; the one safe write.",
        description="Rebuild the (rebuildable) index from the on-disk source "
                    "tree. This is the only verb that writes.",
    )
    sp.add_argument(
        "--dry-run", action="store_true",
        help="compute and print counts without writing anything.",
    )
    _add_format_args(sp)

    # -- WRITE verbs (Phase 2, authoring) ------------------------------------
    # These MUTATE the on-disk library + index (every read verb above is
    # read-only). They author context files (knowledge/instruction) and record
    # a changelog row per mutation. Grouped/labeled apart from the read verbs.
    sp = sub.add_parser(
        "create",
        help="[WRITE] create a context-file stub (knowledge|instruction).",
        description="[WRITE] Create a context-file stub from kind/title/"
                    "category: derives a name slug, writes minimal frontmatter "
                    "+ a heading under the kind's category dir, indexes it, and "
                    "records a changelog row. Rejects collisions. --dry-run "
                    "computes the planned id/path without writing.",
    )
    sp.add_argument("--kind", choices=["knowledge", "instruction"], required=True,
                    help="context-file kind to create.")
    sp.add_argument("--title", required=True, help="human title (non-empty).")
    sp.add_argument("--category", required=True,
                    help="category sub-directory (a safe slug).")
    sp.add_argument("--name", help="explicit slug (overrides title-derived).")
    sp.add_argument("--by", help="actor recorded in the changelog "
                                 "(default: $AI_TRACKING_ID or 'unknown').")
    sp.add_argument("--dry-run", action="store_true",
                    help="compute the planned id/path without writing.")
    _add_format_args(sp)

    sp = sub.add_parser(
        "update",
        help="[WRITE] replace a context-file's body (keeps frontmatter).",
        description="[WRITE] Replace the BODY of an existing context-file item, "
                    "preserving its frontmatter, then reindex + record a "
                    "changelog row. Provide --content or --content-file.",
    )
    sp.add_argument("id", help="item id, e.g. knowledge:reference/glossary.")
    grp = sp.add_mutually_exclusive_group(required=True)
    grp.add_argument("--content", help="new body text.")
    grp.add_argument("--content-file", help="read new body text from this file.")
    sp.add_argument("--by", help="actor recorded in the changelog "
                                 "(default: $AI_TRACKING_ID or 'unknown').")
    _add_format_args(sp)

    sp = sub.add_parser(
        "link",
        help="[WRITE] add a reference edge from a bundle to another item.",
        description="[WRITE] Add a reference from a bundle (role/profile/skill/"
                    "global) src to dst by editing src's YAML in the place "
                    "reindex reads (context_files bucket for a leaf dst, the "
                    "roles/skills list for a bundle dst), then incrementally "
                    "refresh src's edges + record a changelog row. Rejects self/"
                    "cycle/missing/non-bundle; idempotent on a re-link. "
                    "--dry-run reports the planned ref without writing.",
    )
    sp.add_argument("src_id", help="bundle id, e.g. role:architect.")
    sp.add_argument("dst_id", help="referenced item id, e.g. knowledge:reference/x.")
    sp.add_argument("--by", help="actor recorded in the changelog "
                                 "(default: $AI_TRACKING_ID or 'unknown').")
    sp.add_argument("--dry-run", action="store_true",
                    help="report the planned ref/file without writing.")
    _add_format_args(sp)

    sp = sub.add_parser(
        "unlink",
        help="[WRITE] remove a reference edge from a bundle.",
        description="[WRITE] Remove a reference from a bundle src to dst by "
                    "dropping the entry from src's YAML (tidying now-empty "
                    "lists/buckets), then incrementally refresh src's edges + "
                    "record a changelog row. Rejects when not currently linked. "
                    "--dry-run reports the planned change without writing.",
    )
    sp.add_argument("src_id", help="bundle id, e.g. role:architect.")
    sp.add_argument("dst_id", help="referenced item id to remove.")
    sp.add_argument("--by", help="actor recorded in the changelog "
                                 "(default: $AI_TRACKING_ID or 'unknown').")
    sp.add_argument("--dry-run", action="store_true",
                    help="report the planned change without writing.")
    _add_format_args(sp)

    sp = sub.add_parser(
        "move",
        help="[WRITE] rename/relocate an item, repointing all inbound refs.",
        description="[WRITE] Rename (--name) and/or relocate (--category) an "
                    "item with REFERENTIAL INTEGRITY: computes the new path+id, "
                    "rejects a target-path/new-id collision, repoints EVERY "
                    "inbound YAML reference to the new location, moves the file "
                    "(and any *_latest symlink), updates the item id + all edge "
                    "src/dst, and records a changelog row. --dry-run returns the "
                    "repoint PLAN (from/to/inbound) without writing.",
    )
    sp.add_argument("id", help="item id to move, e.g. knowledge:reference/glossary.")
    sp.add_argument("--name", help="new name/slug (rename); may carry a "
                                   "category prefix for leaves, e.g. reference/x.")
    sp.add_argument("--category", help="new category dir (relocate the leaf).")
    sp.add_argument("--by", help="actor recorded in the changelog "
                                 "(default: $AI_TRACKING_ID or 'unknown').")
    sp.add_argument("--dry-run", action="store_true",
                    help="return the repoint plan without writing.")
    _add_format_args(sp)

    for verb in ("delete", "archive"):
        sp = sub.add_parser(
            verb,
            help="[WRITE] soft-delete (archive) an item into its _archive/ "
                 "subtree.",
            description="[WRITE] SOFT-DELETE: move the item's file into the "
                        "kind's _archive/ subtree (which reindex classifies as "
                        "archived, so it survives a reindex and drops out of "
                        "active listings), update the index, and record a "
                        "changelog row. Inbound-ref guard: rejected with the "
                        "referrers list unless --force (a forced archive leaves "
                        "those refs dangling, surfaced by `validate`). "
                        "--dry-run returns the plan without writing. "
                        "Alias: `archive`.",
        )
        sp.add_argument("id", help="item id to archive, e.g. "
                                   "knowledge:reference/glossary.")
        sp.add_argument("--force", action="store_true",
                        help="archive even when other items reference it "
                             "(leaves dangling refs that `validate` reports).")
        sp.add_argument("--by", help="actor recorded in the changelog "
                                     "(default: $AI_TRACKING_ID or 'unknown').")
        sp.add_argument("--dry-run", action="store_true",
                        help="return the archive plan without writing.")
        _add_format_args(sp)

    sp = sub.add_parser(
        "edit",
        help="[WRITE] open a context file in $EDITOR (interactive).",
        description="[WRITE] Resolve the item's path + $EDITOR (default vi) and "
                    "launch the editor on it. Interactive — the human edits the "
                    "body directly.",
    )
    sp.add_argument("id", help="item id to open in the editor.")

    for verb in ("repl", "shell"):
        sub.add_parser(
            verb,
            help="start an interactive REPL over the index (also the default "
                 "with no subcommand).",
            description="Start an interactive read-eval-print loop. Each line is "
                        "dispatched through the same verbs as the CLI; type "
                        "`help`, `help-examples`, or `quit` to exit.",
        )

    return p


# ---------------------------------------------------------------------------
# Output formatting — shared across verbs. ``--json`` is the stable machine
# shape (unchanged); human/oneline are convenience renderings only.
# ---------------------------------------------------------------------------

def _fmt_of(args) -> str:
    if getattr(args, "json", False):
        return "json"
    if getattr(args, "oneline", False):
        return "oneline"
    return "human"


def _emit(cmd: str, result, fmt: str, *, out=None) -> None:
    if fmt == "json":
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False), file=out)
        return
    print(_render_human(cmd, result, oneline=(fmt == "oneline")), file=out)


def _render_human(cmd: str, result, *, oneline: bool) -> str:
    if cmd == "list":
        return _render_item_rows(result, oneline=oneline)
    if cmd == "search":
        return _render_search(result, oneline=oneline)
    if cmd == "refs":
        return _render_refs(result)
    if cmd == "history":
        return _render_history(result)
    if cmd == "get":
        return _render_get(result)
    if cmd == "content":
        return _render_content(result)
    if cmd == "tree":
        return _render_tree(result)
    if cmd in ("resolve", "preview"):
        return _render_resolve(result)
    if cmd == "validate":
        return _render_validate(result)
    if cmd == "graph":
        return _render_graph(result)
    if cmd == "reindex":
        return _render_reindex(result)
    if cmd in ("create", "update", "edit", "link", "unlink", "move",
               "delete", "archive"):
        return _render_write(cmd, result)
    return json.dumps(result, indent=2, default=str, ensure_ascii=False)


def _render_write(cmd: str, d) -> str:
    if not isinstance(d, dict):
        return str(d)
    if not d.get("ok"):
        if d.get("error") == "referenced":
            refs = d.get("referrers") or []
            return ("error: referenced by {} item(s); pass --force to archive "
                    "anyway (leaves dangling refs):\n  {}".format(
                        len(refs), "\n  ".join(refs)))
        return "error: {}".format(d.get("error") or "unknown error")
    if cmd in ("delete", "archive"):
        frm = d.get("from") or {}
        to = d.get("to") or {}
        prefix = "would archive" if d.get("dry_run") else "archived"
        lines = [
            "{} {} -> {}".format(prefix, frm.get("id"), to.get("id")),
            "  from: {}".format(frm.get("path")),
            "  to:   {}".format(to.get("path")),
        ]
        refs = d.get("referrers") or []
        if refs:
            lines.append("  WARNING: {} now-dangling referrer(s) (run "
                         "`validate`):".format(len(refs)))
            for r in refs:
                lines.append("    {}".format(r))
        return "\n".join(lines)
    if cmd == "create":
        prefix = "would create" if d.get("dry_run") else "created"
        return "{} {}\n  path: {}".format(prefix, d.get("id"), d.get("path"))
    if cmd == "update":
        return "updated {}\n  path: {}".format(d.get("id"), d.get("path"))
    if cmd == "edit":
        return "{} {}".format(d.get("editor"), d.get("path"))
    if cmd == "link":
        if d.get("already_linked"):
            return "already linked: {} -> {}".format(
                d.get("src_id"), d.get("dst_id"))
        prefix = "would link" if d.get("dry_run") else "linked"
        return "{} {} -> {}\n  ref:  {}\n  file: {}".format(
            prefix, d.get("src_id"), d.get("dst_id"), d.get("ref"), d.get("file"))
    if cmd == "unlink":
        prefix = "would unlink" if d.get("dry_run") else "unlinked"
        return "{} {} -> {}\n  file: {}".format(
            prefix, d.get("src_id"), d.get("dst_id"), d.get("file"))
    if cmd == "move":
        frm = d.get("from") or {}
        to = d.get("to") or {}
        inbound = d.get("inbound") or []
        prefix = "would move" if d.get("dry_run") else "moved"
        lines = [
            "{} {} -> {}".format(prefix, frm.get("id"), to.get("id")),
            "  from: {}".format(frm.get("path")),
            "  to:   {}".format(to.get("path")),
            "  inbound refs repointed: {}".format(len(inbound)),
        ]
        for e in inbound:
            lines.append("    {}  {} -> {}".format(
                e.get("src_id"), e.get("ref_old"), e.get("ref_new")))
        return "\n".join(lines)
    return json.dumps(d, indent=2, default=str, ensure_ascii=False)


def _item_oneline(r: dict) -> str:
    return "{:<34} {}".format(r.get("id") or "", r.get("title") or "")


def _item_block(r: dict) -> str:
    lines = [r.get("id") or ""]
    if r.get("title"):
        lines.append("  title:   {}".format(r["title"]))
    if r.get("summary"):
        lines.append("  summary: {}".format(r["summary"]))
    lines.append("  status:  {}   scope: {}".format(
        r.get("status") or "-", r.get("scope") or "-"))
    if r.get("path"):
        lines.append("  path:    {}".format(r["path"]))
    return "\n".join(lines)


def _render_item_rows(rows, *, oneline: bool) -> str:
    if not rows:
        return "(no items)"
    if oneline:
        return "\n".join(_item_oneline(r) for r in rows)
    return "\n\n".join(_item_block(r) for r in rows)


def _render_search(rows, *, oneline: bool) -> str:
    if not rows:
        return "(no matches)"
    out = []
    for r in rows:
        head = "{:<34} {}".format(r.get("id") or "", r.get("title") or "")
        if oneline:
            out.append(head)
        else:
            snippet = r.get("snippet")
            out.append(head + ("\n  …{}".format(snippet) if snippet else ""))
    return "\n".join(out)


def _render_refs(rows) -> str:
    if not rows:
        return "(no edges)"
    out = []
    for r in rows:
        mark = "" if r.get("resolved") else "   [DANGLING]"
        out.append("{}  --{}-->  {}{}".format(
            r.get("src_id"), r.get("edge_type"), r.get("dst_id"), mark))
    return "\n".join(out)


def _render_history(rows) -> str:
    if not rows:
        return "(no history)"
    out = []
    for r in rows:
        out.append("{}  {}  {}  {}".format(
            r.get("changed_at"), r.get("op"), r.get("field") or "",
            r.get("changed_by") or ""))
    return "\n".join(out)


def _render_get(item) -> str:
    if item is None:
        return "(not found)"
    lines = [item.get("id") or ""]
    for k in ("kind", "loader", "name", "title", "summary", "status", "scope",
              "path", "size_bytes", "updated_at"):
        v = item.get(k)
        if v not in (None, ""):
            lines.append("  {:<9} {}".format(k + ":", v))
    c = item.get("counts") or {}
    lines.append("  edges:    outbound={} inbound={}".format(
        c.get("outbound", 0), c.get("inbound", 0)))
    return "\n".join(lines)


def _render_content(d) -> str:
    if d is None:
        return "(not found)"
    head = "{}  [{}]  {}".format(
        d.get("id") or "", d.get("kind") or "", d.get("path") or "")
    body = d.get("content")
    if body is None:
        return head + "\n(content unavailable)"
    return head + "\n" + body


def _render_tree(node, depth: int = 0) -> str:
    tags = [t for t in ("unresolved", "cycle", "truncated") if node.get(t)]
    suffix = "   [{}]".format(", ".join(tags)) if tags else ""
    title = node.get("title")
    line = "{}{}{}{}".format(
        "  " * depth, node.get("id") or "",
        "  — {}".format(title) if title else "", suffix)
    lines = [line]
    for ch in node.get("children", []):
        lines.append(_render_tree(ch, depth + 1))
    return "\n".join(lines)


def _render_resolve(d) -> str:
    resolved = d.get("resolved", [])
    lines = ["{} resolves to {} leaf file(s), {} bytes:".format(
        d.get("id"), len(resolved), d.get("total_size_bytes", 0))]
    for r in resolved:
        count = r.get("count")
        badge = "  x{}".format(count) if count and count > 1 else ""
        lines.append("  {:<34} {}{}".format(
            r.get("id") or "", r.get("path") or "", badge))
        if count and count > 1:
            for chain in r.get("via", []):
                lines.append("      via {}".format(" -> ".join(chain) or "(direct)"))
    unresolved = d.get("unresolved", [])
    if unresolved:
        lines.append("  unresolved (dangling refs): {}".format(len(unresolved)))
        for u in unresolved:
            lines.append("    {}".format(u))
    return "\n".join(lines)


def _render_validate(d) -> str:
    dangling = d.get("dangling", [])
    orphans = d.get("orphans", [])
    lines = ["dangling edges: {}".format(len(dangling))]
    for e in dangling:
        lines.append("  {}  ->  {}".format(e.get("src_id"), e.get("dst_id")))
    lines.append("orphan items: {}".format(len(orphans)))
    for o in orphans:
        if isinstance(o, dict):
            lines.append("  [{:<4}] {}".format(o.get("severity") or "?", o.get("id")))
        else:  # back-compat: a bare id string
            lines.append("  {}".format(o))
    return "\n".join(lines)


def _render_graph(d) -> str:
    items = d.get("items", [])
    edges = d.get("edges", [])
    by_kind = Counter(it.get("kind") for it in items)
    lines = ["graph: {} item(s), {} edge(s)".format(len(items), len(edges))]
    for k in sorted(by_kind):
        lines.append("  {:<13} {}".format(k + ":", by_kind[k]))
    return "\n".join(lines)


def _render_reindex(d) -> str:
    by_kind = d.get("items_by_kind", {})
    lines = ["reindex complete:"]
    for k in sorted(by_kind):
        lines.append("  {:<13} {}".format(k + ":", by_kind[k]))
    lines.append("  {:<13} {}".format("edges:", d.get("edges", 0)))
    lines.append("  {:<13} {}".format("unresolved:", d.get("unresolved", 0)))
    return "\n".join(lines)


def _dispatch(idx: "ContextIndex", args):
    """Execute one parsed command against ``idx`` and return its result.

    Shared by both ``main()`` (one-shot CLI) and ``repl()`` (interactive) so
    verb logic lives in exactly one place. The caller renders the result with
    :func:`_emit`. Raises whatever the underlying read method raises (e.g.
    ``ValueError`` for a bad ``refs`` direction).
    """
    cmd = args.cmd
    if cmd == "list":
        if args.id:
            return idx.children(args.id)
        return idx.list_items(
            kind=args.kind, status=args.status, scope=args.scope,
            loader=args.loader, limit=args.limit, offset=args.offset,
        )
    if cmd == "get":
        return idx.get_item(args.id)
    if cmd == "content":
        return idx.content(args.id)
    if cmd == "search":
        return idx.search(args.query, kind=args.kind, limit=args.limit)
    if cmd == "refs":
        return idx.refs(args.id, direction=args.direction)
    if cmd == "tree":
        return idx.tree(args.id, max_depth=args.max_depth)
    if cmd in ("resolve", "preview"):
        return idx.resolve(args.id)
    if cmd == "validate":
        return idx.validate()
    if cmd == "graph":
        return idx.graph()
    if cmd == "history":
        return idx.history(args.id, limit=args.limit)
    if cmd == "reindex":
        return idx.reindex(dry_run=args.dry_run)
    if cmd == "create":
        return idx.create(
            kind=args.kind, title=args.title, category=args.category,
            name=args.name, by=args.by, dry_run=args.dry_run,
        )
    if cmd == "update":
        content = args.content
        if content is None:
            content = Path(args.content_file).read_text(encoding="utf-8")
        return idx.update_content(args.id, content, by=args.by)
    if cmd == "link":
        return idx.link(args.src_id, args.dst_id, by=args.by, dry_run=args.dry_run)
    if cmd == "unlink":
        return idx.unlink(args.src_id, args.dst_id, by=args.by, dry_run=args.dry_run)
    if cmd == "move":
        return idx.move(
            args.id, new_category=args.category, new_name=args.name,
            by=args.by, dry_run=args.dry_run,
        )
    if cmd in ("delete", "archive"):
        return idx.delete(args.id, force=args.force, by=args.by,
                          dry_run=args.dry_run)
    if cmd == "edit":
        return idx.edit_command(args.id)
    raise ValueError("unknown command: {}".format(cmd))


# ---------------------------------------------------------------------------
# Interactive REPL — a thin convenience loop over the same verb dispatch. The
# index is read-only; this just keeps one ContextIndex open and feeds each
# input line through the CLI parser. Designed to be testable: callers can
# inject ``input_lines`` and ``out`` to script a session without a TTY.
# ---------------------------------------------------------------------------

_REPL_QUIT = frozenset({"quit", "exit", "q"})

# Tab-completion candidates for the REPL: verbs + common flags + the 8 kinds.
_REPL_VERBS = [
    "list", "get", "content", "search", "refs", "tree", "resolve", "preview",
    "validate", "graph", "history", "reindex", "help", "help-examples", "quit",
]
_REPL_FLAGS = [
    "--kind", "--status", "--scope", "--loader", "--limit", "--oneline", "--json",
    "--in", "--out", "--both",
]
_REPL_KINDS = [
    "brief", "memory", "knowledge", "instruction",
    "role", "profile", "skill", "global",
]
_REPL_COMPLETER_WORDS = _REPL_VERBS + _REPL_FLAGS + _REPL_KINDS

# Shared readline REPL base (history/arrow-keys/tab-completion) lives in
# scripts/lib/. Add it to sys.path so the manager can delegate to it.
_LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))


def repl(index: "ContextIndex" = None, *, db=None, input_lines=None, out=None) -> int:
    """Run the interactive REPL.

    Each input line is shlex-split into an argv and dispatched through the SAME
    argparse verbs as the CLI (``list``, ``resolve``, ``tree``, ``refs``,
    ``search``, ``validate``, ``reindex`` …), honoring ``--oneline``/``--json``
    per line. ONE :class:`ContextIndex` is kept open for the whole session.

    The loop itself (history, arrow keys, tab completion, quit/EOF handling,
    error isolation) is owned by the shared :func:`repl_base.run_repl`; this
    function only supplies the per-line ``dispatch`` and the banner. ``help``
    prints the verb list, ``help-examples`` prints the walkthrough, and
    ``quit``/``exit``/``q``/EOF exit cleanly. Errors in a command print a short
    message and return to the prompt — the loop never exits on a command error.

    Args:
        index: a pre-opened ContextIndex; if None one is opened from ``db``.
        db: optional DB path override (used only when ``index`` is None).
        input_lines: an iterable of input lines for scripted/testing use. When
            None, lines are read interactively from stdin via ``input()``.
        out: output stream (defaults to ``sys.stdout``).

    Returns 0 on a clean exit.
    """
    from uai_toolkit.common_utils.repl_base import run_repl  # local import: sys.path set up above

    out = out if out is not None else sys.stdout
    idx = index if index is not None else (
        ContextIndex(db_path=db) if db else ContextIndex()
    )
    parser = _build_parser()

    try:
        n_items = len(idx.list_items(status="all", limit=None))
    except Exception:  # pragma: no cover - defensive; banner is best-effort
        n_items = 0

    banner = (
        "context_mgr — interactive REPL\n"
        "{} item(s) indexed. Type `help` or `help-examples`; `quit` to exit.".format(
            n_items)
    )

    def dispatch(line: str) -> None:
        """Handle one REPL line: help verbs, then the shared argparse dispatch."""
        low = line.lower()
        if low == "help":
            parser.print_help(out)
            return
        if low in ("help-examples", "--help-examples"):
            print(HELP_EXAMPLES, file=out)
            return

        try:
            argv = shlex.split(line)
        except ValueError as e:
            print("parse error: {} (try `help`)".format(e), file=out)
            return
        if not argv:
            return
        if argv[0] in ("repl", "shell"):
            print("already in the REPL.", file=out)
            return

        # Parse through the shared CLI parser. argparse exits on bad usage; we
        # trap that so a bad line just prints a hint and we keep looping.
        try:
            args = parser.parse_args(argv)
        except SystemExit:
            print(
                "unknown command or bad arguments: {!r} (try `help`)".format(line),
                file=out,
            )
            return
        if not getattr(args, "cmd", None):
            print("unknown command: {!r} (try `help`)".format(line), file=out)
            return

        # A real dispatch/emit error propagates to run_repl, which prints
        # ``error: <msg>`` and keeps the loop alive.
        result = _dispatch(idx, args)
        _emit(args.cmd, result, _fmt_of(args), out=out)

    return run_repl(
        dispatch=dispatch,
        prompt="context> ",
        history_file=Path.home() / ".context_mgr_history",
        completer_words=_REPL_COMPLETER_WORDS,
        banner=banner,
        out=out,
        input_lines=input_lines,
    )


def main(argv=None) -> int:
    """argparse entry point. Prints human-readable output by default;
    ``--oneline`` for one line per item, ``--json`` for the stable machine
    shape. ``--help-examples`` prints a walkthrough and exits.

    With NO subcommand (or an explicit ``repl``/``shell`` verb), launches the
    interactive REPL.

    Returns 0 on success, 2 on bad usage, 1 on an unexpected error.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    # Short-circuit the walkthrough before the required-subcommand check.
    if "--help-examples" in argv:
        print(HELP_EXAMPLES)
        return 0

    parser = _build_parser()
    args = parser.parse_args(argv)

    # No subcommand, or an explicit repl/shell verb -> interactive REPL.
    if not getattr(args, "cmd", None) or args.cmd in ("repl", "shell"):
        return repl(db=args.db)

    idx = ContextIndex(db_path=args.db) if args.db else ContextIndex()

    # The `edit` verb resolves the path+editor then launches the OS editor
    # (interactive). Resolution failure prints the error and stops.
    if args.cmd == "edit":
        res = idx.edit_command(args.id)
        if not res.get("ok"):
            print("error: {}".format(res.get("error")), file=sys.stderr)
            return 1
        import subprocess
        rc = subprocess.call([res["editor"], res["path"]])
        # After the editor exits, reconcile: reindex + audit only if the file
        # actually changed (so an interactive edit is never invisible to the
        # index or unaudited — the same single-write-path guarantee the
        # programmatic verbs already have).
        applied = idx.apply_edit(args.id, before_hash=res.get("content_hash"))
        if applied.get("ok") and applied.get("changed"):
            print("edit recorded + reindexed: {}".format(args.id), file=sys.stderr)
        elif applied.get("ok"):
            print("no changes detected: {}".format(args.id), file=sys.stderr)
        else:
            print("warning: {}".format(applied.get("error")), file=sys.stderr)
        return rc

    result = _dispatch(idx, args)
    _emit(args.cmd, result, _fmt_of(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
