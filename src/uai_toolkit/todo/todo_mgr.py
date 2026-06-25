#!/usr/bin/env python3
"""
todo_mgr - Interactive and CLI todo management.

Provides both an interactive REPL and one-shot CLI commands for
managing the filesystem-based todo system.

Usage:
    todo_mgr                      # Interactive REPL
    todo_mgr <command> [args...]  # One-shot CLI mode
    todo_mgr --help               # Show help

Examples:
    todo_mgr kanban
    todo_mgr list ready
    todo_mgr view IP2
    todo_mgr status IP2 reviewing
    todo_mgr flag add IP2 high_priority
"""

from __future__ import annotations

import atexit
import fnmatch
import json
import os
import re
try:
    import readline
except ImportError:  # REPL-only; absent on bare Windows
    readline = None
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from textwrap import indent, dedent
from typing import Callable

from uai_toolkit.common_utils.lib_outputColors import Colors

# === Configuration ===

SCRIPT_PATH = Path(__file__).resolve()
SCRIPTS_DIR = SCRIPT_PATH.parent
APPLE_SCRIPT_DIR = SCRIPTS_DIR / "applescripts"
DEFAULT_APPLESCRIPT = APPLE_SCRIPT_DIR / "todo_mgr_demo.applescript"
# Derive the todos root from the single canonical AI_ROOT (default ~/AI/ai_root),
# NOT a hardcoded path. TODO_ROOT stays an optional override for non-standard
# layouts; when it's unset (e.g. MCP servers don't inherit it) we fall back to
# the AI_ROOT-derived location.
_AI_ROOT = Path(os.environ.get("AI_ROOT") or (Path.home() / "AI" / "ai_root"))
_FALLBACK_ROOT = _AI_ROOT / "ai_general" / "work" / "todos"
DEFAULT_ROOT = Path(os.environ.get("TODO_ROOT") or _FALLBACK_ROOT).resolve()
CURRENT_ROOT = DEFAULT_ROOT

VERSION = "2.5.0"
HISTORY_FILE = Path.home() / ".todo_mgr_history"

# Ref cache: keeps refs stable between display commands in REPL mode.
# Mutation commands use cached refs for resolution but ops layer loads fresh state.
_ref_cache: dict = {"todos": None, "refs": None}

def get_template_dirs() -> list[Path]:
    """Return list of possible template directories in priority order."""
    return [
        CURRENT_ROOT / "_todo_item_template",
        CURRENT_ROOT / "todo_item",  # legacy
    ]

STATUS_ORDER = [
    ("Triaging", "TR"),
    ("Needs_Research", "NR"),
    ("Needs_Derivation", "ND"),
    ("Ready", "RD"),
    ("In_Progress", "IP"),
    ("Reviewing", "RV"),
    ("Accepting", "AC"),
    ("Blocked", "BL"),
    ("Done", "DN"),
    ("Cancelled", "CN"),
]
STATUS_CODES = {code: status for status, code in STATUS_ORDER}
STATUS_TO_CODE = {status: code for status, code in STATUS_ORDER}
ACTIVE_STATUSES = {"Triaging", "Needs_Research", "Needs_Derivation", "Ready",
                   "In_Progress", "Reviewing", "Accepting", "Blocked"}


def resolve_status(status_input: str) -> str:
    """Resolve status code, name, or abbreviation to canonical name.

    Accepts: 'RD', 'rd', 'Ready', 'ready', 'READY', etc.
    Returns: 'Ready' (canonical capitalized form)
    Raises: ValueError if unrecognized.
    """
    s = status_input.strip()

    # Check 2-letter codes (case-insensitive)
    if s.upper() in STATUS_CODES:
        return STATUS_CODES[s.upper()]

    # Check full status names (case-insensitive)
    for status_name, _ in STATUS_ORDER:
        if status_name.lower() == s.lower():
            return status_name

    raise ValueError(
        f"Invalid status: '{status_input}'. "
        f"Valid: {', '.join(f'{s} ({c})' for s, c in STATUS_ORDER)}"
    )


# === Colors (imported from common_utils) ===


def c(text: str, *codes: str) -> str:
    """Apply color codes to text if colors enabled."""
    if not Colors.enabled():
        return text
    code_str = "".join(codes)
    return f"{code_str}{text}{Colors.RESET}"


# Status colors
STATUS_COLORS = {
    "Triaging": Colors.BRIGHT_BLACK,
    "Needs_Research": Colors.YELLOW,
    "Needs_Derivation": Colors.YELLOW,
    "Ready": Colors.GREEN,
    "In_Progress": Colors.CYAN,
    "Reviewing": Colors.MAGENTA,
    "Accepting": Colors.MAGENTA,
    "Blocked": Colors.RED,
    "Done": Colors.BRIGHT_BLACK,
    "Cancelled": Colors.BRIGHT_BLACK,
}


def colored_status(status: str) -> str:
    """Return status with appropriate color."""
    color = STATUS_COLORS.get(status, "")
    return c(status, color)


def colored_ref(ref: str) -> str:
    """Return reference code with color based on status prefix."""
    if len(ref) >= 2:
        code = ref[:2]
        if code in STATUS_CODES:
            status = STATUS_CODES[code]
            color = STATUS_COLORS.get(status, "")
            return c(ref, Colors.BOLD, color)
    return c(ref, Colors.BOLD)


# === Data Structures ===

def get_groups_dir() -> Path:
    path = CURRENT_ROOT / "groups"
    path.mkdir(exist_ok=True)
    return path


def set_current_root(path: Path) -> None:
    global CURRENT_ROOT
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"TODO root not found: {resolved}")
    CURRENT_ROOT = resolved


@dataclass
class Todo:
    path: Path
    status: str
    flags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    assigned: list[str] = field(default_factory=list)
    parent: Path | None = None
    children: list[Path] = field(default_factory=list)
    summary: str = ""
    title: str = ""
    created: str = ""
    updated: str = ""
    owner: str = ""                      # single owner from origin.yml (WHO executes: session|team|project id)
    project: str = ""                    # project/scope from origin.yml (WHAT context: project/team id)
    origin: dict = field(default_factory=dict)  # full origin.yml contents (provenance)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def rel_path(self) -> Path:
        return self.path.relative_to(CURRENT_ROOT)
    
    @property
    def depth(self) -> int:
        """Return nesting depth (0 = root level)."""
        return len(self.rel_path.parts) - 1


def todo_to_dict(todo: Todo, ref: str = "") -> dict:
    """Convert Todo dataclass to dict for JSON serialization."""
    return {
        "id": todo.name,
        "ref": ref,
        "path": str(todo.path),
        "rel_path": str(todo.rel_path),
        "status": todo.status,
        "flags": todo.flags,
        "tags": todo.tags,
        "assigned": todo.assigned,
        "title": todo.title,
        "summary": todo.summary,
        "created": todo.created,
        "updated": todo.updated,
        # `parent` is DERIVED from physical directory nesting (the single source
        # of truth for parent/child grouping) — never an editable origin.yml field.
        "parent": str(todo.parent.relative_to(CURRENT_ROOT)) if todo.parent else None,
        "children": [str(c.relative_to(CURRENT_ROOT)) for c in todo.children],
        # Unified Work Tracking (origin.yml) extensions — additive, optional.
        # owner = WHO executes; project = WHAT scope it belongs to (distinct axes).
        "owner": todo.owner or None,
        "project": todo.project or None,
        "created_by": todo.origin.get("created_by"),
        "source": todo.origin.get("source"),
        "origin": todo.origin or None,
    }


def load_todos(include_completed: bool = False, include_trash: bool = False) -> dict[Path, Todo]:
    """Load all todos from filesystem.

    Args:
        include_completed: If True, also load todos from completed/ directory.
        include_trash: If True, also load todos from trash/ directory.
    """
    todos: dict[Path, Todo] = {}
    template_names = {tpl.name for tpl in get_template_dirs() if tpl.exists()}
    excluded_dirs = {"incoming", "groups", "__pycache__"}
    if not include_completed:
        excluded_dirs.add("completed")
    if not include_trash:
        excluded_dirs.add("trash")
    
    for status_file in CURRENT_ROOT.rglob("*.status"):
        todo_dir = status_file.parent
        
        # Skip if in template directory
        if todo_dir.name in template_names:
            continue
        
        # Skip if any parent directory is excluded (handles nested paths)
        rel_parts = todo_dir.relative_to(CURRENT_ROOT).parts
        if any(part in excluded_dirs for part in rel_parts):
            continue
        
        # Lightweight floor (Unified Work Tracking): a todo is valid if it has
        # EITHER a rich notes.md OR a one-line `summary` file. This keeps the
        # ~300 existing rich todos parsing exactly as before while allowing the
        # new minimal form (summary + <Status>.status + origin.yml).
        has_notes = (todo_dir / "notes.md").exists()
        has_summary = (todo_dir / "summary").exists()
        if not has_notes and not has_summary:
            continue

        status = status_file.stem
        flags = sorted(f.stem for f in todo_dir.glob("*.flag"))
        tags = sorted(t.stem for t in todo_dir.glob("*.tag"))

        # Load assigned URIs
        assigned_file = todo_dir / "assigned.yml"
        if assigned_file.exists():
            import yaml
            assigned = yaml.safe_load(assigned_file.read_text()) or []
        else:
            assigned = []

        # Determine parent
        parent = todo_dir.parent
        if parent == CURRENT_ROOT or parent.name in ("completed", "trash"):
            parent = None
        
        # Extract metadata from notes (rich) or the summary file (lightweight)
        notes_path = todo_dir / "notes.md"
        if has_notes:
            title, summary, created, updated = extract_notes_metadata(notes_path)
        else:
            title, summary, created, updated = "", "", "", ""
        if not summary and has_summary:
            summary = next(
                (ln.strip() for ln in (todo_dir / "summary").read_text().splitlines()
                 if ln.strip()),
                "",
            )

        # Provenance / ownership (origin.yml) — absent on legacy todos.
        origin = read_origin(todo_dir)
        owner = str(origin.get("owner") or "")
        project = str(origin.get("project") or "")
        if not created and origin.get("created_at"):
            created = str(origin["created_at"])

        todos[todo_dir] = Todo(
            path=todo_dir,
            status=status,
            flags=flags,
            tags=tags,
            assigned=assigned,
            parent=parent,
            summary=summary,
            title=title or todo_dir.name,
            created=created,
            updated=updated,
            owner=owner,
            project=project,
            origin=origin,
        )
    
    # Populate children (guard against self-listing)
    for todo in todos.values():
        if todo.parent and todo.parent in todos and todo.parent != todo.path:
            todos[todo.parent].children.append(todo.path)
    
    return todos


def extract_notes_metadata(notes_path: Path) -> tuple[str, str, str, str]:
    """Extract title, summary, created, updated from notes.md."""
    title = ""
    summary_lines = []
    created = ""
    updated = ""
    
    try:
        with notes_path.open() as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return title, "", created, updated
    
    capture_summary = False
    for line in lines:
        stripped = line.strip()
        
        # Title from first heading
        if not title and stripped.startswith("# "):
            title = stripped[2:]
            continue
        
        # Created/Updated dates
        if stripped.startswith("**Created:**"):
            created = stripped.replace("**Created:**", "").strip()
        elif stripped.startswith("**Updated:**"):
            updated = stripped.replace("**Updated:**", "").strip()
        
        # Summary from Description section
        if stripped == "## Description":
            capture_summary = True
            continue
        if capture_summary and stripped.startswith("## "):
            break
        if capture_summary and stripped:
            summary_lines.append(stripped)
            if len(summary_lines) >= 3:
                break
    
    summary = " ".join(summary_lines[:3])
    return title, summary, created, updated


def build_reference_map(todos: dict[Path, Todo]) -> dict[str, Path]:
    """Build map of reference codes (IP1, RD2, etc.) to paths."""
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path, todo in todos.items():
        grouped[todo.status].append(path)
    
    reference_map: dict[str, Path] = {}
    for status, code in STATUS_ORDER:
        entries = sorted(grouped.get(status, []), key=lambda p: p.name)
        for idx, path in enumerate(entries, 1):
            reference_map[f"{code}{idx}"] = path
    
    return reference_map


# === Display Functions ===

def render_kanban(todos: dict[Path, Todo], include_done: bool = False, include_cancelled: bool = False) -> str:
    """Render kanban board view."""
    ref_map = build_reference_map(todos)
    inverse_ref = {path: ref for ref, path in ref_map.items()}
    
    grouped: dict[str, list[Todo]] = defaultdict(list)
    for todo in todos.values():
        grouped[todo.status].append(todo)
    
    lines: list[str] = []
    for status, code in STATUS_ORDER:
        # Skip Done/Cancelled unless requested
        if status == "Done" and not include_done:
            continue
        if status == "Cancelled" and not include_cancelled:
            continue
        
        items = sorted(grouped.get(status, []), key=lambda t: t.rel_path.as_posix())
        
        # Header with color
        header_text = f"{code} ({len(items)}) - {status.replace('_', ' ')}"
        header = c(header_text, Colors.BOLD, STATUS_COLORS.get(status, ""))
        lines.append(header)
        lines.append(c("-" * len(header_text), Colors.DIM))
        
        if not items:
            lines.append(c("  (none)", Colors.DIM))
        else:
            for todo in items:
                ref = inverse_ref.get(todo.path, "??")
                
                # Flags with icons
                flag_icons = []
                if "high_priority" in todo.flags:
                    flag_icons.append(c("🔥", Colors.RED))
                if "needs_testing" in todo.flags:
                    flag_icons.append(c("⚠️", Colors.YELLOW))
                if "blocked_by_other" in todo.flags:
                    flag_icons.append(c("🚫", Colors.RED))
                flags_str = "".join(flag_icons)
                
                # Tags
                tags_str = " ".join(c(f"#{tag}", Colors.BLUE) for tag in todo.tags[:3])
                
                # Build line
                ref_colored = colored_ref(ref)
                name = todo.rel_path.as_posix()
                line = f"  {ref_colored}. {name} {flags_str} {tags_str}".rstrip()
                lines.append(line)
                
                if todo.summary:
                    lines.append(c(f"       {todo.summary[:80]}", Colors.DIM))
        
        lines.append("")
    
    return "\n".join(lines).rstrip()


def render_tree(todos: dict[Path, Todo], include_done: bool = False) -> str:
    """Render tree view showing parent/child hierarchy."""
    import re
    
    ref_map = build_reference_map(todos)
    inverse_ref = {path: ref for ref, path in ref_map.items()}
    
    def extract_id(path) -> str:
        """Extract todo_NNNN from path name."""
        match = re.match(r"(todo_\d{4})", path.name)
        return match.group(1) if match else ""
    
    # Find root-level todos (no parent or parent not in todos)
    roots = []
    for path, todo in todos.items():
        if not include_done and todo.status in ("Done", "Cancelled"):
            continue
        if todo.parent is None or todo.parent not in todos:
            roots.append(todo)
    
    roots.sort(key=lambda t: (STATUS_TO_CODE.get(t.status, "ZZ"), t.name))
    
    lines = []
    
    def render_todo(todo: Todo, prefix: str = "", is_last: bool = True):
        ref = inverse_ref.get(todo.path, "??")
        connector = "└── " if is_last else "├── "
        
        # Status indicator
        status_short = STATUS_TO_CODE.get(todo.status, "??")
        status_colored = c(f"[{status_short}]", STATUS_COLORS.get(todo.status, ""))
        
        # Todo ID
        todo_id = extract_id(todo.path)
        todo_id_colored = c(todo_id, Colors.DIM) if todo_id else ""
        
        # Flags
        flag_str = ""
        if "high_priority" in todo.flags:
            flag_str += c("🔥", Colors.RED)
        if "blocked_by_other" in todo.flags:
            flag_str += c("🚫", Colors.RED)
        
        ref_colored = colored_ref(ref)
        name = todo.title or todo.name
        
        # Format: connector REF [STATUS] todo_NNNN name flags
        line = f"{prefix}{connector}{ref_colored} {status_colored} {todo_id_colored} {name} {flag_str}".rstrip()
        lines.append(line)
        
        # Render children
        children = [todos[cp] for cp in todo.children if cp in todos]
        if not include_done:
            children = [ch for ch in children if ch.status not in ("Done", "Cancelled")]
        children.sort(key=lambda t: t.name)
        
        child_prefix = prefix + ("    " if is_last else "│   ")
        for i, child in enumerate(children):
            render_todo(child, child_prefix, i == len(children) - 1)
    
    lines.append(c("TODO Tree", Colors.BOLD, Colors.UNDERLINE))
    lines.append("")
    
    for i, root in enumerate(roots):
        render_todo(root, "", i == len(roots) - 1)
    
    return "\n".join(lines)


