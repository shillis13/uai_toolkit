# Codex Architecture Review: UAI Architecture Spec v1.0

**Review date:** 2026-04-22  
**Reviewer:** Codex  
**Primary target:** `architecture/uai_architecture_v1.0.md`  
**Context read:** `gap_analysis.md`, `docs/lessons-learned.md`, `current_references/spec_session_identity_current.md`, `current_references/uci_data_architecture.md`, archived component/API and v0.2 architecture docs.

---

## Verdict: REQUEST CHANGES

This is a strong conceptual consolidation document. It captures the right strategic direction: external stores as truth, component contracts, command bus, notification bus, hooks, entity relationships, typed APIs, packaged-build testing, and a staged rebuild instead of another monolith. It is good enough as a **vision document**.

It is **not yet safe as an implementation spec**. Several foundation sections contradict current accepted references, and several critical mechanics are stated as principles rather than designed as protocols. If workers build against this as-is, they will make incompatible decisions around identity, store ownership, command execution, relationship storage, event delivery, AI communication, and renderer/main authority.

The largest risks:

1. **Session Identity section conflicts with current v5.3 source of truth.** It has the wrong Codex platform suffix (`cdx` vs `cod`), wrong timestamp semantics (local vs UTC), and a field-ownership model that conflicts with the slim registry/sessionInfo split.
2. **External Ground Truth is directionally right but under-specified.** The optimistic/draft model lacks revisions, locks, signal contracts, snapshots, reconciliation rules, and multi-store transaction semantics already captured in the UCI data architecture reference.
3. **Component API and Command Bus are not clearly separated across renderer/main/persistence boundaries.** The spec says synchronous state operations and async persistence, but also says all mutations hit external truth. Those cannot both be naively true.
4. **AI-to-AI communication enforcement is aspirational.** The app cannot reliably detect or reroute “wrong mechanism” responses unless requests/responses are structured, correlated, acked, and mediated through a durable queue.
5. **Migration plan puts too much into Phase 1 without first freezing data contracts and store protocols.** The current order invites parallel workers to build incompatible component/store/command assumptions.

I recommend revising v1.0 into v1.1 before delegating broad implementation. Phase 0 should produce a runnable spike plus frozen contracts for identity, stores, command result shape, notification envelope, and component description schema.

---

## Severity Key

- **Critical:** likely to cause wrong architecture, data loss, incompatible implementation, or rebuild failure.
- **Major:** likely to cause rework, divergence, unreliable behavior, or untestable code.
- **Minor:** localized ambiguity or missing detail that should be clarified.
- **Suggestion:** improvement, not blocking.

---

## Executive Findings

| ID | Severity | Area | Finding |
|---|---|---|---|
| F01 | Critical | Session Identity | v1.0 conflicts with `spec_session_identity_current.md` on platform suffix, timestamp semantics, registry fields, and sessionInfo ownership. |
| F02 | Critical | Data Architecture | External Ground Truth lacks the concrete revision/signal/snapshot/multi-store protocol needed to prevent divergence. |
| F03 | Critical | Command/Component Boundary | The spec says all mutations flow through component APIs, all user actions through command bus, and external truth writes immediately; authority boundaries are contradictory. |
| F04 | Major | Entity Model | Entity IDs are not namespaced; relationship storage lacks metadata/uniqueness/inverse rules; Folders/Views are missing as first-class app concepts. |
| F05 | Major | Component Self-Description | `ComponentDescription` is useful but insufficient for embedded AI: lacks schemas, examples, side effects, preconditions, safety, selectors, versioning, and async semantics. |
| F06 | Major | Command Bus | Command shape/result are too weak for async commands, multi-store mutations, undo, correlation, snapshots, structured errors, idempotency, and audit. |
| F07 | Major | Access Control | Access matrix is too coarse and unsafe for embedded AI/external API; read access is overbroad; debug mode is an all-powerful footgun. |
| F08 | Major | Events/Notifications | Internal events and cross-boundary notifications are conflated; no delivery state, ack, retry, dedupe, TTL, priority, or failure semantics. |
| F09 | Critical | AI Comms | “App detects wrong response mechanism and reroutes” is unrealistic without a structured request/response protocol. Prompt-default creates context pollution and interruption risks. |
| F10 | Major | Hooks | Hook levels are conceptually right, but platform capabilities and delivery timing are underspecified and partly inaccurate. |
| F11 | Major | UI Context | “Action queries parent chain” risks service-locator/context-spooky-action anti-pattern unless formalized as explicit context providers/selectors. |
| F12 | Major | Testing | Testing strategy misses contract-schema tests, store-reconciliation tests, notification/comms tests, and quality-gate attestation learned from the prior failure. |
| F13 | Major | Migration | Build order is too broad after Phase 0; data contracts and adapters must freeze before component teams parallelize. |
| F14 | Major | Observability | Logging/error handling are mentioned but not architected despite being a stated new requirement. |
| F15 | Major | Performance | Screen parsing, JSONL parsing, statusline updates, and many-session event storms need throttling/backpressure/cache policies. |
| F16 | Major | Security/Safety | Embedded AI, shell commands, external API, prompt injection, and terminal writes need a threat model even for single-user macOS. |

