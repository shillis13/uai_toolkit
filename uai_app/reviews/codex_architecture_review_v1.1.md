# Codex Architecture Re-Review: UAI Architecture Spec v1.1

**Review date:** 2026-04-22  
**Reviewer:** Codex  
**Primary target:** `architecture/uai_architecture_v1.1.md`  
**Baseline:** `reviews/codex_architecture_review_v1.md`  
**Method:** Re-reviewed v1.1 against original findings F01-F16, then scanned for new regressions/ambiguities introduced by the revision.

---

## Verdict: REQUEST CHANGES — much improved, but not clean yet

v1.1 is a major improvement over v1.0. The document is no longer just a vision document; it now contains real protocols for store synchronization, sagas, command envelopes, notification lifecycle, action context, quality gates, performance, observability, and safety. Most v1 findings are either resolved or close enough to move into Phase 0A contract work.

However, I would **not** mark v1.1 approved as the implementation-driving architecture yet. There are still a few contract-level contradictions, especially around session identity. The biggest remaining issue is that v1.1 claims alignment with `spec_session_identity v5.3` while still contradicting it on Tracking ID timestamp semantics, registry slimness, `sessionInfo` filename, and selected field ownership.

The revised verdict is therefore:

- **Architecture direction:** approve.
- **v1.1 as final worker build spec:** request changes.
- **v1.1 as input to Phase 0A Contract Freeze:** approve, with the required fixes below folded into Phase 0A before broad implementation.

---

## Summary by Original Finding

| Finding | v1.1 Status | Assessment |
|---|---|---|
| **F01** Session Identity | **Partially resolved — still blocking** | `cod` fixed and three-store split added, but timestamp semantics still conflict with v5.3; registry is not slim; `sessionInfo.{uuid8}.json` conflicts with v5.3 `sessionInfo.json`; `project_dir` mutability conflicts. |
| **F02** Store Sync | **Resolved** | Two-channel change model, signal contract, revisions, snapshots, refresh rules, and saga protocol added. Needs only slice completeness follow-up. |
| **F03** Renderer/Main/Store Authority | **Resolved** | Dovetailed authority model and component conventions now make command bus the domain mutation path. |
| **F04** Entity Model | **Mostly resolved** | Namespaced IDs, relationship metadata, folder/view/tag distinction added. Minor gaps remain around tag table naming and relationship orphan status. |
| **F05** Component Self-Description | **Resolved** | Schema, safety, side effects, pre/postconditions, context, events, async semantics added. |
| **F06** Command Bus | **Mostly resolved** | Command/result shape now strong enough. Remaining issue: command registry/schema location and `payload: Record<string, any>` should be tightened in Phase 0A. |
| **F07** Access Control | **Partially resolved** | Capabilities and safety classes added, but capability taxonomy is too coarse and misses entity/store-specific scopes. |
| **F08** Events/Notifications | **Mostly resolved** | Durable lifecycle added. Remaining issue: storage authority and ack/retry worker details need finalization. |
| **F09** AI Comms | **Resolved** | Structured request/response added; unrealistic reroute claim removed. Prompt-default risks are reduced, not eliminated. |
| **F10** Hooks | **Partially resolved** | Capability matrix added, but Claude hook semantics and Codex/Gemini prompt injection guarantees still need empirical validation. |
| **F11** UI Context | **Resolved** | ActionContextProvider replaces parent-chain service locator. |
| **F12** Testing | **Resolved** | Quality gates, contract tests, E2E fixtures, packaged smoke tests added. |
| **F13** Migration | **Resolved** | Phase 0A/0B/1A/1B/1C/1D ordering added; migration plan much better. |
| **F14** Observability | **Resolved** | Logging schema, destinations, debug inspection added. |
| **F15** Performance | **Resolved** | Backpressure, high-frequency throttling, many-session scaling, JSONL strategy added. |
| **F16** Security/Safety | **Partially resolved** | Threat model added, but shell command safety and embedded AI scopes need more concrete enforcement rules. |

