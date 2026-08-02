#!/usr/bin/env python3
"""Dependency-closure check — does every vendored file's dependencies ship too?

WHY THIS EXISTS
    The manifest is a hand-maintained allowlist. Nothing verified that when a module
    was vendored, the things it actually needs came with it. That gap shipped four
    separate breakages:

      grok.py                  platform_adapters/__init__ imported it -> ImportError
      hook config files        handlers ran with an empty policy, silently
      declare_stop.config.yml  declare_stop raised RuntimeError outright
      3 jsonl modules          read_jsonl's --turns / branches / tail all failed

    The existing checks could not catch these:
      * `smoke_test.py` runs `--help` on console scripts. `read_jsonl --help` passes
        while `read_jsonl branches` raises — the failure is past the help path.
      * a plain import sweep only executes MODULE-LEVEL imports. A lazy import inside
        a function, a file loaded by path, or a subprocess target is invisible to it.

WHAT THIS CHECKS
    Walks every vendored .py with the abstract syntax tree (AST) and resolves:

      1. imports at ANY depth — including inside functions (the lazy ones a plain
         import sweep never executes)
      2. sibling files loaded BY PATH — `Path(__file__).parent / "x.py"`, the exact
         shape that hid the two-different-lib_cli_common bug
      3. subprocess / script references — string literals naming a `.py` file
      4. sibling data and config files — `.yml` / `.yaml` / `.json` a module reads
         beside itself (how the hook configs went missing)

    Anything a vendored file needs that is neither vendored, nor stdlib, nor a
    declared dependency, nor explicitly excused is reported as a break.

USAGE
    python3 tools/check_closure.py            # report; exit 1 if anything is missing
    python3 tools/check_closure.py --verbose  # also list what resolved and how

    Intended to run in the same place the tests do, so this class of breakage
    becomes a build failure instead of something a user discovers at runtime.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import sysconfig
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "src" / "uai_toolkit"

# Third-party distributions this package declares. Import name -> why it is allowed.
# Kept explicit rather than parsed from pyproject so an undeclared import cannot pass
# by accident when someone edits the dependency list.
DECLARED = {
    "yaml": "pyyaml (core)",
    "tomli": "tomli (core, python<3.11)",
    "psutil": "full extra",
    "httpx": "full extra",
    "websockets": "full extra",
    "tqdm": "full extra",
    "mcp": "mcp extra (the MCP SDK — NOT this package's mcp/ subpackage)",
    "jsonschema": "mcp extra",
    "PIL": "images extra (pillow)",
    "pytest": "dev extra",
    "setuptools": "build",
}

# Deliberate absences: needed only on a path we do not ship, or owned elsewhere.
# Every entry needs a reason — an unexplained entry is how a real break gets hidden.
EXCUSED = {
    "chain_skip.py": "context-reclaim successor; not vendored (see redev/jsonl notes)",
    "memory_manager.py": "source-tree only; context_ops degrades without it",
    "check_resume_integrity.py": "source-tree only; pre-bounce gate",
    "condense.py": "source-tree only; external condenser path",
    "auto_brief.py": "source-tree only",
    "lllm_prompt.py": "local-LLM stack deliberately not shipped (2026-07-27)",
    "lllm_manager.py": "local-LLM stack deliberately not shipped (2026-07-27)",
    "agy_to_jsonl.py": "obsolete converter; Antigravity writes native jsonl",
    "turn_digest.py": "source-tree only",
    "context_stats.py": "source-tree only",
}

SKIP_DIRS = {"__pycache__", ".pytest_cache", "content", "tests", "test_files"}
DATA_SUFFIXES = {".yml", ".yaml", ".json", ".toml", ".sql", ".sh"}

# `Path(__file__)... / "name.ext"` — a sibling file loaded by path rather than import.
SIBLING_RE = re.compile(r'__file__[^\n]{0,120}?/\s*[\'"]([A-Za-z0-9_.\-]+\.[a-z]{2,4})[\'"]')
# A bare string naming a python script, e.g. a subprocess target.
SCRIPT_RE = re.compile(r'[\'"]([A-Za-z0-9_\-]+\.py)[\'"]')


def _stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", set()))
    names |= set(sys.builtin_module_names)
    stdlib_dir = sysconfig.get_paths().get("stdlib")
    if stdlib_dir:
        for p in Path(stdlib_dir).iterdir():
            if p.suffix == ".py":
                names.add(p.stem)
            elif p.is_dir() and (p / "__init__.py").exists():
                names.add(p.name)
    return names


STDLIB = _stdlib_names()


def vendored_files() -> list[Path]:
    return [p for p in sorted(PKG.rglob("*.py"))
            if not any(part in SKIP_DIRS for part in p.relative_to(PKG).parts)]


def vendored_index(files: list[Path]) -> tuple[set[str], set[str]]:
    """(importable dotted names + bare stems, every shipped filename)."""
    modules: set[str] = set()
    filenames: set[str] = set()
    for p in PKG.rglob("*"):
        if p.is_file():
            filenames.add(p.name)
    for f in files:
        rel = f.relative_to(PKG).with_suffix("")
        parts = list(rel.parts)
        modules.add(parts[-1])                                  # bare stem
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            modules.add("uai_toolkit." + ".".join(parts))
            modules.add(".".join(parts))
    modules.add("uai_toolkit")
    return modules, filenames


def imported_names(tree: ast.AST) -> set[str]:
    """Every imported top-level name, at ANY nesting depth (lazy imports included)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:                 # skip relative
                found.add(node.module)
    return found