def format_table(todos: list[Todo], sort_key: str = "status",
                  indent_children: bool = True,
                  show_dates: bool = False) -> str:
    """Format todos as a table with aligned columns.

    Args:
        todos: List of Todo objects to display.
        sort_key: Sort field - name, status, created, updated, ref, flags.
        indent_children: If True, group children under parents with indentation.
        show_dates: If True, include Created and Updated columns.

    Returns:
        Formatted table string.
    """
    if not todos:
        return c("(no todos)", Colors.DIM)

    import re
    ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')

    def visible_len(s: str) -> int:
        """Get visible length of string (excluding ANSI codes)."""
        return len(ANSI_ESCAPE.sub('', s))

    def pad(s: str, width: int) -> str:
        """Pad string to width, accounting for ANSI codes."""
        padding = width - visible_len(s)
        return s + (" " * max(0, padding))

    def truncate(s: str, w: int) -> str:
        """Truncate to width with ellipsis."""
        if len(s) <= w:
            return s
        return s[:w-2] + ".."

    def extract_id(path) -> str:
        """Extract todo_NNNN_name from path."""
        return path.name

    ref_map = build_reference_map({todo.path: todo for todo in todos})
    inverse_ref = {path: ref for ref, path in ref_map.items()}

    # Build sort function
    sort_funcs = {
        "name": lambda t: (t.name.lower(),),
        "status": lambda t: (STATUS_TO_CODE.get(t.status, "ZZ"), t.name),
        "created": lambda t: (t.created or "9999", t.name),
        "updated": lambda t: (t.updated or "9999", t.name),
        "ref": lambda t: (inverse_ref.get(t.path, "ZZZ"),),
        "flags": lambda t: (",".join(t.flags) if t.flags else "zzz", t.name),
    }
    sort_fn = sort_funcs.get(sort_key, sort_funcs["status"])

    # Build display order with optional hierarchy
    todo_paths = {t.path for t in todos}
    todo_by_path = {t.path: t for t in todos}

    if indent_children:
        # Separate roots from children within the filtered list
        children_map: dict[Path, list[Path]] = defaultdict(list)
        roots = []
        for t in todos:
            if t.parent and t.parent in todo_paths:
                children_map[t.parent].append(t.path)
            else:
                roots.append(t)

        roots.sort(key=sort_fn)

        # Recursively collect parent then children
        def collect_hierarchy(todo: Todo, depth: int) -> list[tuple[Todo, int]]:
            """Collect todo and its children recursively with depth."""
            result = [(todo, depth)]
            kids = children_map.get(todo.path, [])
            kid_todos = [todo_by_path[p] for p in kids]
            kid_todos.sort(key=sort_fn)
            for child in kid_todos:
                result.extend(collect_hierarchy(child, depth + 1))
            return result

        ordered: list[tuple[Todo, int]] = []
        for root in roots:
            ordered.extend(collect_hierarchy(root, 0))
    else:
        ordered = [(t, 0) for t in sorted(todos, key=sort_fn)]

    # Column widths — use terminal width for dynamic ID column
    term_w = shutil.get_terminal_size((120, 24)).columns
    REF_W = 5
    STATUS_W = 17
    FLAGS_W = 18
    TAGS_W = 25
    DATE_W = 12
    fixed_w = REF_W + STATUS_W + FLAGS_W + TAGS_W + 10  # 10 for separators
    if show_dates:
        fixed_w += (DATE_W + 2) * 2
    ID_W = max(35, min(80, term_w - fixed_w))

    rows = []

    # Header
    hdr_parts = [
        pad("Ref", REF_W), pad("ID", ID_W), pad("Status", STATUS_W),
    ]
    if show_dates:
        hdr_parts.extend([pad("Created", DATE_W), pad("Updated", DATE_W)])
    hdr_parts.extend([pad("Flags", FLAGS_W), "Tags"])
    hdr = "  ".join(hdr_parts)
    rows.append(c(hdr, Colors.DIM))

    total_w = REF_W + ID_W + STATUS_W + FLAGS_W + TAGS_W + 8
    if show_dates:
        total_w += (DATE_W + 2) * 2
    rows.append(c("─" * total_w, Colors.DIM))

    for todo, indent_level in ordered:
        ref = inverse_ref.get(todo.path, "")
        todo_id = extract_id(todo.path)

        # Apply indent prefix for child todos
        indent_prefix = "  " * indent_level
        display_id = truncate(indent_prefix + todo_id, ID_W)

        flags_str = truncate(",".join(todo.flags), FLAGS_W) if todo.flags else "-"
        tags_str = truncate(",".join(todo.tags), TAGS_W) if todo.tags else "-"

        ref_colored = colored_ref(ref)
        status_colored = colored_status(todo.status)
        flags_display = c(flags_str, Colors.YELLOW) if todo.flags else c("-", Colors.DIM)
        tags_display = c(tags_str, Colors.BLUE) if todo.tags else c("-", Colors.DIM)

        row_parts = [
            pad(ref_colored, REF_W),
            pad(display_id, ID_W),
            pad(status_colored, STATUS_W),
        ]
        if show_dates:
            created_str = truncate(todo.created or "-", DATE_W)
            updated_str = truncate(todo.updated or "-", DATE_W)
            row_parts.append(pad(c(created_str, Colors.DIM), DATE_W))
            row_parts.append(pad(c(updated_str, Colors.DIM), DATE_W))
        row_parts.extend([pad(flags_display, FLAGS_W), tags_display])
        rows.append("  ".join(row_parts))

    return "\n".join(rows)


def view_todo_detail(todo: Todo, refs: dict[str, Path],
                     todos: dict[Path, "Todo"] | None = None) -> str:
    """Render detailed view of a single todo."""
    inverse_ref = {path: ref for ref, path in refs.items()}
    ref = inverse_ref.get(todo.path, "")
    
    lines = []
    
    # Header
    title = todo.title or todo.name
    lines.append(c(f"{title}", Colors.BOLD, Colors.UNDERLINE))
    lines.append("")
    
    # Metadata table
    lines.append(f"  {c('Reference:', Colors.DIM)}  {colored_ref(ref)}")
    lines.append(f"  {c('Status:', Colors.DIM)}     {colored_status(todo.status)}")
    lines.append(f"  {c('Path:', Colors.DIM)}       {c(str(todo.rel_path), Colors.BRIGHT_BLACK)}")

    if todo.created:
        lines.append(f"  {c('Created:', Colors.DIM)}    {c(todo.created, Colors.GREEN)}")
    if todo.updated:
        lines.append(f"  {c('Updated:', Colors.DIM)}    {c(todo.updated, Colors.GREEN)}")
    
    # Flags
    if todo.flags:
        flags_colored = ", ".join(c(f, Colors.YELLOW) for f in todo.flags)
        lines.append(f"  {c('Flags:', Colors.DIM)}      {flags_colored}")
    else:
        lines.append(f"  {c('Flags:', Colors.DIM)}      {c('(none)', Colors.DIM)}")
    
    # Tags
    if todo.tags:
        tags_colored = ", ".join(c(f"#{t}", Colors.BLUE) for t in todo.tags)
        lines.append(f"  {c('Tags:', Colors.DIM)}       {tags_colored}")
    else:
        lines.append(f"  {c('Tags:', Colors.DIM)}       {c('(none)', Colors.DIM)}")

    # Assigned
    if todo.assigned:
        assigned_colored = ", ".join(c(a, Colors.CYAN) for a in todo.assigned)
        lines.append(f"  {c('Assigned:', Colors.DIM)}   {assigned_colored}")

    # Owner + project (origin.yml) — distinct axes: WHO executes vs WHAT scope.
    if todo.owner:
        lines.append(f"  {c('Owner:', Colors.DIM)}      {c(todo.owner, Colors.CYAN)}")
    if todo.project:
        lines.append(f"  {c('Project:', Colors.DIM)}    {c(todo.project, Colors.CYAN)}")

    # Parent — DERIVED from physical directory nesting (single source of truth).
    if todo.parent:
        parent_rel = todo.parent.relative_to(CURRENT_ROOT)
        lines.append(f"  {c('Parent:', Colors.DIM)}     {c(str(parent_rel), Colors.CYAN)}")
    
    # Children
    if todo.children:
        lines.append(f"  {c('Children:', Colors.DIM)}")
        for child_path in sorted(todo.children):
            child_todo = todos.get(child_path) if todos else None
            if child_todo and child_todo.status:
                status_str = f"  [{colored_status(child_todo.status)}]"
            else:
                status_str = ""
            lines.append(f"    - {c(child_path.name, Colors.CYAN)}{status_str}")
    
    lines.append("")
    
    # Sections from notes.md
    notes_path = todo.path / "notes.md"
    if notes_path.exists():
        sections = extract_populated_sections(notes_path)
        for heading, content in sections.items():
            lines.append(c(f"{heading}:", Colors.BOLD, Colors.YELLOW))
            lines.append(indent(content, "  "))
            lines.append("")

    return "\n".join(lines)


def extract_section(notes_path: Path, heading: str) -> str:
    """Extract a section from notes.md by heading."""
    lines = notes_path.read_text().splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == f"## {heading}":
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            collected.append(line)
    return "\n".join(collected) if collected else ""


def _has_real_content(lines: list[str]) -> bool:
    """Check if lines have content beyond just HTML comments and whitespace."""
    text = "\n".join(lines)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    return bool(text.strip())


def extract_populated_sections(notes_path: Path) -> dict[str, str]:
    """Extract all ## sections from notes.md that have actual content.

    Args:
        notes_path: Path to notes.md file.

    Returns:
        Dict mapping section heading to its content string.
    """
    sections: dict[str, str] = {}
    current_section = None
    current_content: list[str] = []

    file_lines = notes_path.read_text().splitlines()
    for line in file_lines:
        if line.startswith("## "):
            if current_section and _has_real_content(current_content):
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip()
            current_content = []
        elif current_section is not None:
            current_content.append(line)

    # Handle last section
    if current_section and _has_real_content(current_content):
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def tail_notes(notes_path: Path, num_lines: int = 8) -> str:
    """Get last N lines of notes.md."""
    content = notes_path.read_text().splitlines()
    return "\n".join(content[-num_lines:]) if content else ""


# === Resolution & Scripts ===

def resolve_target(token: str, todos: dict[Path, Todo], refs: dict[str, Path]) -> Path:
    """Resolve a token (ref, path, name, or number) to a todo path.
    
    Resolution order:
    1. Reference code (IP2, RD1, TR3, etc.)
    2. Absolute path
    3. Relative path from TODO_ROOT
    4. Exact directory name match
    5. With todo_/task_ prefix added
    6. By todo number (0038 -> todo_0038_*)
    7. Partial match on directory name
    """
    if not token:
        raise ValueError("Empty reference/path")
    
    # 1. Try as reference code (IP2, RD1, etc.)
    upper = token.upper()
    if upper in refs:
        return refs[upper]
    
    # 2. Try as absolute path
    candidate = Path(token)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    
    # 3. Try as relative path from root
    rel_candidate = CURRENT_ROOT / token
    if rel_candidate.exists():
        return rel_candidate
    
    # 4 & 5. Try as directory name match (exact or with prefix)
    for path in todos:
        if path.name == token:
            return path
        if path.name == f"todo_{token}" or path.name == f"task_{token}":
            return path
    
    # 6. Try as todo number (e.g., "0038" or "38" matches "todo_0038_*")
    # Strip leading zeros for comparison, but also try with zeros
    if token.isdigit():
        num_str = token.zfill(4)  # Pad to 4 digits
        for path in todos:
            # Match todo_NNNN_* or task_NNNN_* pattern
            name = path.name
            if name.startswith(f"todo_{num_str}_") or name.startswith(f"task_{num_str}_"):
                return path
    
    # 7. Try partial/substring match on directory name
    token_lower = token.lower()
    matches = []
    for path in todos:
        name_lower = path.name.lower()
        # Check if token appears in the name (after the number prefix)
        # e.g., "tool_arch" matches "todo_0038_tool_architecture"
        if token_lower in name_lower:
            matches.append(path)
    
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        # Return the best match (shortest name that contains the token)
        matches.sort(key=lambda p: len(p.name))
        return matches[0]
    
    raise ValueError(f"Could not resolve: {token}")


def run_script(script_name: str, *args: str, quiet: bool = False) -> str:
    """Inline implementation of todo marker-file operations.

    Replaces the former shell-script helpers (set_status, add_flag,
    remove_flag, add_tag, remove_tag) with pure Python equivalents.
    """
    if script_name == "set_status":
        _inline_set_status(*args)
    elif script_name == "add_flag":
        _inline_add_marker(*args, suffix=".flag")
    elif script_name == "remove_flag":
        _inline_remove_marker(*args, suffix=".flag")
    elif script_name == "add_tag":
        _inline_add_marker(*args, suffix=".tag")
    elif script_name == "remove_tag":
        _inline_remove_marker(*args, suffix=".tag")
    else:
        raise FileNotFoundError(f"Unknown script: {script_name}")
    return ""


_STATUS_ALIASES: dict[str, str] = {
    "incoming": "Triaging", "triaging": "Triaging", "triage": "Triaging",
    "needs_research": "Needs_Research", "needsresearch": "Needs_Research", "research": "Needs_Research",
    "needs_derivation": "Needs_Derivation", "needsderivation": "Needs_Derivation", "needs-derivation": "Needs_Derivation",
    "pending": "Ready", "ready": "Ready",
    "in_progress": "In_Progress", "inprogress": "In_Progress", "in-progress": "In_Progress",
    "blocked": "Blocked",
    "reviewing": "Reviewing", "review": "Reviewing",
    "accepting": "Accepting", "acceptance": "Accepting",
    "done": "Done", "completed": "Done",
    "cancelled": "Cancelled", "canceled": "Cancelled",
}


def _inline_set_status(status: str, todo_dir: str = ".") -> None:
    """Set todo status by replacing the .status marker file."""
    normalized = _STATUS_ALIASES.get(status.lower().replace(" ", "_"))
    if not normalized:
        raise ValueError(f"Invalid status: {status}")
    d = Path(todo_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"Todo directory not found: {todo_dir}")
    for f in d.glob("*.status"):
        f.unlink()
    (d / f"{normalized}.status").touch()


def _inline_add_marker(name: str, todo_dir: str = ".", *, suffix: str) -> None:
    """Create a marker file (.flag or .tag) in a todo directory."""
    d = Path(todo_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"Todo directory not found: {todo_dir}")
    (d / f"{name}{suffix}").touch()


def _inline_remove_marker(name: str, todo_dir: str = ".", *, suffix: str) -> None:
    """Remove a marker file (.flag or .tag) from a todo directory."""
    d = Path(todo_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"Todo directory not found: {todo_dir}")
    target = d / f"{name}{suffix}"
    if target.exists():
        target.unlink()


def _assign_todo(todo_dir: Path, uri: str) -> str:
    """Assign a URI to a todo. Creates/updates assigned.yml."""
    import yaml
    assigned_file = todo_dir / "assigned.yml"
    if assigned_file.exists():
        assigned = yaml.safe_load(assigned_file.read_text()) or []
    else:
        assigned = []
    if uri in assigned:
        return "Already assigned to {}".format(uri)
    assigned.append(uri)
    assigned_file.write_text(yaml.dump(assigned, default_flow_style=False))
    return "Assigned to {}".format(uri)


def _unassign_todo(todo_dir: Path, uri: str) -> str:
    """Remove a URI assignment from a todo."""
    import yaml
    assigned_file = todo_dir / "assigned.yml"
    if not assigned_file.exists():
        return "Not assigned to {}".format(uri)
    assigned = yaml.safe_load(assigned_file.read_text()) or []
    if uri not in assigned:
        return "Not assigned to {}".format(uri)
    assigned.remove(uri)
    if assigned:
        assigned_file.write_text(yaml.dump(assigned, default_flow_style=False))
    else:
        assigned_file.unlink()
    return "Unassigned from {}".format(uri)


# === Unified Work Tracking helpers (origin.yml / history.log) ===
# Backward-compatible additions. Legacy todos simply lack these files; they are
# created on demand when a todo is created via the lightweight path or when an
# owner/parent/status mutation touches a todo for the first time.

def now_local_iso() -> str:
    """Local timestamp with timezone offset, e.g. 2026-06-16T16:00:00-04:00."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def current_session() -> str:
    """This session's tracking id from the environment, or 'unknown'."""
    return (os.environ.get("AI_TRACKING_ID")
            or os.environ.get("AI_CLI_SESSION_ID")
            or "unknown")