Resolution count:

- **Resolved / mostly resolved:** 12 findings
- **Partially resolved:** 4 findings — F01, F07, F10, F16
- **Still open outright:** 0 findings, but F01 remains contract-blocking because it contradicts the cited source of truth.

---

## Detailed Finding Disposition

## F01 — Session Identity

**Original severity:** Critical  
**v1.1 status:** **Partially resolved — still blocking**

### What v1.1 fixed

- Codex platform code corrected to `cod` rather than `cdx`.
- Independent state axes are now cleanly separated.
- Draft lifecycle gained `failed` and `orphaned` states.
- Draft ID lifecycle rules were added.
- Three-store field ownership is explicit.

### What remains wrong

v1.1 says it aligns with `spec_session_identity v5.3`, but it still contradicts it in several places.

#### 1. Tracking ID timestamp semantics still conflict

v1.1 says:

> Timestamp in Tracking IDs use local time for human readability.

`spec_session_identity_current.md` v5.3 says:

> Timestamp is UTC launch time.

This was one of the exact v1.0 findings. v1.1 partially corrected UTC for internal timestamps, but not for the Tracking ID itself. If v1.1 intentionally changes Tracking ID timestamp semantics, it must say it **supersedes** v5.3. It cannot simultaneously claim alignment.

**Required fix:** choose one:

- Keep v5.3: Tracking ID timestamp is UTC.
- Supersede v5.3: write/update `spec_session_identity_current.md` and migration/compat notes.

I recommend preserving v5.3 UTC. Human readability is not worth identity ambiguity across timezone/DST boundaries.

#### 2. Registry is not actually slim

v5.3 registry schema is explicitly slim:

```sql
tracking_id, cli_session_id, platform, terminal_session, session_dir, project_dir, history_file
```

v1.1 SQLite registry includes:

- `display_name`
- `role`
- `spawned_by`
- `archived`
- `identity_status`
- `tags`

That may be a valid UAI evolution, but then call it an evolution, not alignment. The current text says “aligns with the slim registry model” while expanding the registry.

**Required fix:** distinguish:

- **identity registry fields** — v5.3 slim contract;
- **SQLite indexed metadata fields** — UAI additions, query/index layer;
- **source of truth** for each indexed field.

For example, `display_name` can be SQLite-owned if that is the new contract, but the spec must say v5.3 is extended and identify who else reads/writes it.

#### 3. `sessionInfo.{uuid8}.json` conflicts with v5.3

v5.3 path is:

```text
{session_dir}/sessionInfo.json
```

v1.1 changes this to:

```text
sessionInfo.{uuid8}.json
```

This may follow the broader per-instance naming convention in the AI root system, but it is not in the cited v5.3 spec. Again: either update v5.3 or preserve `sessionInfo.json` with compatibility fallback.

**Recommended fix:** use helper resolution:

- writer writes canonical v5.3 `sessionInfo.json` until v5.4 is approved;
- reader may also check discriminated `sessionInfo.{uuid8}.json` as forward-compatible fallback, or vice versa after spec update.

#### 4. `project_dir` mutability conflict

v5.3 says `project_dir` is immutable. v1.1 field table marks `project_dir` mutable.

**Required fix:** decide whether project root can change. If yes, it is no longer the launch/session identity project root and needs a separate mutable `working_dir`/`current_project_dir` or relationship to Project entity. My recommendation: keep `project_dir` immutable; use relationships for project reassignment.

### F01 final disposition

**Partial. Still blocking.** Do not delegate implementation against identity fields until this is reconciled.

---

## F02 — Store Sync / External Ground Truth

**Original severity:** Critical  
**v1.1 status:** **Resolved**

v1.1 imports the essential concrete machinery:

- two-channel change notification (`onStoreChanged`, `onRuntimeChanged`);
- `StoreChangedEvent` with sequence, commandId, changed slices, revisions, snapshots;
- change detection by source;
- renderer refresh rules;
- SQLite signal contract;
- multi-store saga protocol with startup repair.

