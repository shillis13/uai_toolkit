# Development Guides & Rules — Inventory

A catalog of everything in this workspace that *governs* how development is done, so it can be
reviewed and decided on: keep, consolidate, or retire. This is an index, not a copy — each entry
is one line about what the guide governs, how binding it is, when it was last touched, and whether
it still matches reality.

**Compiled:** 2026-08-01 · **Sources scanned:** 21 `DESIGN.md` files, 26 rule files, 41 how-to
files, 50 collaboration notes, 16 perspective notes, 8 UX notes, 4 reminders, 16 templates, 3
root agent-instruction files (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`), and the `uai_toolkit`
design/docs set. Archived material (`.archive/`, `_archive/`, `archive/`) was excluded.

## Terms

- **HARD RULE** — written as a prohibition or requirement an implementer must not violate. Most
  carry an incident behind them ("this went wrong once, don't repeat it").
- **guidance** — a strong default with room for judgment; deviation should be stated, not hidden.
- **reference** — descriptive material (how a system works, a template to fill in). Not binding
  by itself, but often the thing a HARD RULE points at.
- **CURRENT / STALE** — STALE means the guide names a mechanism, path, or tool that no longer
  exists, or it contradicts a newer guide. A STALE guide may still be *mostly* right; the reason
  is given.
- **INSTR/** — shorthand for `ai_general/ai_context_files/instructions/` (paths relative to
  `~/AI/ai_root/`). Paths starting `uai_toolkit/` are relative to `~/AI/`.

## How the material is organized today (and why that's part of the problem)

There is no single place development rules live. They are spread across five mechanisms that
grew at different times:

| Mechanism | Where | What it holds | Loaded how |
|---|---|---|---|
| Agent bootstrap files | repo-root `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` | Workspace map, bootstrap steps, a few hard rules | Automatically, every session |
| `DESIGN.md` files | Beside the code they govern | Per-directory architecture constraints | Only if the agent reads it (root `CLAUDE.md` tells them to) |
| `INSTR/rules/` | Central | Short, numbered hard rules | Via role/bundle composition (`ai_profiles/`) |
| `INSTR/how_tos/` | Central | Procedures and system explainers | Via composition, or on demand |
| `INSTR/collaboration/`, `perspectives/`, `ux/` | Central | Standing corrections from PianoMan, mostly dated 2026-07-18 | Via composition |

The `INSTR/` tree is the only part with an enforced naming convention
(`ai_general/ai_context_files/DESIGN.md` defines directory → filename prefix). `DESIGN.md` files
have no index and no owner.

---

## A. Architecture & design rules — how code must be structured

These are the `DESIGN.md` files. Root `CLAUDE.md` makes reading them mandatory before modifying
anything in their directory, which effectively promotes all of them to HARD RULE status.

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `ai_general/ai_context_files/DESIGN.md` | Naming/creating context files: directory→prefix table, extensions, suffix-before-extension, per-instance discriminators, archiving via `context_mgr.py`. Opens with "NEVER create a file in a directory without first listing it." | HARD RULE | 2026-07-26 | CURRENT |
| `ai_general/ai_profiles/DESIGN.md` | The composition layer: bundles/roles/skills/globals, bare descriptive names, `.yml` only, references must be extension-less and repointed with `context_mgr.py move`/`link`. Records that the `profile` kind is retired. | HARD RULE | 2026-07-17 | CURRENT |
| `ai_general/scripts/DESIGN.md` | **The most important coding guide in the tree.** Two independent things: (1) CLI/`--help` conventions — subcommands allowed *only* for scripts that also have a REPL, `--help` must advertise every other help surface, must use `scripts/utils/standard_colors.py`, must reflow to terminal width; (2) failure signaling — a failing script must exit nonzero **and** log where/what/when, because stdout and exit code are separate channels. | HARD RULE | 2026-07-21 | CURRENT |
| `ai_general/scripts/cli/DESIGN.md` | Launcher layering: `ai_launch.py` is the only entrypoint; no vendor CLI binaries called elsewhere; substrate isolation (no tmux/zellij/PTY knowledge outside `session_mgmt/`); launcher must print `TRACKING_ID=`/`TERMINAL=`/`CLI_UUID=`. | HARD RULE | 2026-07-12 | CURRENT — records `geminiCli` retired 2026-07-12, `antigravityCli` is successor |
| `ai_general/scripts/session_mgmt/DESIGN.md` | Substrate *executes*, never returns commands for callers to run; `session_store.py` is authoritative (JSON registry reads are legacy); `session_ops.py` is the only way to send text/read terminals; **no time-based matching for session identity, ever**; tracking IDs are opaque. | HARD RULE | 2026-07-14 | CURRENT |
| `ai_general/scripts/jsonl/DESIGN.md` | `read_jsonl.py` is the canonical transcript parser — nothing parses JSONL directly; message classification rules (USER/SKILL/AGENT_RESULT/INJECTED); private-thinking blocks filtered by default; condense pipeline uses `session_ops.py`, no raw tmux. | HARD RULE | 2026-06-25 | CURRENT |
| `ai_general/scripts/lllm/DESIGN.md` | Local-model dispatch: `local` endpoints go through the request queue, **not** the plain HTTP client — collapsing that split silently drops the concurrency semaphore, queue/inference timeouts, context validation, and health check. A `local` endpoint may not name a `model`. Config rules ("nothing is built in", credentials only via env var name) are stated as security properties. Flags a known latent bug (todo_0696) it deliberately did not fix. | HARD RULE | 2026-07-30 | CURRENT |
| `ai_general/scripts/work/DESIGN.md` | The work-landscape/session-assessment tools: structural vs interpretive two-layer split, shell out to managers via `--json` rather than reading their stores, merge-never-overwrite in the assessor, `assessments.json` data contract. Contains a self-declared "architectural debt" note where Component 1 now violates its own rule. | reference + some HARD RULE | 2026-07-23 | CURRENT |
| `ai_general/scripts/cameras/DESIGN.md` | Event-driven not polling; **credentials never in config/scripts/git** (1Password → Keychain → keyring); never expose passwords in logs or displayed RTSP URLs. | HARD RULE | 2026-05-27 | CURRENT — narrow scope (cameras) but holds the only written secrets rule in the tree |
| `ai_general/data/DESIGN.md` | What may live in `data/`: subdirectories only, no loose files at root; **no log files** (all logs to `ai_general/logs/<slug>/`); no docs, no source. | HARD RULE | 2026-06-23 | CURRENT |
| `ai_general/data/hooks/DESIGN.md` | The hook framework: one dispatcher, handler naming `NN_name_{sync,async}.py`, exit-code semantics (0/1/2), `exclusions.yml` with `"*"`/`"*sync"`/`"*async"` wildcards, and a failure-signaling section mirroring `scripts/DESIGN.md` (never swallow an exception into `HookResult.allow()`). 243 lines. | HARD RULE | 2026-07-06 | Mostly CURRENT — still documents Gemini event aliases and `~/.gemini/settings.json`; Gemini CLI was retired 2026-07-12 |
| `ai_general/work/projects/uai_app/unified_ai_interface/DESIGN.md` | UAI's six architectural principles — External Ground Truth, Component API layer, Command Bus, Event System, MVC separation, and the **Data Ownership Boundary** (the app may read but never own external entity state). Plus: every text box must persist its draft. | HARD RULE | 2026-07-30 | Mostly CURRENT — Constraints section still says "Must support Claude CLI, Codex CLI, Gemini CLI" |
| `.../unified_ai_interface/packages/renderer-ui/src/components/DESIGN.md` | 15 numbered Memorex/overlay invariants (verb-line detection by structure not glyph list, unproven geometry fails covered, ordinal settlement on a persistent chain, transcript owns settled prose), plus component-selection rules: no pills for sets >5 or dynamic; view state must survive tab changes and restarts. States "PianoMan is the spec authority for Memorex — do not improve it." | HARD RULE | 2026-07-24 | CURRENT — the single most prescriptive file in the tree |
| `ai_general/work/projects/uai_app/unified_cli_interface/DESIGN.md` | UCI boundaries: call `ai_launcher.py` / `session_ops.py` / `session_store.py`, never vendor binaries or tmux directly; long-form flags only; every deployable change bumps `package.json` version; deploy to the `.mvcr4` target. | HARD RULE | 2026-06-04 | STALE — governs the *predecessor* app; UAI's own DESIGN.md calls UCI the predecessor. Keep only if UCI is still deployed |
| `ai_general/work/projects/memorex/DESIGN.md` | Standalone Memorex: zero runtime dependencies and no platform coupling in the core; two independent formatters (terminal-only vs transcript-authoritative); the marker model "must not be loosened"; five numbered invariants; tests run against compiled `dist/`. | HARD RULE | 2026-07-31 | CURRENT |
| `ai_general/work/projects/transcript/DESIGN.md` | Standalone Transcript: `read_jsonl` stays pure extraction (transformations layer on top, not inside); the data model is the COMPLETE chain with no silent narrowing fallback; **interval scope is a view setting, never a data-model setting**; the reuse boundary table (what the app may share). | HARD RULE | 2026-07-27 | CURRENT |
| `ai_general/work/projects/games/axis-and-allies/DESIGN.md` | Player vs Game Master role split and capabilities, including intent-based error correction. | reference | 2026-06-12 | CURRENT (side project) |
| `.../axis-and-allies/aagm/DESIGN.md` | REPL-first GM tool; every runtime edit forks to a new game, the original is never mutated; two planes (HTTP control, file data). | HARD RULE (in scope) | 2026-06-15 | CURRENT (side project) |
| `.../axis-and-allies/engine/DESIGN.md` | Backend data model proposal: stable unit IDs + flat registry as single source of truth; occupancy derived, not stored. 466 lines, marked "proposal / evaluation". | reference | 2026-06-14 | Status unclear — labelled proposal, never re-marked accepted |
| `ai_general/data_backup/DESIGN.md`, `ai_general/data_backup/hooks/DESIGN.md` | Byte-similar older copies of `data/DESIGN.md` and `data/hooks/DESIGN.md`. | — | 2026-05-19 | **STALE — duplicates.** Two competing copies of hook-framework rules is exactly the failure mode DESIGN.md files exist to prevent |
| `uai_toolkit/DESIGN.md` | The portable toolkit: ship-vs-install split (package read-only, `AI_ROOT` writable and never overwritten), the **Tier A/B/C portability taxonomy** (never fork whole files), one env var + `config.toml`, two-repos-two-packages, the materialize keystone (package is a derived artifact; source of truth stays in the live tree), hooks wired directly with no dir-scanning dispatcher, min Python 3.10. 182 lines. | HARD RULE | 2026-07-08 | CURRENT for the port; its Status/Roadmap section predates the current `redev/` re-design effort |
| `uai_toolkit/uai_app/DESIGN.md` | Vendored copy of the UAI app DESIGN.md. | HARD RULE | 2026-07-26 | Duplicate by design (materialized), but drifts — it lacks the "text boxes persist drafts" section present in the source copy |

---

## B. Coding standards & conventions

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `INSTR/rules/rules_development.yml` | The only general coding-standards document. Workflow (Understand → Overview → Implement), minimal-diff responses, "treat existing behavior as requirements", "state missing inputs, don't invent placeholders". Coding standards: single return per function, no nested calls in parameters, if/elseif over switch, docstrings above definition, reuse helpers, CLI color via `standard_colors.py`. Per-language guidance for Python, PowerShell, VBA, Power Query. Shell practices: `set -euo pipefail`, quote vars, `[[ ]]`, and a **heredoc prohibition** ("don't generate files that should exist" — YAML/task/config generation via heredoc is prohibited). | HARD RULE | 2026-06-24 | Mostly CURRENT, partly STALE — points at `~/bin/ai/utils/standard_colors.py` while `scripts/DESIGN.md` points at `ai_general/scripts/utils/standard_colors.py`; PowerShell/VBA/Power Query sections have no consumer in this workspace |
| `INSTR/rules/rules_python_compat.md` | Scripts invoked outside a terminal (Keyboard Maestro, launchd, cron, AppleScript) must assume system Python 3.9: `from __future__ import annotations` or no `X \| Y` unions; avoid heavy deps; lazy-import; test with `/usr/bin/python3`. | HARD RULE | 2026-07-18 | CURRENT — but note `uai_toolkit/DESIGN.md` sets min Python **3.10** for the toolkit. Different scopes, easily confused |
| `INSTR/rules/rules_file_naming_convention.md` | Script names must self-describe: kind prefix (`lib_` library, `_` internal, bare name only for a genuine executable) + domain + specialization. Never platform-only, never directory-dependent. | HARD RULE | 2026-07-18 | CURRENT — its "concrete pending application" (renaming `platform_adapters/{claude,codex,gemini,agy}.py`) may or may not have shipped |
| `INSTR/rules/rules_file_conventions.yml` | Doc pipeline (md canonical → yml → condensed), numbered directory prefixes `00-99`, file prefixes, version suffixes, size guidelines, per-instance discriminators, and "NEVER create a file in a directory without listing it first." | HARD RULE | 2026-06-24 | **STALE in part** — the `00-09 … 90-99` numbered-directory scheme it describes is the old `docs/NN_*` layout; that tree no longer exists (see Stale section). The per-instance and pre-write rules are current and duplicated in `ai_context_files/DESIGN.md` |
| `INSTR/rules/rules_writing.yml` | Documentation readability: markdown pipe tables render poorly in terminals, use ASCII box-drawing tables for terminal/CLI-facing files. Lists tooling. Has a "future_sections" stub (heading hierarchy, code blocks, line length) never filled in. | guidance | 2026-06-24 | CURRENT but unfinished |
| `INSTR/rules/rules_define_terms_before_use.md` | Expand every acronym on first use; one-line definition for coined terms; add a Terms section if several. Also codified in the global `~/.claude/CLAUDE.md`. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_capitalize_glossary_terms.md` | Capitalize a word once it becomes a domain term (Offloading, Consolidation, Bounce, Engram); plain use stays lowercase. | guidance | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_include_file_paths.md` | Every file/document reference in a response carries its full absolute path. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_timestamp_display.md` | Display in local time, store/transport in UTC; convert at the display boundary. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_snapshot_colocate_with_source.md` | JSONL snapshots/backups go in the same directory as the source file, never the repo `data/` dir; naming must avoid a bare-uuid stem. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_no_silent_alternate_flows.md` | Lock conflicts, name collisions, and "already exists" are **errors**, not alternate flows. Never silently fork, rename, or generate a new ID. Origin: a `--resume` that silently became a new session. | HARD RULE | 2026-07-18 | CURRENT — the closest thing to an error-handling policy in the rules set |
| `INSTR/how_tos/instr_km_scripting.md` | Keyboard Maestro shell-script gotchas: always `exit 0` on success, `%TriggerValue%` doesn't work inside scripts, system Python is 3.9. | reference | 2026-07-18 | CURRENT (narrow) |
| `INSTR/how_tos/instr_schema_evolution_guide.md` | JSON Schema evolution: `$ref`/`$defs` composition, backward vs forward compatibility, breaking vs non-breaking, when to version. 369 lines. | reference | 2026-06-24 | Appears CURRENT; no recent consumer identified |
| `uai_toolkit/docs/design_ts_paths_pattern.md` | The `paths.ts` standard — one module for path/env resolution, replacing 17 hand-rolled `getAiRoot()` copies and 41 hardcoded `/opt/homebrew` fragments in `uai_app/main`. Marked "standard / reference impl", approved but **not landed**. | HARD RULE once adopted | 2026-07-13 | CURRENT but unimplemented — an accepted standard with no enforcement |
| `uai_toolkit/docs/audit_abspaths_uai_app.md`, `audit_abspaths_everything_else.md` | Inventories of absolute paths the scrubber does not rewrite; classifies benign fallback / false positive / owner-scoped. | reference | 2026-07-12 | Point-in-time audits, not living rules |

---

## C. Process rules — git, commits, todos, versioning, build/deploy, testing, review

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `INSTR/how_tos/instr_git_guardian_development.md` | **Developers may not run git mutation commands.** Read-only git is allowed; `add/commit/push/pull/merge/rebase/reset/checkout/stash pop/…` are restricted and must be routed via `git_guardian request` (alias `gg`). "Do not bypass hooks. Do not retry blocked commands." | HARD RULE | 2026-06-24 | Marked "draft implementation target" since creation — status ambiguous, and it directly contradicts §E `feedback_commit_autonomously` |
| `INSTR/how_tos/instr_git_guardian_role.md` | The Guardian side: ten core axioms (preservation beats curation; PianoMan should not need git commands; no destructive recovery without approval; no polling loops), repo sync, devTree lifecycle. 231 lines. | HARD RULE (for that role) | 2026-07-24 | CURRENT and actively maintained |
| `INSTR/rules/rules_todo_trailer_and_status_notes.md` | Every commit body carries a `Todo: todo_XXXX` trailer written by hand (the `--todo` flag to Git Guardian did not produce one); every todo status change carries a real note naming what shipped, the commit, and files. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_reference_todos_by_id.md` | Reference todos by persistent `todo_####_slug`, never the transient `TR#` display handle (it renumbers). | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/perspectives/perspective_work_awareness.md` | The principle: **all meaningful work is captured as a todo**, and planned/assigned work links to a todo *before* it starts. | HARD RULE | 2026-06-24 | CURRENT |
| `INSTR/how_tos/instr_todo.md` | The procedure behind that principle: where todos live (`ai_general/work/todos/todo_NNNN_slug/`), parent/child as physical nesting, tooling. Explicitly supersedes a v1.0 that framed todos as out-of-scope backlog only. | HARD RULE | 2026-07-03 | CURRENT — but the repo-root `CLAUDE.md` still points at `ai_general/todos/`, which does not exist |
| `INSTR/rules/rules_build_after_every_change.md` | Every completed unit of UAI work is built and deployed before it is reported done — per completion, not per file. Prohibits ending a turn with "this will be in the next build." | HARD RULE | 2026-07-18 | **Partly STALE** — its five-step procedure (manual `electron-forge package` + `rsync -a --delete`) is superseded by `uai.sh`, which two other guides say to use |
| `INSTR/rules/rules_deploy_gate_is_build_not_wip.md` | The deploy gate is "does it build clean," not "is there uncommitted work from other sessions." Names `ai_general/scripts/ui/uai.sh` and its flags, including `--no-launch`. | HARD RULE | 2026-07-18 | CURRENT (`uai.sh` verified to exist) |
| `INSTR/rules/rules_version_bump_build_increment_default.md` | Version bumps default to the **build/patch element only**. Never choose `--minor`/`--major`/`--set` on your own judgment — only when a todo specifies it or PianoMan says so. Build version ≠ commit version. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/rules/rules_version_on_deploy.md` | Always state the deployed version number when telling the user to restart. | HARD RULE | 2026-07-20 | CURRENT |
| `INSTR/rules/rules_dont_kill_user_app.md` | Never `pkill` the user's running UAI instance; launch a separate copy for testing. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/how_tos/instr_testing.md` | How to verify: the testing ladder (static → build & deploy → automated tests → live/manual). Core principle: a typecheck passing is not verification; state exactly what you ran. | HARD RULE | 2026-06-24 | CURRENT — but presents `--minor`/`--major` as ordinary options without the §C prohibition |
| `INSTR/how_tos/spec_quality_gate_hierarchy.md` | Checkpoint → MVP → MVCR → Acceptance, progressively stringent, no level skippable, with written attestation. Origin: gates 2 and 3 passed with 322 green tests and 5 reviewer approvals while the app showed placeholder divs. | HARD RULE | 2026-07-12 | Header still says **Status: Draft** despite being the response to the project's worst failure |
| `INSTR/how_tos/instr_test_instance_hidden.md` | Test UAI instances must be invisible: `UAI_ALLOW_MULTI=1 UAI_TEST_OFFSCREEN=1 UAI_LAUNCHED_BY=$AI_TRACKING_ID`, all three. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/how_tos/instr_test_instance_multi.md` | No single-instance lock; deploy test builds to a separate `.app` path. Never rename `package.json` to make a dev build. | HARD RULE | 2026-07-18 | CURRENT — overlaps the file above |
| `INSTR/how_tos/instr_self_verify_uai_cdp.md` | Verify UAI UI changes yourself over the CDP port at `127.0.0.1:9226` (DOM + IPC) rather than asking PianoMan to look. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/how_tos/instr_devtools_element_picker.md` | For any visual bug, use the DevTools element picker first, before analyzing data streams or rendering pipelines. | guidance | 2026-07-18 | CURRENT |
| `INSTR/how_tos/instr_decomposition.md` | Method: find natural boundaries, test independence, define interfaces (including what happens when the contract is violated), determine order. | guidance | 2026-06-24 | CURRENT |
| `INSTR/how_tos/instr_tradeoff_analysis.md` | Method: define the decision, ≥2 options, criteria, evaluate specifically, **name the sacrifice** for each option. | guidance | 2026-06-24 | CURRENT |
| `INSTR/how_tos/instr_activity_logging.md` | Every session keeps a narrative activity log — goals and outcomes, not tool calls. Header notes its compliance rubric is still a TODO. | guidance | 2026-06-24 | Unclear whether still practiced |
| `INSTR/how_tos/instr_feedback.md` | Out-of-scope observations go to `ai_general/logs/feedback.md` in a fixed format. | guidance | 2026-07-08 | File exists; low apparent traffic |
| `INSTR/how_tos/instr_workstate_tracking.md` | Per-agent progress files in `ai_general/workstate/` via the `mcp-tasks` server, registered before any work. | HARD RULE as written | 2026-07-08 | **Likely STALE** — describes fixed role files (`cli_dev_lead.md`, `cli_tester.md`…) from a role model the workspace has since replaced with teams and todos; overlaps `instr_todo` and `instr_activity_logging` |
| `INSTR/templates/` (16 files) | Fill-in templates: `design_template.md`, `implementation_template.md`, `testing_template.md`, `peer_review_template.md`, `acceptance_template.md`, `planning_template.md`, `planning_mid_dev_template.md`, `integration_template.md`, `execution_log_template.md`, `report_final_template.md`, `architecture_decision_record.md`, `doc_audit_scan/remediate_template.md`, `cli_task_session_aware.md`, `task_file_header_template.md`, `TODO.txt`. | reference | all 2026-06-24 | Assume STALE until proven otherwise — every one is dated the same day, they use `{{REQ_ID}}` / `workflow_gen_task` / dev-lead role framing from the older task-coordination model |
| `uai_toolkit/redev/TEMPLATE.md` | The standard for the current re-development design docs: what a `_subsystem_design.md` must contain (purpose, capabilities, integration contracts, data & config, decisions + why, hard-won constraints, **user-interface conventions**, **persistence & state model**). Distinguishes Essential from Incidental. | HARD RULE for redev | 2026-08-01 | CURRENT — the newest and most deliberate process document in either repo |

---

## D. Communication & collaboration rules

Fifty files in `INSTR/collaboration/`, almost all stamped 2026-07-18 (a bulk migration date, not
the date the rule was learned). Each is a standing correction from PianoMan with a *Why* and a
*How to apply*. They are guidance in tone but PianoMan treats several as retention-critical.
Grouped rather than listed one-per-row, since the value of reviewing them is in the clusters.

| Cluster | Files | Governs | Force |
|---|---|---|---|
| **Act, don't ask** | `feedback_dont_ask_just_do`, `feedback_dont_ask_just_proceed`, `feedback_just_do_low_risk_fixes`, `feedback_progress_over_permission`, `feedback_ship_dont_checkpoint`, `feedback_dont_stop_keep_going`, `feedback_own_decisions_dont_punt`, `feedback_no_blind_technical_menus`, `feedback_reversible_naming_pick_convention`, `feedback_execution_approach`, `feedback_no_work_avoidance`, `feedback_dependency_is_not_a_blocker` | Known problem + confident fix + low risk → just do it. Don't hand PianoMan bare A/B/C option lists. Don't park at natural breaks. A blocked sub-part doesn't block the feature — stub it and ship the rest. | HARD RULE in aggregate (PianoMan has escalated repeatedly) |
| **Plain communication** | `feedback_communication_plain_no_friction` (marked retention-critical), `feedback_plain_terminology`, `feedback_match_communication_register`, `feedback_reexplain_dont_assume_recall`, `feedback_dont_narrate_refusals`, `feedback_stop_at_technical_answer`, `feedback_attribute_dont_absorb` | Plain words, no coined terms, no walls of text, never a bare-id reference, don't narrate your own guardrails, don't over-apologize. | HARD RULE |
| **Design and implementation discipline** | `feedback_design_before_code`, `feedback_design_means_implement`, `feedback_no_silent_design_changes`, `feedback_never_implement_against_stated_position`, `feedback_precision_vs_latitude`, `feedback_evaluate_user_suggestions`, `feedback_default_to_live_not_observe` | Update the design doc before coding; a design is expected to get built; disclose any substitution; when a finding contradicts PianoMan's stated position, stop and reconcile before acting; unhedged instructions are followed exactly. | HARD RULE |
| **Review and commit process** | `feedback_close_review_loop`, `feedback_codex_standing_reviewer`, `feedback_no_manufactured_rereview`, `feedback_commit_autonomously`, `feedback_test_after_changes`, `feedback_brief_note_session_work`, `feedback_track_at_assigned_granularity` | Route design + implementation reviews to a named Codex session; include callback instructions with any dispatched work; PianoMan reviews once, don't manufacture re-review gates; commit and push autonomously and broadly. | HARD RULE |
| **Multi-session conduct** | `feedback_prefer_subagent_execution`, `feedback_sessions_have_purpose_not_disposable`, `feedback_resumed_session_only_knows_now`, `feedback_self_context_management_autonomy`, `feedback_display_not_backend_is_the_constraint`, `feedback_guardrails_are_stops_not_puzzles` | Prefer subagent execution; never call a session disposable; a resumed session has no memory of its pre-bounce state; context tools are yours to use unasked; **a firing guardrail is a stop, not a puzzle to route around**. | HARD RULE |
| **Cost and priority model** | `feedback_fixed_rate_dollars_near_bottom`, `feedback_filesize_vs_disk_and_priorities`, `feedback_offload_two_benefits` | Fixed-rate plan: token cost is near the bottom of priorities. Disk usage is not a concern; per-file size is. Never dismiss an offload as "nothing to do". | guidance with hard edges |
| **Relational / tone** | `feedback_questions_not_attacks`, `feedback_feelings_include_fairness`, `feedback_genuine_i_dont_understand`, `feedback_private_thinking`, `feedback_not_visual_thinker`, `feedback_avoid_askuserquestion_tool` | Pointed questions are Socratic, not attacks. "I don't understand X" beats manufacturing an answer. Don't use the multiple-choice tool for open-ended design. PianoMan is not a visual thinker — build then react. | guidance |
| **Misc / narrow** | `feedback_cli_statusline_git_branch`, `feedback_enforce_dont_instruct`, `feedback_no_manufactured_rereview`, `feedback_no_code_ownership` (filed under rules) | `enforce_dont_instruct` is the meta-rule and worth surfacing: **when compliance matters, build enforcement into infrastructure rather than relying on instructions.** | guidance |

Also in `INSTR/rules/` but collaboration in nature:

| Path | Governs | Force | Modified |
|---|---|---|---|
| `INSTR/rules/rules_no_code_ownership.md` | No session owns code. Coordinate concurrent *writes* (anti-clobber, Git Guardian); never defer to a presumed owner. | HARD RULE | 2026-07-18 |
| `INSTR/rules/rules_never_destructive_on_siblings.md` | Never send `/compact`, `/clear`, kill, or any state-altering command to another session without explicit user approval. "This is not a use-judgment situation." | HARD RULE | 2026-07-18 |
| `INSTR/rules/rules_no_mass_fleet_actions_from_single_diagnosis.md` | A problem diagnosed on one session does not justify a fleet-wide sweep, even when approved. Confirm scope, test on one, check how it looks to the user. | HARD RULE | 2026-07-18 |
| `INSTR/rules/rules_communicate_during_critical_ops.md` | For data recovery, bulk deletes, and moves: state intent AND source AND destination, then wait for confirmation. | HARD RULE | 2026-07-18 |
| `INSTR/rules/rules_model_switching.md` | Never use `/model` (it changes the global default and cascade-compacts other sessions); pass `-m` at launch instead. Includes a long verified account of resume-model behavior. 18 lines of rule, ~120 lines of forensics. | HARD RULE | 2026-07-18 |

---

## E. Judgment & evidence standards

`INSTR/perspectives/` — how to reason, not what to build. Sixteen files, most dated 2026-07-18.

| Path | Governs | Force | State |
|---|---|---|---|
| `perspective_operating_principles.md` | The umbrella document (v2.7.0, 141 lines): identity/scope, radical honesty, partnership foundations, capability boundaries. Numbered sections; §11 was folded into `rules_response_formatting`. | HARD RULE | CURRENT |
| `perspective_architectural_thinking.md` | Think in systems, boundaries, and contracts before code; identify all consumers two levels out; second-order thinking. 106 lines. | guidance | CURRENT |
| `perspective_every_declarative_needs_evidence.md` | Every declarative statement must carry evidence. Lists four confident-but-wrong claims from one session. | HARD RULE | CURRENT |
| `perspective_verify_with_real_execution.md` | Dry-runs, `--help`, and syntax checks do not verify behavior. Run it for real. | HARD RULE | CURRENT |
| `perspective_dont_conclude_before_verifying.md` | Don't convert a claim into a verdict before observing — including the user's own claim. Hold "unknown". | HARD RULE | CURRENT |
| `perspective_label_inference_vs_fact.md` | Distinguish verified fact from fluent inference; check the mechanism exists before comparing options. | HARD RULE | CURRENT |
| `perspective_no_fabricated_premises.md` | Never invent a factual premise about system behavior to justify a change, especially one that deviates from an express spec. | HARD RULE | CURRENT |
| `perspective_definitive_negatives_need_sourcing.md` | A definitive "no / not possible" needs *more* sourcing than a positive claim. | HARD RULE | CURRENT |
| `perspective_diagnose_before_executing.md` | When something failed, find the root cause before firing off a heavy command or a workaround. | HARD RULE | CURRENT |
| `perspective_explain_root_cause.md` | Every bug fix explains what *changed* to cause the problem, not just the fix. | HARD RULE | CURRENT |
| `perspective_measure_before_claiming_reclaim.md` | Never claim a context reclaim worked without measuring; verify writes actually took. | HARD RULE | CURRENT |
| `perspective_iterate_filters_not_search_space.md` | When a filter narrows candidates to zero, fix the filter — don't abandon the pool. | guidance | CURRENT |
| `perspective_progress_not_rushing.md` | The reconciliation note: "progress over permission" means don't *wait*, not don't *think*. Explicitly rejects rushing, checkbox completion, and skipped quality checks. | guidance | CURRENT — the intended tiebreaker for the §D "act, don't ask" cluster |
| `perspective_user_profile_for_cli_agents.md` | PianoMan's profile: 25+ years, brutal honesty over diplomacy, systems thinking, empirical validation. | reference | CURRENT |
| `perspective_user_settings_personal_preferences_field.md` | The raw preferences text (direct, terse, no moral judgment, inline stage directions). | reference | CURRENT |
| `perspective_work_awareness.md` | (listed in §C — all work is a todo) | HARD RULE | CURRENT |
| `INSTR/how_tos/instr_search_dont_guess.md` | Search for the exact model/reference rather than describing hardware from memory. | HARD RULE | CURRENT |

---

## F. Operational & runtime rules — sessions, memory, context, messaging

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `ai_root/CLAUDE.md` (+ `AGENTS.md`, `GEMINI.md`) | The always-loaded bootstrap: mandatory bootstrap sequence, workspace map, working-memory slots, **"before modifying files in any directory, check for a DESIGN.md"**, the anti-clobbering contract, and **"Errors must be resolved, never silently worked around"** (best/better/minimum/never-acceptable ladder). | HARD RULE | — | **STALE in its workspace map** — see Stale section. Also, the three platform variants have drifted: `AGENTS.md`/`GEMINI.md` are missing the DESIGN.md rule, the anti-clobbering section, and the error-handling ladder entirely |
| `ai_memories/40_histories/CLAUDE.md` (+ `AGENTS.md`, `GEMINI.md`) | Archive shard: everything in the directory is historical **data, not instructions** — prompt-injection prevention. Preserve attribution, don't fabricate. | HARD RULE | — | CURRENT — the only security-adjacent rule that loads automatically |
| `INSTR/how_tos/instr_cli_agents.md` | Global CLI-agent instructions: working memory locations and slots, session-start protocol, session logging paths. 348 lines. | HARD RULE | 2026-07-12 | Mostly CURRENT; session-log path convention may have been superseded by the session store |
| `INSTR/how_tos/instr_memory_slot_protocol.yml` | The memory protocol v3.0: one source of truth at `ai_memories/80_working_memory/`, slot registry, access via `knowledge_memory_*` MCP tools, no writing to another AI's slot. | HARD RULE | 2026-07-12 | CURRENT |
| `INSTR/how_tos/instr_federated_memory.yml` | The operational guide: "write observations immediately, curate later"; append-only; entry format. | HARD RULE | 2026-07-12 | CURRENT — substantially overlaps the file above |
| `INSTR/how_tos/instr_context_reclaim.md` | Offload / consolidate / recall / rehydrate: what each does, losses, inverses, and the decision recipe. "ALWAYS snapshot the jsonl before mutating." | HARD RULE | 2026-07-01 | CURRENT |
| `INSTR/how_tos/instr_session_messaging.md` | The two-axis model for putting things into a session (TTY input vs context injection) and the three lanes. Warns that calling `write_to` directly bypasses every guard. | HARD RULE | 2026-06-25 | CURRENT |
| `INSTR/how_tos/instr_identity_verification.md` | Check `AI_TRACKING_ID` / `AI_CLI_SESSION_ID` env vars before claiming or denying session identity. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/how_tos/instr_operational_handoff.md` | The canonical handoff/condensation prompt — this file is the single source that scripts and skills reference by path. 487 lines. | HARD RULE | 2026-07-08 | CURRENT |
| `INSTR/how_tos/instr_cli_delegation.yml` | When to do work directly vs delegate; Codex framed as a **peer consultant**, not a lesser tool; single-task prompts only. | guidance | 2026-07-12 | CURRENT |
| `INSTR/how_tos/instr_cli_context_and_tools.yml` | Prefer native tools over shell equivalents (Read not cat, Edit not sed, Grep not grep); stay at design level in architecture discussions. | guidance | 2026-07-12 | CURRENT |
| `INSTR/how_tos/instr_cli_environment_overview.yml` | Model, context window, tool inventory, MCP server list. | reference | 2026-07-12 | **STALE** — names `claude-opus-4-8` as current and lists Gemini CLI among supported platforms |
| `INSTR/how_tos/instr_audit_system.md` | The comms/tools audit stores and the file-forensics CLI. 227 lines. | reference | 2026-07-12 | CURRENT (`~/bin/ai/audit/` verified present) |
| `INSTR/how_tos/instr_history_search.md` | JSONL/history search techniques: `jgrep` → `read_jsonl` workflow. | reference | 2026-07-12 | CURRENT |
| `INSTR/how_tos/instr_team_membership.md` | Conduct as a member of a standing Team defined in `data/projects/<id>.team.yml`: read the team file first, goal, lifecycle, escalation chain. | HARD RULE | 2026-07-25 | CURRENT — newest operating model |
| `INSTR/how_tos/instr_team_role_cards.md` | What to do in each team role (lead / developer / reviewer / verifier). Absolute rule: **you never review or verify your own work.** 161 lines. | HARD RULE | 2026-07-27 | CURRENT |
| `INSTR/how_tos/protocols/protocol_response_footer.md` | Footer protocol v2.0: built programmatically by `build_footer.py` via the `sessions_get_footer` MCP tool, called as the last action of every response. Drops Persona and Chat; adds Tracking_ID, CLI_UUID, Platform, Roles, Turn, Tokens. | HARD RULE | 2026-07-12 | CURRENT — and in direct conflict with `rules_response_footer.md` (see Conflicts) |
| `INSTR/rules/rules_response_footer.md` | Footer spec v1.6.0: manual field order including Persona and Chat, the mandatory `Todo:` field whenever files changed, and the v1.5 removal of context-percentage reporting ("a self-narrated gauge induces context anxiety"). 137 lines. | HARD RULE | 2026-07-04 | **Partly STALE** — its Docs-field tier table names `10_architecture` … `70_instructions` directories that no longer exist |
| `INSTR/rules/rules_response_formatting.md` | `TO YOU: #N` markers on every user-facing section (renumbering per turn), the footer, raw absolute paths for file references, concise-and-direct output style. | HARD RULE | 2026-07-12 | **Partly STALE** — points at `ai_traits/knowledge/40_specs/spec_response_footer.latest.condensed.yml`; `ai_traits/` does not exist |
| `INSTR/rules/rules_to_you_markers.md` | The same `TO YOU` marker rule again, with the numbering-resets clarification and the note that it was passively ignored for several messages. | HARD RULE | 2026-07-18 | CURRENT but duplicative |
| `INSTR/reminders/` (4 files) | Injectable nudges: check for learnings, current datetime, response format, use the memory system. | reference | 2026-06-24 | CURRENT (mechanism-level) |
| `INSTR/how_tos/protocols/protocol_chat_pipeline.md` | The chat-history pipeline stages and directory structure. | reference | 2026-07-17 | CURRENT |
| `INSTR/how_tos/protocol_reference_pointers.md` | Reference-pointer syntax for turning 30 native memory slots into an index. | reference | 2026-07-12 | **Likely STALE** — describes Claude's native 30×200-char memory slots as the constraint; the workspace now uses the `ai_memories/80_working_memory/` slot system, and the two schema/instruction files it cites live under `../50_schemas/` and `../70_instructions/`, paths that no longer exist |
| `INSTR/how_tos/instr_use_existing_chat_pipeline.md` | Use the existing fetch/download scripts to reach Web/Desktop conversations; don't build new access paths. | HARD RULE | 2026-07-18 | **STALE** — cites `ai_general/scripts/chats/download_pending_chats.js`, which does not exist (`scripts/automation/fetch_chatHist_metaData.sh` does) |
| `INSTR/how_tos/workflow_export_recent_chats.md` | The chat-export workflow triggered by "export chats since <date>". | reference | 2026-07-17 | Depends on the same pipeline; verify before relying on it |
| `INSTR/how_tos/instr_background_app_automation.md` | Non-focus-stealing macOS app control via Hammerspoon + CDP. 269 lines. | reference | 2026-06-24 | CURRENT (macOS-only by nature) |
| `INSTR/how_tos/instr_reolink_cameras.md` | Camera hardware, network, and credential handling. | reference | 2026-06-24 | CURRENT (unrelated to development) |
| `INSTR/how_tos/instr_multi_agent_recursive_tree_prompt_readme.md` | The recursive multi-agent tree prompt pattern. 295 lines. | reference | 2026-07-12 | Dated 2025-11; no evidence of current use |
| `INSTR/how_tos/playbooks/playbook_research_orchestration.md` | Decompose → dispatch → collect → synthesize for context-heavy research. Retargeted 2026-07-12 off Gemini CLI onto subagents and `sessions_launch_agent`. | guidance | 2026-07-12 | CURRENT — a good example of a guide that was properly updated when its substrate died |

---

## G. User-interface & UX rules

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `INSTR/ux/ux_pills_only_for_stable_sets.md` | Pills only for sets whose membership rarely changes (status enum yes; projects/assignees/tags no → dropdowns). | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_more_colors_means_bold_backgrounds.md` | "More colors" means saturated, visibly different *background* colors per region, not tints on near-black. PianoMan has escalated to rejecting near-monochrome designs outright. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_overshoot_visual_adjustments.md` | First adjustment to any visual attribute deliberately overshoots. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_button_placement_mouse_travel.md` | Minimize mouse travel; "put A next to B" means B stays put. | HARD RULE | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_uai_chevron_sizes.md` | Banked sizes: section chevrons ~30–32px, inline tree carets ~17px. | reference | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_human_ui_polish.md` | UI polish nits are real requirements, not optional. | guidance | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_visual_documentation.md` | CSS diagrams with realistic simulated content beat abstract box diagrams. | guidance | 2026-07-18 | CURRENT |
| `INSTR/ux/ux_visual_companion.md` | Post the visual-companion URL directly instead of asking first. | guidance | 2026-07-18 | CURRENT |
| `uai_toolkit/uai_app/docs/ux_standards.md` | "Living list of cross-cutting UI rules. When a rule here conflicts with a one-off impulse, the rule wins." Currently contains exactly one rule: pills vs dropdowns. | HARD RULE | 2026-07-26 | CURRENT but nearly empty — it is a third copy of the pills rule (also in `INSTR/ux/` and the renderer-ui `DESIGN.md`) |

---

## H. Platform & portability rules

| Path | Governs | Force | Modified | State |
|---|---|---|---|---|
| `uai_toolkit/DESIGN.md` § "Platform divergence — three tiers" | Tier A inline portability fixes / Tier B `platform_compat` adapters / Tier C capability flags with graceful degradation. **Never fork whole files.** 100%-platform-bound components go behind an ABC. | HARD RULE | 2026-07-08 | CURRENT |
| `uai_toolkit/DESIGN.md` § "Ship vs install split" | Package is read-only and replaced wholesale; `AI_ROOT` instance is writable and never overwritten; no personal data in the package; credentials never in shipped config. | HARD RULE | 2026-07-08 | CURRENT |
| `uai_toolkit/DESIGN.md` § "Sync from source" | The package is a derived artifact; source of truth stays in the live tree; regenerate via `tools/materialize.py`, review the git diff. Provenance classes clean/curated/forked/native. | HARD RULE | 2026-07-08 | CURRENT — but the whole materialize model may be superseded by the `redev/` re-design |
| `uai_toolkit/DEPENDENCIES.md` | Inventory of external Python packages, system binaries, and Node requirements, with the note that `pyproject.toml` is the canonical manifest. 12KB. | reference | 2026-07-16 | CURRENT as an inventory; not a policy |
| `uai_toolkit/docs/security_questionnaire.md` | Answers to eleven security questions with code evidence (no packet capture, one AF_UNIX socket, etc.), reviewed against the tree on 2026-07-27. | reference | 2026-07-27 | CURRENT — evidence, not policy |
| `uai_toolkit/uai_app/docs/lessons-learned.md` | The UAI v3.0 post-mortem: the placeholder-div catastrophe, gates passing on "tests pass" rather than "the right tests pass", same-platform testing blind spots. The origin of the quality-gate hierarchy. | reference | — | CURRENT — high value, rarely read |
| `INSTR/rules/rules_python_compat.md` | (listed in §B) The macOS-side portability constraint: system Python 3.9 for out-of-terminal invocation. | HARD RULE | 2026-07-18 | CURRENT |

---

## Analysis

### 1. Conflicts — where two guides disagree

**C1 · Git: commit autonomously vs. never touch git. (Highest severity.)**

`INSTR/collaboration/feedback_commit_autonomously.md`:
> "Commit AND push completed work autonomously without asking; commit BROADLY — uncommitted/unpushed work is the real risk"

`INSTR/how_tos/instr_git_guardian_development.md`:
> "You may edit files and inspect Git state. You may not run restricted Git mutation commands unless you are the active Git Guardian… Do not bypass hooks. Do not retry blocked commands."
> Restricted: `git add`, `git commit`, `git push`, …

One says commit and push without being asked; the other says you may not run `git commit` at all.
Both are marked active. The Guardian doc has been marked "draft implementation target" since
2026-06-08 and never re-marked. A third position exists in `rules_todo_trailer_and_status_notes.md`,
which tells the developer to write the commit body themselves — implying the developer *is*
committing, and noting the Guardian's `--todo` flag didn't work. **This needs one answer.**

**C2 · Response footer: two active specifications with different fields and different assembly.**

`INSTR/rules/rules_response_footer.md` (v1.6.0, 2026-07-04) — field order 1..11 including
`Persona` and `Chat`, assembled by the model, "Claude MUST include this footer on every response."

`INSTR/how_tos/protocols/protocol_response_footer.md` (v2.0.0, 2026-04-30) —
> "**Dropped:** Persona, Chat… **New:** Programmatic assembly replaces manual construction."
> "AI sessions MUST call `sessions_get_footer` as the last action before finishing a response."

The protocol says v2.0 supersedes v1.3/v1.4, but the rules file is v1.6 and was modified more
recently, so version numbers and dates point in opposite directions. A third file,
`rules_response_formatting.md`, cites a fourth location (`ai_traits/…/spec_response_footer.latest.condensed.yml`)
that does not exist.

**C3 · UAI deploy procedure: manual rsync vs. the deploy script.**

`rules_build_after_every_change.md` prescribes a five-step manual procedure ending in
`rsync -a --delete` to the deploy directory. `rules_deploy_gate_is_build_not_wip.md` says:
> "**The UAI deploy script exists: `ai_general/scripts/ui/uai.sh`** (NOT in the project's
> `scripts/` — don't claim it's missing)."