def resolves(name: str, modules: set[str]) -> tuple[bool, str]:
    root = name.split(".")[0]
    # This package's own `mcp` subpackage must not be mistaken for the MCP SDK.
    if name.startswith("uai_toolkit."):
        return (name in modules or root in modules), "vendored"
    if root in STDLIB:
        return True, "stdlib"
    if root in DECLARED:
        return True, f"declared: {DECLARED[root]}"
    if name in modules or root in modules:
        return True, "vendored"
    return False, "UNRESOLVED"


def check() -> tuple[list[str], dict]:
    files = vendored_files()
    modules, filenames = vendored_index(files)
    breaks: list[str] = []
    stats = {"files": len(files), "imports": 0, "sibling": 0, "scripts": 0}

    for f in files:
        rel = f.relative_to(REPO)
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (OSError, SyntaxError) as e:
            breaks.append(f"{rel}: cannot parse — {type(e).__name__}: {e}")
            continue

        for name in sorted(imported_names(tree)):
            stats["imports"] += 1
            ok, _ = resolves(name, modules)
            if not ok:
                breaks.append(f"{rel}: imports '{name}' — not vendored, stdlib, or declared")

        # sibling files loaded by path (py AND data/config)
        for fname in set(SIBLING_RE.findall(src)):
            stats["sibling"] += 1
            if fname in EXCUSED or fname in filenames:
                continue
            if Path(fname).suffix in DATA_SUFFIXES or fname.endswith(".py"):
                breaks.append(f"{rel}: loads sibling '{fname}' by path — not shipped")

        # subprocess / script targets named as bare strings
        for fname in set(SCRIPT_RE.findall(src)):
            stats["scripts"] += 1
            if fname in EXCUSED or fname in filenames:
                continue
            breaks.append(f"{rel}: references script '{fname}' — not shipped "
                          f"(add to EXCUSED with a reason if deliberate)")

    return breaks, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verbose", action="store_true", help="also print what was scanned")
    args = ap.parse_args(argv)

    breaks, stats = check()

    print("=== dependency-closure check ===")
    if args.verbose:
        print(f"  scanned {stats['files']} vendored modules")
        print(f"  {stats['imports']} imports, {stats['sibling']} by-path siblings, "
              f"{stats['scripts']} script references")
        print(f"  {len(EXCUSED)} deliberate exclusions\n")

    if not breaks:
        print(f"  OK — every dependency of {stats['files']} vendored modules ships "
              f"(or is stdlib / declared / explicitly excused).")
        return 0

    print(f"  {len(breaks)} unmet dependenc{'y' if len(breaks) == 1 else 'ies'}:\n")
    for b in breaks:
        print(f"    {b}")
    print("\n  Fix by adding the file to tools/manifest.py, or — if the absence is "
          "deliberate — to EXCUSED in this file WITH A REASON.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
