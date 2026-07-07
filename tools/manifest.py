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
    "aigen": "~/AI/ai_root/ai_general",                # for shippable content corpora
}

# Content trees vendored into the package as data (shipped, then copied into
# AI_ROOT by `uai-toolkit install`). Text files (.md/.yml/.yaml/...) are scrubbed;
# EXCLUDES prune scratch/archive/binary noise. Dest is under src/uai_toolkit/.
CONTENT = [
    {"dest": "content/ai_context_files", "source": "aigen:ai_context_files"},  # knowledge base (~4.7M)
    {"dest": "content/ai_profiles",      "source": "aigen:ai_profiles"},       # composition layer (~328K)
]
CONTENT_EXCLUDE_DIRS = {"__pycache__", ".obsidian", ".claude", "node_modules", ".venv",
                        "versions", ".drafts", "_archive", "_backups", ".git"}
CONTENT_EXCLUDE_DIR_PREFIXES = ("_archive", "_backup")
CONTENT_EXCLUDE_FILES = {".DS_Store"}
CONTENT_TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".txt", ".json", ".toml", ".sql"}

# App trees vendored as SIBLINGS of src/ (repo-root dest, git-tracked, NOT Python
# package-data). The UAI Electron monorepo ships its SOURCE; node_modules restore
# via `npm ci` and build outputs are excluded. Included per PianoMan 2026-07-06:
# the toolkit is now a Python-package + Node-app monorepo.
APP_TREES = [
    {"dest": "uai_app", "source": "aigen:work/projects/uai_app/unified_ai_interface"},
]
APP_EXCLUDE_DIRS = CONTENT_EXCLUDE_DIRS | {".vite", "dist", "out", "UAI.app", ".turbo", "coverage"}
APP_EXCLUDE_FILES = {".DS_Store", "activity_log.txt"}
APP_TEXT_SUFFIXES = CONTENT_TEXT_SUFFIXES | {".ts", ".tsx", ".js", ".jsx", ".mjs",
                                             ".cjs", ".css", ".scss", ".html", ".d.ts"}

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

    # ---- Expansion (2026-07-07): substrate + coordination layer ----
    # session_mgmt/*  (both `from X` and bare `import X` forms)
    (r"\bfrom (session_store|store|lib_session|lib_uri|lib_session_substrate|lib_session_activity|lib_session_identity|lib_identity_display|session_ops|session_mgr|build_footer|send_slash_command|compact_auth|get_comms_id|discover_sessions|session_context_registry|tag_mgr)\b",
     r"from uai_toolkit.session_mgmt.\1"),
    (r"^(\s*)import (session_store|store|lib_session|lib_uri|lib_session_substrate|lib_session_activity|lib_session_identity|lib_identity_display|session_ops|session_mgr|build_footer|send_slash_command|compact_auth|get_comms_id|discover_sessions|session_context_registry|tag_mgr)\b",
     r"\1from uai_toolkit.session_mgmt import \2"),
    # callbacks
    (r"\bfrom callback_lib\b", "from uai_toolkit.callbacks.callback_lib"),
    (r"^(\s*)import callback_lib\b", r"\1from uai_toolkit.callbacks import callback_lib"),
    # messages
    (r"\bfrom (messaging_mgr|messaging|messages_lib|comms_index|broadcast|broadcast_mgr|prompt_blocks|lib_reply_rule|lib_identity_resolve|recipient_uris|notify_lib)\b",
     r"from uai_toolkit.messages.\1"),
    (r"^(\s*)import (messaging_mgr|messaging|messages_lib|comms_index|broadcast|broadcast_mgr|prompt_blocks|lib_reply_rule|lib_identity_resolve|recipient_uris|notify_lib)\b",
     r"\1from uai_toolkit.messages import \2"),
    # scheduling
    (r"\bfrom (launchd_backend|scheduled_task_mgr)\b", r"from uai_toolkit.scheduling.\1"),
    (r"^(\s*)import (launchd_backend|scheduled_task_mgr)\b", r"\1from uai_toolkit.scheduling import \2"),
    # tasks
    (r"\bfrom (task_coord_lib|task_coord_cli)\b", r"from uai_toolkit.tasks.\1"),
    (r"^(\s*)import (task_coord_lib|task_coord_cli)\b", r"\1from uai_toolkit.tasks import \2"),
    # context_files (authoring/index side; guidance_* stay in guidance/)
    (r"\bfrom (context_mgr|trait_mgr|generate_frontmatter)\b", r"from uai_toolkit.context_files.\1"),
    (r"^(\s*)import (context_mgr|trait_mgr|generate_frontmatter)\b", r"\1from uai_toolkit.context_files import \2"),
    # cli/*
    (r"\bfrom (lib_paths|lib_cli_common|lib_orchestrator|lib_cli_wrapper|lib_session_mgr|lib_agent_ops|lib_brief_loading|stage_context|fork_into_dir|find_jsonl_transcript|load_context)\b",
     r"from uai_toolkit.cli.\1"),
    (r"^(\s*)import (lib_paths|lib_cli_common|lib_orchestrator|lib_cli_wrapper|lib_session_mgr|lib_agent_ops|lib_brief_loading|stage_context|fork_into_dir|find_jsonl_transcript|load_context)\b",
     r"\1from uai_toolkit.cli import \2"),
    # utils leftovers + lib -> common_utils
    (r"\bfrom (lib_clean_text|repl_base|colors)\b", r"from uai_toolkit.common_utils.\1"),
    (r"^(\s*)import (lib_clean_text|repl_base)\b", r"\1from uai_toolkit.common_utils import \2"),
    (r"\bfrom utils\.lib_clean_text\b", "from uai_toolkit.common_utils.lib_clean_text"),
    # hooks common libs
    (r"\bfrom (lib_hook_base|lib_stop_hooks|lib_context_load|lib_hook_scripts|lib_offload_metrics|dump_stdin)\b",
     r"from uai_toolkit.hooks.common.\1"),
    (r"^(\s*)import (lib_hook_base|lib_stop_hooks|lib_context_load|lib_hook_scripts|lib_offload_metrics|dump_stdin)\b",
     r"\1from uai_toolkit.hooks.common import \2"),
    # out-of-scope-but-required deps pulled in as siblings
    (r"\bfrom audit\.lib_audit\b", "from uai_toolkit.audit.lib_audit"),
    (r"\bfrom coordination\.(feed_lib|feed_identity)\b", r"from uai_toolkit.coordination.\1"),
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
    # scan_registry.py = ported with semantic rewiring (packaged schema, mcps/git
    # guards); curated so a source change surfaces as a sidecar, never clobbers.
    {"dest": "guidance/scan_registry.py",             "source": "ai:context_files/scan_traits_registry.py",    "kind": "curated"},
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

    # ---- Expansion per-file entries (2026-07-07) ----
    # utils/lib leaves folded into common_utils
    {"dest": "common_utils/repl_base.py",       "source": "ai:lib/repl_base.py",             "kind": "clean"},
    {"dest": "common_utils/lib_clean_text.py",  "source": "ai:utils/lib_clean_text.py",      "kind": "clean"},
    {"dest": "common_utils/colors.py",          "source": "ai:utils/colors.py",              "kind": "clean"},
    # required-but-out-of-scope deps (session_ops + hooks import these) — pulled as siblings
    {"dest": "audit/lib_audit.py",              "source": "ai:audit/lib_audit.py",           "kind": "clean"},
    {"dest": "coordination/feed_lib.py",        "source": "ai:coordination/feed_lib.py",     "kind": "clean"},
    {"dest": "coordination/feed_identity.py",   "source": "ai:coordination/feed_identity.py","kind": "clean"},
    # mcp shared framework piece needed by comms+sessions servers
    {"dest": "mcp/shared/handler_dispatch.py",  "source": "mcps:shared/handler_dispatch.py", "kind": "clean"},
    # comms + sessions MCP servers (no server deferred) — servers curated (sys.path/AI_ROOT rewire), tools.yml data
    {"dest": "mcp/comms/server.py",             "source": "mcps:comms/server.py",            "kind": "curated", "mcp_pkg": "comms"},
    {"dest": "mcp/comms/tools.yml",             "source": "mcps:comms/tools.yml",            "kind": "clean"},
    {"dest": "mcp/sessions/server.py",          "source": "mcps:sessions/server.py",         "kind": "curated", "mcp_pkg": "sessions"},
    {"dest": "mcp/sessions/tools.yml",          "source": "mcps:sessions/tools.yml",         "kind": "clean"},
    # hook system: live Python dispatcher + exclusions CLI + image-size checker
    {"dest": "hooks/dispatch.py",               "source": "aigen:data/hooks/dispatch.py",    "kind": "curated"},
    {"dest": "hooks/hook_exclusions.py",        "source": "ai:hooks/hook_exclusions.py",     "kind": "clean"},
    {"dest": "hooks/check_image_dimensions.py", "source": "aigen:data/hooks/check_image_dimensions.py", "kind": "clean"},
]