# Preferred key order for origin.yml readability.
# NOTE: `parent` is intentionally NOT here — parent/child grouping is physical
# directory nesting (the single source of truth), never an editable origin field.
_ORIGIN_KEY_ORDER = ["created_by", "created_at", "source", "owner", "project"]


def read_origin(todo_dir: Path) -> dict:
    """Read origin.yml for a todo. Returns {} if absent/unreadable."""
    origin_file = Path(todo_dir) / "origin.yml"
    if not origin_file.exists():
        return {}
    import yaml
    try:
        return yaml.safe_load(origin_file.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _ordered_origin(origin: dict) -> dict:
    """Reorder origin keys for stable, readable output; drop empties."""
    out: dict = {}
    for k in _ORIGIN_KEY_ORDER:
        if origin.get(k) not in (None, "", []):
            out[k] = origin[k]
    for k, v in origin.items():
        if k not in out and v not in (None, "", []):
            out[k] = v
    return out


def write_origin(todo_dir: Path, origin: dict) -> None:
    """Write origin.yml (key-ordered, empties dropped)."""
    import yaml
    origin_file = Path(todo_dir) / "origin.yml"
    origin_file.write_text(
        yaml.dump(_ordered_origin(origin), default_flow_style=False, sort_keys=False)
    )


def init_origin(todo_dir: Path, *, created_by: str = "", source: str = "agent",
                owner: str = "", project: str = "") -> dict:
    """Create origin.yml for a fresh todo. No-op if one already exists.

    `owner` (WHO executes) and `project` (WHAT scope) are independent, optional
    fields. Parent/child grouping is NOT recorded here — it is physical directory
    nesting (the single source of truth).
    """
    todo_dir = Path(todo_dir)
    if (todo_dir / "origin.yml").exists():
        return read_origin(todo_dir)
    origin = {
        "created_by": created_by or current_session(),
        "created_at": now_local_iso(),
        "source": source,
    }
    if owner:
        origin["owner"] = owner
    if project:
        origin["project"] = project
    write_origin(todo_dir, origin)
    return origin


def append_history(todo_dir: Path, status: str, *,
                   session: str = "", note: str = "") -> None:
    """Append one line to the append-only history.log:
        <local-ts> | <status> | <session> | <note>
    """
    line = "{} | {} | {} | {}".format(
        now_local_iso(), status, session or current_session(), note
    ).rstrip()
    with (Path(todo_dir) / "history.log").open("a") as fh:
        fh.write(line + "\n")


def read_history(todo_dir: Path) -> list[dict]:
    """Parse history.log into [{ts, status, session, note}, ...]."""
    hist = Path(todo_dir) / "history.log"
    if not hist.exists():
        return []
    entries = []
    for raw in hist.read_text().splitlines():
        if not raw.strip():
            continue
        parts = [p.strip() for p in raw.split("|", 3)]
        while len(parts) < 4:
            parts.append("")
        entries.append({"ts": parts[0], "status": parts[1],
                        "session": parts[2], "note": parts[3]})
    return entries


def create_lightweight_todo(name: str, parent_dir: Path, summary: str) -> Path:
    """Create a minimal todo dir: summary + Triaging.status. No notes.md/data/.

    Mirrors create_todo_from_template's numbering/slug rules so lightweight and
    rich todos share one numbering space.
    """
    num = get_next_todo_number()
    slug = re.sub(r'_+', '_', re.sub(r'[^a-z0-9_]+', '_', name.lower())).strip('_')
    if not slug:
        raise ValueError("Invalid todo name - no valid characters")
    prefix = f"todo_{num:04d}_"
    max_slug_len = 255 - len(prefix)
    if len(slug) > max_slug_len:
        slug = slug[:max_slug_len].rstrip('_')
    target_dir = parent_dir / f"{prefix}{slug}"
    if target_dir.exists():
        raise ValueError(f"Directory already exists: {target_dir}")
    target_dir.mkdir(parents=True)
    body = (summary or name.replace("_", " ")).strip()
    (target_dir / "summary").write_text(body + "\n")
    (target_dir / "Triaging.status").touch()
    return target_dir


def ops_create_light(
    name: str,
    summary: str = "",
    status: str = "triaging",
    owner: str = "",
    project: str = "",
    source: str = "agent",
    created_by: str = "",
) -> dict:
    """Create a lightweight todo (summary + status + origin.yml). Returns dict."""
    if not name or not name.strip():
        return {"success": False, "error": "Name required"}
    try:
        resolved = resolve_status(status)
        new_path = create_lightweight_todo(name, CURRENT_ROOT, summary)
        if resolved != "Triaging":
            run_script("set_status", resolved.lower(), str(new_path), quiet=True)
        init_origin(new_path, created_by=created_by, source=source,
                    owner=owner, project=project)
        append_history(new_path, resolved,
                       session=created_by or current_session(),
                       note=f"created via {source}")

        todos = load_todos()
        refs = build_reference_map(todos)
        inverse_ref = {p: r for r, p in refs.items()}
        todo = todos.get(new_path)
        return {
            "success": True,
            "todo": todo_to_dict(todo, inverse_ref.get(new_path, "")) if todo else {},
            "message": f"Created (lightweight): {new_path.name}",
            "origin": read_origin(new_path),
        }
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


def ops_set_owner(identifier: str, owner: str) -> dict:
    """Set the single owner in origin.yml (creates origin.yml if absent)."""
    todos = load_todos(include_completed=True)
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    origin = read_origin(path)
    if not origin:
        origin = init_origin(path)
    previous = origin.get("owner")
    origin["owner"] = owner
    write_origin(path, origin)
    return {"success": True, "todo_id": path.name,
            "owner": owner, "previous_owner": previous}


def ops_clear_owner(identifier: str) -> dict:
    """Remove the owner key from origin.yml (todo becomes unowned)."""
    todos = load_todos(include_completed=True)
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    origin = read_origin(path)
    previous = origin.pop("owner", None)
    if origin:
        write_origin(path, origin)
    return {"success": True, "todo_id": path.name, "previous_owner": previous}


def ops_set_project(identifier: str, project: str) -> dict:
    """Set the project/scope in origin.yml (creates origin.yml if absent).

    `project` is SEPARATE from `owner`: owner = WHO executes, project = WHAT
    context/scope the todo belongs to (for project rollups). Independent — an
    unowned todo can still carry a project.
    """
    todos = load_todos(include_completed=True)
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    origin = read_origin(path)
    if not origin:
        origin = init_origin(path)
    previous = origin.get("project")
    origin["project"] = project
    write_origin(path, origin)
    return {"success": True, "todo_id": path.name,
            "project": project, "previous_project": previous}


def ops_clear_project(identifier: str) -> dict:
    """Remove the project key from origin.yml (todo becomes project-less)."""
    todos = load_todos(include_completed=True)
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    origin = read_origin(path)
    previous = origin.pop("project", None)
    if origin:
        write_origin(path, origin)
    return {"success": True, "todo_id": path.name, "previous_project": previous}


def ops_history(identifier: str) -> dict:
    """Return the parsed history.log for a todo."""
    todos = load_todos(include_completed=True)
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
    except ValueError as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "todo_id": path.name, "history": read_history(path)}


# === Operations Layer ===
# Pure operations returning structured dicts. Used by cmd_*() and MCP server.


def ops_list(
    status: str | None = None,
    tag: str | None = None,
    flag: str | None = None,
    assigned: str | None = None,
    name_pattern: str | None = None,
    sort_key: str | None = None,
    include_all: bool = False,
    include_done: bool = False,
    include_cancelled: bool = False,
) -> dict:
    """List todos with filtering. Returns {"todos": [dict], "count": int}."""
    needs_completed = include_all or include_done
    if status and not needs_completed:
        try:
            needs_completed = resolve_status(status) in ("Done", "Cancelled")
        except ValueError:
            pass
    todos = load_todos(include_completed=needs_completed)
    refs = build_reference_map(todos)
    inverse_ref = {path: ref for ref, path in refs.items()}

    # Resolve status filter once
    resolved_status = None
    if status:
        try:
            resolved_status = resolve_status(status)
        except ValueError:
            return {"todos": [], "count": 0, "error": f"Unknown status: {status}"}

    results = []
    for path, todo in todos.items():
        # Status visibility filtering
        if not include_all:
            if todo.status == "Done" and not include_done:
                continue
            if todo.status == "Cancelled" and not include_cancelled:
                continue

        # Explicit status filter
        if resolved_status and todo.status != resolved_status:
            continue

        if tag and tag not in todo.tags:
            continue
        if flag and flag not in todo.flags:
            continue
        if assigned and assigned not in todo.assigned:
            continue
        if name_pattern and not fnmatch.fnmatch(todo.name.lower(), name_pattern.lower()):
            continue

        ref = inverse_ref.get(path, "")
        results.append(todo_to_dict(todo, ref))

    # Sort
    status_order = {s: i for i, (s, _) in enumerate(STATUS_ORDER)}
    if sort_key == "created":
        results.sort(key=lambda t: t.get("created", ""))
    elif sort_key == "updated":
        results.sort(key=lambda t: t.get("updated", ""))
    elif sort_key == "name":
        results.sort(key=lambda t: t["id"])
    else:
        results.sort(key=lambda t: (status_order.get(t["status"], 99), t["id"]))

    return {"todos": results, "count": len(results)}


def ops_get(identifier: str) -> dict:
    """Get a single todo by identifier. Returns todo dict or error."""
    todos = load_todos()
    refs = build_reference_map(todos)
    inverse_ref = {path: ref for ref, path in refs.items()}

    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}

        notes_path = todo.path / "notes.md"
        notes_content = ""
        if notes_path.exists():
            notes_content = notes_path.read_text()

        result = todo_to_dict(todo, inverse_ref.get(path, ""))
        result["notes"] = notes_content
        result["history"] = read_history(path)
        result["success"] = True
        return result
    except ValueError as e:
        return {"success": False, "error": str(e)}


def ops_status(identifiers: list[str], new_status: str, note: str = "") -> dict:
    """Change status for one or more todos. Appends to each todo's history.log."""
    try:
        resolved = resolve_status(new_status)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    todos = load_todos()
    refs = build_reference_map(todos)
    results = []

    for identifier in identifiers:
        try:
            path = resolve_target(identifier, todos, refs)
            todo = todos.get(path)
            if not todo:
                results.append({"id": identifier, "success": False, "error": "Not found"})
                continue
            old_status = todo.status
            run_script("set_status", resolved.lower(), str(todo.path), quiet=True)

            # Clear flags when completing or cancelling
            if resolved in ("Done", "Cancelled"):
                for flag_file in path.glob("*.flag"):
                    flag_file.unlink()

            # Append-only status trail (only when the status actually changed)
            if old_status != resolved:
                append_history(path, resolved, note=note)

            results.append({
                "id": todo.name, "success": True,
                "old_status": old_status, "new_status": resolved
            })
        except (ValueError, subprocess.CalledProcessError) as e:
            results.append({"id": identifier, "success": False, "error": str(e)})

    return {"success": all(r["success"] for r in results), "results": results}


