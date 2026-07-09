#!/usr/bin/env python3
"""
delivery_baseline.py — golden-baseline harness for the guidance delivery path.

Invokes the CURRENT guidance_lib delivery entrypoints (the same ones the
knowledge MCP's get_role / get_context / how_to / remind_me back) for a fixed,
representative sample and writes each assembled output to a target directory.

Run it once against the legacy path (before porting guidance_lib to context.db)
and again against the ported path, then diff the two directories.

Usage:
    python3 delivery_baseline.py /tmp/guidance_baseline      # capture
    python3 delivery_baseline.py /tmp/guidance_ported        # re-capture

The sample identifiers are chosen to resolve in BOTH the legacy registry and
context.db (they name the same on-disk files), so a diff isolates delivery
behaviour rather than sample availability. This is a batch dev harness (single
positional arg, no subcommands); it exits nonzero if the target dir can't be
written or the library can't be imported.
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.guidance import guidance_lib  # noqa: E402

# --- Sample set --------------------------------------------------------------

ROLES = ["condenser", "dev", "architect", "tester", "librarian"]

# Leaf context files (get_context, recursive) — instruction + knowledge kinds.
CONTEXT_LEAVES = [
    "instr_operational_handoff",
    "ref_tools_manifest",
    "ref_directory_structure",
    "rules_development",
    "perspective_operating_principles",
]

# Bootstrap: the global 'base' composition. Try both the bare name and the
# context.db-style qualified id so we see which resolves.
BOOTSTRAP = ["base", "global:base"]

HOW_TO = ["how to delegate work", "commit conventions", "operational handoff"]

GET_KNOWLEDGE = ["ref_directory_structure", "ref_tools_manifest"]


def _write(out_dir: Path, name: str, text: str) -> None:
    (out_dir / name).write_text(text if text is not None else "<None>", encoding="utf-8")


def _capture(out_dir: Path, name: str, fn) -> None:
    try:
        txt = fn()
    except Exception as e:  # noqa: BLE001 — record per-sample failures as data
        txt = "[HARNESS-ERROR] {}: {}".format(type(e).__name__, e)
    _write(out_dir, name, txt)


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/guidance_baseline")
    out_dir.mkdir(parents=True, exist_ok=True)

    L = guidance_lib

    for r in ROLES:
        _capture(out_dir, "role__{}.txt".format(r),
                 lambda r=r: L.handle_get_role({"name": r}, L.get_db()))

    for ref in CONTEXT_LEAVES:
        _capture(out_dir, "ctx__{}.txt".format(ref),
                 lambda ref=ref: L.assemble_context(ref, L.get_db(), L.LOAD_RECURSIVE))

    for ref in BOOTSTRAP:
        _capture(out_dir, "bootstrap__{}.txt".format(ref.replace(":", "_")),
                 lambda ref=ref: L.assemble_context(ref, L.get_db(), L.LOAD_RECURSIVE))

    for q in HOW_TO:
        _capture(out_dir, "howto__{}.txt".format(q.replace(" ", "_")),
                 lambda q=q: L.handle_how_to({"query": q}, L.get_db()))

    for t in GET_KNOWLEDGE:
        _capture(out_dir, "knowledge__{}.txt".format(t),
                 lambda t=t: L.handle_get_knowledge({"topics": [t]}, L.get_db()))

    _capture(out_dir, "reminders.txt", lambda: L.handle_remind_me(L.get_db()))

    print("Wrote {} sample outputs to {}".format(len(list(out_dir.glob('*.txt'))), out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
