#!/usr/bin/env python3
"""Materialize the uai_toolkit package from authoritative source.

Source of truth is the live tree (`~/bin/ai`, `~/bin/all_languages/python/src`,
`ai_general/apps/mcps`). This regenerates the curated toolkit subset so drift
becomes a reviewable diff instead of silent rot. See tools/manifest.py.

Usage:
    python3 tools/materialize.py                 # DRY RUN — show what would change
    python3 tools/materialize.py --apply         # write clean files + curated sidecars
    python3 tools/materialize.py --only jsonl    # limit to dests under a prefix
    python3 tools/materialize.py --diff          # dry run + full unified diffs

Behavior by provenance class (manifest `kind`):
  clean   -> copy + import-rewrite + scrub, written in place on --apply.
  curated -> copy + rewrite + scrub, written to `<dest>.materialized` sidecar for
             manual diff/merge (never overwrites the hand-curated file).
  forked  -> skipped; reported (source improvement should be back-ported instead).
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manifest import (  # noqa: E402
    APP_EXCLUDE_DIRS, APP_EXCLUDE_FILES, APP_TEXT_SUFFIXES, APP_TREES,
    CONTENT, CONTENT_EXCLUDE_DIR_PREFIXES, CONTENT_EXCLUDE_DIRS,
    CONTENT_EXCLUDE_FILES, CONTENT_TEXT_SUFFIXES,
    IMPORT_REWRITES, MODULES, SCRUB_PATTERNS, SOURCE_ROOTS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "src" / "uai_toolkit"


def _resolve_root(key: str) -> Path:
    return Path(SOURCE_ROOTS[key]).expanduser()


def _resolve_source(spec: str) -> Path:
    root_key, _, rel = spec.partition(":")
    return _resolve_root(root_key) / rel


_MODULE_INDEX: dict = {}  # module stem -> its uai_toolkit package (built in main)


def build_module_index() -> dict:
    """Map every vendored module stem -> its package (e.g. session_store ->
    uai_toolkit.session_mgmt). Lets us auto-rewrite intra-package sibling imports
    (bare `import gemini_memory_lock`, `from resume_marker import ...`) that aren't
    worth hand-listing in IMPORT_REWRITES. First definition wins on collision.
    """
    idx: dict = {}
    for e in list(MODULES) + expand_module_dirs():
        dest = e["dest"]
        if not dest.endswith(".py"):
            continue
        p = Path(dest)
        if p.stem == "__init__" or not p.parent.parts:
            continue
        pkg = "uai_toolkit." + ".".join(p.parent.parts)
        idx.setdefault(p.stem, pkg)
    return idx


def apply_rewrites(text: str, mcp_pkg: str | None) -> str:
    for pattern, repl in IMPORT_REWRITES:
        # MULTILINE so `^`-anchored `import X` rules match per-line, not just file start.
        text = re.sub(pattern, repl, text, flags=re.MULTILINE)
    # Auto-derived intra-package sibling rewrites (residual not in IMPORT_REWRITES).
    # Word-boundary + line-anchored so it never touches already-`uai_toolkit.`-prefixed
    # lines or stdlib names embedded in longer identifiers.
    for stem, pkg in _MODULE_INDEX.items():
        text = re.sub(rf"^(\s*)from {stem} import ", rf"\1from {pkg}.{stem} import ", text, flags=re.MULTILINE)
        text = re.sub(rf"^(\s*)import {stem}(\s|$|\s+as\s)", rf"\1from {pkg} import {stem}\2", text, flags=re.MULTILINE)
    # mcp packages: `from tools import X` -> `from uai_toolkit.mcp.<pkg>.tools import X`
    if mcp_pkg:
        text = re.sub(r"\bfrom tools\b", f"from uai_toolkit.mcp.{mcp_pkg}.tools", text)
        text = re.sub(r"\bfrom tools\.", f"from uai_toolkit.mcp.{mcp_pkg}.tools.", text)
    return text


def scrub(text: str) -> tuple[str, list[str]]:
    """Replace machine-specific absolutes; return (text, survivors_report)."""
    for pattern, repl in SCRUB_PATTERNS:
        text = re.sub(pattern, repl, text)
    survivors = re.findall(r"/Users/[A-Za-z0-9_.-]+", text)
    return text, sorted(set(survivors))


def transform(source_text: str, entry: dict) -> tuple[str, list[str]]:
    # docs (README.md/DESIGN.md): scrub only, no import rewrites.
    if entry.get("kind") == "doc":
        return scrub(source_text)
    text = apply_rewrites(source_text, entry.get("mcp_pkg"))
    text, survivors = scrub(text)
    return text, survivors


def process(entry: dict, apply: bool, show_diff: bool) -> dict:
    dest_rel = entry["dest"]
    dest = PKG_ROOT / dest_rel
    kind = entry["kind"]
    result = {"dest": dest_rel, "kind": kind, "status": "", "detail": "", "survivors": []}

    if kind == "forked":
        result["status"] = "SKIP-forked"
        result["detail"] = "toolkit diverged (improvement absent from source); back-port instead"
        return result

    src = _resolve_source(entry["source"])
    if not src.exists():
        result["status"] = "ERROR"
        result["detail"] = f"source missing: {src}"
        return result

    source_text = src.read_text(encoding="utf-8", errors="replace")
    new_text, survivors = transform(source_text, entry)
    result["survivors"] = survivors

    if kind == "curated":
        out = dest.with_suffix(dest.suffix + ".materialized")
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        if new_text == old:
            result["status"] = "sidecar-unchanged"
        else:
            result["status"] = "SIDECAR"
            result["detail"] = f"-> {out.name} (manual merge vs curated {dest.name})"
            if apply:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(new_text, encoding="utf-8")
        return result

    # clean
    old = dest.read_text(encoding="utf-8", errors="replace") if dest.exists() else ""
    if new_text == old:
        result["status"] = "unchanged"
        return result
    result["status"] = "UPDATE" if old else "CREATE"
    n_added = sum(1 for _ in difflib.unified_diff(old.splitlines(), new_text.splitlines(), n=0))
    result["detail"] = f"{len(old.splitlines())} -> {len(new_text.splitlines())} lines"
    if show_diff:
        diff = "\n".join(difflib.unified_diff(
            old.splitlines(), new_text.splitlines(),
            fromfile=f"a/{dest_rel}", tofile=f"b/{dest_rel}", lineterm=""))
        result["diff"] = diff
    if apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_text, encoding="utf-8")
    return result


def _excluded_dir(name: str) -> bool:
    return (name in CONTENT_EXCLUDE_DIRS
            or name.startswith(CONTENT_EXCLUDE_DIR_PREFIXES))


def process_content(entry: dict, apply: bool) -> dict:
    """Vendor a content tree into the package: copy + scrub text files, prune noise."""
    dest_rel = entry["dest"]
    dest_root = PKG_ROOT / dest_rel
    src_root = _resolve_source(entry["source"])
    result = {"dest": dest_rel, "kind": "content", "status": "", "detail": "", "survivors": []}
    if not src_root.exists():
        result["status"] = "ERROR"
        result["detail"] = f"source missing: {src_root}"
        return result

    copied = scrubbed = skipped = 0
    survivors: set[str] = set()
    for src in src_root.rglob("*"):
        rel = src.relative_to(src_root)
        if any(_excluded_dir(part) for part in rel.parts):
            continue
        # Dangling symlink (target removed, e.g. a *.latest.* pointing at a pruned
        # version): is_dir()/is_file() are both False and read would throw. Skip it.
        if src.is_symlink() and not src.exists():
            skipped += 1
            continue
        if src.is_dir():
            continue
        if src.name in CONTENT_EXCLUDE_FILES:
            skipped += 1
            continue
        out = dest_root / rel
        if src.suffix.lower() in CONTENT_TEXT_SUFFIXES:
            text = src.read_text(encoding="utf-8", errors="replace")
            new_text, surv = scrub(text)
            survivors.update(surv)
            if new_text != text:
                scrubbed += 1
            if apply:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(new_text, encoding="utf-8")
        else:  # binary/opaque: copy verbatim
            if apply:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(src.read_bytes())
        copied += 1

    result["status"] = "CONTENT"
    result["detail"] = f"{copied} files ({scrubbed} scrubbed, {skipped} skipped)"
    result["survivors"] = sorted(survivors)
    return result


def process_app_tree(entry: dict, apply: bool) -> dict:
    """Vendor an app source tree to a REPO-ROOT sibling (not Python package-data).

    Excludes node_modules + build outputs (restored via `npm ci` / build on the
    target). Text files scrubbed; binaries copied verbatim.
    """
    dest_rel = entry["dest"]
    dest_root = REPO_ROOT / dest_rel
    src_root = _resolve_source(entry["source"])
    result = {"dest": dest_rel + "/ (app)", "kind": "app", "status": "", "detail": "", "survivors": []}
    if not src_root.exists():
        result["status"] = "ERROR"
        result["detail"] = f"source missing: {src_root}"
        return result

    copied = scrubbed = 0
    survivors: set[str] = set()
    for src in src_root.rglob("*"):
        rel = src.relative_to(src_root)
        if any(p in APP_EXCLUDE_DIRS for p in rel.parts):
            continue
        if src.is_symlink() and not src.exists():  # dangling symlink — skip
            continue
        if src.is_dir() or src.name in APP_EXCLUDE_FILES:
            continue
        out = dest_root / rel
        if src.suffix.lower() in APP_TEXT_SUFFIXES:
            text = src.read_text(encoding="utf-8", errors="replace")
            new_text, surv = scrub(text)
            survivors.update(surv)
            if new_text != text:
                scrubbed += 1
            if apply:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(new_text, encoding="utf-8")
        else:
            if apply:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(src.read_bytes())
        copied += 1
    result["status"] = "APP"
    result["detail"] = f"{copied} files ({scrubbed} scrubbed) -> {dest_rel}/ (excl node_modules+build)"
    result["survivors"] = sorted(survivors)
    return result


def _do_not_port(src_file: Path, src_root: Path) -> bool:
    """True if a DO_NOT_PORT.flag sits in src_file's dir chain up to src_root.

    PianoMan drops DO_NOT_PORT.flag into a source dir to exclude it from porting
    (sh->py AND Windows). Respected here so materialize never vendors flagged dirs.
    """
    d = src_file.parent
    while True:
        if (d / "DO_NOT_PORT.flag").exists():
            return True
        if d == src_root or d == d.parent:
            return False
        d = d.parent


def expand_module_dirs():
    """Expand each MODULE_DIRS dir-glob into concrete per-file MODULE entries.

    Globs *.py (+ opaque data files) under a source dir, honoring exclude /
    include_only, and applies per-file `kind` overrides. Keeps the engine's
    per-file provenance model while letting the manifest declare whole packages.
    """
    try:
        from manifest import MODULE_DIRS
    except ImportError:
        return []
    expanded = []
    for spec in MODULE_DIRS:
        src_root = _resolve_source(spec["source"])
        if not src_root.exists():
            expanded.append({"dest": spec["dest"] + "/<MISSING>", "source": spec["source"],
                             "kind": "forked", "_error": f"source missing: {src_root}"})
            continue
        exclude = set(spec.get("exclude", []))
        include_only = spec.get("include_only")
        overrides = spec.get("overrides", {})
        default_kind = spec.get("kind", "clean")
        mcp_pkg = spec.get("mcp_pkg")
        # Skip a whole dir-glob if its source root is flagged DO_NOT_PORT.
        if (src_root / "DO_NOT_PORT.flag").exists():
            expanded.append({"dest": spec["dest"] + "/<DO_NOT_PORT>", "source": spec["source"],
                             "kind": "native", "_skip": "DO_NOT_PORT.flag at source root"})
            continue
        for src in sorted(src_root.rglob("*.py")):
            rel = src.relative_to(src_root)
            relstr = str(rel)
            parts = rel.parts
            if any(p in exclude for p in parts) or relstr in exclude:
                continue
            if include_only and parts[0] not in include_only:
                continue
            if any(p in ("__pycache__", ".pytest_cache", "archive", ".archive", "_shelved", "tests", "test_files")
                   or p.startswith(("_backup", "_archive")) for p in parts):
                continue
            # honor a DO_NOT_PORT.flag anywhere between src_root and this file
            if _do_not_port(src, src_root):
                continue
            kind = overrides.get(relstr, overrides.get(rel.name, default_kind))
            entry = {"dest": f"{spec['dest']}/{relstr}", "source": f"{spec['source'].split(':')[0]}:{src.relative_to(_resolve_root(spec['source'].split(':')[0]))}", "kind": kind}
            if mcp_pkg:
                entry["mcp_pkg"] = mcp_pkg
            expanded.append(entry)
        # carry each dir's docs (README.md/DESIGN.md) alongside the code — scrub only
        root_key = spec["source"].split(":")[0]
        for doc in sorted(src_root.rglob("README.md")) + sorted(src_root.rglob("DESIGN.md")):
            rel = doc.relative_to(src_root)
            parts = rel.parts
            if any(p in exclude for p in parts):        # honor the entry's exclude list
                continue
            if any(p in ("__pycache__", ".pytest_cache", "archive", ".archive", "_shelved", "tests", "test_files")
                   or p.startswith(("_backup", "_archive")) for p in parts):
                continue
            if include_only and len(parts) > 1 and parts[0] not in include_only:
                continue
            if _do_not_port(doc, src_root):
                continue
            expanded.append({"dest": f"{spec['dest']}/{rel}",
                             "source": f"{root_key}:{doc.relative_to(_resolve_root(root_key))}",
                             "kind": "doc"})
    return expanded


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Materialize uai_toolkit from source.")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--only", default="", help="limit to dests starting with this prefix")
    ap.add_argument("--diff", action="store_true", help="print full unified diffs (clean files)")
    ap.add_argument("--content", action="store_true", help="also materialize content trees (ai_context_files, ai_profiles)")
    ap.add_argument("--app", action="store_true", help="also materialize app source trees (uai_app)")
    ap.add_argument("--dirs", action="store_true", help="also materialize MODULE_DIRS dir-globs (session_mgmt, messages, ...)")
    args = ap.parse_args(argv)

    global _MODULE_INDEX
    _MODULE_INDEX = build_module_index()  # for auto-derived sibling import rewrites

    all_modules = list(MODULES)
    if args.dirs:
        all_modules += expand_module_dirs()
    entries = [e for e in all_modules if e["dest"].startswith(args.only)]
    results = [process(e, apply=args.apply, show_diff=args.diff) for e in entries]
    if args.content:
        results += [process_content(e, apply=args.apply)
                    for e in CONTENT if e["dest"].startswith(args.only)]
    if args.app:
        results += [process_app_tree(e, apply=args.apply) for e in APP_TREES]

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== materialize uai_toolkit [{mode}] — {len(results)} entries ===\n")
    buckets: dict[str, list] = {}
    for r in results:
        buckets.setdefault(r["status"], []).append(r)
        flag = ""
        if r["status"] in ("UPDATE", "CREATE", "SIDECAR", "ERROR", "SKIP-forked"):
            flag = "  *"
        line = f"  {r['status']:18} {r['dest']}"
        if r["detail"]:
            line += f"   ({r['detail']})"
        print(line + flag)
        if r.get("survivors"):
            print(f"      !! unscrubbed absolute paths: {r['survivors']}")
        if r.get("diff"):
            print("\n".join("      " + ln for ln in r["diff"].splitlines()) + "\n")

    print("\n--- summary ---")
    for status in sorted(buckets):
        print(f"  {status:18} {len(buckets[status])}")
    errors = len(buckets.get("ERROR", []))
    if not args.apply and any(k in buckets for k in ("UPDATE", "CREATE", "SIDECAR")):
        print("\n(dry run — re-run with --apply to write)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