---

## Per-Section Review

## 1. Purpose & Principles

### Finding 1.1 — External Ground Truth principle is correct but currently overclaims
**Severity:** Major  
**Section:** 1, 3

“App reflects external state” is the right north star. But the spec currently says:

- all component state operations are synchronous and persistence is async/debounced;
- the app writes external stores immediately for optimistic updates;
- multiple writers are acceptable;
- no divergent copies exist.

Those can coexist only with a much stricter model:

- renderer memory is a **cache/snapshot**, not a truth store;
- command handlers in the main process are the only app writer to app-owned files;
- SQLite writes go through `session_store.py` or an equivalent single API;
- every store has revisions/change signals;
- command results include changed slices/snapshots;
- external writes are detected through signals/polling and reconciled by revision.

`current_references/uci_data_architecture.md` already has much of this. v1.0 should absorb it instead of restating a weaker version.

**Required change:** Add a “Store Synchronization Contract” subsection defining writer paths, atomic write rules, revisions, signal files, change events, stale revision handling, and startup reconciliation.

### Finding 1.2 — MVC wording may mislead React implementation
**Severity:** Minor

“MVC Separation” is useful as a discipline, but React implementations tend to drift if “Model = component state in stores” is not precise. The spec should say:

- durable domain model lives in external stores;
- renderer stores hold snapshots and UI-only state;
- components render selectors and dispatch commands;
- command handlers mutate authoritative stores through main-process services.

Otherwise workers may re-create local component-owned domain models.

---

## 2. Entity Model

### Finding 2.1 — Session field ownership conflicts with current identity spec
**Severity:** Critical  
**Sections:** 2.1, 3.3, 10  
**Evidence:** `spec_session_identity_current.md` v5.3 says the registry is a slim identity/pointer index: `tracking_id`, `cli_session_id`, `platform`, `terminal_session`, `session_dir`, `project_dir`, `history_file`. Mutable runtime metadata such as `working_dir`, `display_name`, `parent_tracking_id`, `model`, `roles`, status, etc. lives in `sessionInfo.json`.

v1.0 instead assigns several fields to SQLite:

- `display_name` → SQLite
- `role` → SQLite
- `spawned_by` → SQLite
- `model` → SQLite
- `identity_status` → SQLite
- `project_dir` mutable in SQLite

Some of these may be desired UAI changes, but then the spec must explicitly supersede v5.3. It currently says v5 is the current spec and cross-references it, so this is an unresolved contradiction.

**Required change:** Decide one canonical model:

Option A — preserve v5.3:
- SQLite registry remains slim.
- `sessionInfo.json` owns mutable per-session metadata.
- UAI indexes selected fields into SQLite only as derived/search caches with explicit reconciliation.

Option B — evolve v5.3:
- Update the session identity spec first.
- Define migration from sessionInfo-owned fields to SQLite-owned fields.
- Define conflict handling for mirrored fields.

Do not let implementation proceed with two sources of truth.

### Finding 2.2 — Session status axes are conflated
**Severity:** Major  
**Section:** 2.1, Appendix A  
**Evidence:** UCI data architecture defines three independent state axes: terminal/substrate state, interaction/runtime state, and archival state. v1.0 has `status`, `activity_state`, `identity_status`, and `SessionStatus = 'running' | 'idle' | 'stopped' | 'archived'`.

This mixes:

- terminal/process state (`running`, `stopped`)
- interaction state (`idle`, `responding`, `blocked`)
- user archival intent (`archived`)
- identity lifecycle (`draft`, `pending`, `confirmed`)

**Required change:** Define independent axes:

```ts
type IdentityStatus = 'draft' | 'pending' | 'confirmed' | 'error';
type TerminalState = 'unknown' | 'connected' | 'disconnected' | 'killed';
type RuntimeState = 'unknown' | 'running' | 'idle' | 'responding' | 'blocked' | 'error' | 'stopped';
type ArchiveState = 'active' | 'archived';
```

Then map each to owner/store/source.

### Finding 2.3 — `Session.type` reintroduces a distinction the design says is soft/eliminated
**Severity:** Major  
**Section:** 2.1, 8.6  

The spec says `type` is mutable (`chat | worker`) and stored in `app_state.json`, while the gap analysis says the workers/chat distinction is eliminated or soft. UCI data architecture says session kind is derived from role, not persisted.

Persisting `type` invites stale classification and inconsistent UI behavior. If the distinction is soft, avoid making it a core field. Use role, relationships, and team/project membership.

**Recommended change:** Replace `type` with derived selectors:

- `isInteractiveAssistant(session)`
- `isSpawned(session)`
- `roleCategory(session.role)`
- `relationshipContext(session)`

If the UI needs a manual override, store it as an app annotation, not a model axis.

### Finding 2.4 — Entity IDs are not namespaced; collision risk is real
**Severity:** Major  
**Sections:** 2.6, Appendix A  

`EntityRef` is `{ type, id }`, which is fine in memory. But folders, tags, selection sets, command payloads, and external APIs need serializable IDs. UCI data architecture solved this with namespaced `CardId` (`session:<tracking_id>`, `brief:<name>`).