# Whole-dir globs — materialized with `--dirs`. Each expands to per-file MODULE
# entries (see materialize.expand_module_dirs): globs *.py under source, honors
# exclude/include_only, applies per-file `kind` overrides. Symlinks in source are
# excluded (their canonical targets are ported elsewhere).
MODULE_DIRS = [
    {"dest": "session_mgmt", "source": "ai:session_mgmt", "kind": "clean",
     "exclude": ["trait_mgr.py", "session_traits.py"]},               # symlinks -> context_files / session_context_registry
    {"dest": "callbacks",    "source": "ai:callbacks",    "kind": "clean"},
    {"dest": "messages",     "source": "ai:messages",     "kind": "clean",
     "exclude": ["messaging.py"]},                                    # symlink -> messaging_mgr.py
    {"dest": "scheduling",   "source": "ai:scheduling",   "kind": "clean",
     "exclude": ["install_scheduled_tasks.py", "meridian_reflection", "cadence_reflection.py"],
     "overrides": {"launchd_backend.py": "curated", "scheduled_task_mgr.py": "curated"}},  # launchd -> cron/systemd
    {"dest": "git_guardian", "source": "ai:git_guardian", "kind": "curated"},  # osascript notification
    {"dest": "tasks",        "source": "ai:tasks",        "kind": "clean",
     "exclude": ["create_topics_tasks.py"]},                          # hardcoded path, one-off
    {"dest": "context_files", "source": "ai:context_files", "kind": "clean",
     "exclude": ["guidance_cli.py", "guidance_lib.py", "scan_traits_registry.py", "test_registry.py"],
     "overrides": {"trait_mgr.py": "curated"}},
    {"dest": "cli",          "source": "ai:cli",          "kind": "clean",
     "exclude": ["archive"],
     "overrides": {"capture_uuid_playwright.py": "curated"}},          # heavy playwright dep -> optional
    {"dest": "mcp/comms/tools",    "source": "mcps:comms/tools",    "kind": "clean", "mcp_pkg": "comms"},
    {"dest": "mcp/sessions/tools", "source": "mcps:sessions/tools", "kind": "clean", "mcp_pkg": "sessions"},
    {"dest": "hooks/common",       "source": "aigen:data/hooks/common", "kind": "clean"},
    {"dest": "hooks/handlers",     "source": "aigen:data/hooks",    "kind": "clean",
     "include_only": ["Notification", "PostCompact", "PostToolUse", "PreCompact", "PreToolUse",
                      "SessionStart", "Stop", "UserPromptSubmit"]},
]