This addresses the core problem. Remaining follow-up is slice completeness: `StoreSlice` currently includes `sessions | folders | appState | briefs | groups`. v1.1 adds Projects, Teams, notifications, logs, and maybe app configuration/design tokens. Either those need slices, or they need documented ownership under existing slices.

**Disposition:** Resolved, with new minor issue N02 below.

---

## F03 — Renderer/Main/Store Authority

**Original severity:** Critical  
**v1.1 status:** **Resolved**

v1.1’s “Dovetailed Authority” principle and component conventions are much clearer:

- renderer holds snapshots;
- components read synchronously from snapshots;
- domain mutations dispatch commands;
- main process mutates authoritative stores;
- change events update renderer snapshots.

This is the correct shape. The remaining implementation requirement is to enforce this structurally: no renderer direct filesystem/SQLite writes; no component direct domain mutation methods except command aliases.

**Disposition:** Resolved.

---

## F04 — Entity Model

**Original severity:** Major  
**v1.1 status:** **Mostly resolved**

v1.1 adds:

- `EntityId` and `CardId` namespacing;
- relationship `metadata_json`, `created_by`, uniqueness key;
- inverse derivation rule;
- additional relationship types;
- conceptual model separating Folders, Views, Tags, Relationships, Teams/Projects.

Good correction.

Remaining issues:

1. `card_tags` is named and shaped for `session:`/`brief:` only, while Section 2.5 says any entity can have tags. If projects/teams/folders can be tagged, the table should be `entity_tags(entity_id, tag)` or separate `card_tags` and `entity_tags`.
2. “Deleting an entity marks its relationships as orphaned” but the relationship schema has no `status` column. Either add `status`/`deleted_at` or say orphaning is derived by missing target.
3. `assigned_to` mentions `task`, but `task` is not an `EntityType`. Either add `task` as future entity, call it freeform metadata, or remove task from the relationship description.

**Disposition:** Mostly resolved. Minor schema cleanup required.

---

## F05 — Component Self-Description

**Original severity:** Major  
**v1.1 status:** **Resolved**

v1.1’s `ComponentDescription` is substantially better:

- schema version;
- stable path;
- JSON Schema instead of TS string types;
- safety class;
- side effects;
- affected stores;
- pre/postconditions;
- idempotency;
- async/latency hints;
- context requirements;
- events;
- deprecation.

This is adequate for Phase 0A. The next step is to produce the actual JSON Schema file and contract tests.

**Disposition:** Resolved.

---

## F06 — Command Bus

**Original severity:** Major  
**v1.1 status:** **Mostly resolved**

The command envelope/result is now much stronger:

- command ID;
- actor;
- correlation ID;
- idempotency key;
- dry run;
- structured error;
- changed slices;
- snapshots;
- effect records;
- undo descriptor.

Remaining concern: `type: string` and `payload: Record<string, any>` are fine in an architecture doc, but Phase 0A must create a real command registry/schema so workers are not inventing command payloads independently.

**Required Phase 0A artifact:** `command_registry.schema.json` plus typed command definitions.

**Disposition:** Mostly resolved.

---

## F07 — Access Control

**Original severity:** Major  
**v1.1 status:** **Partially resolved**

Capabilities, actor identity, safety classification, debug expiry, and privacy notes are all good additions.

Still too coarse for implementation:

- no scopes for `briefs`, `projects`, `teams`, `tags`, `relationships`, `folders`, `notifications`, `logs`;
- `sessions:read` is broad — session metadata vs transcript vs notes vs private messages need separate scopes;
- `terminal:send` should distinguish staged prompt, submitted prompt, raw keys, shell command, kill/interrupt;
- `files:read/write` is dangerously broad and unclear inside an Electron app;
- no scoping syntax is defined, e.g. “this embedded AI can control only session X and descendants.”

Suggested capability model:

```ts
interface CapabilityGrant {
  capability: Capability;
  scope?: EntityId | EntityId[] | 'focused' | 'own-session' | 'descendants';
  expiresAt?: string;
}
```

**Disposition:** Partially resolved. Good direction, needs finer capability taxonomy before embedded AI/external API implementation.

---

## F08 — Events / Notifications

**Original severity:** Major  
**v1.1 status:** **Mostly resolved**

The NotificationRecord lifecycle addresses the original issue well:

- durable status;
- delivery/ack timestamps;
- retry count;
- TTL;
- dedupe;
- response refs.

Remaining issues:

1. Storage is ambiguous: “app-local SQLite table or JSON log.” This should be decided. Durable delivery state should be queryable and mutable; JSON log is not enough unless paired with an index/table.
2. Ack semantics need definition: what constitutes ack for prompt delivery? terminal injection? model response? explicit `comms.respond`? Those are different levels.
3. Retry worker ownership needs definition: who advances `queued -> delivering -> delivered -> failed`?

**Disposition:** Mostly resolved. Needs storage/ack finalization in Phase 0A.

---

## F09 — AI-to-AI Communication

**Original severity:** Critical  
**v1.1 status:** **Resolved**

v1.1 fixes the critical flaw:

- no more claim that app can magically detect and reroute unstructured wrong-mechanism responses;
- structured `CommsRequest`/`CommsResponse` with `messageId` and `inReplyTo`;
- durable FeedbackRequest and dueAt;
- waiting-for-response UI;
- prompt/message mechanism explicit.

Prompt-default still has interruption/context-pollution risk, but the spec now has enough structure for sane queuing and timeout behavior.

**Disposition:** Resolved.

---

## F10 — Hooks Platform Capabilities

**Original severity:** Major  
**v1.1 status:** **Partially resolved**

The capability matrix is a necessary improvement. But I would not call this fully resolved until it is empirically verified.

Concerns:

1. “Claude CLI pre-tool hook” may not equal “inject before user-submitted prompt.” Tool hooks fire around tools, not necessarily arbitrary prompt submission. Verify against actual Claude Code hook behavior.
2. “Claude can write queued prompt without accidental submission via hook injection” needs validation. Hook injection and prompt staging are not the same as terminal text staging.
3. Codex/Gemini “app injects prompts via send-keys when idle” is operationally plausible but still fragile; needs busy-state parser confidence and typed-delivery safeguards.
4. Session post-response for hookless platforms via “next poll” needs a poll cadence and false-positive policy.

**Disposition:** Partially resolved. The design is acceptable as hypothesis; Phase 0B must prove it with live fixtures.

---

## F11 — UI Context

**Original severity:** Major  
**v1.1 status:** **Resolved**

ActionContextProvider directly addresses the service-locator/parent-chain concern. Requiring components to declare context in `describe().context` and tests to verify provider presence is the correct structural fix.

**Disposition:** Resolved.

---

## F12 — Testing

**Original severity:** Major  
**v1.1 status:** **Resolved**

Quality gates, contract tests, store tests, parser fixtures, E2E terminal fixtures, and packaged app smoke testing are now present. This reflects the lessons-learned document much better.

Follow-up: Phase 0A should convert these into actual checklist files/scripts, not leave them prose-only.

**Disposition:** Resolved.

---

## F13 — Migration

**Original severity:** Major  
**v1.1 status:** **Resolved**

The build order is now dependency-ordered:

- Phase 0A contract freeze;
- Phase 0B vertical slice spike;
- Phase 1A stores/commands;
- Phase 1B core UI;
- Phase 1C organization entities;
- Phase 1D observability/gates;
- Phase 2 projects/teams/AI comms;
- Phase 3 extended.

Existing data migration is also much more explicit.

Open item: side-by-side UCI/UAI says separate app_state/folders files, but SQLite/session_store sharing policy should be stated. Can both apps write the same SQLite? If yes, signal compatibility matters. If no, migration fork policy matters.