v1.0 omits this and uses `Set<string>` in several APIs. This will cause collisions and ambiguity in generic list components, tags, folders, and embedded AI commands.

**Required change:** Add typed/namespaced refs:

```ts
type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder';
type EntityId = `${EntityType}:${string}`;
interface EntityRef { type: EntityType; id: string; ref: EntityId; }
```

For UI “cards,” preserve `CardId = session:<id> | brief:<id>` or generalize deliberately.

### Finding 2.5 — Relationship table lacks implementation-critical columns and rules
**Severity:** Major  
**Section:** 2.6

The relationship model is directionally correct but incomplete. It needs:

- `metadata_json` for role-in-team, launch params, review status, source command, etc.
- `created_by` / `origin` for audit.
- uniqueness key definition.
- whether inverse rows are stored or derived.
- delete/cascade behavior.
- allowed source/target matrix per relationship type.
- relationship status (`active`, `archived`, `superseded`) or timestamped edges.

UCI reference already defines an `entity_relationships` table with `metadata_json` and single-row inverse derivation. v1.0 should adopt or explicitly supersede that.

### Finding 2.6 — Relationship taxonomy is too small for Projects/Teams/Reviews
**Severity:** Major

Current pairs cover fork/brief/load/supersede/member/relates. Missing likely relationships:

- `assigned_to` / `has_assignment` — session assigned to project/task/team role.
- `reviewed` / `reviewed_by` — reviewer produced review of entity.
- `depends_on` / `blocks` — task/session dependency.
- `continues` / `continued_by` — successor session from handoff/compaction/resume.
- `owns` / `owned_by` — project owns brief/session/team artifacts.
- `implements` / `implemented_by` — session/PR implements spec/brief.
- `notifies` / `notified_by` may be better as notification logs, not relationships.

Do not add everything prematurely, but add an extensibility rule and allowed metadata.

### Finding 2.7 — Folders and Views are missing from the entity/concept model
**Severity:** Major  
**Sections:** 2, 8.4  

The spec has tags and relationships, but folders and views are core app concepts. UCI data architecture explicitly distinguishes:

- Folders = where did I put this? (`folders.json`)
- Views = computed filtered subsets, not stored
- Tags = metadata labels
- Groups/Teams = domain relationships

v1.0 mentions folders in navigator APIs but not in the model. That omission caused prior UCI confusion; do not reintroduce it.

**Required change:** Add a “Navigation/Organization Concepts” subsection defining Folder, View, Tag, Relationship, Team, Project, and their boundaries.

### Finding 2.8 — Project and Team external truth lacks indexing/versioning/reconciliation
**Severity:** Major

Projects live in devTree directories; Teams live as YAML. Fine. But the app needs search/filter/list performance and change detection.

Define:

- canonical file paths and schema versions;
- stable project/team IDs;
- how YAML is indexed into SQLite or renderer snapshots;
- who may write files;
- atomic write rules;
- how external edits are detected;
- what happens if a project dir is deleted/moved/renamed.

---

## 3. Data Architecture

### Finding 3.1 — Optimistic update/draft pattern is incomplete and may still diverge
**Severity:** Critical  
**Section:** 3.2

The five-step optimistic update flow is too high-level. If the app writes external store immediately, then what is “draft”? The draft indicator is not about persistence; it is about **confirmation by the same read path all other consumers use**. That requires revisions and command correlation.

Needed mechanics:

- each command has `commandId`;
- each store write increments a store revision or sequence;
- command result returns changed slices and snapshots;
- external change event includes `commandId`, `sequence`, `changed`, `revisions`, optional snapshots;
- renderer marks pending until it observes revision >= expected revision or receives authoritative snapshot;
- timeout/error path if no signal arrives;
- stale event handling.

This is already substantially described in UCI data architecture Section 5.3. v1.0 should import it.

### Finding 3.2 — Multi-store command consistency is missing
**Severity:** Critical

Commands like “create brief and launch,” “move session to project,” “launch team,” “archive session,” and “condense session” can touch multiple stores:

- YAML file
- SQLite metadata/relationships
- folders.json
- app_state.json
- terminal substrate
- queued prompt/notification state

The spec needs defined write order, rollback/repair policy, and startup reconciliation. UCI reference gives an example for `briefs.create`; v1.0 should generalize it.

**Required change:** Add a “Multi-Store Transactions / Sagas” section. Do not pretend these are atomic DB transactions. Define sagas with compensating repair.

### Finding 3.3 — Store details omit `sessionInfo.json` even though current identity depends on it
**Severity:** Critical

Section 3.3 lists filesystem “Session info: per-session directories with sessionInfo.json” but Section 2 ownership map mostly ignores sessionInfo. Current v5.3 relies on it. This is a spec split-brain.

**Required change:** Add `sessionInfo.json` to the ownership map and store synchronization contract, or explicitly remove it from the architecture by updating identity spec.

### Finding 3.4 — Multiple writers need a single API contract, not just “acceptable”
**Severity:** Major

Multiple writers are acceptable only if they use the same write APIs and signals. v1.0 should say:

- SQLite writers MUST use `session_store.py` or a new shared library with identical signal contract.
- Raw SQLite writes are unsupported.
- `folders.json` and `app_state.json` have one writer: app main process.
- YAML writes use atomic file write and index update.
- External tools call APIs, not mutate files directly, unless explicitly treated as out-of-band edits requiring repair.

### Finding 3.5 — Schema versioning needs store-specific placement and migration ownership
**Severity:** Major

The schema version section is good but too generic. Define:

- where each version lives (`PRAGMA user_version`, JSON top-level `schema_version`, YAML frontmatter field, sessionInfo field);
- migration script location;
- backup policy before migration;
- locking while migrating;
- behavior if one store migrates and another fails;
- test fixture expectations.

---

## 4. Component API Contracts

### Finding 4.1 — Component API should not be the only mutation path; command bus should be
**Severity:** Critical  
**Sections:** 4, 5

The principles say every UI component exposes get/set/update/delete/list and “all state inspection and mutation flows through these APIs.” Section 5 says all mutations flow through command bus. These are not the same.

Recommended architecture:

- Component API exposes **read/select/describe** and component-local UI state setters only where safe.
- Domain mutations execute **commands**.
- Commands call services/stores.
- Components update by subscribing to store snapshots/events.

If component `set()` can mutate durable state directly, the command bus is bypassed. If `set()` merely dispatches commands, then call it that and remove direct mutation semantics.

### Finding 4.2 — “All state operations are synchronous” conflicts with external truth
**Severity:** Major

Component-local reads can be synchronous against renderer snapshots. Durable mutations cannot be synchronous in Electron because they cross renderer/main/filesystem/subprocess boundaries.

Use:

```ts
get/select/list/describe -> synchronous against current snapshot
execute(command) -> Promise<CommandResult>
set/update/delete -> either local-only sync OR command aliases returning Promise
```

Be explicit per key whether it is snapshot, local UI state, or durable external state.

### Finding 4.3 — `ComponentDescription` is insufficient for embedded AI discovery
**Severity:** Major  
**Section:** 4.2

The proposed interface is a good start, but embedded AI needs more to safely operate:

- schema version for the description itself;
- stable component path and instance IDs;
- command parameter JSON Schema, not TypeScript strings;
- enum values, defaults, constraints, examples;
- side effects and affected stores;
- preconditions and postconditions;
- safety/confirmation level (`safe`, `destructive`, `requires_confirmation`);
- async/latency expectations;
- idempotency information;
- access requirements by origin;
- error codes;
- selectors/queries separate from commands;
- context contract: what parent/selection context is available;
- event subscriptions exposed by the component;
- deprecation/versioning metadata.

Without this, the embedded AI can discover names but cannot reliably know how to use them.

### Finding 4.4 — APIs use non-serializable structures and method-overloading awkwardness
**Severity:** Major

Examples:

- `get("selected_ids"): Set<string>` is not JSON-serializable. Use arrays for API boundary.
- `set("tabs.open", value)` and `execute("stage")` mix setter semantics with commands.
- Dynamic paths like `get("folders.{id}")` need escaping rules if IDs contain dots/slashes.
- `list("folders")` and `get("folders.{id}")` blur component state vs store-backed domain state.

Define a formal API transport shape even if initially in-process.

### Finding 4.5 — PromptBox API is underspecified for prompt delivery safety
**Severity:** Major

PromptBox touches the most dangerous boundary: writing to live AI terminals. Need:

- staged vs submitted distinction;
- target focus rules in grid view;
- busy-state behavior;
- queue behavior;
- cancellation/edit of queued prompts;
- prompt provenance and logging;
- pre/post addendum merge order;
- max length / truncation / file-based prompt path;
- shell mode sandbox/confirmation rules.

UCI had multiple prompt delivery bugs; this deserves a dedicated protocol.

---

## 5. Command System

### Finding 5.1 — Command shape needs IDs, async result, structured error, changed slices, snapshots
**Severity:** Major

Current shape:

```ts
interface Command { type, payload, origin, timestamp, parent_command? }
interface CommandResult { ok, previous?, effects?, error? }
```

Insufficient. Use something closer to UCI reference:

```ts
interface Command {
  id: string;
  type: CommandType;
  payload: unknown;
  origin: CommandOrigin;
  actor?: ActorRef;
  parentId?: string;
  correlationId?: string;
  idempotencyKey?: string;
  timestamp: string;
  dryRun?: boolean;
}

interface CommandResult<T = unknown> {
  ok: boolean;
  commandId: string;
  data?: T;
  error?: { code: string; message: string; details?: unknown; retryable?: boolean };
  changed?: Partial<Record<StoreSlice, boolean>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
  effects?: EffectRecord[];
  undo?: UndoDescriptor;
}
```

This is needed for debugging, replay, tests, external API, embedded AI, and optimistic confirmation.

### Finding 5.2 — Command hierarchy is missing many required command families
**Severity:** Major

Missing or underrepresented:

