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
from manifest import IMPORT_REWRITES, MODULES, SCRUB_PATTERNS, SOURCE_ROOTS  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parent.parent / "src" / "uai_toolkit"


def _resolve_root(key: str) -> Path:
    return Path(SOURCE_ROOTS[key]).expanduser()


def _resolve_source(spec: str) -> Path:
    root_key, _, rel = spec.partition(":")
    return _resolve_root(root_key) / rel


def apply_rewrites(text: str, mcp_pkg: str | None) -> str:
    for pattern, repl in IMPORT_REWRITES:
        text = re.sub(pattern, repl, text)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Materialize uai_toolkit from source.")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--only", default="", help="limit to dests starting with this prefix")
    ap.add_argument("--diff", action="store_true", help="print full unified diffs (clean files)")
    args = ap.parse_args(argv)

    entries = [e for e in MODULES if e["dest"].startswith(args.only)]
    results = [process(e, apply=args.apply, show_diff=args.diff) for e in entries]

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