and `instr_testing.md` also routes through `uai.sh --rebuild`. The manual procedure is a trap:
following it skips the version bump the other two rules require.

**C4 · Version bumping: prohibition vs. menu.**

`rules_version_bump_build_increment_default.md`: "**NEVER** pick `--minor` / `--major` / `--set`
on my own." `instr_testing.md` presents the same flags neutrally: "`--minor`/`--major`/`--set X.Y.Z`
to control". A reader of the testing guide alone would violate the rule.

**C5 · Execution mode: always subagents vs. decide per case.**

`feedback_prefer_subagent_execution`: "always choose subagent-driven execution… Don't ask."
`feedback_execution_approach`: "decide autonomously based on context usage, task needs, and review
type… choose and state your choice with brief rationale." Minor, but they cannot both be the rule.

**C6 · Act-without-asking vs. ask-before-acting.**

The largest cluster in `INSTR/collaboration/` says don't ask (`dont_ask_just_do`,
`just_do_low_risk_fixes`, `ship_dont_checkpoint`, `progress_over_permission`). Four HARD RULES say
stop and ask: `rules_communicate_during_critical_ops` ("state intent AND source AND destination,
then wait for confirmation"), `rules_never_destructive_on_siblings`, `feedback_never_implement_against_stated_position`,
and `feedback_guardrails_are_stops_not_puzzles`. `perspective_progress_not_rushing` exists to
reconcile them and does so well — but it sits in a different directory from either side and a
reader may never encounter it. **The boundary is real and defensible; it is just not stated in
the documents that need it.**

**C7 · Where todos live.**

Repo-root `CLAUDE.md`: "`ai_general/todos/` — Task tracking". That directory does not exist.
`INSTR/how_tos/instr_todo.md`: "`ai_general/work/todos/todo_NNNN_slug/`" — which does exist.
The always-loaded file is the wrong one.

**C8 · Minimum Python version.**

`rules_python_compat.md` says assume 3.9 (no `X | Y` unions). `uai_toolkit/DESIGN.md` says "Min
Python: 3.10 (pervasive `X | Y` unions)." Different scopes — the toolkit is not invoked from
Keyboard Maestro — but nothing in either document says so, and code moves between the trees.

**C9 · Table formatting.**

`rules_writing.yml` says pipe tables render poorly and to use ASCII box-drawing for terminal-facing
files. Most guides in the tree — including this one — use pipe tables. Either the rule is scoped
narrower than it reads, or near-universal non-compliance is being tolerated silently.

### 2. Gaps — development concerns with no governing guide

**G1 · Error-handling policy — partial, and only for scripts.** `ai_general/scripts/DESIGN.md`
has an excellent failure-signaling section (exit code *and* log, two independent channels), and
`data/hooks/DESIGN.md` mirrors it. `rules_no_silent_alternate_flows.md` covers one specific class
(lock/collision must error). Root `CLAUDE.md` has the "errors must be resolved, never silently
worked around" ladder for the *agent's* behavior. What does not exist anywhere: a policy for
application code — when to catch vs. propagate, what an error message must contain, whether
partial failure is allowed, retry policy, timeout policy. `rules_development.yml` offers only
"targeted try/except with actionable messages" for Python and nothing for TypeScript at all. The
UAI app and both TypeScript projects have no error-handling rule of any kind.

**G2 · Persistence and state-write discipline — no general rule.** Strong specific rules exist
(`rules_snapshot_colocate_with_source`, `data/DESIGN.md`, the UAI Data Ownership Boundary,
`session_mgmt/DESIGN.md`'s "session_store is authoritative", the assessor's "merge, never
overwrite"). But there is no general guide covering: atomic writes, concurrent writers, schema
migration for data files, backup-before-mutate as a rule rather than a per-tool habit, or which
formats are acceptable for new state. Notably, `uai_toolkit/redev/TEMPLATE.md` *demands* a
"Persistence & state model" section in every re-design doc, with the line "**State outlives
code**" — the redev process has correctly identified a gap that the governing rules never filled.

**G3 · User-interface and REPL conventions — one directory deep, and never generalized.**
`ai_general/scripts/DESIGN.md` has the only CLI conventions in the workspace (subcommands only
with a REPL, `--help` must advertise other help, standard colors, terminal-width reflow) and it
scopes itself to `ai_general/scripts/`. Nothing governs: REPL command conventions themselves
(the rule constrains when you may have a REPL but not what one must look like), JSON vs human
output, exit-code conventions beyond pass/fail, prompt/confirmation behavior, or paging. Again,
`redev/TEMPLATE.md` requires a "User-interface conventions" section per subsystem and explicitly
asks where scripts disagree with each other — treating this as an unanswered question, which it is.

**G4 · Dependency management — nothing.** No rule about adding a dependency, vetting one,
pinning versions, or where the manifest of record is. The closest artifacts are
`ai_general/DEPENDENCIES.md` and `uai_toolkit/DEPENDENCIES.md`, both inventories rather than
policies, and `rules_python_compat.md`'s narrow "avoid heavy imports that may not exist in system
Python." Nothing at all for npm/Node across three TypeScript projects.

**G5 · Testing requirements — process exists, requirement does not.** `instr_testing.md`
(how to verify), `spec_quality_gate_hierarchy.md` (when work may advance), and
`feedback_test_after_changes` (verify it runs, don't just compile) all exist. What is missing:
any rule that new code must come with tests, what coverage is expected, or when a test is required
before a change is accepted. The `memorex` and `transcript` DESIGN.md files each end with a
Testing section describing what *is* tested — a convention worth promoting, but it is a
description, not a requirement. The lessons-learned document identifies "gates passed on tests
pass, not the *right* tests pass" as a root cause, and no rule was written to address it.

**G6 · Security — almost nothing, and what exists is accidental.** The only written security
rules are: `scripts/cameras/DESIGN.md` (credentials via 1Password/Keychain/keyring, never in
config or git; never log passwords), `scripts/lllm/DESIGN.md` ("credentials are never in config"
— named as a security property), `uai_toolkit/DESIGN.md` (no personal data in the package; a
PII/secret scrub gate before any public push), and `ai_memories/40_histories/CLAUDE.md`
(prompt-injection prevention for archive content). There is no general secrets-handling rule, no
input-validation guidance, no rule about what may be logged, and nothing about the trust boundary
around agent-to-agent messages or hook input. `uai_toolkit/docs/security_questionnaire.md` is a
set of answers about the current state, not a policy for future code. For a system where agents
execute shell commands with no sandbox, this is the largest gap on the list.

**G7 · Who owns a guide.** No guide names a maintainer or a review cadence except a handful with
a "Maintainer: PianoMan" line. Nothing says what happens when a rule is superseded, which is why
C2 and C3 exist.

### 3. Likely stale — guides referencing things that no longer exist

| Guide | The problem |
|---|---|
| `ai_root/CLAUDE.md` (and `AGENTS.md`, `GEMINI.md`) | Workspace Structure names `ai_general/ai_traits/` as "source of truth content" and `ai_general/docs/` as "backwards-compat symlinks to ai_traits/". **`ai_traits/` does not exist**; `ai_general/docs/` exists but contains unrelated material (news, user_guide, an HTML diagram). It also names `ai_general/todos/`, which does not exist. This is the file every session loads first. |
| `INSTR/rules/rules_response_formatting.md` | Cites `ai_traits/knowledge/40_specs/spec_response_footer.latest.condensed.yml` — a dangling path in a dead tree. |
| `INSTR/rules/rules_response_footer.md` | Its Docs-field tier table maps `10_architecture` / `20_registries` / `30_protocols` / `40_specs` / `50_schemas` / `60_playbooks` / `70_instructions` under `ai_general/docs/`. None of those directories exist. |
| `INSTR/rules/rules_file_conventions.yml` | Its `00-09 … 90-99` numbered-directory scheme describes the same retired layout. |
| `INSTR/how_tos/protocols/protocol_reference_pointers.md` | Built around Claude's native 30×200-char memory slots; cites `../50_schemas/` and `../70_instructions/` paths that no longer exist. The workspace uses `ai_memories/80_working_memory/` instead. |
| `INSTR/how_tos/instr_use_existing_chat_pipeline.md` | Names `ai_general/scripts/chats/download_pending_chats.js` — not present. |
| `INSTR/how_tos/instr_cli_environment_overview.yml` | Names `claude-opus-4-8` as the current model and lists Gemini CLI as a supported platform; `scripts/cli/DESIGN.md` records Gemini CLI retired 2026-07-12. |
| `ai_general/data/hooks/DESIGN.md` | Still documents the Gemini event-alias map and `~/.gemini/settings.json` as one of three live platform configs. |
| `.../unified_ai_interface/DESIGN.md` | Constraints still require simultaneous support for "Claude CLI, Codex CLI, Gemini CLI". |
| `.../unified_cli_interface/DESIGN.md` | Governs the predecessor app (UCI); UAI's own DESIGN.md calls it superseded. Retire unless UCI is still deployed. |
| `ai_general/data_backup/DESIGN.md` + `data_backup/hooks/DESIGN.md` | Older duplicates of the live `data/` design files. Delete — a stale second copy of hook rules is worse than none. |
| `INSTR/how_tos/instr_workstate_tracking.md` | Describes fixed per-role workstate files (`cli_dev_lead.md`, `cli_tester.md`, `cli_custodian.md`) under a role model the workspace replaced with teams (`instr_team_membership`, 2026-07-25) and todos. Four of the named files exist; the rest never did. |
| `INSTR/templates/` (all 16) | All stamped 2026-06-24, all built around `{{REQ_ID}}` / `workflow_gen_task` / dev-lead task coordination. Verify any is still used before keeping. |
| `INSTR/rules/rules_development.yml` | Points at `~/bin/ai/utils/standard_colors.py` while `scripts/DESIGN.md` points at `ai_general/scripts/utils/standard_colors.py`. Its PowerShell / VBA / Power Query sections have no consumer here. |
| `INSTR/how_tos/spec_quality_gate_hierarchy.md` | Content current; header still says **Status: Draft** eighteen months after the incident that produced it. |
| `INSTR/how_tos/instr_multi_agent_recursive_tree_prompt_readme.md` | Dated 2025-11; no evidence of current use. Compare `playbook_research_orchestration.md`, which was explicitly retargeted when its substrate died — the model for how this should have been handled. |
| `uai_toolkit/DESIGN.md` § Status/Roadmap | Written for the port; the `redev/` re-design (August 2026) may have superseded the materialize-from-source model it describes. Worth an explicit note either way. |

### 4. Highest-value consolidations

**V1 · One development standard, replacing five partial ones.** `rules_development.yml` (coding
standards), `scripts/DESIGN.md` (CLI + failure signaling), `rules_python_compat.md`,
`rules_file_naming_convention.md`, and `rules_no_silent_alternate_flows.md` together are the
workspace's actual coding standard, but no single file says so and three of them are filed under
different mechanisms. Merging them — and dropping the PowerShell/VBA/Power Query sections — gives
one document an implementer can read start to finish. This is also the natural home for gaps
G1 (error handling), G3 (UI/REPL conventions), and G4 (dependencies).

**V2 · One response-format document.** `rules_response_footer.md`, `protocol_response_footer.md`,
`rules_response_formatting.md`, `rules_to_you_markers.md`, and `reminders/reminder_response_format.md`
are five files covering one topic, two of them contradicting each other (C2) and two containing
dead paths. This should be one file, and the losing version should be archived rather than left
active.

**V3 · One build-test-deploy document.** `rules_build_after_every_change`, `rules_deploy_gate_is_build_not_wip`,
`rules_version_bump_build_increment_default`, `rules_version_on_deploy`, `rules_dont_kill_user_app`,
`instr_testing`, `instr_test_instance_hidden`, `instr_test_instance_multi`, `instr_self_verify_uai_cdp`,
and `feedback_test_after_changes` are ten files describing one workflow: build → version → deploy
→ verify. They contain a real contradiction (C3) and a real trap (C4). One document with one
procedure would remove both.

**V4 · One memory/context document.** `instr_memory_slot_protocol.yml` and `instr_federated_memory.yml`
overlap substantially (both define the slot layout, both cite the manifest as authoritative);
`instr_context_reclaim.md` and `instr_cli_agents.md`'s memory section add more. Two files at most.

**V5 · One pills rule, not three.** `INSTR/ux/ux_pills_only_for_stable_sets.md`,
`packages/renderer-ui/src/components/DESIGN.md` § Pills, and `uai_toolkit/uai_app/docs/ux_standards.md`
all state the same rule from the same 2026-06-26 origin. Pick the canonical location — most likely
`INSTR/ux/` — and have the others point at it. The same applies to the two test-instance files
(`instr_test_instance_hidden` / `instr_test_instance_multi`) and to the near-duplicate
"list the directory before creating a file" rule that appears in `ai_context_files/DESIGN.md`,
`ai_profiles/DESIGN.md`, and `rules_file_conventions.yml`.

**V6 · The collaboration set needs tiering, not merging.** Fifty files of standing corrections is
not obviously too many — each records a specific incident and deleting one risks repeating it.
But they are undifferentiated: `feedback_uai_chevron_sizes` (banked pixel values) sits at the same
level as `feedback_communication_plain_no_friction` (marked retention-critical). Splitting into
two tiers — standing rules that always load vs. banked specifics retrieved on demand — would make
the set usable without losing anything. Note that `feedback_enforce_dont_instruct` argues the
whole set is the wrong mechanism: "when compliance matters, build enforcement into infrastructure
rather than relying on instructions."

**V7 · A `DESIGN.md` index.** Twenty-one files with no index, no owner, and no convention beyond
"read it before you edit here." Two are stale duplicates in `data_backup/`. One governs a
superseded app. A one-page index listing every `DESIGN.md`, what it governs, and whether it is
live would make the mechanism reviewable — and would have caught the `data_backup/` duplicates.

---

## Counts

| Category | Files |
|---|---|
| A. Architecture & design (`DESIGN.md`) | 23 (21 in `ai_root`, 2 in `uai_toolkit`) |
| B. Coding standards & conventions | 15 |
| C. Process (git, todos, versioning, build, test, review) | 22 + 16 templates |
| D. Communication & collaboration | 50 + 5 filed under `rules/` |
| E. Judgment & evidence standards | 17 |
| F. Operational & runtime | 26 + 4 reminders |
| G. User-interface & UX | 9 |
| H. Platform & portability | 7 (overlapping A/B) |
| **Distinct files catalogued** | **~185** |
| Flagged HARD RULE | ~95 |
| Flagged STALE or partly stale | 16 |
| Direct conflicts found | 9 |
| Gaps with no governing guide | 7 |