- `folders.*` — create/rename/delete/move/reorder/unfile/validate.
- `tags.*` — add/remove/create/update/delete.
- `relationships.*` — link/unlink/list/update metadata.
- `view.*` or `navigation.*` — folder browser, breadcrumbs, back/forward/up.
- `appState.*` — panel sizes, card display config, preferences.
- `terminal.*` — attach, detach, kill, send, dump screen, clear/copy mode.
- `transcript.*` — search, load range, select messages, export excerpt.
- `notification.*` — ack, retry, cancel, mark delivered/read.
- `comms.*` — request/response correlation, timeout scheduling, escalation.
- `debug.*` — inspect component, validate stores, repair indexes.
- `migration.*` — run/validate/back up.

The hierarchy can stay high-level in architecture, but implementation needs these categories.

### Finding 5.3 — Access control is too coarse
**Severity:** Major

Current matrix says all reads always allowed, user/internal always write/execute, embedded AI per-command whitelist, external API debug-only.

Problems:

- “Read all” exposes prompts, notes, messages, possibly private thinking/transcripts.
- `internal` can become a bypass if any compromised component or plugin dispatches internal commands.
- Debug mode granting all origins full access is unsafe and makes testing lie.
- No concept of destructive commands requiring confirmation.
- No actor/session scoping. Embedded AI should not necessarily read/control all sessions.

Add:

- capabilities/scopes (`sessions:read`, `terminal:send`, `files:write`, `app:debug`);
- command safety class;
- optional human confirmation policy;
- actor identity (`user`, `embedded-ai:<session>`, `external:<client>`);
- audit log for denied/allowed commands;
- redaction rules for reads.

### Finding 5.4 — Undo is asserted but not designed
**Severity:** Minor/Major depending on roadmap

`previous` is not enough for undo when commands touch multiple stores or external terminals. If undo is a future goal, command results need an `UndoDescriptor` and commands must declare whether undoable.

For Phase 0, mark undo as non-goal except for local UI state, or design it properly.

---

## 6. Event & Notification System

### Finding 6.1 — Internal event system lacks ownership between main and renderer
**Severity:** Major

Events are described as synchronous within renderer. But durable store changes happen in main process/filesystem/subprocesses. The architecture needs two event channels:

- renderer-local state events for UI reactivity;
- main-to-renderer store/runtime events for external changes.

UCI reference has `onStoreChanged` and `onRuntimeChanged`; v1.0 should adopt this split.

### Finding 6.2 — Notification bus needs a delivery lifecycle
**Severity:** Major

A cross-boundary notification is not just an event. It needs state:

```ts
type DeliveryStatus = 'queued' | 'delivering' | 'delivered' | 'acknowledged' | 'failed' | 'expired' | 'cancelled';
```

Required fields:

- `id`, `correlationId`, `replyTo`, `expiresAt`, `createdAt`;
- target entity/session/user/team;
- delivery mechanism requested and actual mechanism used;
- retry count/backoff;
- ack requirement;
- failure reason;
- dedupe key.

Without this, feedback timeout and AI comms enforcement cannot work.

### Finding 6.3 — Latency claims are optimistic
**Severity:** Minor

“Claude with hooks < 1 second” and Codex/Gemini “next turn” are not guarantees. State them as best-effort by adapter capability. Delivery must be measured and recorded.

---

## 7. Hooks Architecture

### Finding 7.1 — Hook mechanism descriptions need verification against actual platform capabilities
**Severity:** Major

The table says Claude `session.pre_prompt` uses “Claude Code pre-tool hook.” Pre-tool hooks are not necessarily pre-prompt hooks. Codex/Gemini have no hooks, so “app injects addendum text” is not a hook unless UAI controls the next prompt submission.

Define platform capabilities precisely:

- can inject before user-submitted prompt?
- can inject while idle without user action?
- can notify after model response completion?
- can read status/busy state?
- can write queued prompt without accidental submission?
- can distinguish staged vs submitted?

Then map hooks to mechanisms.

### Finding 7.2 — AI feedback timeout pattern is right but needs durable request records
**Severity:** Major

The pattern solves a real failure mode. But it cannot rely only on agents scheduling their own timeout. The app should also record feedback requests and monitor them.

Add `FeedbackRequest` entity/table/log:

```ts
id, requester, responder, mechanism, status, createdAt, dueAt,
timeoutAction, contentRef, responseRef, retries, escalationState
```

Then either AI self-prompt or app timeout can recover.

### Finding 7.3 — Timeout defaults need guardrails
**Severity:** Minor

300 seconds may be fine for active review; too short/long for other tasks. Define profiles:

- review: 5 min
- permission/approval: immediate + periodic reminder
- long-running work: heartbeat interval
- low-priority FYI: no timeout

---

## 8. AI-to-AI Response Mechanism Enforcement

### Finding 8.1 — “App detects wrong mechanism and reroutes” is not currently realistic
**Severity:** Critical  
**Sections:** 7.3, 12.3

If an AI replies by printing terminal output, how does the app know it is a response to a specific request? It cannot reliably infer that from unstructured terminal text. If it arrives through `messages` MCP, the app can detect it only if messages are integrated and correlated.

Required protocol:

- every request has `requestId` and `replyTo`;
- prompt to responder includes machine-readable response instructions;
- responder must call a tool/command or emit structured response marker;
- app monitors the durable response channel;
- if responder outputs unstructured terminal text, at most the app can flag “possible orphan response,” not reroute confidently.