def ops_flag(action: str, identifier: str, flag_name: str) -> dict:
    """Add or remove a flag. action: 'add' or 'remove'."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}

        flag_slug = re.sub(r'[^a-z0-9_]+', '_', flag_name.lower()).strip('_')
        if not flag_slug:
            return {"success": False, "error": "Invalid flag name"}

        if action == "add":
            if flag_slug in todo.flags:
                return {"success": True, "todo_id": todo.name, "flag": flag_slug, "already_exists": True}
            run_script("add_flag", flag_slug, str(todo.path), quiet=True)
        elif action == "remove":
            if flag_slug not in todo.flags:
                return {"success": True, "todo_id": todo.name, "flag": flag_slug, "not_found": True}
            run_script("remove_flag", flag_slug, str(todo.path), quiet=True)
        else:
            return {"success": False, "error": f"Invalid action: {action}. Use 'add' or 'remove'."}

        return {"success": True, "todo_id": todo.name, "action": action, "flag": flag_slug}
    except (ValueError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


def ops_tag(action: str, identifier: str, tag_name: str) -> dict:
    """Add or remove a tag. action: 'add' or 'remove'."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}

        tag_slug = re.sub(r'[^a-z0-9_]+', '_', tag_name.lower()).strip('_')
        if not tag_slug:
            return {"success": False, "error": "Invalid tag name"}

        if action == "add":
            if tag_slug in todo.tags:
                return {"success": True, "todo_id": todo.name, "tag": tag_slug, "already_exists": True}
            run_script("add_tag", tag_slug, str(todo.path), quiet=True)
        elif action == "remove":
            if tag_slug not in todo.tags:
                return {"success": True, "todo_id": todo.name, "tag": tag_slug, "not_found": True}
            run_script("remove_tag", tag_slug, str(todo.path), quiet=True)
        else:
            return {"success": False, "error": f"Invalid action: {action}. Use 'add' or 'remove'."}

        return {"success": True, "todo_id": todo.name, "action": action, "tag": tag_slug}
    except (ValueError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


def ops_assign(identifier: str, uri: str) -> dict:
    """Assign a URI to a todo."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}
        msg = _assign_todo(path, uri)
        already = "Already assigned" in msg
        return {"success": True, "todo_id": todo.name, "uri": uri, "message": msg, "already_assigned": already}
    except ValueError as e:
        return {"success": False, "error": str(e)}


def ops_unassign(identifier: str, uri: str) -> dict:
    """Remove a URI assignment from a todo."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}
        msg = _unassign_todo(path, uri)
        not_assigned = "Not assigned" in msg
        return {"success": True, "todo_id": todo.name, "uri": uri, "message": msg, "not_assigned": not_assigned}
    except ValueError as e:
        return {"success": False, "error": str(e)}


def ops_assigned(identifier: str) -> dict:
    """List current assignments for a todo."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}
        return {"success": True, "todo_id": todo.name, "assigned": todo.assigned}
    except ValueError as e:
        return {"success": False, "error": str(e)}


def verify_todo(todo_path: Path, expected: dict) -> dict:
    """Read-back verification of a todo against expected state.

    Args:
        todo_path: Path to the todo directory.
        expected: Dict with expected values. Keys: status, tags, flags, parent_name.

    Returns:
        Dict with verified (bool) and mismatches (list of strings).
    """
    mismatches = []

    if not todo_path.is_dir():
        return {"verified": False, "mismatches": ["directory does not exist"]}

    notes_path = todo_path / "notes.md"
    if not notes_path.exists():
        mismatches.append("notes.md missing")
    elif notes_path.stat().st_size == 0:
        mismatches.append("notes.md is empty")
    else:
        content = notes_path.read_text()
        for placeholder in ("__DATE__", "__TODO_NAME__", "__TASK_NAME__"):
            if placeholder in content:
                mismatches.append(f"unresolved template placeholder: {placeholder}")

    # Check status file
    status_files = list(todo_path.glob("*.status"))
    if not status_files:
        mismatches.append("no .status file")
    elif len(status_files) > 1:
        mismatches.append(f"multiple .status files: {[f.name for f in status_files]}")
    elif "status" in expected:
        actual_status = status_files[0].stem
        expected_status = expected["status"]
        if actual_status.lower() != expected_status.lower():
            mismatches.append(f"status: expected '{expected_status}', got '{actual_status}'")

    # Check tags
    if "tags" in expected:
        actual_tags = sorted(f.stem for f in todo_path.glob("*.tag"))
        expected_tags = sorted(expected["tags"])
        if actual_tags != expected_tags:
            mismatches.append(f"tags: expected {expected_tags}, got {actual_tags}")

    # Check flags
    if "flags" in expected:
        actual_flags = sorted(f.stem for f in todo_path.glob("*.flag"))
        expected_flags = sorted(expected["flags"])
        if actual_flags != expected_flags:
            mismatches.append(f"flags: expected {expected_flags}, got {actual_flags}")

    # Check owner / project (origin.yml) — only when the caller specifies them
    if "owner" in expected or "project" in expected:
        origin = read_origin(todo_path)
        if "owner" in expected:
            actual_owner = str(origin.get("owner") or "")
            if actual_owner != str(expected["owner"] or ""):
                mismatches.append(f"owner: expected '{expected['owner']}', got '{actual_owner}'")
        if "project" in expected:
            actual_project = str(origin.get("project") or "")
            if actual_project != str(expected["project"] or ""):
                mismatches.append(f"project: expected '{expected['project']}', got '{actual_project}'")

    return {"verified": len(mismatches) == 0, "mismatches": mismatches}


def ops_create(
    name: str,
    parent: str = ".",
    status: str = "triaging",
    tags: list[str] | None = None,
    flags: list[str] | None = None,
    description: str = "",
    owner: str = "",
    project: str = "",
    source: str = "agent",
    created_by: str = "",
) -> dict:
    """Create a new (rich) todo. Returns created todo dict with verification.

    `parent` keeps its existing meaning (physical directory nesting — the single
    source of truth for grouping). `owner` (WHO executes) and `project` (WHAT
    scope) are independent optional origin.yml fields.
    """
    if not name or not name.strip():
        return {"success": False, "error": "Name required"}

    try:
        todos = load_todos()
        refs = build_reference_map(todos)

        # Resolve parent
        if parent in (".", "/", "root"):
            parent_dir = CURRENT_ROOT
        else:
            parent_dir = resolve_target(parent, todos, refs)

        new_path = create_todo_from_template(name, parent_dir)

        # Set status (uses resolve_status to handle codes like 'RD')
        resolved = resolve_status(status)
        if resolved != "Triaging":
            run_script("set_status", resolved.lower(), str(new_path), quiet=True)

        # Add tags
        for tag in (tags or []):
            tag_slug = re.sub(r'[^a-z0-9_]+', '_', tag.lower()).strip('_')
            if tag_slug:
                run_script("add_tag", tag_slug, str(new_path), quiet=True)

        # Add flags
        for flag in (flags or []):
            flag_slug = re.sub(r'[^a-z0-9_]+', '_', flag.lower()).strip('_')
            if flag_slug:
                run_script("add_flag", flag_slug, str(new_path), quiet=True)

        # Set description
        if description:
            notes_path = new_path / "notes.md"
            if notes_path.exists():
                update_notes_section(notes_path, "Description", description)

        # Provenance / ownership (origin.yml) + initial history trail.
        init_origin(new_path, created_by=created_by, source=source,
                    owner=owner, project=project)
        append_history(new_path, resolved,
                       session=created_by or current_session(),
                       note=f"created via {source}")

        # Build expected state for verification
        resolved_status = resolve_status(status)
        expected_tags = sorted(
            re.sub(r'[^a-z0-9_]+', '_', t.lower()).strip('_')
            for t in (tags or []) if re.sub(r'[^a-z0-9_]+', '_', t.lower()).strip('_')
        )
        expected_flags = sorted(
            re.sub(r'[^a-z0-9_]+', '_', f.lower()).strip('_')
            for f in (flags or []) if re.sub(r'[^a-z0-9_]+', '_', f.lower()).strip('_')
        )
        expected = {"status": resolved_status, "tags": expected_tags, "flags": expected_flags}
        if owner:
            expected["owner"] = owner
        if project:
            expected["project"] = project

        verification = verify_todo(new_path, expected)

        # Reload and return
        todos = load_todos()
        refs = build_reference_map(todos)
        inverse_ref = {p: r for r, p in refs.items()}
        todo = todos.get(new_path)

        return {
            "success": True,
            "todo": todo_to_dict(todo, inverse_ref.get(new_path, "")) if todo else {},
            "message": f"Created: {new_path.name}",
            "verification": verification,
        }
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


def ops_update(
    identifier: str,
    section: str,
    content: str,
) -> dict:
    """Update a section in a todo's notes.md.

    Args:
        identifier: Todo ID, number, or reference code
        section: Section heading (without ##), e.g. 'Description', 'Notes'
        content: New content for the section (replaces existing content)

    Returns:
        Result dict with success status
    """
    try:
        todos = load_todos()
        refs = build_reference_map(todos)
        target = resolve_target(identifier, todos, refs)
        notes_path = target / "notes.md"

        if not notes_path.exists():
            return {"success": False, "error": f"No notes.md found at {target}"}

        update_notes_section(notes_path, section, content)

        return {
            "success": True,
            "todo_id": target.name,
            "section": section,
            "message": f"Updated section '{section}' in {target.name}",
        }
    except (ValueError, OSError) as e:
        return {"success": False, "error": str(e)}


def ops_complete(identifier: str) -> dict:
    """Mark todo Done and move to completed/."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}

        run_script("set_status", "done", str(todo.path), quiet=True)

        # Append history before moving so the trail travels with the dir.
        if todo.status != "Done":
            append_history(path, "Done", note="completed")

        # Clear flags
        for flag_file in path.glob("*.flag"):
            flag_file.unlink()

        completed_dir = CURRENT_ROOT / "completed"
        completed_dir.mkdir(exist_ok=True)
        dest = completed_dir / todo.path.name
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = completed_dir / f"{todo.path.name}_{ts}"

        shutil.move(str(todo.path), str(dest))

        return {"success": True, "todo_id": todo.name, "moved_to": str(dest)}
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


def ops_trash(identifier: str) -> dict:
    """Move todo to trash/ (soft delete)."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)
        todo = todos.get(path)
        if not todo:
            return {"success": False, "error": f"Todo not found: {identifier}"}

        trash_dir = CURRENT_ROOT / "trash"
        trash_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = trash_dir / f"{todo.path.name}_{ts}"

        shutil.move(str(todo.path), str(dest))

        return {"success": True, "todo_id": todo.name, "moved_to": str(dest)}
    except (ValueError, OSError) as e:
        return {"success": False, "error": str(e)}


def ops_kanban(include_done: bool = False, include_cancelled: bool = False) -> dict:
    """Get kanban board as structured data."""
    todos = load_todos(include_completed=include_done or include_cancelled)
    refs = build_reference_map(todos)
    inverse_ref = {path: ref for ref, path in refs.items()}

    columns = {}
    for status_name, code in STATUS_ORDER:
        if status_name == "Done" and not include_done:
            continue
        if status_name == "Cancelled" and not include_cancelled:
            continue
        if status_name not in ACTIVE_STATUSES and not include_done and not include_cancelled:
            continue
        columns[code] = {"status": status_name, "todos": []}

    for path, todo in todos.items():
        code = STATUS_TO_CODE.get(todo.status)
        if code and code in columns:
            ref = inverse_ref.get(path, "")
            columns[code]["todos"].append({
                "ref": ref,
                "id": todo.name,
                "title": todo.title or todo.name,
                "flags": todo.flags,
                "tags": todo.tags[:3],
                "summary": todo.summary[:80] if todo.summary else "",
            })

    for col in columns.values():
        col["todos"].sort(key=lambda t: t["ref"])

    summary = {code: len(col["todos"]) for code, col in columns.items()}
    return {"columns": columns, "summary": summary, "total_active": sum(summary.values())}


def ops_validate() -> dict:
    """Validate the todo tree. Returns issues found.

    Checks:
    - Duplicate todo IDs (same directory name under different parents)
    - Missing .status files
    - Multiple .status files
    - Completed todos still in the active directory tree
    - Orphaned children (parent dir doesn't exist or isn't a todo)
    """
    todos = load_todos(include_completed=True, include_trash=True)
    issues: list[dict] = []

    # Build name -> paths map for duplicate detection
    name_to_paths: dict[str, list[Path]] = {}
    for path in todos:
        name = path.name
        name_to_paths.setdefault(name, []).append(path)

    # Check duplicates
    for name, paths in name_to_paths.items():
        if len(paths) > 1:
            locations = [str(p.relative_to(CURRENT_ROOT)) for p in paths]
            issues.append({
                "type": "duplicate_id",
                "id": name,
                "locations": locations,
                "message": f"Duplicate todo ID '{name}' found in {len(paths)} locations",
            })

    # Per-todo checks
    for path, todo in todos.items():
        rel = str(path.relative_to(CURRENT_ROOT))

        # Missing status
        status_files = list(path.glob("*.status"))
        if not status_files:
            issues.append({
                "type": "missing_status",
                "id": todo.name,
                "path": rel,
                "message": f"No .status file in {rel}",
            })
        elif len(status_files) > 1:
            issues.append({
                "type": "multiple_status",
                "id": todo.name,
                "path": rel,
                "statuses": [f.stem for f in status_files],
                "message": f"Multiple .status files in {rel}: {[f.stem for f in status_files]}",
            })

        # Completed todo in active tree (not under completed/ or trash/)
        if todo.status in ("Done", "Cancelled"):
            parts = path.relative_to(CURRENT_ROOT).parts
            if "completed" not in parts and "trash" not in parts:
                issues.append({
                    "type": "completed_in_active",
                    "id": todo.name,
                    "path": rel,
                    "status": todo.status,
                    "message": f"{todo.status} todo '{todo.name}' is still in the active tree at {rel}",
                })

    return {
        "valid": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
    }


def ops_move(identifier: str, new_parent: str) -> dict:
    """Move todo to new parent."""
    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        source = resolve_target(identifier, todos, refs)

        if new_parent.lower() in ("root", ".", "/"):
            new_parent_path = CURRENT_ROOT
        else:
            new_parent_path = resolve_target(new_parent, todos, refs)

        dest = new_parent_path / source.name
        if dest.exists():
            return {"success": False, "error": f"Destination already exists: {dest.relative_to(CURRENT_ROOT)}"}

        shutil.move(str(source), str(dest))
        return {
            "success": True,
            "todo_id": source.name,
            "new_location": str(dest.relative_to(CURRENT_ROOT)),
        }
    except (ValueError, OSError) as e:
        return {"success": False, "error": str(e)}


def ops_duplicate(identifier: str, new_name: str) -> dict:
    """Duplicate a todo with a new name."""
    if not new_name or not new_name.strip():
        return {"success": False, "error": "New name required"}

    todos = load_todos()
    refs = build_reference_map(todos)
    try:
        path = resolve_target(identifier, todos, refs)

        new_dir = path.parent / f"todo_{new_name}"
        if new_dir.exists():
            return {"success": False, "error": f"Already exists: {new_dir.name}"}

        shutil.copytree(path, new_dir, symlinks=True)

        # Update notes.md
        notes_path = new_dir / "notes.md"
        if notes_path.exists():
            text = notes_path.read_text()
            today = datetime.now().strftime("%Y-%m-%d")
            text = text.replace(path.name, new_name, 1)
            text = re.sub(r'\*\*Created:\*\* .+', f'**Created:** {today}', text)
            text = re.sub(r'\*\*Updated:\*\* .+', f'**Updated:** {today}', text)
            notes_path.write_text(text)

        run_script("set_status", "triaging", str(new_dir), quiet=True)

        # Reload and return
        todos = load_todos()
        refs = build_reference_map(todos)
        inverse_ref = {p: r for r, p in refs.items()}
        todo = todos.get(new_dir)

        return {
            "success": True,
            "todo": todo_to_dict(todo, inverse_ref.get(new_dir, "")) if todo else {},
            "message": f"Duplicated: {new_dir.relative_to(CURRENT_ROOT)}",
        }
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        return {"success": False, "error": str(e)}


# === Commands ===

def cmd_kanban(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Show kanban board. Use --all to include Done/Cancelled."""
    include_done = "--all" in args or "--done" in args
    include_cancelled = "--all" in args or "--cancelled" in args
    if include_done or include_cancelled:
        todos = load_todos(include_completed=True)
    return render_kanban(todos, include_done=include_done, include_cancelled=include_cancelled)


def cmd_tree(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Show tree view of todo hierarchy. Use --all to include Done/Cancelled."""
    include_done = "--all" in args or "--done" in args
    return render_tree(todos, include_done=include_done)


def cmd_list(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """List todos, optionally filtered by status.

    Args:
        args: Command arguments. Supports status filter, --sort, and --flat.
        todos: Dict of path to Todo objects.
        refs: Reference map.

    Returns:
        Formatted table string.
    """
    status_filter = None
    sort_key = "name"
    flat = False
    show_dates = False
    show_all = False
    show_done = False
    show_cancelled = False
    name_pattern = None
    assigned_filter = None

    # Parse args
    positional_args = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--sort="):
            sort_key = arg.split("=", 1)[1]
        elif arg == "--sort" and i + 1 < len(args):
            i += 1
            sort_key = args[i]
        elif arg == "--flat":
            flat = True
        elif arg in ("--show-dates", "--dates"):
            show_dates = True
        elif arg == "--all":
            show_all = True
        elif arg == "--done":
            show_done = True
        elif arg == "--cancelled":
            show_cancelled = True
        elif arg == "--assigned" and i + 1 < len(args):
            i += 1
            assigned_filter = args[i]
        elif not arg.startswith("--"):
            positional_args.append(arg)
        i += 1

    # Validate sort key
    valid_sorts = ("name", "id", "status", "created", "updated", "ref", "flags")
    if sort_key == "id":
        sort_key = "name"  # "id" and "name" both sort by todo directory name
    if sort_key not in valid_sorts:
        return c(f"Unknown sort key: {sort_key}. Valid: {', '.join(valid_sorts)}", Colors.RED)

    # Auto-show dates when sorting by date fields
    if sort_key in ("created", "updated"):
        show_dates = True

    # Classify positional args as status filter or name pattern
    for pos_arg in positional_args:
        if "*" in pos_arg or "?" in pos_arg:
            name_pattern = pos_arg
        elif status_filter is None:
            status_filter = pos_arg

    # Reload with completed/ if needed
    needs_completed = show_all or show_done
    if status_filter and not needs_completed:
        try:
            needs_completed = resolve_status(status_filter) in ("Done", "Cancelled")
        except ValueError:
            pass
    if needs_completed:
        todos = load_todos(include_completed=True)

    # Apply status filter
    if status_filter:
        sf = status_filter.lower()
        if sf.upper() in STATUS_CODES:
            sf = STATUS_CODES[sf.upper()].lower()
        filtered = [t for t in todos.values() if t.status.lower() == sf]
    elif show_all:
        filtered = list(todos.values())
    else:
        excluded = set()
        if not show_done:
            excluded.add("Done")
        if not show_cancelled:
            excluded.add("Cancelled")
        filtered = [t for t in todos.values() if t.status not in excluded]

    # Apply name pattern filter
    if name_pattern:
        filtered = [t for t in filtered
                    if fnmatch.fnmatch(t.name.lower(), name_pattern.lower())]

    # Apply assigned URI filter
    if assigned_filter:
        filtered = [t for t in filtered if assigned_filter in t.assigned]

    return format_table(filtered, sort_key=sort_key, indent_children=not flat,
                        show_dates=show_dates)


def _find_all_matches(token: str, todos: dict[Path, Todo], refs: dict[str, Path]) -> list[Path]:
    """Find ALL todos matching a token, not just the first.

    Used by cmd_view to surface duplicate IDs.
    """
    matches = []
    # Reference code — unique by definition
    upper = token.upper()
    if upper in refs:
        return [refs[upper]]

    # Name / number matching — collect all
    for path in todos:
        name = path.name
        if name == token:
            matches.append(path)
        elif name == f"todo_{token}" or name == f"task_{token}":
            matches.append(path)
        elif token.isdigit():
            num_str = token.zfill(4)
            if name.startswith(f"todo_{num_str}_") or name.startswith(f"task_{num_str}_"):
                matches.append(path)

    if matches:
        return matches

    # Partial / substring match
    lower = token.lower()
    for path in todos:
        if lower in path.name.lower():
            matches.append(path)
    return matches


def cmd_view(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """View detailed info about a todo. Searches completed/trash if not found in active."""
    if not args:
        return c("Usage: view <ref|path>", Colors.RED)

    # Check for duplicates by finding all matches
    all_todos = load_todos(include_completed=True, include_trash=True)
    all_refs = build_reference_map(all_todos)
    matches = _find_all_matches(args[0], all_todos, all_refs)

    if not matches:
        return c(f"Todo not found: {args[0]}", Colors.RED)

    if len(matches) == 1:
        todo = all_todos.get(matches[0])
        if not todo:
            return c(f"Todo not in cache: {args[0]}", Colors.RED)
        return view_todo_detail(todo, all_refs, all_todos)

    # Multiple matches — show all with duplicate warning
    parts = [c(f"Found {len(matches)} todos matching '{args[0]}':", Colors.YELLOW), ""]
    for i, path in enumerate(matches, 1):
        todo = all_todos.get(path)
        if todo:
            rel = str(path.relative_to(CURRENT_ROOT))
            parts.append(c(f"--- Match {i}: {rel} ---", Colors.CYAN))
            parts.append(view_todo_detail(todo, all_refs, all_todos))
            parts.append("")
    return "\n".join(parts)


def cmd_status(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Change todo status. Usage: status <new_status> <ref> [ref2 ...] [--note <text>]"""
    # Extract optional --note <text> (so transitions can be annotated in history.log)
    note = ""
    if "--note" in args:
        i = args.index("--note")
        note = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]

    if len(args) < 2:
        return c("Usage: status <new_status> <ref> [ref2 ...] [--note <text>]", Colors.RED)

    # First arg is the status, remaining are identifiers
    new_status_input = args[0]
    identifiers = args[1:]

    try:
        resolved = resolve_status(new_status_input)
    except ValueError as e:
        return c(str(e), Colors.RED)

    results = []
    for identifier in identifiers:
        try:
            path = resolve_target(identifier, todos, refs)
            # Capture the prior status so we only record a history entry on a real change
            existing_status = next((p.stem for p in path.glob("*.status")), None)
            run_script("set_status", resolved.lower(), str(path))

            # Append-only history on an actual transition
            if existing_status != resolved:
                append_history(path, resolved, note=note)

            # Clear flags when completing or cancelling
            if resolved in ("Done", "Cancelled"):
                for flag_file in path.glob("*.flag"):
                    flag_file.unlink()

            results.append(c(f"  ✓ {path.name} → {resolved}", Colors.GREEN))
        except (ValueError, subprocess.CalledProcessError) as e:
            results.append(c(f"  ✗ {identifier}: {e}", Colors.RED))

    if len(results) == 1:
        return results[0].strip()
    return "\n".join(results)


def cmd_flag(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Add or remove flags. Usage: flag add|remove <ref> <flag_name>"""
    if len(args) < 3:
        return c("Usage: flag add|remove <ref> <flag_name>", Colors.RED)

    action, ref, flag_name = args[0], args[1], args[2]
    result = ops_flag(action, ref, flag_name)
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    if result.get("already_exists"):
        return c(f"Flag already exists: {result['flag']} on {result['todo_id']}", Colors.YELLOW)
    if result.get("not_found"):
        return c(f"Flag not present: {result['flag']} on {result['todo_id']}", Colors.YELLOW)
    return c(f"Flag {action}ed: {result['flag']} on {result['todo_id']}", Colors.GREEN)


def cmd_tag(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Add or remove tags. Usage: tag add|remove <ref> <tag_name>"""
    if len(args) < 3:
        return c("Usage: tag add|remove <ref> <tag_name>", Colors.RED)

    action, ref, tag_name = args[0], args[1], args[2]
    result = ops_tag(action, ref, tag_name)
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    if result.get("already_exists"):
        return c(f"Tag already exists: {result['tag']} on {result['todo_id']}", Colors.YELLOW)
    if result.get("not_found"):
        return c(f"Tag not present: {result['tag']} on {result['todo_id']}", Colors.YELLOW)
    return c(f"Tag {action}ed: {result['tag']} on {result['todo_id']}", Colors.GREEN)


def cmd_assign(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Assign a URI to a todo. Usage: assign <ref> <uri>"""
    if len(args) < 2:
        return c("Usage: assign <ref> <uri>", Colors.RED)
    result = ops_assign(args[0], args[1])
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    if result.get("already_assigned"):
        return c(f"Already assigned: {result['uri']} on {result['todo_id']}", Colors.YELLOW)
    return c(f"Assigned: {result['uri']} to {result['todo_id']}", Colors.GREEN)


def cmd_unassign(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Remove a URI assignment from a todo. Usage: unassign <ref> <uri>"""
    if len(args) < 2:
        return c("Usage: unassign <ref> <uri>", Colors.RED)
    result = ops_unassign(args[0], args[1])
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    if result.get("not_assigned"):
        return c(f"Not assigned: {result['uri']} on {result['todo_id']}", Colors.YELLOW)
    return c(f"Unassigned: {result['uri']} from {result['todo_id']}", Colors.GREEN)


def cmd_assigned(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """List current assignments for a todo. Usage: assigned <ref>"""
    if not args:
        return c("Usage: assigned <ref>", Colors.RED)
    result = ops_assigned(args[0])
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    assigned = result["assigned"]
    if not assigned:
        return c(f"No assignments for {result['todo_id']}", Colors.DIM)
    lines = [c(f"Assignments for {result['todo_id']}:", Colors.BOLD)]
    for uri in assigned:
        lines.append(f"  {c(uri, Colors.CYAN)}")
    return "\n".join(lines)


def cmd_create_light(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """create-light <name> [--summary s] [--status s] [--owner id] [--project id] [--source src]"""
    if not args:
        return c("Usage: create-light <name> [--summary <s>] [--status <s>] "
                 "[--owner <id>] [--project <id>] [--source agent|backfill|manual]", Colors.RED)
    name = args[0]
    rest = list(args[1:])
    summary = _pop_flag(rest, "--summary") or ""
    status = _pop_flag(rest, "--status") or "triaging"
    owner = _pop_flag(rest, "--owner") or ""
    project = _pop_flag(rest, "--project") or ""
    source = _pop_flag(rest, "--source") or "agent"
    created_by = _pop_flag(rest, "--by") or ""
    result = ops_create_light(name=name, summary=summary, status=status,
                              owner=owner, project=project, source=source,
                              created_by=created_by)
    if result["success"]:
        return c(f"✓ {result['message']}", Colors.GREEN)
    return c(f"Error: {result['error']}", Colors.RED)


def cmd_owner(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """owner <ref> [<owner-id> | --clear]  — show, set, or clear the single owner."""
    if not args:
        return c("Usage: owner <ref> <owner-id>  |  owner <ref> --clear", Colors.RED)
    identifier = args[0]
    if len(args) >= 2 and args[1] in ("--clear", "clear"):
        result = ops_clear_owner(identifier)
        if result["success"]:
            return c(f"✓ Owner cleared on {result['todo_id']} "
                     f"(was {result.get('previous_owner')})", Colors.GREEN)
        return c(f"Error: {result['error']}", Colors.RED)
    if len(args) >= 2:
        result = ops_set_owner(identifier, args[1])
        if result["success"]:
            return c(f"✓ Owner of {result['todo_id']} set to {result['owner']}", Colors.GREEN)
        return c(f"Error: {result['error']}", Colors.RED)
    # show
    info = ops_get(identifier)
    if not info.get("success"):
        return c(f"Error: {info.get('error')}", Colors.RED)
    return f"Owner of {info['id']}: {info.get('owner') or c('(unowned)', Colors.DIM)}"


def cmd_project(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """project <ref> [<project-id> | --clear]  — show, set, or clear the project/scope.

    Project is SEPARATE from owner: owner = WHO executes, project = WHAT scope.
    (Parent/child grouping is physical directory nesting — use `move`, not this.)
    """
    if not args:
        return c("Usage: project <ref> <project-id>  |  project <ref> --clear", Colors.RED)
    identifier = args[0]
    if len(args) >= 2 and args[1] in ("--clear", "clear"):
        result = ops_clear_project(identifier)
        if result["success"]:
            return c(f"✓ Project cleared on {result['todo_id']} "
                     f"(was {result.get('previous_project')})", Colors.GREEN)
        return c(f"Error: {result['error']}", Colors.RED)
    if len(args) >= 2:
        result = ops_set_project(identifier, args[1])
        if result["success"]:
            return c(f"✓ Project of {result['todo_id']} set to {result['project']}", Colors.GREEN)
        return c(f"Error: {result['error']}", Colors.RED)
    info = ops_get(identifier)
    if not info.get("success"):
        return c(f"Error: {info.get('error')}", Colors.RED)
    return f"Project of {info['id']}: {info.get('project') or c('(none)', Colors.DIM)}"


def cmd_history(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """history <ref>  — show the append-only status trail."""
    if not args:
        return c("Usage: history <ref>", Colors.RED)
    result = ops_history(args[0])
    if not result["success"]:
        return c(f"Error: {result['error']}", Colors.RED)
    entries = result["history"]
    if not entries:
        return c(f"No history for {result['todo_id']}", Colors.DIM)
    lines = [c(f"History — {result['todo_id']}", Colors.BOLD)]
    for e in entries:
        status = colored_status(e["status"]) if e["status"] in STATUS_COLORS else e["status"]
        lines.append(f"  {c(e['ts'], Colors.DIM)}  {status}  "
                     f"{c(e['session'], Colors.CYAN)}  {e['note']}")
    return "\n".join(lines)


def get_next_todo_number() -> int:
    """Get the next available todo number by scanning all directories."""
    max_num = 0
    
    # Scan all directories (active, completed, trash) for todo_NNNN_* pattern
    for scan_dir in [CURRENT_ROOT, CURRENT_ROOT / "completed", CURRENT_ROOT / "trash"]:
        if not scan_dir.exists():
            continue
        for item in scan_dir.rglob("todo_*"):
            if item.is_dir():
                match = re.match(r"todo_(\d{4})_", item.name)
                if match:
                    num = int(match.group(1))
                    max_num = max(max_num, num)
    
    return max_num + 1


def create_todo_from_template(name: str, parent_dir: Path) -> Path:
    """Create a new todo directory from template with auto-numbering.
    
    Returns the path to the created todo directory.
    """
    # Get next number
    num = get_next_todo_number()
    
    # Slugify name
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9_]+', '_', slug)
    slug = re.sub(r'_+', '_', slug).strip('_')

    if not slug:
        raise ValueError("Invalid todo name - no valid characters")

    # Truncate slug to stay within filesystem NAME_MAX (255)
    prefix = f"todo_{num:04d}_"
    max_slug_len = 255 - len(prefix)
    if len(slug) > max_slug_len:
        slug = slug[:max_slug_len].rstrip('_')

    # Build directory name
    dir_name = f"{prefix}{slug}"
    target_dir = parent_dir / dir_name
    
    if target_dir.exists():
        raise ValueError(f"Directory already exists: {target_dir}")
    
    # Find template
    template_dir = None
    for tpl in get_template_dirs():
        if tpl.exists():
            template_dir = tpl
            break
    
    if not template_dir:
        # Create minimal structure if no template
        target_dir.mkdir(parents=True)
        (target_dir / "data").mkdir()
        (target_dir / "Triaging.status").touch()
        
        # Create basic notes.md
        display_name = name.replace("_", " ").title()
        today = datetime.now().strftime("%Y-%m-%d")
        notes_content = f"""# {display_name}

**Created:** {today}
**Updated:** {today}

## Description

## Requirements

## Done When

## Notes

"""
        (target_dir / "notes.md").write_text(notes_content)
    else:
        # Copy from template
        shutil.copytree(template_dir, target_dir, symlinks=True)

        # Remove stale scripts symlink if copied from template
        scripts_link = target_dir / "scripts"
        if scripts_link.is_symlink() or scripts_link.exists():
            scripts_link.unlink()

        # Update notes.md
        notes_path = target_dir / "notes.md"
        if notes_path.exists():
            display_name = name.replace("_", " ").title()
            today = datetime.now().strftime("%Y-%m-%d")
            
            content = notes_path.read_text()
            content = content.replace("__TODO_NAME__", display_name)
            content = content.replace("__TASK_NAME__", display_name)
            content = content.replace("__DATE__", today)

            # Remove HTML comment placeholders from template
            content = re.sub(r'\n*<!--\s*\n.*?\n-->\n*', '\n\n', content, flags=re.DOTALL)
            # Collapse excessive blank lines left by removal
            content = re.sub(r'\n{3,}', '\n\n', content)
            notes_path.write_text(content)
    
    # Ensure data directory and status file exist (required for loading)
    (target_dir / "data").mkdir(exist_ok=True)
    if not any(target_dir.glob("*.status")):
        (target_dir / "Triaging.status").touch()
    
    return target_dir


def cmd_create(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path], interactive: bool = True) -> str:
    """Create a new todo. Usage: create <name> [--parent <ref>] [--status <status>] [--tags t1,t2] [--flags f1,f2] [--owner <id>] [--project <scope>]"""
    if not args:
        if not interactive:
            return c("Usage: create <name> [--parent <ref>] [--status <status>] [--tags t1,t2] [--flags f1,f2] [--owner <id>] [--project <scope>]", Colors.RED)
        return create_todo_interactive()
    
    name = args[0]
    parent = "."
    status = "triaging"
    tags = []
    flags = []
    description = ""
    owner = ""
    project = ""
    unknown = []

    # Parse optional args
    i = 1
    while i < len(args):
        if args[i] == "--parent" and i + 1 < len(args):
            parent = args[i + 1]
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == "--tags" and i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--flags" and i + 1 < len(args):
            flags = [f.strip() for f in args[i + 1].split(",")]
            i += 2
        elif args[i] in ("--description", "-d") and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif args[i] == "--owner" and i + 1 < len(args):
            owner = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i].startswith("--"):
            unknown.append(args[i])
            i += 1
        else:
            i += 1

    result = ops_create(name=name, parent=parent, status=status,
                        tags=tags, flags=flags, description=description,
                        owner=owner, project=project)
    if result["success"]:
        lines = [c(f"✓ {result['message']}", Colors.GREEN)]
        if unknown:
            lines.append(c(f"  ⚠ Ignored unknown flags: {' '.join(unknown)}", Colors.YELLOW))
        v = result.get("verification", {})
        if v.get("verified"):
            lines.append(c("  ✓ Verified: all fields match", Colors.DIM))
        elif v.get("mismatches"):
            lines.append(c("  ⚠ Verification mismatches:", Colors.YELLOW))
            for m in v["mismatches"]:
                lines.append(c(f"    - {m}", Colors.YELLOW))
        return "\n".join(lines)
    return c(f"Error: {result['error']}", Colors.RED)


def create_todo_interactive() -> str:
    """Interactive todo creation wizard."""
    print(c("\n=== Create New Todo ===", Colors.BOLD))

    name = input(f"  {c('Name:', Colors.CYAN)} ").strip()
    if not name:
        return c("Cancelled - name required", Colors.YELLOW)

    parent = input(f"  {c('Parent (blank for root):', Colors.CYAN)} ").strip() or "."

    # Show available statuses
    print(c("  Available statuses:", Colors.DIM))
    for status_name, code in STATUS_ORDER:
        print(f"    {c(code, Colors.CYAN)}: {status_name}")
    status = input(f"  {c('Status [triaging]:', Colors.CYAN)} ").strip() or "triaging"

    # Show existing tags in use
    todos = load_todos()
    all_tags = set()
    for t in todos.values():
        all_tags.update(t.tags)
    if all_tags:
        print(c(f"  Existing tags: {', '.join(sorted(all_tags))}", Colors.DIM))
    tags = input(f"  {c('Tags (comma separated):', Colors.CYAN)} ").strip()
    flags = input(f"  {c('Flags (comma separated):', Colors.CYAN)} ").strip()
    description = input(f"  {c('Description (optional):', Colors.CYAN)} ").strip()

    args = [name]
    if parent and parent != ".":
        args.extend(["--parent", parent])
    if status:
        args.extend(["--status", status])
    if tags:
        args.extend(["--tags", tags])
    if flags:
        args.extend(["--flags", flags])
    if description:
        args.extend(["--description", description])
    
    refs = build_reference_map(todos)
    return cmd_create(args, todos, refs, interactive=False)


def cmd_move(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Move todo(s) to target. Usage: move <target|root> <ref1> [ref2...]

    Use 'root', '.', or '/' as target to move to root level (unparent).
    """
    if len(args) < 2:
        return c("Usage: move <target|root> <ref1> [ref2...]", Colors.RED)

    target = args[0]
    sources = args[1:]
    lines = []
    for src in sources:
        result = ops_move(src, target)
        if result["success"]:
            lines.append(c(f"Moved: {result['todo_id']} → {result['new_location']}", Colors.GREEN))
        else:
            lines.append(c(f"Error ({src}): {result['error']}", Colors.RED))
    return "\n".join(lines)


def cmd_link(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Create symlink relationship between todos. Usage: link <source> <target> [label]
    
    Creates a symlink in source's data/ directory pointing to target.
    Unlike move, this creates a relationship without changing hierarchy.
    """
    if len(args) < 2:
        return c("Usage: link <source> <target> [label]", Colors.RED)
    
    try:
        source = resolve_target(args[0], todos, refs)
        target = resolve_target(args[1], todos, refs)
        label = args[2] if len(args) > 2 else target.name
        
        data_dir = source / "data"
        data_dir.mkdir(exist_ok=True)
        
        link_path = data_dir / label
        if link_path.exists():
            return c(f"Link already exists: {link_path.relative_to(CURRENT_ROOT)}", Colors.YELLOW)
        
        relative_target = os.path.relpath(target, data_dir)
        link_path.symlink_to(relative_target)
        
        # Add note
        notes_path = source / "notes.md"
        if notes_path.exists():
            append_note(notes_path, f"Linked to {target.relative_to(CURRENT_ROOT)} via data/{label}")
        
        return c(f"Linked: {source.name} → {target.name}", Colors.GREEN)
    
    except (ValueError, OSError) as e:
        return c(f"Error: {e}", Colors.RED)


def append_note(notes_path: Path, note: str) -> None:
    """Append a timestamped note to notes.md."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"{timestamp}: {note}\n"
    with notes_path.open("a") as fh:
        fh.write(entry)


def cmd_edit(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Edit todo fields interactively. Usage: edit <ref> [field]
    
    Fields: title, description, status, tags, flags, requirements, done_when, notes
    """
    if not args:
        return c("Usage: edit <ref> [field]", Colors.RED)
    
    try:
        path = resolve_target(args[0], todos, refs)
        todo = todos.get(path)
        if not todo:
            return c(f"Todo not found: {args[0]}", Colors.RED)

        notes_path = path / "notes.md"

        # If specific field given, edit just that
        if len(args) > 1:
            field = args[1].lower()
            inline = " ".join(args[2:]) if len(args) > 2 else None
            if field in ("child", "c"):
                return edit_child(todo, todos, refs, inline)
            return edit_field(todo, field, notes_path, inline)

        # Otherwise show menu
        return edit_menu(todo, notes_path)
    
    except ValueError as e:
        return c(str(e), Colors.RED)


def edit_menu(todo: Todo, notes_path: Path) -> str:
    """Show interactive edit menu.

    Supports inline parameters: type 'g api' to add tag directly,
    's ready' to set status directly, etc.
    """
    while True:
        print(c(f"\n=== Edit: {todo.name} ===", Colors.BOLD))
        print()

        # Current values - strip HTML comments for display
        def _clean_section(name: str) -> str:
            raw = extract_section(notes_path, name).strip()
            cleaned = re.sub(r'<!--.*?-->', '', raw, flags=re.DOTALL).strip()
            result = cleaned[:80] or "(empty)"
            return result

        desc = _clean_section("Description")
        reqs = _clean_section("Requirements")
        done_when = _clean_section("Done When")

        # Field order matches view: title, status, flags, tags, then sections
        children_str = ", ".join(ch.name for ch in sorted(
            (todos[cp] for cp in todo.children if cp in todos),
            key=lambda t: t.name)) or "(none)"
        fields = [
            ("t", "title", todo.title),
            ("s", "status", todo.status),
            ("f", "flags", ", ".join(todo.flags) or "(none)"),
            ("g", "tags", ", ".join(todo.tags) or "(none)"),
            ("c", "child", children_str),
            ("d", "description", desc),
            ("r", "requirements", reqs),
            ("w", "done_when", done_when),
            ("n", "notes", "Add timestamped note"),
            ("o", "open", "Open notes.md in $EDITOR"),
        ]

        edit_val_w = max(60, shutil.get_terminal_size((120, 24)).columns - 30)
        edit_val_w = min(edit_val_w, 200)
        for key, name, value in fields:
            print(f"  {c(f'[{key}]', Colors.CYAN)} {name:<16} "
                  f"{c(str(value)[:edit_val_w], Colors.DIM)}")

        print()
        print(f"  {c('[q]', Colors.YELLOW)} quit editing")
        print()

        choice_raw = input("Edit field: ").strip()

        if not choice_raw or choice_raw.lower() in ("q", "quit"):
            break

        # Parse inline value (e.g., "g api" or "s ready")
        parts = choice_raw.split(None, 1)
        choice = parts[0].lower()
        inline_value = parts[1] if len(parts) > 1 else None

        for key, name, _ in fields:
            if choice == key or choice == name:
                if name == "open":
                    editor = os.environ.get("EDITOR", "nano")
                    subprocess.run([editor, str(notes_path)])
                    print(c("Opened in editor", Colors.GREEN))
                    # Reload todo after editor closes
                    todos = load_todos()
                    if todo.path in todos:
                        todo = todos[todo.path]
                    break
                elif name == "child":
                    result = edit_child(todo, todos, refs, inline_value)
                    print(result)
                    # Reload todo
                    todos = load_todos()
                    refs = build_reference_map(todos)
                    if todo.path in todos:
                        todo = todos[todo.path]
                        notes_path = todo.path / "notes.md"
                    break
                else:
                    result = edit_field(todo, name, notes_path, inline_value)
                    print(result)
                    # Reload todo
                    todos = load_todos()
                    if todo.path in todos:
                        todo = todos[todo.path]
                        notes_path = todo.path / "notes.md"
                    else:
                        # Directory was renamed (title edit), paths are stale
                        return c("Done editing (directory renamed)", Colors.GREEN)
                break

    return c("Done editing", Colors.GREEN)


def input_with_prefill(prompt: str, prefill: str = "") -> str:
    """Prompt for input with a pre-filled editable default value.

    Args:
        prompt: The prompt string to display.
        prefill: Text to pre-populate in the input buffer.

    Returns:
        The user's input string.
    """
    def hook():
        readline.insert_text(prefill)
        readline.redisplay()
    readline.set_pre_input_hook(hook)
    try:
        result = input(prompt)
    finally:
        readline.set_pre_input_hook()
    return result


def edit_field(todo: Todo, field: str, notes_path: Path,
               inline_value: str = None) -> str:
    """Edit a specific field.

    Args:
        todo: The todo to edit.
        field: Field name to edit.
        notes_path: Path to notes.md.
        inline_value: Optional pre-provided value (from inline edit command).
    """
    if field == "title":
        print(f"  Current: {c(todo.title, Colors.DIM)}")
        new_val = inline_value or input_with_prefill("  New title: ", todo.title).strip()
        if new_val:
            update_notes_field(notes_path, "title", new_val)

            # Convert to slug and rename directory
            new_slug = new_val.lower()
            new_slug = re.sub(r'[^a-z0-9_]+', '_', new_slug)
            new_slug = re.sub(r'_+', '_', new_slug).strip('_')

            if new_slug:
                match = re.match(r'^((?:todo|task)_\d{4}_)', todo.path.name)
                if match:
                    prefix = match.group(1)
                    new_name = f"{prefix}{new_slug}"
                    new_path = todo.path.parent / new_name

                    if new_name != todo.path.name:
                        if new_path.exists():
                            return c(f"Title updated but rename skipped: "
                                     f"{new_name} already exists", Colors.YELLOW)
                        shutil.move(str(todo.path), str(new_path))
                        return c(f"Title updated and renamed: "
                                 f"{todo.path.name} -> {new_name}", Colors.GREEN)

            return c("Title updated", Colors.GREEN)

    elif field == "status":
        print(f"  Current: {colored_status(todo.status)}")
        if not inline_value:
            print(f"  Valid: {', '.join(s for s, _ in STATUS_ORDER)}")
        new_val = inline_value or input("  New status: ").strip()
        if new_val:
            if new_val.upper() in STATUS_CODES:
                new_val = STATUS_CODES[new_val.upper()]
            valid_statuses = {s.lower() for s, _ in STATUS_ORDER}
            if new_val.lower() not in valid_statuses:
                valid_list = ", ".join(s for s, _ in STATUS_ORDER)
                return c(f"Unknown status: {new_val}. Valid: {valid_list}",
                         Colors.RED)
            run_script("set_status", new_val.lower(), str(todo.path))
            return c(f"Status updated to {new_val}", Colors.GREEN)

    elif field == "tags":
        print(f"  Current: {', '.join(todo.tags) or '(none)'}")
        if not inline_value:
            print("  Enter tags (comma separated, prefix with - to remove):")
        new_val = inline_value or input("  Tags: ").strip()
        if new_val:
            for tag in new_val.split(","):
                tag = tag.strip()
                if tag.startswith("-"):
                    run_script("remove_tag", tag[1:], str(todo.path))
                elif tag:
                    run_script("add_tag", tag, str(todo.path))
            return c("Tags updated", Colors.GREEN)

    elif field == "flags":
        print(f"  Current: {', '.join(todo.flags) or '(none)'}")
        if not inline_value:
            print("  Enter flags (comma separated, prefix with - to remove):")
        new_val = inline_value or input("  Flags: ").strip()
        if new_val:
            for flag in new_val.split(","):
                flag = flag.strip()
                if flag.startswith("-"):
                    run_script("remove_flag", flag[1:], str(todo.path))
                elif flag:
                    run_script("add_flag", flag, str(todo.path))
            return c("Flags updated", Colors.GREEN)

    elif field in ("description", "requirements", "done_when"):
        section_name = {"description": "Description", "requirements": "Requirements",
                       "done_when": "Done When"}[field]
        current = extract_section(notes_path, section_name).strip()
        display = re.sub(r'<!--.*?-->', '', current, flags=re.DOTALL).strip()
        print(f"  Current {section_name}:")
        print(indent(display or "(empty)", "    "))
        print("  Enter new content (blank line to finish, 'keep' to cancel):")

        lines = []
        while True:
            line = input("  > ")
            if line.strip().lower() == "keep":
                return c("Cancelled", Colors.YELLOW)
            if line == "":
                break
            lines.append(line)

        if lines:
            update_notes_section(notes_path, section_name, "\n".join(lines))
            return c(f"{section_name} updated", Colors.GREEN)

    elif field == "notes":
        print("  Add a timestamped note:")
        new_val = inline_value or input("  Note: ").strip()
        if new_val:
            append_note(notes_path, new_val)
            return c("Note added", Colors.GREEN)

    return c("No changes made", Colors.YELLOW)


def edit_child(todo: Todo, todos: dict[Path, Todo],
               refs: dict[str, Path], inline_value: str = None) -> str:
    """Add a child to the current todo.

    With a value (ref or name of existing todo): moves that todo as a child.
    Without a value: creates a new child todo interactively.

    Args:
        todo: The parent todo.
        todos: All loaded todos.
        refs: Reference map.
        inline_value: Optional ref/name of existing todo to move as child.

    Returns:
        Status message string.
    """
    if inline_value:
        # Move existing todo as child of current
        try:
            child_path = resolve_target(inline_value, todos, refs)
            if child_path == todo.path:
                return c("Cannot make a todo its own child", Colors.RED)
            dest = todo.path / child_path.name
            if dest.exists():
                return c(f"Already exists: {child_path.name}", Colors.RED)
            shutil.move(str(child_path), str(dest))
            return c(f"Moved {child_path.name} as child of {todo.name}", Colors.GREEN)
        except ValueError as e:
            return c(str(e), Colors.RED)

    # No inline value — prompt for action
    print(f"  {c('[m]', Colors.CYAN)} Move existing todo as child")
    print(f"  {c('[n]', Colors.CYAN)} Create new child todo")
    action = input("  Action: ").strip().lower()

    if action in ("m", "move"):
        ref_input = input("  Todo ref to move: ").strip()
        if not ref_input:
            return c("Cancelled", Colors.YELLOW)
        try:
            child_path = resolve_target(ref_input, todos, refs)
            if child_path == todo.path:
                return c("Cannot make a todo its own child", Colors.RED)
            dest = todo.path / child_path.name
            if dest.exists():
                return c(f"Already exists: {child_path.name}", Colors.RED)
            shutil.move(str(child_path), str(dest))
            return c(f"Moved {child_path.name} as child of {todo.name}", Colors.GREEN)
        except ValueError as e:
            return c(str(e), Colors.RED)

    elif action in ("n", "new", "create"):
        child_name = input("  New child name: ").strip()
        if not child_name:
            return c("Cancelled", Colors.YELLOW)
        try:
            new_path = create_todo_from_template(child_name, todo.path)
            return c(f"Created child: {new_path.name}", Colors.GREEN)
        except (ValueError, OSError) as e:
            return c(f"Error: {e}", Colors.RED)

    return c("Cancelled", Colors.YELLOW)


def update_notes_field(notes_path: Path, field: str, value: str) -> None:
    """Update a field in notes.md."""
    content = notes_path.read_text()
    
    if field == "title":
        # Replace first # heading
        content = re.sub(r'^# .+$', f'# {value}', content, count=1, flags=re.MULTILINE)
    
    notes_path.write_text(content)


def update_notes_section(notes_path: Path, section: str, new_content: str) -> None:
    """Update a section in notes.md.

    Args:
        notes_path: Path to the notes.md file.
        section: Section heading (without ##) to update.
        new_content: New content for the section.
    """
    lines = notes_path.read_text().splitlines()

    new_lines = []
    in_section = False
    section_written = False

    for line in lines:
        if line.strip() == f"## {section}":
            new_lines.append(line)
            new_lines.append("")
            new_lines.append(new_content)
            new_lines.append("")
            in_section = True
            section_written = True
            continue

        if in_section and line.startswith("## "):
            in_section = False

        if not in_section:
            new_lines.append(line)

    # If section didn't exist, append it
    if not section_written:
        new_lines.append("")
        new_lines.append(f"## {section}")
        new_lines.append("")
        new_lines.append(new_content)
        new_lines.append("")

    notes_path.write_text("\n".join(new_lines))


def cmd_validate(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Validate the todo tree and report issues."""
    result = ops_validate()
    if result["valid"]:
        return c("No issues found.", Colors.GREEN)
    lines = [c(f"Found {result['issue_count']} issue(s):", Colors.YELLOW), ""]
    for issue in result["issues"]:
        icon = {"duplicate_id": "DUP", "missing_status": "NO_STATUS",
                "multiple_status": "MULTI_STATUS", "completed_in_active": "MISPLACED"
                }.get(issue["type"], issue["type"])
        lines.append(f"  [{c(icon, Colors.RED)}] {issue['message']}")
    return "\n".join(lines)


def cmd_complete(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Mark todo as Done and move to completed/. Usage: complete <ref>"""
    if not args:
        return c("Usage: complete <ref>", Colors.RED)

    result = ops_complete(args[0])
    if result["success"]:
        return c(f"Completed: {result['todo_id']} → completed/", Colors.GREEN)
    return c(f"Error: {result['error']}", Colors.RED)


def cmd_delete(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path], interactive: bool = True) -> str:
    """Move todo to trash/. Usage: delete <ref> [--force]

    Soft delete - moves to trash/ for potential recovery.
    Use 'purge' for permanent deletion.
    """
    if not args:
        return c("Usage: delete <ref> [--force]", Colors.RED)

    force = "--force" in args or "-f" in args
    ref_arg = [a for a in args if not a.startswith("-")][0]

    # Confirm unless forced (need to resolve name for prompt)
    if interactive and not force:
        try:
            path = resolve_target(ref_arg, todos, refs)
            confirm = input(f"  {c('Delete', Colors.YELLOW)} {path.name}? [y/N] ").strip().lower()
            if confirm not in ("y", "yes"):
                return c("Cancelled", Colors.DIM)
        except ValueError as e:
            return c(f"Error: {e}", Colors.RED)

    result = ops_trash(ref_arg)
    if result["success"]:
        return c(f"Deleted: {result['todo_id']} → trash/", Colors.YELLOW)
    return c(f"Error: {result['error']}", Colors.RED)


def cmd_purge(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path], interactive: bool = True) -> str:
    """Permanently delete todo. Usage: purge <ref> [--force]
    
    WARNING: This cannot be undone. Use 'delete' for soft delete to trash/.
    """
    if not args:
        return c("Usage: purge <ref> [--force]", Colors.RED)
    
    force = "--force" in args or "-f" in args
    ref_arg = [a for a in args if not a.startswith("-")][0]
    
    try:
        path = resolve_target(ref_arg, todos, refs)
        todo_name = path.name
        
        # Always confirm for purge unless forced
        if interactive and not force:
            print(c(f"  WARNING: Permanent deletion of {todo_name}", Colors.RED))
            confirm = input(f"  {c('Type the todo number to confirm:', Colors.YELLOW)} ").strip()
            # Extract number from name for confirmation
            import re
            match = re.search(r"todo_(\d+)_", todo_name)
            expected = match.group(1) if match else todo_name
            if confirm != expected:
                return c("Cancelled - confirmation did not match", Colors.DIM)
        
        shutil.rmtree(str(path))
        return c(f"Purged: {todo_name} (permanently deleted)", Colors.RED)
    
    except (ValueError, OSError) as e:
        return c(f"Error: {e}", Colors.RED)


def cmd_duplicate(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path], interactive: bool = True) -> str:
    """Duplicate a todo. Usage: duplicate <ref> [new_name]"""
    if not args:
        return c("Usage: duplicate <ref> [new_name]", Colors.RED)

    if len(args) > 1:
        new_name = args[1]
    elif interactive:
        new_name = input("New name (without prefix): ").strip()
    else:
        return c("New name required in non-interactive mode", Colors.RED)

    if not new_name:
        return c("Name required", Colors.YELLOW)

    result = ops_duplicate(args[0], new_name)
    if result["success"]:
        return c(f"Duplicated: {result['message']}", Colors.GREEN)
    return c(f"Error: {result['error']}", Colors.RED)


def cmd_json(args: list[str], todos: dict[Path, Todo], refs: dict[str, Path]) -> str:
    """Output todos as JSON."""
    result = ops_list(include_all="--all" in args)
    return json.dumps(result["todos"], indent=2)


# === Help System ===

HELP_OVERVIEW = """
{bold}todo_mgr{reset} - Interactive and CLI todo management (v{version})

{bold}USAGE:{reset}
    todo_mgr                      Interactive REPL mode
    todo_mgr <command> [args...]  One-shot CLI mode
    todo_mgr help [command]       Show help

{bold}COMMON COMMANDS:{reset}
    {cyan}kanban{reset}          Show kanban board (default view)
    {cyan}tree{reset}            Show hierarchical tree view
    {cyan}list{reset} [status] [pattern] [options]  List todos (--sort, --flat, --show-dates)
    {cyan}view{reset} <ref>      Show todo details
    {cyan}create{reset} <name>   Create new todo
    {cyan}status{reset} <r> <s>  Change todo status
    {cyan}edit{reset} <ref>      Interactive editor
    {cyan}move{reset} <target> <ref...>  Move todo(s) to target (or 'root')
    {cyan}assign{reset} <ref> <uri>  Assign a URI to a todo
    {cyan}unassign{reset} <ref> <uri>  Remove a URI assignment
    {cyan}assigned{reset} <ref>  List current assignments
    {cyan}complete{reset} <ref>  Mark done and archive
    {cyan}delete{reset} <ref>    Move to trash (alias: rm)
    {cyan}purge{reset} <ref>     Permanently delete (no recovery)

{bold}REFERENCE RESOLUTION:{reset}
    Todos can be referenced multiple ways (tried in order):
    1. Status code: IP1, RD2, TR3 (status prefix + number)
    2. Full path: todo_0038_tool_architecture
    3. Todo number: 0038 or 38 (matches todo_0038_*)
    4. Partial name: tool_arch (substring match)
    
    {dim}Status codes: TR=Triaging, NR=Needs_Research, ND=Needs_Derivation, RD=Ready
    IP=In_Progress, RV=Reviewing, AC=Accepting, BL=Blocked, DN=Done, CN=Cancelled{reset}

{bold}QUICK START:{reset}
    todo_mgr kanban              # See what's on your plate
    todo_mgr view IP1            # Details on first In_Progress
    todo_mgr status IP1 reviewing  # Move to reviewing
    todo_mgr help examples       # More examples
    todo_mgr help verbose        # Full command reference
"""

HELP_EXAMPLES = """
{bold}EXAMPLES{reset}

{bold}Viewing:{reset}
    kanban                   # Board view (excludes Done/Cancelled)
    kanban --all             # Board view with all statuses
    tree                     # Hierarchical tree view
    list                     # All active todos (children indented)
    list ready               # Only Ready todos
    list IP                  # Only In_Progress (by code)
    list --sort name         # Sort alphabetically by name
    list --sort created      # Sort by creation date
    list --flat              # Flat list (no child indentation)
    list --show-dates        # Show created/updated date columns
    list ready --sort name   # Filter + sort combined
    list '*memory*'          # Filter by name pattern (glob)
    list '*api*' --sort name # Pattern + sort combined
    view IP2                 # By reference code
    view 0038                # By todo number
    view tool_arch           # By partial name match
    json                     # Export all as JSON

{bold}Creating:{reset}
    create fix_login_bug                    # Interactive creation
    create fix_login_bug --status ready     # Skip to Ready
    create subtask --parent IP2             # Create as child of IP2
    create feature --tags api,backend --flags high_priority

{bold}Modifying:{reset}
    status IP2 reviewing           # Change status
    status IP2 RV                  # Same, using code
    flag add IP2 high_priority     # Add flag
    flag remove IP2 needs_testing  # Remove flag
    tag add IP2 api                # Add tag
    edit IP2                       # Interactive editor
    edit IP2 description           # Edit specific field

{bold}Work tracking (lightweight / origin):{reset}
    create-light fix_typo --summary "Fix typo in header" --owner sess_123
    create-light quick_idea --status ready --source manual
    owner TR5 sess_123             # Set single owner (origin.yml)
    owner TR5 --clear              # Clear owner (unowned)
    parent TR5 todo_0307           # Set logical work-group pointer
    parent TR5 --clear             # Clear group pointer
    history TR5                    # Show append-only status trail
    status TR5 in_progress         # Transition (auto-appends to history.log)

{bold}Assigning:{reset}
    assign IP2 uai://project/abc   # Assign URI to todo
    assigned IP2                   # List assignments
    unassign IP2 uai://project/abc # Remove assignment
    list --assigned uai://project/abc  # Filter by assignment

{bold}Organizing:{reset}
    move todo_0050_parent IP2      # Make IP2 a child of another todo
    move root IP2                  # Move IP2 back to root level
    move . IP2 IP3                 # Unparent multiple todos at once
    link IP2 RD1 related_work      # Create symlink relationship
    duplicate IP2 ip2_copy         # Copy todo

{bold}Completing:{reset}
    complete IP2                   # Mark done, move to completed/
    delete IP2                     # Move to trash/ (with confirmation)
    delete IP2 --force             # Move to trash/ (no confirmation)
    rm 0038                        # Alias for delete
    purge TR5                      # Permanent delete (requires confirmation)
    purge TR5 --force              # Permanent delete (skip confirmation)
"""

HELP_VERBOSE = """
{bold}COMMAND REFERENCE{reset}

{bold}DISPLAY COMMANDS{reset}

  {cyan}kanban{reset} [--all] [--done] [--cancelled]
      Show kanban board organized by status columns.
      By default, excludes Done and Cancelled statuses.
      --all        Include Done and Cancelled
      --done       Include only Done
      --cancelled  Include only Cancelled

  {cyan}tree{reset} [--all]
      Show hierarchical tree view of todos with parent/child relationships.
      --all        Include Done and Cancelled

  {cyan}list{reset} [status] [pattern] [--sort key] [--flat] [--show-dates]
      List todos as a table. Children are indented under parents.
      Optional status filter, name pattern (glob), sort key, --flat, --show-dates.
      Patterns use * and ? wildcards (e.g., *memory*, todo_00?? ).
      Dates shown automatically when sorting by created/updated.
      Examples: list, list ready, list --sort name, list '*memory*'

  {cyan}view{reset} <ref|path>
      Show detailed information about a specific todo including
      description, requirements, done criteria, and recent notes.

  {cyan}json{reset}
      Export all todos as JSON for programmatic access.

{bold}MODIFICATION COMMANDS{reset}

  {cyan}create{reset} <name> [--parent <ref>] [--status <s>] [--tags t1,t2] [--flags f1,f2] [--owner <id>] [--project <scope>]
      Create a new todo. In REPL mode without args, launches wizard.
      --parent     Create as child of another todo
      --status     Initial status (default: triaging)
      --tags       Comma-separated tags
      --flags      Comma-separated flags

  {cyan}status{reset} <ref> <new_status>
      Change todo status. Accepts full names or codes.
      Valid: Triaging, Needs_Research, Needs_Derivation, Ready,
             In_Progress, Reviewing, Accepting, Blocked, Done, Cancelled
      Codes: TR, NR, ND, RD, IP, RV, AC, BL, DN, CN

  {cyan}flag{reset} add|remove <ref> <flag_name>
      Add or remove a flag from a todo.
      Common flags: high_priority, needs_testing, blocked_by_other, quick_win

  {cyan}tag{reset} add|remove <ref> <tag_name>
      Add or remove a tag from a todo.
      Common tags: infrastructure, automation, bugfix, api, memory_system

  {cyan}edit{reset} <ref> [field]
      Interactive editor for todo fields.
      Fields: title, description, status, tags, flags, child, requirements, done_when, notes
      Without field arg, shows menu of all editable fields.
      Child: move existing todo as child, or create new child.

{bold}ASSIGNMENT COMMANDS{reset}

  {cyan}assign{reset} <ref> <uri>
      Assign a URI to a todo. Stored in assigned.yml.
      Multiple URIs can be assigned to one todo.
      Example: assign IP2 uai://project/abc

  {cyan}unassign{reset} <ref> <uri>
      Remove a URI assignment from a todo.
      Removes assigned.yml when empty (no leftover files).
      Example: unassign IP2 uai://project/abc

  {cyan}assigned{reset} <ref>
      List all current URI assignments for a todo.
      Example: assigned IP2

  {cyan}list{reset} --assigned <uri>
      Filter the list command to show only todos assigned to a URI.
      Example: list --assigned uai://project/abc

{bold}ORGANIZATION COMMANDS{reset}

  {cyan}move{reset} <target|root> <ref1> [ref2...]
      Move one or more todos to become children of target, or back to root level.
      Use 'root', '.', or '/' as target to move to root (unparent).

      {dim}move vs link:{reset}
      - move: Physically relocates the todo directory (changes hierarchy)
      - link: Creates a symlink relationship (todos stay in place)

  {cyan}link{reset} <source_ref> <target_ref> [label]
      Create a symlink in source's data/ directory pointing to target.
      Useful for cross-references without changing hierarchy.

  {cyan}duplicate{reset} <ref> [new_name]
      Create a copy of a todo with a new name.
      Resets status to Triaging and updates dates.

{bold}COMPLETION COMMANDS{reset}

  {cyan}complete{reset} <ref>
      Mark todo as Done and move to completed/ directory.

  {cyan}delete{reset} <ref> [--force]
      Move todo to trash/ directory (soft delete).
      --force    Skip confirmation prompt

{bold}SYSTEM COMMANDS{reset}

  {cyan}root{reset} [path]
      Show or change the TODO root directory.

  {cyan}reload{reset}
      Reload todo state from filesystem.

  {cyan}home{reset}
      Show kanban board and help summary (REPL default).

  {cyan}help{reset} [command|examples|verbose]
      Show help. 'help examples' for usage examples.
      'help verbose' for full command reference.
      'help <command>' for specific command help.

{bold}ENVIRONMENT{reset}

  TODO_ROOT    Override default todo directory
  NO_COLOR     Disable colored output
  EDITOR       Editor for 'edit ... open' command (default: nano)
"""

COMMAND_HELP = {
    "kanban": """
{bold}kanban{reset} [--all] [--done] [--cancelled]

Show kanban board organized by status columns.

By default, excludes Done and Cancelled to focus on active work.

{bold}Options:{reset}
    --all        Include Done and Cancelled columns
    --done       Include only Done column
    --cancelled  Include only Cancelled column

{bold}Examples:{reset}
    kanban           # Active todos only
    kanban --all     # Everything including archived
""",
    "list": """
{bold}list{reset} [status] [pattern] [--sort key] [--flat] [--show-dates]

List todos as a table with children indented under parents.

By default, excludes Done and Cancelled. Children of visible parents
are indented with a 2-space prefix to show hierarchy.

Supports glob patterns with * and ? wildcards to filter by name.

{bold}Options:{reset}
    --sort <key>    Sort by: name, status, created, updated, ref, flags
                    Default: status (then name within status)
    --flat          Disable child indentation (flat list)
    --show-dates    Show Created and Updated date columns
                    (automatic when --sort is created or updated)

{bold}Examples:{reset}
    list                     # Active todos, children indented
    list ready               # Only Ready status
    list IP                  # Only In_Progress (by code)
    list --sort name         # Sort alphabetically
    list --sort created      # Sort by creation date (dates shown)
    list --show-dates        # Show date columns
    list ready --sort name   # Filter and sort combined
    list '*memory*'          # Filter by name pattern
    list '*api*' --sort name # Pattern + sort
    list --flat              # No indentation
""",
    "ls": """
{bold}ls{reset} - Alias for {cyan}list{reset}. See: help list
""",
    "tree": """
{bold}tree{reset} [--all]

Show hierarchical tree view of todos.

Displays parent/child relationships visually. Useful for seeing
how subtasks relate to their parent todos.

{bold}Options:{reset}
    --all    Include Done and Cancelled todos

{bold}Example output:{reset}
    └── IP1 [IP] Parent Todo 🔥
        ├── IP2 [IP] Child One
        └── TR1 [TR] Child Two
""",
    "move": """
{bold}move{reset} <target|root> <ref1> [ref2...]

Move one or more todos to become children of target, or back to root.

This physically relocates the directory. The todo's path changes.

{bold}To move under a parent:{reset}
    move todo_0050_epic IP2       # IP2 becomes child of todo_0050_epic
    move todo_0050_epic IP2 IP3   # Move multiple at once

{bold}To move back to root (unparent):{reset}
    move root IP2    # Move to root level
    move . IP2       # Same
    move / IP2 IP3   # Unparent multiple

{bold}move vs link:{reset}
    move  - Changes directory location (hierarchy)
    link  - Creates symlink reference (no hierarchy change)
""",
    "link": """
{bold}link{reset} <source> <target> [label]

Create a symlink relationship between todos.

Creates a symlink in source's data/ directory pointing to target.
Unlike move, neither todo changes location.

{bold}Use cases:{reset}
    - Cross-reference related work
    - Track dependencies without hierarchy
    - Link to external todos

{bold}Example:{reset}
    link IP2 RD1 depends_on      # IP2/data/depends_on -> RD1
    link IP2 RD1                 # Uses target name as label
""",
    "edit": """
{bold}edit{reset} <ref> [field]

Interactive editor for todo fields.

Without a field argument, shows a menu of all editable fields
with current values and keyboard shortcuts.

{bold}Fields:{reset}
    [t] title         Title and directory slug (auto-renames directory)
    [s] status        Current status
    [f] flags         Workflow flags (comma separated)
    [g] tags          Domain tags (comma separated)
    [c] child         Add/move child todo
    [d] description   Main description text
    [r] requirements  Requirements section
    [w] done_when     Completion criteria
    [n] notes         Add a timestamped note
    [o] open          Open notes.md in $EDITOR

Supports inline values: type 's ready' to set status directly,
'g api,backend' to add tags, 'c IP3' to move IP3 as child, etc.

{bold}Examples:{reset}
    edit IP2              # Interactive menu
    edit IP2 status       # Edit just status
    edit IP2 s ready      # Set status directly
    edit IP2 g api        # Add tag directly
    edit IP2 c IP3        # Move IP3 as child of IP2
    edit IP2 tags         # Edit tags (prefix with - to remove)
""",
    "status": """
{bold}status{reset} <new_status> <ref> [ref2 ...]

Change the status of one or more todos.

Status comes first, then one or more todo references.
Accepts full status names or two-letter codes (case-insensitive).

{bold}Valid statuses:{reset}
    TR  Triaging          NR  Needs_Research
    ND  Needs_Derivation  RD  Ready
    IP  In_Progress       RV  Reviewing
    AC  Accepting         BL  Blocked
    DN  Done              CN  Cancelled

When status is set to Done or Cancelled, all flags are automatically cleared.

{bold}Examples:{reset}
    status reviewing IP2     # By full name
    status RV IP2            # By code
    status ready 0038        # By todo number
    status IP RD1 RD2 RD3    # Multiple todos at once
""",
    "view": """
{bold}view{reset} <ref|path>

Show detailed information about a specific todo.

Displays metadata (status, flags, tags, dates, parent, children)
and all populated sections from notes.md.

{bold}Examples:{reset}
    view IP2            # By reference code
    view 0038           # By todo number
    view tool_arch      # By partial name match
""",
    "complete": """
{bold}complete{reset} <ref>

Mark a todo as Done and move it to the completed/ directory.
All flags are automatically cleared on completion.

{bold}Examples:{reset}
    complete IP2        # By reference code
    complete 0038       # By todo number
""",
    "delete": """
{bold}delete{reset} <ref> [--force]

Move a todo to the trash/ directory (soft delete).
Can be recovered from trash/ if needed.

{bold}Options:{reset}
    --force, -f    Skip confirmation prompt

{bold}Examples:{reset}
    delete TR5            # With confirmation
    delete TR5 --force    # Skip confirmation
    rm 0038               # Alias for delete
""",
    "flag": """
{bold}flag{reset} add|remove <ref> <flag_name>

Add or remove a flag from a todo.

{bold}Common flags:{reset}
    high_priority, needs_testing, blocked_by_other, quick_win

{bold}Examples:{reset}
    flag add IP2 high_priority
    flag remove IP2 needs_testing
""",
    "tag": """
{bold}tag{reset} add|remove <ref> <tag_name>

Add or remove a tag from a todo.

{bold}Examples:{reset}
    tag add IP2 api
    tag remove IP2 legacy
""",
    "assign": """
{bold}assign{reset} <ref> <uri>

Assign a URI to a todo. Stored in assigned.yml in the todo directory.
Multiple URIs can be assigned to the same todo.

{bold}Examples:{reset}
    assign IP2 uai://project/abc
    assign 0038 uai://session/20260521_043029_6784ebe3_cla
""",
    "unassign": """
{bold}unassign{reset} <ref> <uri>

Remove a URI assignment from a todo.
When the last assignment is removed, the assigned.yml file is deleted.

{bold}Examples:{reset}
    unassign IP2 uai://project/abc
""",
    "assigned": """
{bold}assigned{reset} <ref>

List all current URI assignments for a todo.

{bold}Examples:{reset}
    assigned IP2
    assigned 0038
""",
    "create": """
{bold}create{reset} <name> [--parent <ref>] [--status <s>] [--tags t1,t2] [--flags f1,f2] [--owner <id>] [--project <scope>]

Create a new todo.

In REPL mode without arguments, launches an interactive wizard.

{bold}Options:{reset}
    --parent <ref>     Create as child of another todo
    --status <status>  Initial status (default: triaging)
    --tags t1,t2       Comma-separated tags to add
    --flags f1,f2      Comma-separated flags to add
    --owner <id>       Owner — WHO executes (session/team/project id)
    --project <scope>  Project — WHAT scope/context (independent of owner)

{bold}Examples:{reset}
    create fix_login_bug
    create api_refactor --status ready --tags api,backend
    create subtask --parent IP2 --flags high_priority
    create hamilton_infra --owner Anvil --project hamilton
""",
}


def format_help(text: str) -> str:
    """Format help text with colors."""
    return text.format(
        bold=Colors.BOLD if Colors.enabled() else "",
        reset=Colors.RESET if Colors.enabled() else "",
        cyan=Colors.CYAN if Colors.enabled() else "",
        dim=Colors.DIM if Colors.enabled() else "",
        yellow=Colors.YELLOW if Colors.enabled() else "",
        version=VERSION,
    )


def cmd_help(args: list[str]) -> str:
    """Show help."""
    if not args:
        return format_help(HELP_OVERVIEW)
    
    topic = args[0].lower()
    
    if topic == "examples":
        return format_help(HELP_EXAMPLES)
    elif topic == "verbose":
        return format_help(HELP_VERBOSE)
    elif topic in COMMAND_HELP:
        return format_help(COMMAND_HELP[topic])
    else:
        # Try to find partial match
        for cmd, help_text in COMMAND_HELP.items():
            if cmd.startswith(topic):
                return format_help(help_text)
        return c(f"No help for: {topic}. Try 'help verbose' for all commands.", Colors.YELLOW)


# === REPL ===

def run_command(line: str, interactive: bool = True) -> str | None:
    """Parse and run a command, returning output string."""
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return c(f"Parse error: {e}", Colors.RED)
    
    if not parts:
        return None
    
    cmd = parts[0].lower()
    args = parts[1:]

    # Resolve aliases
    COMMAND_ALIASES = {
        "ls": "list", "show": "view", "new": "create", "rm": "delete",
        "done": "complete", "dup": "duplicate", "?": "help",
        "mv": "move",
    }
    cmd = COMMAND_ALIASES.get(cmd, cmd)

    # Commands that refresh the display cache (refs become current)
    DISPLAY_COMMANDS = {"kanban", "list", "tree", "view", "json", "home", "reload"}

    # In interactive mode, use cached refs for stability (todo_0081 item 9).
    # Display commands and CLI mode always load fresh state.
    if interactive and cmd not in DISPLAY_COMMANDS and _ref_cache["todos"] is not None:
        todos = _ref_cache["todos"]
        refs = _ref_cache["refs"]
    else:
        todos = load_todos()
        refs = build_reference_map(todos)
        _ref_cache["todos"] = todos
        _ref_cache["refs"] = refs

    # Command dispatch
    commands: dict[str, Callable] = {
        "kanban": lambda: cmd_kanban(args, todos, refs),
        "tree": lambda: cmd_tree(args, todos, refs),
        "list": lambda: cmd_list(args, todos, refs),
        "view": lambda: cmd_view(args, todos, refs),
        "status": lambda: cmd_status(args, todos, refs),
        "flag": lambda: cmd_flag(args, todos, refs),
        "tag": lambda: cmd_tag(args, todos, refs),
        "create": lambda: cmd_create(args, todos, refs, interactive),
        "move": lambda: cmd_move(args, todos, refs),
        "link": lambda: cmd_link(args, todos, refs),
        "edit": lambda: cmd_edit(args, todos, refs),
        "delete": lambda: cmd_delete(args, todos, refs, interactive),
        "purge": lambda: cmd_purge(args, todos, refs, interactive),
        "complete": lambda: cmd_complete(args, todos, refs),
        "duplicate": lambda: cmd_duplicate(args, todos, refs, interactive),
        "json": lambda: cmd_json(args, todos, refs),
        "validate": lambda: cmd_validate(args, todos, refs),
        "assign": lambda: cmd_assign(args, todos, refs),
        "unassign": lambda: cmd_unassign(args, todos, refs),
        "assigned": lambda: cmd_assigned(args, todos, refs),
        "create-light": lambda: cmd_create_light(args, todos, refs),
        "owner": lambda: cmd_owner(args, todos, refs),
        "project": lambda: cmd_project(args, todos, refs),
        "history": lambda: cmd_history(args, todos, refs),
        "help": lambda: cmd_help(args),
    }

    if cmd in commands:
        return commands[cmd]()

    # REPL-only commands
    if interactive:
        if cmd == "home":
            return cmd_kanban([], todos, refs) + "\n\n" + format_help(HELP_OVERVIEW)
        elif cmd == "root":
            if args:
                try:
                    set_current_root(Path(args[0]))
                    _ref_cache["todos"] = None  # Invalidate cache on root change
                    _ref_cache["refs"] = None
                    return c(f"Switched to: {CURRENT_ROOT}", Colors.GREEN)
                except Exception as e:
                    return c(f"Error: {e}", Colors.RED)
            else:
                return f"Current root: {CURRENT_ROOT}"
        elif cmd == "reload":
            _ref_cache["todos"] = None
            _ref_cache["refs"] = None
            return c("State reloaded", Colors.GREEN)
        elif cmd in ("quit", "exit", "q"):
            return None  # Signal to exit
    
    return c(f"Unknown command: {cmd}. Try 'help' for options.", Colors.YELLOW)


def repl() -> None:
    """Interactive REPL mode."""
    from uai_toolkit.common_utils.lib_readline import setup_readline
    setup_readline(history_file=HISTORY_FILE, history_length=500)

    print(c(f"todo_mgr v{VERSION}", Colors.BOLD), f"- TODO_ROOT={CURRENT_ROOT}")
    print(run_command("kanban"))
    print()
    print(c("Type 'help' for commands, 'quit' to exit.", Colors.DIM))

    while True:
        try:
            # Wrap ANSI codes in \001..\002 so readline knows they're
            # non-printing — fixes cursor offset on arrow-key history navigation
            if Colors.enabled():
                prompt = f"\001{Colors.CYAN}\002todo> \001{Colors.RESET}\002"
            else:
                prompt = "todo> "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        
        if not line:
            continue
        
        if line.lower() in ("quit", "exit", "q"):
            break
        
        result = run_command(line, interactive=True)
        if result:
            print(result)


def run_json_command(args: list[str]) -> None:
    """Run a command in JSON mode — calls ops_* functions and prints JSON to stdout."""
    if not args:
        print(json.dumps({"error": "No command provided"}))
        sys.exit(1)

    cmd = args[0].lower()
    cmd_args = args[1:]

    try:
        if cmd == "list":
            result = ops_list(
                status=_pop_flag(cmd_args, "--status"),
                tag=_pop_flag(cmd_args, "--tag"),
                flag=_pop_flag(cmd_args, "--flag"),
                assigned=_pop_flag(cmd_args, "--assigned"),
            )
        elif cmd == "get":
            if not cmd_args:
                result = {"error": "Usage: get <identifier>"}
            else:
                result = ops_get(cmd_args[0])
        elif cmd == "create":
            name = _pop_flag(cmd_args, "--name") or (cmd_args[0] if cmd_args else None)
            if not name:
                result = {"error": "Usage: create --name <name>"}
            else:
                result = ops_create(
                    name=name,
                    description=_pop_flag(cmd_args, "--description") or "",
                    tags=_pop_flag_list(cmd_args, "--tags"),
                    status=_pop_flag(cmd_args, "--status") or "triaging",
                    owner=_pop_flag(cmd_args, "--owner") or "",
                    project=_pop_flag(cmd_args, "--project") or "",
                    source=_pop_flag(cmd_args, "--source") or "agent",
                    created_by=_pop_flag(cmd_args, "--by") or "",
                )
        elif cmd == "update":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if cmd_args else None)
            section = _pop_flag(cmd_args, "--section")
            content = _pop_flag(cmd_args, "--content")
            if not all([identifier, section, content]):
                result = {"error": "Usage: update --id <id> --section <section> --content <content>"}
            else:
                result = ops_update(identifier=identifier, section=section, content=content)
        elif cmd == "create-light":
            note_text = _pop_flag(cmd_args, "--summary") or ""
            name = _pop_flag(cmd_args, "--name") or (cmd_args[0] if cmd_args else None)
            if not name:
                result = {"error": "Usage: create-light --name <name> [--summary <s>] "
                                   "[--status <s>] [--owner <id>] [--project <id>] "
                                   "[--source agent|backfill|manual] [--by <session>]"}
            else:
                result = ops_create_light(
                    name=name,
                    summary=note_text,
                    status=_pop_flag(cmd_args, "--status") or "triaging",
                    owner=_pop_flag(cmd_args, "--owner") or "",
                    project=_pop_flag(cmd_args, "--project") or "",
                    source=_pop_flag(cmd_args, "--source") or "agent",
                    created_by=_pop_flag(cmd_args, "--by") or "",
                )
        elif cmd == "owner":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if cmd_args else None)
            clear = "--clear" in cmd_args
            owner_val = _pop_flag(cmd_args, "--owner")
            if not identifier:
                result = {"error": "Usage: owner --id <id> --owner <owner> | --clear"}
            elif clear:
                result = ops_clear_owner(identifier)
            elif owner_val is not None:
                result = ops_set_owner(identifier, owner_val)
            else:
                result = {"error": "Usage: owner --id <id> --owner <owner> | --clear"}
        elif cmd == "project":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if cmd_args else None)
            clear = "--clear" in cmd_args
            project_val = _pop_flag(cmd_args, "--project")
            if not identifier:
                result = {"error": "Usage: project --id <id> --project <id> | --clear"}
            elif clear:
                result = ops_clear_project(identifier)
            elif project_val is not None:
                result = ops_set_project(identifier, project_val)
            else:
                result = {"error": "Usage: project --id <id> --project <id> | --clear"}
        elif cmd == "history":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if cmd_args else None)
            if not identifier:
                result = {"error": "Usage: history <id>"}
            else:
                result = ops_history(identifier)
        elif cmd == "status":
            note_text = _pop_flag(cmd_args, "--note") or ""
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if len(cmd_args) >= 2 else None)
            new_status = _pop_flag(cmd_args, "--status") or (cmd_args[1] if len(cmd_args) >= 2 else None)
            if not identifier or not new_status:
                result = {"error": "Usage: status --id <id> --status <status> [--note <note>]"}
            else:
                result = ops_status([identifier], new_status, note=note_text)
        elif cmd == "flag":
            action = _pop_flag(cmd_args, "--action") or (cmd_args[0] if len(cmd_args) >= 3 else None)
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[1] if len(cmd_args) >= 3 else None)
            flag_name = _pop_flag(cmd_args, "--flag") or (cmd_args[2] if len(cmd_args) >= 3 else None)
            if not all([action, identifier, flag_name]):
                result = {"error": "Usage: flag --action add|remove --id <id> --flag <flag>"}
            else:
                result = ops_flag(action, identifier, flag_name)
        elif cmd == "tag":
            action = _pop_flag(cmd_args, "--action") or (cmd_args[0] if len(cmd_args) >= 3 else None)
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[1] if len(cmd_args) >= 3 else None)
            tag_name = _pop_flag(cmd_args, "--tag") or (cmd_args[2] if len(cmd_args) >= 3 else None)
            if not all([action, identifier, tag_name]):
                result = {"error": "Usage: tag --action add|remove --id <id> --tag <tag>"}
            else:
                result = ops_tag(action, identifier, tag_name)
        elif cmd == "complete":
            if not cmd_args:
                result = {"error": "Usage: complete <identifier>"}
            else:
                result = ops_complete(cmd_args[0])
        elif cmd == "trash":
            if not cmd_args:
                result = {"error": "Usage: trash <identifier>"}
            else:
                result = ops_trash(cmd_args[0])
        elif cmd == "move":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if len(cmd_args) >= 2 else None)
            new_parent = _pop_flag(cmd_args, "--parent") or (cmd_args[1] if len(cmd_args) >= 2 else None)
            if not identifier or not new_parent:
                result = {"error": "Usage: move --id <id> --parent <parent>"}
            else:
                result = ops_move(identifier, new_parent)
        elif cmd == "kanban":
            result = ops_kanban()
        elif cmd == "validate":
            result = ops_validate()
        elif cmd == "assign":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if len(cmd_args) >= 2 else None)
            uri = _pop_flag(cmd_args, "--uri") or (cmd_args[1] if len(cmd_args) >= 2 else None)
            if not identifier or not uri:
                result = {"error": "Usage: assign --id <id> --uri <uri>"}
            else:
                result = ops_assign(identifier, uri)
        elif cmd == "unassign":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if len(cmd_args) >= 2 else None)
            uri = _pop_flag(cmd_args, "--uri") or (cmd_args[1] if len(cmd_args) >= 2 else None)
            if not identifier or not uri:
                result = {"error": "Usage: unassign --id <id> --uri <uri>"}
            else:
                result = ops_unassign(identifier, uri)
        elif cmd == "assigned":
            identifier = _pop_flag(cmd_args, "--id") or (cmd_args[0] if cmd_args else None)
            if not identifier:
                result = {"error": "Usage: assigned <identifier>"}
            else:
                result = ops_assigned(identifier)
        elif cmd == "find":
            pattern = _pop_flag(cmd_args, "--pattern") or (cmd_args[0] if cmd_args else None)
            if not pattern:
                result = {"error": "Usage: find --pattern <glob>"}
            else:
                result = ops_list(name_pattern=pattern, include_all=True)
        else:
            result = {"error": f"Unknown JSON command: {cmd}"}

        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def _pop_flag(args: list[str], flag: str) -> str | None:
    """Extract a --flag value from args list, removing both flag and value."""
    try:
        idx = args.index(flag)
        if idx + 1 < len(args):
            value = args[idx + 1]
            del args[idx:idx + 2]
            return value
    except ValueError:
        pass
    return None


