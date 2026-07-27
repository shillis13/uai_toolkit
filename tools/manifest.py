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
CONTENT_EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".obsidian", ".claude",
                        "node_modules", ".venv", "versions", ".drafts",
                        "archive", ".archive", "_archive", "_backups", ".git"}
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
# Repo-root transient bundle emitted by an ad-hoc Vite invocation. It is not app
# source (the real main entry is app/.vite/build/index.js at build time), and it
# can inline third-party code such as js-yaml. Keep source-only materialization
# source-only even when this untracked artifact exists in the live shared tree.
APP_EXCLUDE_REL_PATHS = {"index.js"}
APP_TEXT_SUFFIXES = CONTENT_TEXT_SUFFIXES | {".ts", ".tsx", ".js", ".jsx", ".mjs",
                                             ".cjs", ".css", ".scss", ".html", ".d.ts"}

# Ordered mechanical import rewrites (regex, replacement), applied to clean +
# curated files. Specific patterns only — we deliberately do NOT blanket-rewrite
# `mcp.` so the PyPI MCP SDK imports (`from mcp.server`, `from mcp.types`) are
# left untouched. `{PKG}` is substituted with the entry's mcp package when set.
IMPORT_REWRITES = [
    # Source scripts may prepend their scripts directory when run in-place. In
    # the installed package, the same fallback points at ``uai_toolkit/`` and
    # makes its ``mcp`` subpackage shadow the third-party MCP SDK. Preserve an
    # explicitly supplied AI_SCRIPTS override, but do not synthesize a package-
    # root fallback: package imports already resolve without it.
    (
        r'^sys\.path\.insert\(0, os\.environ\.get\("AI_SCRIPTS"\) or str\(Path\(__file__\)\.resolve\(\)\.parents\[1\]\)\)$',
        '_ai_scripts = os.environ.get("AI_SCRIPTS")\nif _ai_scripts:\n    sys.path.insert(0, _ai_scripts)',
    ),
    (r"\bfrom common_utils\.", "from uai_toolkit.common_utils."),
    (r"\bfrom utils\.standard_colors\b", "from uai_toolkit.common_utils.standard_colors"),
    # text_utils + calc (pylib) vendored 2026-07-26: bare sibling / package imports -> toolkit form.
    (r"\bfrom standard_colors import\b", "from uai_toolkit.common_utils.standard_colors import"),
    (r"\bfrom file_utils\.lib_fileInput\b", "from uai_toolkit.file_utils.lib_fileInput"),
    (r"\bfrom calc\b", "from uai_toolkit.calc"),
    # shared env-var resolver: Noctis's env-migration writes `from utils.paths` in
    # source (interim, since uai_toolkit isn't on ai_general's path yet) -> toolkit form.
    (r"\bfrom utils\.paths\b", "from uai_toolkit.paths"),
    (r"\bfrom utils import paths\b", "from uai_toolkit import paths"),
    (r"\bfrom lib_readline\b", "from uai_toolkit.common_utils.lib_readline"),
    (r"\bfrom lib_outputColors\b", "from uai_toolkit.common_utils.lib_outputColors"),
    (r"\bfrom lib_dryrun\b", "from uai_toolkit.common_utils.lib_dryrun"),
    (r"\bfrom read_jsonl\b", "from uai_toolkit.jsonl.read_jsonl"),
    (r"^(\s*)import read_jsonl\b", r"\1from uai_toolkit.jsonl import read_jsonl"),
    (r"\bfrom (lib_jsonl_archive|lib_engram)\b", r"from uai_toolkit.jsonl.\1"),
    (r"^(\s*)import (lib_jsonl_archive|lib_engram)\b", r"\1from uai_toolkit.jsonl import \2"),
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
    (r"\bfrom audit\.", "from uai_toolkit.audit."),
    (r"\bfrom audit import lib_audit\b", "from uai_toolkit.audit import lib_audit"),
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
    # ---- Hook BEHAVIOR configs ----
    # MODULE_DIRS only globs *.py, so a sibling config file that a handler LOADS was
    # silently absent and the handler ran with an empty policy. Git Guardian caught
    # intent_check being inert for exactly this reason (2026-07-27). Listed here
    # per-file; kind=doc = copy + path-scrub, no import rewriting. The intent
    # config is curated only to correct its evaluator comment for the toolkit's
    # shared `intent_check` client; its policy values still match the source.
    #
    # DELIBERATELY NOT VENDORED (instance data, not code):
    #   Stop/exclusions.yml, PreToolUse/exclusions.yml,
    #   Stop/turn_digest_allowlist.yml, Stop/branch_index_allowlist.yml
    #     — these list REAL session tracking IDs (personal data). Per DESIGN.md the
    #       package carries no personal data; they belong in the user's AI_ROOT.
    #   common/quality_gate_endpoints.json
    #     — a live endpoint chain. This package ships NO endpoints by design.
    {"dest": "hooks/handlers/Stop/intent_without_action.config.yml",
     "source": "aigen:data/hooks/Stop/intent_without_action.config.yml", "kind": "curated"},
    {"dest": "hooks/handlers/Stop/stop_gate.config.yml",
     "source": "aigen:data/hooks/Stop/stop_gate.config.yml",             "kind": "doc"},
    {"dest": "hooks/handlers/Stop/todo_audit.config.json",
     "source": "aigen:data/hooks/Stop/todo_audit.config.json",           "kind": "doc"},
    # declare_stop.py HARD-FAILS (raises RuntimeError) without its sibling taxonomy
    # config — not a soft degrade like the hooks above. Same *.py-only glob gap.
    {"dest": "session_mgmt/declare_stop.config.yml",
     "source": "ai:session_mgmt/declare_stop.config.yml",                "kind": "doc"},

    # ---- per-dir docs for the per-file-sourced packages (dir-glob pkgs get theirs
    #      automatically). kind=doc = copy + scrub, no import rewrite. ----
    {"dest": "jsonl/README.md",         "source": "ai:jsonl/README.md",              "kind": "doc"},
    {"dest": "memory/README.md",        "source": "ai:memories/README.md",           "kind": "doc"},
    {"dest": "history/README.md",       "source": "ai:histories/README.md",          "kind": "doc"},
    {"dest": "file_access/README.md",   "source": "ai:file_access/README.md",         "kind": "doc"},
    {"dest": "audit/README.md",         "source": "ai:audit/README.md",               "kind": "doc"},
    {"dest": "coordination/README.md",  "source": "ai:coordination/README.md",        "kind": "doc"},
    {"dest": "guidance/README.md",      "source": "ai:context_files/README.md",       "kind": "doc"},
    {"dest": "mcp/knowledge/README.md", "source": "mcps:knowledge/README.md",         "kind": "doc"},
    {"dest": "mcp/workflow/README.md",  "source": "mcps:workflow/README.md",          "kind": "doc"},
    {"dest": "mcp/comms/README.md",     "source": "mcps:comms/README.md",             "kind": "doc"},
    # curated with the toolkit's reduced, configurable-endpoint reasoning surface.
    {"dest": "mcp/sessions/README.md",  "source": "mcps:sessions/README.md",          "kind": "curated"},

    # ---- shared env-var path resolver (source-authoritative in ai_general;
    #      Noctis + Portage merged model: env>config.toml>default, platform-aware
    #      discovery, ai_root()/config()/get() accessors + AI_* constants) ----
    {"dest": "paths.py",  "source": "ai:utils/paths.py",  "kind": "clean"},
    {"dest": "ai_env.sh", "source": "ai:utils/ai_env.sh", "kind": "clean"},

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
    # text_utils (pylib) — clean_text + field_reorder + the md-table reformatters (PianoMan 2026-07-26).
    # __init__.py is a NATIVE trimmed copy (native, not materialized): the source __init__
    # eagerly imports text_formatter, which was NOT requested and isn't vendored.
    {"dest": "text_utils/clean_text.py",              "source": "pylib:text_utils/clean_text.py",              "kind": "clean"},
    {"dest": "text_utils/field_reorder.py",           "source": "pylib:text_utils/field_reorder.py",           "kind": "clean"},
    {"dest": "text_utils/md_table_reformat_shared.py","source": "pylib:text_utils/md_table_reformat_shared.py", "kind": "clean"},
    {"dest": "text_utils/md_table_reformat.py",       "source": "pylib:text_utils/md_table_reformat.py",       "kind": "clean"},
    {"dest": "text_utils/md_file_table_reformat.py",  "source": "pylib:text_utils/md_file_table_reformat.py",  "kind": "clean"},
    # file_utils — dependency of the text_utils tools (shared stdin/clipboard input helper).
    {"dest": "file_utils/__init__.py",                "source": "pylib:file_utils/__init__.py",                "kind": "clean"},
    {"dest": "file_utils/lib_fileInput.py",           "source": "pylib:file_utils/lib_fileInput.py",           "kind": "clean"},

    # ---- jsonl ----
    {"dest": "jsonl/standardized_session.py",         "source": "ai:jsonl/lib_standardized_session.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/__init__.py",   "source": "ai:jsonl/platform_adapters/__init__.py",      "kind": "clean"},
    {"dest": "jsonl/platform_adapters/common.py",     "source": "ai:jsonl/platform_adapters/common.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/agy.py",        "source": "ai:jsonl/platform_adapters/agy.py",           "kind": "clean"},
    {"dest": "jsonl/platform_adapters/claude.py",     "source": "ai:jsonl/platform_adapters/claude.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/codex.py",      "source": "ai:jsonl/platform_adapters/codex.py",         "kind": "clean"},
    {"dest": "jsonl/platform_adapters/gemini.py",     "source": "ai:jsonl/platform_adapters/gemini.py",        "kind": "clean"},
    {"dest": "jsonl/platform_adapters/grok.py",       "source": "ai:jsonl/platform_adapters/grok.py",          "kind": "clean"},
    # read_jsonl ported FAITHFULLY (2026-07-07): was curated/trimmed (archive+engram
    # amputated -858 lines); now clean+complete with its deps ported alongside, so
    # it round-trips. (PianoMan: minimize curation, port faithfully.)
    {"dest": "jsonl/read_jsonl.py",                   "source": "ai:jsonl/read_jsonl.py",                      "kind": "clean"},
    {"dest": "jsonl/lib_jsonl_archive.py",            "source": "ai:jsonl/lib_jsonl_archive.py",               "kind": "clean"},
    {"dest": "jsonl/lib_engram.py",                   "source": "ai:jsonl/lib_engram.py",                      "kind": "clean"},
    {"dest": "jsonl/scrub_files.py",                  "source": "ai:jsonl/scrub_files.py",                     "kind": "clean"},
    {"dest": "jsonl/deferred_self_compact.py",        "source": "ai:jsonl/deferred_self_compact.py",           "kind": "clean"},
    {"dest": "jsonl/resume_note.py",                  "source": "ai:jsonl/resume_note.py",                     "kind": "clean"},
    # curated 2026-07-27: the shadow path uses the independently configured
    # consolidation_summary client instead of a non-vendored scripts/lllm import.
    {"dest": "jsonl/summarizer.py",                   "source": "ai:jsonl/summarizer.py",                      "kind": "curated"},
    {"dest": "jsonl/catjsonl.py",                     "source": "ai:jsonl/catjsonl.py",                        "kind": "curated"},
    # jsonl/discovery.py = native shim (no source) — omitted.

    # ---- guidance / memory / history ----
    {"dest": "guidance/guidance_cli.py",              "source": "ai:context_files/guidance_cli.py",            "kind": "clean"},
    # guidance_lib: was curated but carries NO toolkit-unique edits — the in-place
    # was stale 06-24 source. Flipped to clean (faithful current source, consistent
    # with its clean siblings). todo_mgr stays curated (has a TODO_ROOT path edit
    # that Noctis's env-var migration will dissolve, then it flips too).
    {"dest": "guidance/guidance_lib.py",              "source": "ai:context_files/guidance_lib.py",            "kind": "clean"},
    # scan_registry.py + schema.sql REMOVED 2026-07-11 — the legacy
    # context_files_registry.db was retired; guidance_lib now reads context.db via
    # context_mgr.ContextIndex, and `uai-toolkit install` builds it with
    # `context_mgr reindex` (context_files/context_mgr.py, already vendored).
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
    {"dest": "audit/lib_audit_store.py",        "source": "ai:audit/lib_audit_store.py",     "kind": "clean"},
    {"dest": "coordination/feed_lib.py",        "source": "ai:coordination/feed_lib.py",     "kind": "clean"},
    {"dest": "coordination/feed_identity.py",   "source": "ai:coordination/feed_identity.py","kind": "clean"},
    # mcp shared framework piece needed by comms+sessions servers
    {"dest": "mcp/shared/handler_dispatch.py",  "source": "mcps:shared/handler_dispatch.py", "kind": "clean"},
    # comms + sessions MCP servers (no server deferred) — servers curated (sys.path/AI_ROOT rewire), tools.yml data
    {"dest": "mcp/comms/server.py",             "source": "mcps:comms/server.py",            "kind": "curated", "mcp_pkg": "comms"},
    {"dest": "mcp/comms/tools.yml",             "source": "mcps:comms/tools.yml",            "kind": "clean"},
    {"dest": "mcp/sessions/server.py",          "source": "mcps:sessions/server.py",         "kind": "curated", "mcp_pkg": "sessions"},
    # curated: sessions_local_llm's declarations are trimmed to the 3 tools this package
    # implements (see the MODULE_DIRS note below). A clean copy would re-advertise the
    # 7 local-server / async tools the toolkit module cannot answer.
    {"dest": "mcp/sessions/tools.yml",          "source": "mcps:sessions/tools.yml",         "kind": "curated"},
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
    # calc (pylib) — the calculator package: engine + frontends + cli (PianoMan 2026-07-26).
    # Absolute `from calc.` imports are rewritten to `from uai_toolkit.calc.`; carries its
    # own __init__.py files. Test files excluded (pytest is dev-only).
    {"dest": "calc", "source": "pylib:calc", "kind": "clean",
     "exclude": ["test_cli.py", "test_repl.py", "test_evaluate.py", "test_parser.py",
                 "test_tokenizer.py", "docs"]},
    {"dest": "session_mgmt", "source": "ai:session_mgmt", "kind": "clean",
     "exclude": ["trait_mgr.py", "session_traits.py"],                # symlinks -> context_files / session_context_registry
     # tag_mgr/build_footer: source has an importlib-by-path paths.py workaround for
     # the ai_general utils-collision that's unneeded+broken in the toolkit; hand-
     # fixed to `from uai_toolkit.paths import AI_ROOT` -> curated so we don't re-pull it.
     "overrides": {"tag_mgr.py": "curated", "build_footer.py": "curated"}},
    {"dest": "callbacks",    "source": "ai:callbacks",    "kind": "clean"},
    {"dest": "messages",     "source": "ai:messages",     "kind": "clean",
     "exclude": ["messaging.py"]},                                    # symlink -> messaging_mgr.py
    {"dest": "scheduling",   "source": "ai:scheduling",   "kind": "clean",
     "exclude": ["install_scheduled_tasks.py", "meridian_reflection", "cadence_reflection.py"],
     "overrides": {"launchd_backend.py": "curated", "scheduled_task_mgr.py": "curated"}},  # launchd -> cron/systemd
    {"dest": "git_guardian", "source": "ai:git_guardian", "kind": "curated"},  # osascript notification
    # tasks/ (task_coord) REMOVED 2026-07-11 — PianoMan flagged ai:tasks DO_NOT_PORT.
    # (todo_mgr in todo/ is unrelated, from pylib, and stays.)
    {"dest": "context_files", "source": "ai:context_files", "kind": "clean",
     # trait_mgr.py + generate_frontmatter.py EXCLUDED — obsolete traits-management
     # tools (built around the now-gone ai_traits/ dir; superseded by context_mgr /
     # context.db). Unreferenced + broken. context_files/ = context_mgr only.
     "exclude": ["guidance_cli.py", "guidance_lib.py", "scan_traits_registry.py",
                 "test_registry.py", "trait_mgr.py", "generate_frontmatter.py"]},
    {"dest": "cli",          "source": "ai:cli",          "kind": "clean",
     # gemini_*_lock: gemini SHARD subsystem, retired 2026-07-12 (source archived).
     # gemini PARSING/data-model is kept elsewhere (jsonl/platform_adapters/gemini).
     "exclude": ["archive", "gemini_mcp_lock.py", "gemini_memory_lock.py",
                 "capture_uuid_playwright.py"]},   # capture_uuid: deleted (dead recovery tool, retired 2026-07-12)
    {"dest": "mcp/comms/tools",    "source": "mcps:comms/tools",    "kind": "clean", "mcp_pkg": "comms"},
    # sessions_local_llm: CURATED — substantially rewritten for the toolkit (2026-07-27).
    # Upstream shells out to scripts/lllm/{lllm_prompt,lllm_manager}.py to drive a LOCAL
    # model server; this package ships no such server. The toolkit version routes its
    # reasoning calls through the shared per-feature client (feature "mcp_prompt"), so
    # the endpoint is configurable (locally-hosted or a hosted API) and unconfigured by
    # default. It drops the 4 server-lifecycle tools (start/stop/status/switch_model),
    # which have no meaning for an endpoint we don't run, and the async trio, which
    # needs the unvendored local request queue. Sidecar-only, so a re-sync can never
    # restore the subprocess version over it.
    {"dest": "mcp/sessions/tools", "source": "mcps:sessions/tools", "kind": "clean", "mcp_pkg": "sessions",
     "overrides": {"sessions_local_llm.py": "curated"}},
    {"dest": "hooks/common",       "source": "aigen:data/hooks/common", "kind": "clean"},
    {"dest": "hooks/handlers",     "source": "aigen:data/hooks",    "kind": "clean",
     "include_only": ["Notification", "PostCompact", "PostToolUse", "PreCompact", "PreToolUse",
                      "SessionStart", "Stop", "UserPromptSubmit"],
     # 10_force_mcp_for_context_sync: hook RETIRED in source 2026-07-11.
     "exclude": ["10_force_mcp_for_context_sync.py"],
     # hardcoded /opt/homebrew python -> AI_PYTHON (WSL); source-side migration missed these.
     # 03_quality_gate: curated 2026-07-27 — model calls use the shared per-feature
     # client with no default host and no key-derived endpoint. It contacts nothing
     # unless the operator configures the quality_gate feature in that environment.
     # 05_intent_without_action: curated — rewired from a scripts/lllm subprocess to
     # the shared per-feature LLM client (feature "intent_check").
     # 06_todo_audit: curated — the path scrub had turned its config/log paths into
     # LITERAL "$AI_ROOT/..." strings (never expanded by Python), so the log went to a
     # bogus relative path and the config was never found. Now resolver-based, and the
     # config is read from beside the handler in the package.
     "overrides": {"04_store_session_data_async.py": "curated",
                   "11_turn_digest_async.py": "curated",
                   "03_quality_gate_sync.py": "curated",
                   "05_intent_without_action_async.py": "curated",
                   "06_todo_audit_sync.py": "curated"}},
    # transitively-required dirs surfaced by the import-tail scan (port faithfully)
    # reclaim_and_stage: curated 2026-07-27 — its historical --summarizer local-llm
    # mode uses the shared consolidation_summary feature (local or hosted endpoint).
    {"dest": "session_bounce", "source": "ai:session_bounce", "kind": "clean",
     "overrides": {"reclaim_and_stage.py": "curated"}},
    # added 2026-07-12 (PianoMan): devTrees (git-worktree mgmt), notes, prompts, work.
    # projects/ deferred ("soon, not yet").
    {"dest": "devTrees", "source": "ai:devTrees", "kind": "clean"},
    {"dest": "notes",    "source": "ai:notes",    "kind": "clean"},
    {"dest": "prompts",  "source": "ai:prompts",  "kind": "clean"},
    # work_assess_sessions / work_summarize_sessions: curated — rewired from the
    # scripts/lllm subprocess to the shared per-feature LLM client (features
    # "session_assess" / "session_summarize"), each independently configurable.
    # work_landscape: curated — same scrub artifact as 06_todo_audit; MGR_DIR,
    # ASSESSMENTS_FILE and PM_DECISIONS_FILE were literal "$AI_ROOT/..." strings that
    # Python never expands, so all three resolved to bogus relative paths.
    {"dest": "work",     "source": "ai:work",     "kind": "clean",
     "overrides": {"work_assess_sessions.py": "curated",
                   "work_summarize_sessions.py": "curated",
                   "work_landscape.py": "curated"}},
    {"dest": "prompting",      "source": "ai:prompting",      "kind": "clean",
     # scheduling trio set aside (crontab redesign); macOS desktop/webui senders -> curated (Tier-C)
     "exclude": ["set_scheduled_prompt.py", "send_scheduled_prompt.py", "scheduled_prompts_daemon.py"],
     "overrides": {"lib_send_prompt_desktop.py": "curated", "lib_send_prompt_webui.py": "curated",
                   "check_desktop_busy.py": "curated", "poll_desktop_busy.py": "curated"}},
]