Revise claim from “detects and reroutes” to “enforces for mediated responses; flags non-mediated responses when detectable.”

### Finding 8.2 — Prompt-default is useful but dangerous
**Severity:** Major

Prompt delivery ensures the requester processes the response, but it also:

- interrupts current work;
- pollutes context with operational chatter;
- can reorder with user prompts;
- can cause prompt storms/loops;
- can inject stale responses after timeout already resolved;
- can breach private/context boundaries if sent to wrong session.

Needed policies:

- prompt only when responder/requester is idle or when urgency requires interruption;
- queue with visible pending status;
- cancel stale queued prompts;
- coalesce multiple responses;
- include machine-readable header with request ID and urgency;
- require human/lead escalation for repeated failures.

Messages are still valuable as durable storage; prompt should be the **attention mechanism**, not necessarily the only response store.

---

## 8. UI Component Hierarchy

### Finding 8.1 — Parent-chain context query can become a hidden dependency anti-pattern
**Severity:** Major  
**Section:** 8.2

The goal is right: avoid prop-drilling. The proposed mechanism — “action queries its parent chain” — risks a service-locator pattern where any child can depend on invisible ancestor state. That is hard to test and easy to break by moving components.

Use explicit context providers/selectors instead:

```ts
ActionContextProvider value={{ entityRef, selectionScope, location }}
useActionContext(requiredKeys)
```

And include `context` in component descriptions. Tests should verify context contracts.

### Finding 8.2 — Grid View, Tab Groups, and active prompt target need a focus contract
**Severity:** Major

Grid view says each cell has its own tab and focus. Workspace API says `tabs.active` singular. PromptBox has `target_session_id`. Need a precise focus model:

- active workspace tab/group;
- active grid cell;
- focused session pane;
- prompt target session;
- terminal keyboard focus;
- selected entity in navigator.

These are related but not identical. Prior UCI prompt delivery bugs make this critical.

### Finding 8.3 — Runtime-configurable card display needs safe field registry
**Severity:** Minor

`fields: string[]` must reference a registry of allowed card fields with labels, type, source, cost, privacy, and renderer. Otherwise users can configure expensive/private/invalid fields.

---

## 9. Visual System

### Finding 9.1 — Design token strategy is good but needs typed generation and validation
**Severity:** Suggestion

Add:

- JSON schema for token config;
- generated TypeScript token names;
- dev validation forbidding raw colors/magic spacing in component CSS;
- migration path for user overrides when tokens rename;
- light/dark theme support if expected later.

### Finding 9.2 — CSS module/file split is necessary but not sufficient
**Severity:** Minor

“No raw color values, no magic numbers” should be enforced by lint or review script. Structure outlasts instructions.

---

## 10. Session Identity

### Finding 10.1 — Wrong Codex suffix and timestamp semantics
**Severity:** Critical  
**Section:** 10.1  
**Evidence:** v1.0 says platform3: `cla`, `cdx`, `gem`; timestamp local time. Current v5.3 says regex `(cla|cod|gem)`, Codex code is `cod`, timestamp is UTC launch time.

This will break lookup, regex validation, directory paths, and cross-tool compatibility.

**Required change:** Align v1.0 to v5.3 unless deliberately superseding it:

- Codex platform code: `cod`, not `cdx`.
- Timestamp: UTC, not local.
- Example IDs should match current regex.

### Finding 10.2 — Draft TrackingId extension needs collision/expiry/recovery rules
**Severity:** Major

Draft IDs are good. Add:

- who may create drafts;
- idempotency key for repeated launch attempts;
- pending timeout and cleanup;
- failed draft status (`failed` probably needed);
- what happens if launcher is called with an existing confirmed ID;
- what happens if wrapper discovers a different CLI UUID;
- how partial session dirs are repaired/removed.

Identity lifecycle should likely be:

```ts
'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned'
```

### Finding 10.3 — Terminal session name mutability needs stronger invariant
**Severity:** Minor

Section 2 says terminal session name mutable and may change on resume. Current identity spec says normally stable/substrate-owned. If resume can change it, define update mechanism and ensure terminal lookup never uses stale name without fallback by tracking ID/session_dir.

---

## 11. Terminal Substrate

### Finding 11.1 — Substrate interface is Python-only while app is TypeScript/Electron
**Severity:** Major

The interface is shown as Python abstract class. UAI main process will need a TypeScript service boundary to call substrate operations. Define whether Electron calls Python scripts, imports a Node wrapper, or reimplements substrate calls.

Also define error shape, timeouts, and concurrency behavior for terminal operations.

### Finding 11.2 — Platform adapter needs test fixtures and parser confidence
**Severity:** Major

Screen parsing is brittle. For each platform, define:

- fixture screens for idle/responding/permission/error/stopped;
- parser output schema;
- confidence/unknown state behavior;
- throttling cadence;
- fallback when parser fails after CLI UI changes.

Do not let UI logic depend on false precision from parser guesses.

---

## 12. AI Integration

### Finding 12.1 — Embedded AI needs an operational boundary
**Severity:** Major

The embedded AI is powerful. Define:

- where it runs;
- how it authenticates to command bus;
- what context it can read;
- how it asks for confirmation;
- how its actions are displayed/audited;
- how to disable/kill it;
- rate limits and loop prevention.

Otherwise it becomes another hidden autonomous actor in a system already trying to manage autonomous actors.

### Finding 12.2 — LLLM integration should be service-based, not MCP-bound in renderer
**Severity:** Minor

Spec references existing `local-llm` MCP. The Electron app should probably call a local service/CLI wrapper, not depend directly on MCP availability from renderer. Define adapter boundary and failure fallback.

### Finding 12.3 — Prompt rewrite has data-loss risk
**Severity:** Minor

PromptBox rewrite should not silently replace text. It should show diff/preview or keep undo history. Prompt text can be long and operationally important.

---

## 13. Testing Strategy

### Finding 13.1 — Testing strategy must encode lessons-learned quality gates
**Severity:** Major

The testing section correctly prioritizes API tests and packaged build tests, but it does not carry forward the quality-gate hierarchy from lessons-learned:

- planned tests must exist and pass;
- component integration tests must prove wiring;
- packaged app must launch and load real sessions;
- cross-platform review/testing role separation;
- explicit attestation artifacts.

Add a “Quality Gates” subsection and require falsifiable gate checklists.

### Finding 13.2 — Need contract tests for descriptions, commands, events, and stores
**Severity:** Major

Required test families:

- component `describe()` schema compliance;
- command schema validation;
- command access-control matrix tests;
- event subscription granularity tests;
- external SQLite write signal -> renderer refresh;
- folders/app_state atomic mutation/revision tests;
- startup reconciliation after partial multi-store command;
- AI comms request/response/timeout tests;
- parser fixture tests for platform adapter;
- packaged app smoke test with non-empty HOME regression.

### Finding 13.3 — E2E terminal fixture strategy is missing
**Severity:** Major

Lessons-learned specifically call out tmux fixture gaps. v1.0 should define how tests create fake/live terminal sessions in CI/local packaged app tests.

---

## 14. Migration Plan

### Finding 14.1 — Phase 0 should freeze contracts, not only prove one component
**Severity:** Major

Foundation Spike should produce:

1. identity contract aligned with v5.3;
2. store synchronization contract;
3. command envelope/result schema;
4. component description schema;
5. notification envelope/delivery status schema;
6. one vertical slice: launch/draft session -> SQLite/sessionInfo -> renderer list -> open terminal -> send staged prompt -> packaged app smoke.

“SessionStore, CommandBus, EventSystem, one rendered component” is not enough. It may repeat the old placeholder-div failure at a smaller scale.

### Finding 14.2 — Phase 1 is overloaded
**Severity:** Major

Phase 1 includes state layer, command system, core components, support components, main process adaptation, draft IDs. That is too broad for delegation without frozen contracts.

Recommended split:

- **Phase 0A:** Contracts and spike.
- **Phase 0B:** Data/identity migration and store adapters.
- **Phase 1A:** Shell app + SessionNavigator + Workspace + SessionPane vertical slice.
- **Phase 1B:** PromptBox safe delivery + terminal substrate integration.
- **Phase 1C:** Briefs/folders/tags/relationships.
- **Phase 1D:** Context/Bottom panels.
- **Phase 2:** Teams/projects/AI comms/embedded AI.

### Finding 14.3 — Projects are listed Phase 2 in one place but Phase 1 priority in gap analysis
**Severity:** Minor/Major for planning

Gap analysis requirement #9 marks Projects as Phase 1. v1.0 Phase 2 says “Projects, Tags, Teams.” Decide whether Projects are foundational or feature. Given devTrees are core to UAI resurrection, I would design Project schema in Phase 0/1 but delay full UI if necessary.

### Finding 14.4 — Migration from existing UCI data is not specified
**Severity:** Major

Need explicit migration plan for:

- existing SQLite schema;
- existing app_state/folders structures;
- existing session IDs and legacy formats;
- existing briefs and relationships;
- current UCI app package/user data paths;
- rollback/backups;
- ability to run UCI and UAI side by side during resurrection.

---

## Architecture Anti-Patterns Detected

### AP1 — “Principle as Protocol”
External Ground Truth, prompt-default comms, and hooks are stated as principles but not fully specified as protocols. Workers will fill gaps inconsistently.

### AP2 — Split-Brain Source of Truth
Session fields are assigned to SQLite in v1.0 while current identity spec assigns many to sessionInfo.json. This is the most dangerous anti-pattern in the document.

### AP3 — God Bus Risk
A central command bus can become the new God component if commands are untyped payload blobs (`Record<string, any>`) without bounded domain handlers, schemas, and ownership.

### AP4 — Service Locator via Parent Chain
Actionable components querying parent chains can hide dependencies and recreate prop-drilling’s problems in less visible form. Use explicit context providers and selectors.

### AP5 — “AI Magic Enforcement”
The spec assumes the app can detect/reroute wrong AI response mechanisms. Without structured response protocols, this is magical thinking.

### AP6 — Optimistic UI Without Revision Discipline
Optimistic drafts without store revisions, command IDs, and reconciliation paths will recreate the divergence problem under a new label.