def _pop_flag_list(args: list[str], flag: str) -> list[str] | None:
    """Extract a --flag value as comma-separated list."""
    value = _pop_flag(args, flag)
    if value:
        return [t.strip() for t in value.split(",") if t.strip()]
    return None


def main() -> None:
    """Main entry point."""
    args = sys.argv[1:]

    # Handle flags
    json_mode = False
    i = 0
    while i < len(args):
        if args[i] in ("--root", "-r"):
            if i + 1 < len(args):
                try:
                    set_current_root(Path(args[i + 1]))
                except Exception as e:
                    print(c(f"Error setting root: {e}", Colors.RED), file=sys.stderr)
                    sys.exit(1)
                args = args[:i] + args[i+2:]
            else:
                print(c("Missing value for --root", Colors.RED), file=sys.stderr)
                sys.exit(1)
        elif args[i] == "--json":
            json_mode = True
            args = args[:i] + args[i+1:]
        elif args[i] == "--no-color":
            Colors.disable()
            args = args[:i] + args[i+1:]
        elif args[i] in ("--help", "-h"):
            print(format_help(HELP_OVERVIEW))
            sys.exit(0)
        elif args[i] == "--version":
            print(f"todo_mgr v{VERSION}")
            sys.exit(0)
        else:
            i += 1

    # JSON mode — structured output for MCP/scripts
    if json_mode:
        Colors.disable()
        run_json_command(args)
        return

    # If no command args, run REPL
    if not args:
        repl()
        return

    # Otherwise, run single command (CLI mode)
    command_line = " ".join(shlex.quote(a) for a in args)
    result = run_command(command_line, interactive=False)

    if result:
        print(result)


if __name__ == "__main__":
    main()