**Disposition:** Resolved with minor follow-up.

---

## F14 — Observability

**Original severity:** Major  
**v1.1 status:** **Resolved**

Section 16 adds log schema, destinations, retention, debug inspection, and access logging. Good enough for architecture.

Follow-up: define log table schema and retention cleanup owner in Phase 0A.

**Disposition:** Resolved.

---

## F15 — Performance / Backpressure

**Original severity:** Major  
**v1.1 status:** **Resolved**

Section 17 addresses high-frequency sources, coalescing, many-session scaling, virtual list rendering, JSONL chunking, and cache invalidation. This resolves the original finding.

One caution: “screen parse visible/focused full cadence, background every 5s” may still be expensive with many sessions and tmux dump-screen calls. But this is tunable and correctly identified.

**Disposition:** Resolved.

---

## F16 — Security / Safety

**Original severity:** Major  
**v1.1 status:** **Partially resolved**

Section 19 is a good start. It acknowledges embedded AI boundaries, shell command policy, prompt injection, and external API safety.

Remaining gaps:

1. Shell destructive-command detection by strings like `rm`/`git reset` is not sufficient. Shell safety needs either an allowlist mode or a parse/explain/confirm policy. Aliases, scripts, `find -delete`, redirection, and generated commands can evade naive detection.
2. “No raw terminal escape sequence injection” needs an implementation mechanism. Escape stripping? xterm write sanitization? Shell output display sanitization?
3. External socket same-user permission is good, but if embedded AI can call external API via shell or local tools, capability boundaries can be bypassed unless shell/file scopes are enforced consistently.
4. Prompt injection section is thin. Component descriptions static is good; but transcript/content routed into embedded AI and LLLM also need untrusted-content labeling.

**Disposition:** Partially resolved. Acceptable for architecture direction, but Phase 0A should produce a concrete command safety policy.

---

## New Issues / Regressions Introduced in v1.1

## N01 — v1.1 claims identity alignment while still changing identity semantics

**Severity:** Critical  
**Related finding:** F01

This is the most important issue. The spec’s Appendix C says F01 is fixed, but Section 2.1 and 13.1 still contradict v5.3 on local-vs-UTC Tracking ID timestamps. It also changes `sessionInfo.json` naming and registry contents without updating the referenced source spec.

**Required action:** resolve before implementation.

## N02 — StoreSlice enum omits new first-class stores/entities

**Severity:** Major

`StoreSlice = 'sessions' | 'folders' | 'appState' | 'briefs' | 'groups'` predates v1.1’s Projects, Teams, notifications, logs, design tokens, and maybe parser fixtures/config.

If projects/teams are indexed into SQLite, they still need changed slices (`projects`, `teams`) so renderer tabs refresh selectively. If notification records are durable state, they need `notifications` or `comms` slices. Logs may not need renderer refresh except log panels, but then define that.

**Recommended fix:** extend slices:

```ts
type StoreSlice =
  | 'sessions' | 'briefs' | 'projects' | 'teams'
  | 'folders' | 'appState' | 'tags' | 'relationships'
  | 'notifications' | 'logs' | 'config';
```

Or document which slices are grouped under SQLite refresh and why.

## N03 — “Draft pre-population” turns session_store into a launch request queue without a schema

**Severity:** Major

v1.1 says the app writes all context-known fields at draft time and the launcher reads from the store via `--tracking-id` instead of receiving many CLI args. Good simplification, but it creates a new contract:

- where launch params live;
- which fields launcher must read;
- how launcher validates required fields;
- how non-session entities (project/team/brief) are represented at draft time;
- what happens if draft fields change while launcher is starting;
- whether launch params are immutable after pending.

`sessionInfo.launch_params` is wrapper-owned and immutable, but at draft time there is no confirmed sessionInfo. So launch params need a draft/launch_request schema in SQLite or a draft file.

**Required fix:** add `SessionLaunchRequest` / `DraftSessionContext` schema.

