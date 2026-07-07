"""Materialize manifest — the source→package map for uai_toolkit.

The toolkit is a DERIVED artifact: source of truth is the live tree
(`~/bin/ai` == `ai_general/scripts/`, `~/bin/all_languages/python/src`, and
`ai_general/apps/mcps`). `materialize.py` reads this manifest to regenerate the
curated subset, so drift becomes a reviewable `git diff` instead of silent rot.

Provenance classes (per file):
  clean    — pure port: copy + mechanical import rewrite + path scrub. The
             drift-prone bulk (this is where lib_logging silently went stale).
  curated  — source was semantically trimmed in the toolkit (stripped optional
             deps, shim swaps, hand-wired MCP subsets). Auto-copy would REGRESS
             the curation, so materialize writes a `<dest>.materialized` sidecar
             for manual diff/merge — never overwrites in place.
  forked   — toolkit deliberately diverged with an improvement absent from
             source (e.g. SQLite tracker). Skipped + flagged; back-port to
             source is the real fix.
  native   — toolkit-authored, no source. Never touched (listed for completeness
             is optional; omitted here).

Source roots are resolved by `materialize.py` from these keys.
"""

SOURCE_ROOTS = {
    "ai": "~/bin/ai",                                  # symlink -> ai_general/scripts
    "pylib": "~/bin/all_languages/python/src",
    "mcps": "~/AI/ai_root/ai_general/apps/mcps",
}

# Ordered mechanical import rewrites (regex, replacement), applied to clean +
# curated files. Specific patterns only — we deliberately do NOT blanket-rewrite
# `mcp.` so the PyPI MCP SDK imports (`from mcp.server`, `from mcp.types`) are
# left untouched. `{PKG}` is substituted with the entry's mcp package when set.
IMPORT_REWRITES = [
    (r"\bfrom common_utils\.", "from uai_toolkit.common_utils."),
    (r"\bfrom utils\.standard_colors\b", "from uai_toolkit.common_utils.standard_colors"),
    (r"\bfrom lib_readline\b", "from uai_toolkit.common_utils.lib_readline"),
    (r"\bfrom lib_outputColors\b", "from uai_toolkit.common_utils.lib_outputColors"),
    (r"\bfrom lib_dryrun\b", "from uai_toolkit.common_utils.lib_dryrun"),
    (r"\bfrom read_jsonl\b", "from uai_toolkit.jsonl.read_jsonl"),
    (r"\bfrom lib_standardized_session\b", "from uai_toolkit.jsonl.standardized_session"),
    (r"\bfrom platform_adapters\b", "from uai_toolkit.jsonl.platform_adapters"),
    (r"\bimport guidance_lib\b", "from uai_toolkit.guidance import guidance_lib"),
    (r"\bimport memory_lib\b", "from uai_toolkit.memory import memory_lib"),
    (r"\bimport search_lib\b", "from uai_toolkit.history import search_lib"),
    (r"\bfrom file_access_tracker\b", "from uai_toolkit.file_access.tracker"),
    (r"\bfrom shared\.", "from uai_toolkit.mcp.shared."),
]

# Machine-specific absolutes to scrub (materialize warns if any survive in a
# clean file — code must carry no personal paths; those belong in config.toml).
SCRUB_PATTERNS = [
    (r"/Users/shawnhillis/AI/ai_root", "$AI_ROOT"),
    (r"/Users/shawnhillis/bin/ai", "$AI_BIN"),
    (r"/Users/shawnhillis", "$HOME"),
]

