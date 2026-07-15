---
id: directory_structure
name: Directory Structure Reference
status: active
version: 4.0.0
updated: 2026-07-09
---

# Directory Structure Reference

A map of the `~/AI/ai_root` workspace: where things live and what each area is for.
Regenerate/verify against the live tree — this is a snapshot of a moving corpus.

---

## `~/AI/ai_root/` — the workspace root

```
~/AI/ai_root/
├── ai_general/         # THE shared working repo (submodule) — scripts, apps, context-files, profiles, work
├── ai_comms/           # Inter-session messaging + prompt queues (inbox/, prompts_inbox/, comms.db)
├── ai_memories/        # Chat-history pipeline + working-memory slots (80_working_memory/), 40_histories/
├── ai_models/          # Local model weights / ModelVault (encrypted APFS)
├── ai_platforms/       # Per-platform assets
├── ai_chat_artifacts/  # Artifacts generated during chats
├── ai_story_teller/    # Studio / story-teller assets
├── logs/               # Root-level logs
├── CLAUDE.md · AGENTS.md · GEMINI.md   # Per-platform bootstrap instructions
└── ai_root.yml · ai_root_summary.md    # Workspace manifest/summary
```

Git: `ai_general` is a git **submodule**; all git writes route through **Git-Guardian**.

---

## `ai_general/` — the working repo

```
ai_general/
├── ai_context_files/   # Reusable content FOR AI (the "context files") — see below
├── ai_profiles/        # Compositions that assemble context files (globals/roles/skills/profiles)
├── apps/               # Deployed apps + MCP servers (apps/mcps/) — see below
├── scripts/            # All operational logic (the bulk of the code)
├── work/               # Work tracking: todos/, tasks/, projects/, notes/
├── data/               # Runtime data: context.db, comms/, hooks/, audit/, locks/, playbooks/, …
├── docs/               # User-facing documentation tree (docs/user_guide/)
├── prompts/ · references/ · research_and_reports/
├── workstate/          # Third-party task state (mcp-tasks)
└── logs/               # Component logs
```

### `ai_context_files/` — the two-bucket context corpus (todo_0319)

A **context file** is a single reusable content element. Two top-level kinds:

```
ai_context_files/
├── instructions/       # How to think/act (directive)
│   ├── perspectives/   #   mindsets/stances       (perspective_*)
│   ├── how_tos/        #   procedures + protocols  (instr_*; protocols/ nested)
│   ├── rules/          #   normative constraints   (rules_*)
│   ├── templates/      #   reusable scaffolds
│   └── reminders/      #   short standing nudges   (reminder_*)
├── knowledge/          # What is (descriptive)
│   ├── architecture/   #   how the system is built (arch_*)
│   ├── specs/          #   specifications          (spec_*)
│   ├── schemas/        #   data schemas            (schema_*)
│   └── reference/      #   registries, glossaries, manifests (ref_*)
├── globals/ · platforms/   # platform-scoped context
├── .drafts/            # parked/not-ready (skipped by the index)
└── _archive/           # retired (skipped by the index)
```

Semantic filename prefixes encode kind and must match the folder (`instr_`, `arch_`,
`spec_`, `schema_`, `ref_`, `rules_`, `perspective_`, `reminder_`) — see this dir's
`DESIGN.md`. The first path segment of a context id **is** the category
(`instruction:rules/rules_x`).

### `ai_profiles/` — the composition layer

A **context composition** assembles context files. Compositions cascade (profile→role→file);
files themselves are see-also only (never cascade-loaded).

```
ai_profiles/
├── <name>.yml          # profiles (roles + context files)
├── roles/              # roles (context files + sub-roles)
├── skills/             # skills (context files, trigger-driven)
├── globals/            # loaded for EVERY session (base.yml, claude_code.yml, claude_desktop.yml)
└── platforms/
```

### `apps/mcps/` — the local custom MCP servers

```
apps/mcps/
├── comms/          # messaging/coordination         (tools.yml)
├── knowledge/      # knowledge + guidance delivery   (tools.yml; guidance folded in)
├── sessions/       # session mgmt + context ops       (tools.yml)
├── workflow/       # todos/tasks/notes/playbooks       (tools.yml)
├── chat-playwright/# browser/web-chat automation (server.js; aliased "browser"/"chat")
├── shared/ · scripts/   # support
└── archive/             # retired servers
```
(`workstate` = third-party `mcp-tasks`, registered but not under `apps/mcps/`.)

### `scripts/` — operational logic (selected)

```
scripts/
├── context_files/  # context_mgr.py (context.db index) + guidance_lib/guidance_cli (delivery)
├── session_mgmt/   # session_store.py, lib_session_substrate, ai identity
├── messages/       # messaging_mgr, notify_lib, broadcast_mgr (comms engine)
├── cli/            # ai_launch.py (session launcher)
├── git_guardian/   # git_guardian.py (the only sanctioned git-write path)
├── chat_pipeline/  # 01_split … 07_append (chat-history ingestion)
├── notifications/ · callbacks/ · jsonl/ · ui/ · audit/ …
└── _archive/            # retired scripts
```

### `work/` and `data/`

```
work/
├── todos/     # backlog/project memory (todos-mgr / workflow MCP)
├── tasks/     # work packages w/ plans
├── projects/  # project entities
└── notes/     # notes (workflow_note_*)

data/
├── context.db          # the authoritative context-files index (rebuildable; reindexed on commit)
├── comms/ (comms.db)   # messaging state
├── hooks/              # hook dispatch data + stdin dumps
├── audit/ · locks/ · playbooks/ · session_briefs/ · file_access/ …
```

---

## Conventions

- **Git writes** → Git-Guardian only. **Context-file reference edits** → `context_mgr.py link/unlink/move` (never hand-edit refs).
- `_`- and `.`-prefixed dirs (`_archive/`, `.drafts/`) are **skipped by the context index**.
- Single canonical file per item; a semantic prefix encodes kind. (Optional `.condensed.yml`/`*_latest.yml` forms per `ai_context_files/DESIGN.md`.)
- `context.db` is rebuildable — a post-commit hook reindexes it when `ai_context_files/` or `ai_profiles/` change.