### AP7 — Test Strategy Too Abstract
“Test through APIs, not DOM” is correct but insufficient. The previous failure was not lack of unit tests; it was missing integration/acceptance wiring. The architecture must encode that structurally.

---

## Missing Sections / Concepts to Add

1. **Store Synchronization Contract**
   - revisions, signal files, snapshots, store slices, external writes, stale event handling.

2. **Multi-Store Command/Saga Protocol**
   - write order, compensation/repair, startup reconciliation, partial failure behavior.

3. **Command Schema Registry**
   - typed command definitions, JSON schemas, structured errors, safety class, access requirements.

4. **Component Description Schema v1**
   - formal JSON Schema, versioning, examples, side effects, pre/postconditions, access and safety metadata.

5. **Notification/Comms Delivery Lifecycle**
   - durable request/response model, correlation IDs, delivery state, ack, retry, timeout, escalation.

6. **Security/Safety Model**
   - embedded AI permissions, external API auth, shell command policy, prompt injection risks, transcript privacy/redaction.

7. **Focus and Prompt Target Model**
   - active tab vs active grid cell vs terminal focus vs prompt target vs selected entities.

8. **Folders/Views/Tags/Relationships Conceptual Model**
   - preserve UCI’s clean separation.

9. **Observability and Logging**
   - app log schema, command log, notification log, session activity log, debug inspection, failure surfacing.

10. **Performance/Backpressure Plan**
    - statusline coalescing, parser cadence, JSONL caching, event storm mitigation, many-session scaling.

11. **Migration and Rollback Plan**
    - existing data migration, backups, side-by-side UCI/UAI, schema downgrade/read-only behavior.

12. **Quality Gate / Acceptance Protocol**
    - explicit attestation artifacts and packaged-app smoke acceptance.

---

## Specific Recommended Revisions Before Worker Build

### Must Fix Before Broad Delegation

1. Align Section 10 with `spec_session_identity_current.md` or update that spec first.
2. Replace Section 3.2 with concrete revision/signal/snapshot reconciliation protocol from `uci_data_architecture.md`.
3. Clarify renderer/main/store authority:
   - renderer components read snapshots and dispatch commands;
   - main process command handlers mutate external stores;
   - external writers use sanctioned APIs/signals.
4. Replace `CommandResult` with a richer shape including `commandId`, structured error, changed slices, snapshots, effects.
5. Expand `ComponentDescription` into a versioned schema adequate for embedded AI/tooling.
6. Add durable notification/feedback request records with correlation IDs and delivery statuses.
7. Add namespaced entity/card refs and relationship metadata rules.
8. Add focus/prompt target model.
9. Add quality gate and packaged app acceptance requirements.
10. Split Phase 1 into smaller dependency-ordered phases.

### Should Fix Soon

1. Add field-level privacy/read access policy.
2. Add parser fixture requirements.
3. Add store migration/backup strategy.
4. Add project/team indexing strategy.
5. Add command families for folders/tags/relationships/terminal/transcript/notifications.
6. Add runtime-configurable card field registry.

---

## Revised Build Order Recommendation

### Phase 0A — Contract Freeze
Deliverable: docs + schemas + tests only.

- identity contract aligned with v5.3;
- store sync contract;
- command schema/result shape;
- component description schema;
- notification/feedback request schema;
- entity ref/relationship schema;
- focus model.

### Phase 0B — Vertical Slice Spike
Deliverable: packaged app proves architecture.

- bootstrap snapshot from stores;
- render sessions list through component API;
- draft session creation -> launcher -> confirmed identity;
- open session in workspace;
- safe staged prompt delivery;
- store change event refresh;
- packaged app smoke test.

### Phase 1A — Core Stores and Commands

- SessionStore adapter;
- FolderStore/AppState store;
- command bus with schemas/access/logging;
- event channels.

### Phase 1B — Core UI

- Navigator sessions/briefs basic;
- Workspace tabs/grid;
- SessionPane terminal/transcript mode;
- PromptBox safe delivery.

### Phase 1C — Organization Entities

- folders/views/tags/relationships;
- brief registry integration;
- related entities panel.

### Phase 1D — Observability/Quality Gates

- logs;
- monitor drawer;
- packaged app test harness;
- acceptance attestations.

### Phase 2 — Projects/Teams/AI Comms

- project entity UI;
- team definitions;
- notification bus full delivery lifecycle;
- AI feedback timeout;
- embedded AI read/action with restricted permissions.

### Phase 3 — Extended

- WebUI as session;
- plugin architecture;
- playback/time travel;
- advanced orchestration.

---

## Final Assessment

The architecture has the right bones. It is clearly informed by UCI’s failures and has the right instincts: typed APIs, command bus, external truth, notifications, hooks, self-description, and packaged testing. The core problem is that v1.0 compresses several hard protocols into prose principles. That is exactly where worker divergence happens.

I would not reject the direction. I would reject implementation against this draft without a v1.1 pass.

**Final verdict:** `request-changes`

**Minimal acceptance criteria for v1.1:** no contradictions with current identity/data references, concrete store sync protocol, concrete command/result schemas, durable notification/comms protocol, component description schema sufficient for embedded AI, and a dependency-ordered migration plan.