# dest is relative to src/uai_toolkit/. source is "<root_key>:<relpath>".
# rename is implicit (source basename may differ from dest basename).
MODULES = [
    # ---- common_utils (all clean; lib_logging is a clean SUPERSET re-port) ----
    {"dest": "common_utils/compile_check.py",         "source": "pylib:common_utils/compile_check.py",         "kind": "clean"},
    {"dest": "common_utils/lib_argparse_registry.py", "source": "pylib:common_utils/lib_argparse_registry.py", "kind": "clean"},
    {"dest": "common_utils/lib_dryrun.py",            "source": "pylib:common_utils/lib_dryrun.py",            "kind": "clean"},
    {"dest": "common_utils/lib_fileIO.py",            "source": "pylib:common_utils/lib_fileIO.py",            "kind": "clean"},
    {"dest": "common_utils/lib_logging.py",           "source": "pylib:common_utils/lib_logging.py",           "kind": "clean"},
    {"dest": "common_utils/lib_outputColors.py",      "source": "pylib:common_utils/lib_outputColors.py",      "kind": "clean"},
    {"dest": "common_utils/lib_progressBar.py",       "source": "pylib:common_utils/lib_progressBar.py",       "kind": "clean"},
    {"dest": "common_utils/lib_readline.py",          "source": "pylib:common_utils/lib_readline.py",          "kind": "clean"},
    {"dest": "common_utils/lib_undo.py",              "source": "pylib:common_utils/lib_undo.py",              "kind": "clean"},
    {"dest": "common_utils/standard_colors.py",       "source": "ai:utils/standard_colors.py",                 "kind": "clean"},

    # ---- jsonl ----
    {"dest": "jsonl/standardized_session.py",         "source": "ai:jsonl/lib_standardized_session.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/__init__.py",   "source": "ai:jsonl/platform_adapters/__init__.py",      "kind": "clean"},
    {"dest": "jsonl/platform_adapters/common.py",     "source": "ai:jsonl/platform_adapters/common.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/agy.py",        "source": "ai:jsonl/platform_adapters/agy.py",           "kind": "clean"},
    {"dest": "jsonl/platform_adapters/claude.py",     "source": "ai:jsonl/platform_adapters/claude.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/codex.py",      "source": "ai:jsonl/platform_adapters/codex.py",         "kind": "clean"},
    {"dest": "jsonl/platform_adapters/gemini.py",     "source": "ai:jsonl/platform_adapters/gemini.py",        "kind": "clean"},
    {"dest": "jsonl/read_jsonl.py",                   "source": "ai:jsonl/read_jsonl.py",                      "kind": "curated"},
    {"dest": "jsonl/catjsonl.py",                     "source": "ai:jsonl/catjsonl.py",                        "kind": "curated"},
    # jsonl/discovery.py = native shim (no source) — omitted.

    # ---- guidance / memory / history ----
    {"dest": "guidance/guidance_cli.py",              "source": "ai:context_files/guidance_cli.py",            "kind": "clean"},
    {"dest": "guidance/guidance_lib.py",              "source": "ai:context_files/guidance_lib.py",            "kind": "curated"},
    {"dest": "memory/memory_cli.py",                  "source": "ai:memories/memory_cli.py",                   "kind": "clean"},
    {"dest": "memory/memory_lib.py",                  "source": "ai:memories/memory_lib.py",                   "kind": "clean"},
    {"dest": "history/search_cli.py",                 "source": "ai:histories/search_cli.py",                  "kind": "clean"},
    {"dest": "history/search_lib.py",                 "source": "ai:histories/search_lib.py",                  "kind": "clean"},

    # ---- todo (DESIGN corrected: pylib:todo_mgr, not ai:tasks) ----
    {"dest": "todo/todo_mgr.py",                      "source": "pylib:todo_mgr/todo_mgr.py",                  "kind": "curated"},

    # ---- file_access ----
    # tracker.py = FORKED (toolkit SQLite/WAL not in source) — skip, back-port later.
    {"dest": "file_access/tracker.py",                "source": "ai:file_access/file_access_tracker.py",       "kind": "forked"},
    # hooks.py = 3 source scripts merged 3->1; not a same-name port -> curated sidecar.
    {"dest": "file_access/hooks.py",                  "source": "ai:file_access/hook_track_read.py",           "kind": "curated",
     "merge_sources": ["ai:file_access/hook_track_read.py", "ai:file_access/hook_track_write.py", "ai:file_access/hook_check_before_write.py"]},

    # ---- mcp (servers hand-wired subsets = curated; tools/shared = clean) ----
    {"dest": "mcp/shared/subprocess_log.py",          "source": "mcps:shared/subprocess_log.py",               "kind": "clean"},
    {"dest": "mcp/shared/tool_registry.py",           "source": "mcps:shared/tool_registry.py",                "kind": "clean"},
    {"dest": "mcp/knowledge/tools/knowledge_guidance.py", "source": "mcps:knowledge/tools/knowledge_guidance.py", "kind": "clean", "mcp_pkg": "knowledge"},
    {"dest": "mcp/knowledge/tools/knowledge_jsonl.py",    "source": "mcps:knowledge/tools/knowledge_jsonl.py",    "kind": "clean", "mcp_pkg": "knowledge"},
    {"dest": "mcp/knowledge/tools/knowledge_memory.py",   "source": "mcps:knowledge/tools/knowledge_memory.py",   "kind": "clean", "mcp_pkg": "knowledge"},
    {"dest": "mcp/knowledge/tools/knowledge_search.py",   "source": "mcps:knowledge/tools/knowledge_search.py",   "kind": "clean", "mcp_pkg": "knowledge"},
    {"dest": "mcp/knowledge/server.py",               "source": "mcps:knowledge/server.py",                    "kind": "curated", "mcp_pkg": "knowledge"},
    {"dest": "mcp/workflow/tools/workflow_todo.py",   "source": "mcps:workflow/tools/workflow_todo.py",        "kind": "curated", "mcp_pkg": "workflow"},
    {"dest": "mcp/workflow/server.py",                "source": "mcps:workflow/server.py",                     "kind": "curated", "mcp_pkg": "workflow"},
]
