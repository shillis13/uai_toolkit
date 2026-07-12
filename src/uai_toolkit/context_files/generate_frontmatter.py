#!/usr/bin/env python3
"""Generate frontmatter for trait files that are missing it.

Markdown files get --- frontmatter. YAML files get _registry: block.
Only edits canonical source files — never symlinks or generated/condensed files.

Usage:
    generate_frontmatter.py --all              # Process all files missing frontmatter
    generate_frontmatter.py --file <path>      # Process one file
    generate_frontmatter.py --dry-run          # Show what would be generated
    generate_frontmatter.py --check            # Report files missing frontmatter
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402
AI_GENERAL = AI_ROOT / "ai_general"
TRAITS_DIR = AI_GENERAL / "ai_traits"
PROFILES_DIR = AI_GENERAL / "ai_profiles"

EXCLUDE_FILES = {".DS_Store", ".gitkeep", "README.md", "catalog.yml",
                 "package.json", "package-lock.json"}
EXCLUDE_DIRS = {"versions", ".obsidian", ".claude", "__pycache__", "node_modules", ".venv", "generated"}


def infer_id(filename: str) -> str:
    """Strip extensions and .latest/.condensed to get logical ID."""
    name = filename
    for suffix in [".condensed.yml", ".latest.condensed.yml", ".latest.yml",
                   ".latest.md", ".latest.yaml", ".yml", ".yaml", ".md"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name


def infer_name(item_id: str) -> str:
    """Generate human-readable name."""
    name = item_id
    for prefix in ["instr_", "spec_", "schema_", "protocol_", "playbook.", "playbook_",
                    "arch_", "architecture_"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").replace("-", " ").title()


def infer_status(path: Path) -> str:
    """Infer status from path."""
    rel = str(path.relative_to(AI_GENERAL))
    if "_drafts/retired" in rel:
        return "retired"
    if "_drafts" in rel:
        return "draft"
    return "active"


def git_date(path: Path, mode: str = "created") -> str:
    """Get creation or last modification date from git."""
    try:
        if mode == "created":
            result = subprocess.run(
                ["git", "log", "--follow", "--diff-filter=A", "--format=%aI", "--", str(path)],
                capture_output=True, text=True, timeout=10, cwd=str(AI_GENERAL),
            )
        else:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", "--", str(path)],
                capture_output=True, text=True, timeout=10, cwd=str(AI_GENERAL),
            )
        dates = result.stdout.strip().split("\n")
        if dates and dates[-1]:
            return dates[-1][:10]  # YYYY-MM-DD
    except Exception:
        pass
    return ""


def extract_existing_metadata(content: str, filename: str) -> dict:
    """Extract any existing metadata from file content."""
    meta = {}

    # Check for --- frontmatter (markdown)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1])
                if isinstance(fm, dict):
                    meta.update(fm)
            except Exception:
                pass

    # Check for _registry: block (YAML)
    if filename.endswith((".yml", ".yaml")):
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                if "_registry" in data:
                    meta.update(data["_registry"])
                if "metadata" in data and isinstance(data["metadata"], dict):
                    md = data["metadata"]
                    if "version" in md:
                        meta.setdefault("version", str(md["version"]))
                    if "updated" in md or "last_updated" in md:
                        meta.setdefault("updated", str(md.get("updated", md.get("last_updated", ""))))
                    if "status" in md:
                        meta.setdefault("status", md["status"])
                    if "name" in md or "title" in md:
                        meta.setdefault("name", md.get("name", md.get("title", "")))
                    if "created" in md:
                        meta.setdefault("created", str(md["created"]))
        except Exception:
            pass

    # Check for inline meta: {v: X, ...}
    m = re.search(r'^meta:\s*\{(.+?)\}', content, re.MULTILINE)
    if m:
        for pair in m.group(1).split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                k, v = k.strip(), v.strip().strip("'\"")
                if k == "v":
                    meta.setdefault("version", v)
                elif k == "updated":
                    meta.setdefault("updated", v)
                elif k == "status":
                    meta.setdefault("status", v)

    return {k: v for k, v in meta.items() if v}


def has_frontmatter(content: str, filename: str) -> bool:
    """Check if file already has our metadata."""
    if filename.endswith(".md") and content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1])
                if isinstance(fm, dict) and "id" in fm:
                    return True
            except Exception:
                pass

    if filename.endswith((".yml", ".yaml")):
        try:
            data = yaml.safe_load(content)
            if isinstance(data, dict) and "_registry" in data:
                return True
        except Exception:
            pass

    return False


def build_metadata(path: Path, content: str) -> dict:
    """Build the 6-field metadata for a file."""
    filename = path.name
    item_id = infer_id(filename)
    existing = extract_existing_metadata(content, filename)

    meta = {
        "id": existing.get("id", item_id),
        "name": existing.get("name", infer_name(item_id)),
        "status": existing.get("status", infer_status(path)),
        "version": existing.get("version", "1.0.0"),
        "created": existing.get("created", git_date(path, "created") or datetime.now().strftime("%Y-%m-%d")),
        "updated": existing.get("updated", git_date(path, "updated") or datetime.now().strftime("%Y-%m-%d")),
    }

    return meta


def apply_frontmatter_md(content: str, meta: dict) -> str:
    """Add or merge --- frontmatter into a markdown file."""
    if content.startswith("---"):
        # Merge into existing frontmatter
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                existing = yaml.safe_load(parts[1]) or {}
            except Exception:
                existing = {}
            for k, v in meta.items():
                existing.setdefault(k, v)
            fm_str = yaml.dump(existing, default_flow_style=False, sort_keys=False).strip()
            return f"---\n{fm_str}\n---\n{parts[2]}"

    # No existing frontmatter — prepend
    fm_str = yaml.dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{fm_str}\n---\n\n{content}"


def apply_registry_yml(content: str, meta: dict) -> str:
    """Add _registry: block to a YAML file without breaking parsing."""
    try:
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return content  # Can't add to non-dict YAML
    except Exception:
        return content  # Can't parse — don't modify

    if "_registry" in data:
        # Merge into existing
        for k, v in meta.items():
            data["_registry"].setdefault(k, v)
    else:
        data["_registry"] = meta

    # Verify round-trip
    try:
        result = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        # Verify parseable
        yaml.safe_load(result)
        return result
    except Exception:
        return content  # Round-trip failed — don't modify


def is_canonical_source(path: Path) -> bool:
    """Only process canonical source files, not symlinks or generated files."""
    # Skip symlinks
    if path.is_symlink():
        return False
    # Skip files in versions/ directories
    if "versions" in path.parts:
        return False
    # Skip generated/ directories
    if "generated" in path.parts:
        return False
    return True


def collect_files_to_process() -> list[Path]:
    """Find all files that need frontmatter processing."""
    files = []

    for base_dir in [TRAITS_DIR, PROFILES_DIR]:
        for root, dirs, filenames in os.walk(base_dir):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for fname in filenames:
                if fname in EXCLUDE_FILES:
                    continue
                fpath = root_path / fname

                # Only canonical source files
                if not is_canonical_source(fpath):
                    continue

                # Only content files
                if not any(fname.endswith(ext) for ext in [".md", ".yml", ".yaml"]):
                    continue

                files.append(fpath)

    return sorted(files)


def process_file(path: Path, dry_run: bool = False) -> tuple[str, dict]:
    """Process one file. Returns (action, metadata)."""
    try:
        content = path.read_text()
    except Exception as e:
        return f"error: {e}", {}

    if has_frontmatter(content, path.name):
        return "skip: already has metadata", {}

    meta = build_metadata(path, content)

    if dry_run:
        return "would add", meta

    # Apply format-appropriate metadata
    if path.name.endswith(".md"):
        new_content = apply_frontmatter_md(content, meta)
    elif path.name.endswith((".yml", ".yaml")):
        new_content = apply_registry_yml(content, meta)
    else:
        return "skip: unsupported format", {}

    if new_content == content:
        return "skip: no change", {}

    # Verify YAML files still parse
    if path.name.endswith((".yml", ".yaml")):
        try:
            yaml.safe_load(new_content)
        except Exception as e:
            return f"error: YAML validation failed after modification: {e}", {}

    path.write_text(new_content)
    return "added", meta


def main():
    parser = argparse.ArgumentParser(description="Generate frontmatter for trait files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Process all files missing frontmatter")
    group.add_argument("--file", type=str, help="Process one specific file")
    group.add_argument("--check", action="store_true", help="Report files missing frontmatter")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")

    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = AI_GENERAL / path
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        action, meta = process_file(path, dry_run=args.dry_run)
        print(f"{action}: {path.name}")
        if meta:
            for k, v in meta.items():
                print(f"  {k}: {v}")
        return 0

    files = collect_files_to_process()

    if args.check:
        missing = 0
        has = 0
        for fpath in files:
            try:
                content = fpath.read_text()
                if has_frontmatter(content, fpath.name):
                    has += 1
                else:
                    missing += 1
                    print(f"  MISSING: {fpath.relative_to(AI_GENERAL)}")
            except Exception:
                pass
        print(f"\n{has} files have metadata, {missing} files missing metadata")
        return 0

    # --all
    added = 0
    skipped = 0
    errors = 0
    for fpath in files:
        action, meta = process_file(fpath, dry_run=args.dry_run)
        if action.startswith("added") or action.startswith("would add"):
            added += 1
            if args.dry_run:
                print(f"  WOULD ADD: {fpath.relative_to(AI_GENERAL)}")
                for k, v in meta.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  ADDED: {fpath.relative_to(AI_GENERAL)}")
        elif action.startswith("error"):
            errors += 1
            print(f"  ERROR: {fpath.relative_to(AI_GENERAL)} — {action}")
        else:
            skipped += 1

    verb = "Would add" if args.dry_run else "Added"
    print(f"\n{verb}: {added}, Skipped: {skipped}, Errors: {errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