## N04 — `Project` and `Team` filesystem mtime indexing is underspecified

**Severity:** Major

v1.1 says Projects/Teams are indexed into SQLite with change detection via filesystem mtime. That is not enough for robust external truth:

- mtime can miss rapid edits or be coarse;
- deletion/move needs tombstones or unavailable markers;
- YAML parse errors need state;
- SQLite index must know hash/version/source path;
- signal contract for project/team API writes should be defined.

**Recommended fix:** model project/team index rows with `source_path`, `schema_version`, `content_hash`, `indexed_at`, `availability_state`, `parse_error`.

## N05 — Notification persistence location is undecided

**Severity:** Major

“app-local SQLite table or JSON log” is too vague for a system that depends on notification state for timeouts and comms. Logs are append-only; delivery state is mutable. Use SQLite for notification/comms state, plus log entries for audit.

**Required fix:** decide table-backed delivery state.

## N06 — URI protocol registration is likely incorrect/incomplete

**Severity:** Minor/Major depending on implementation timing

Section 15 says registration via `protocol.registerSchemesAsPrivileged`. For OS-level deep links like `uai://...` on macOS, Electron typically also needs `app.setAsDefaultProtocolClient('uai')` and open-url handling. `registerSchemesAsPrivileged` is for custom protocols inside Electron, not sufficient by itself for external `open uai://...` routing.

**Recommended fix:** revise URI section to include `app.setAsDefaultProtocolClient`, `open-url` event handling, single-instance lock forwarding, and URL validation.

## N07 — `CommandAccess` remains coarse and parallel to capabilities

**Severity:** Minor

`CommandDescriptor.access = public | internal | debug` overlaps awkwardly with capability-based access. Workers may implement both inconsistently.

**Recommended fix:** replace `access` with `requiredCapabilities: CapabilityRequirement[]`, or define `access` as documentation only and capabilities as enforcement.

## N08 — `groups` terminology persists despite Teams replacing groups conceptually

**Severity:** Minor

StoreSlice includes `groups`; SQLite store details mention “Groups: future expansion for team membership queries.” The entity model uses Team, not Group. If groups are legacy UCI carry-forward, define relation between Group and Team. Otherwise remove `groups` or rename to `teams`.

---

## Required Fixes Before Approval

1. **Resolve session identity contradictions.** Align Tracking ID timestamp, sessionInfo filename, registry fields, and project_dir mutability with v5.3 or explicitly publish v5.4 superseding it.
2. **Define draft launch request schema.** If launcher reads pre-populated context from store, specify exactly where/how.
3. **Finalize durable notification/comms storage.** Use a mutable table, not optional JSON log.
4. **Expand or explain StoreSlice coverage.** Projects, teams, notifications/comms, logs/config must have update paths.
5. **Refine capability scopes.** Add entity-scoped grants and finer terminal/shell/transcript/privacy capabilities.
6. **Empirically validate hook capability matrix in Phase 0B.** Especially Claude hook semantics and hookless platform idle injection.

---

## Approval Path

I do **not** think this needs another full conceptual rewrite. It needs a focused v1.1.1 or v1.2 contract cleanup.

Recommended path:

1. Fix F01/N01 first. Identity contradictions poison everything downstream.
2. Add small schemas for:
   - `SessionLaunchRequest`
   - `NotificationRecord` table
   - `StoreSlice` / change event coverage
   - `CapabilityGrant`
3. Update Appendix C dispositions from “Fixed” to “Fixed/Partial” where appropriate, or remove the appendix claim language.
4. Then proceed to Phase 0A.

After those changes, I would likely approve the architecture for implementation.

---

## Final Verdict

**Verdict:** `request-changes`

**Tone check:** This is no longer a “bad spec” review. v1.1 is strong. The remaining issues are contract hygiene, not architectural confusion. But contract hygiene is exactly what Phase 0A exists to freeze, and the identity mismatch is too central to hand-wave.

