# Codex Review: Session Identity Specification v5.4

**Review date:** 2026-04-22  
**Reviewer:** Codex  
**Spec under review:** `architecture/spec_session_identity_v5.4.md`  
**Comparison baseline:** `architecture/current_references/spec_session_identity_current.md` (v5.3)  
**Prompt focus:** F01/N01 identity contradictions, identity core vs indexed metadata split, draft lifecycle, and new contradictions.

---

## Verdict: APPROVE WITH MINOR REQUESTED CHANGES

v5.4 resolves the F01/N01 blocker in substance. The critical identity contradictions from the UAI v1.1 re-review are addressed:

- Tracking ID timestamp semantics are restored to **UTC launch time**.
- Codex platform code remains `cod`.
- `project_dir` is explicitly immutable.
- v5.3 identity core is preserved and separated from v5.4 indexed metadata.
- Instance-scoped `sessionInfo.{uuid8}.json` filenames are explicitly documented as a v5.4 supersession with reader fallback.
- Draft session lifecycle and launch request context are now specified.

I would approve this as the identity basis for UAI v1.2 / contract freeze after a small cleanup pass. The cleanup is not conceptual; it is precision work around mirrored-field ownership, registry schema expression, draft write ordering, and status semantics.

---

## Direct Answers to Review Questions

### 1. Does this resolve F01/N01 identity contradictions?

**Yes — resolved, with minor cleanup.**

The prior blocker was that UAI v1.1 claimed v5.3 alignment while contradicting v5.3 on:

- UTC vs local Tracking ID timestamp;
- `cod` vs `cdx` platform suffix;
- slim registry vs expanded registry;
- `sessionInfo.json` vs `sessionInfo.{uuid8}.json`;
- immutable vs mutable `project_dir`.

v5.4 resolves these as follows:

| Prior contradiction | v5.4 resolution | Status |
|---|---|---|
| Tracking ID timestamp local vs v5.3 UTC | Section 3.2 explicitly says UTC launch time, unchanged from v5.3 | Resolved |
| Codex suffix | Section 3.1 uses `cod` | Resolved |
| Slim registry vs extra fields | Section 5.1 preserves identity core; Section 5.2 defines indexed metadata as v5.4 extension | Resolved, cleanup needed |
| `sessionInfo` filename | Section 4.1 explicitly supersedes v5.3, defines discriminated filename and fallback resolution | Resolved |
| `project_dir` mutability | Section 5.1/5.3/6.3 says immutable launch project root | Resolved |

Most importantly, v5.4 no longer pretends all changes are v5.3-compatible without qualification. It correctly says it supersedes v5.3 and explicitly documents the changed areas.

### 2. Is the identity core vs indexed metadata split clean?

**Mostly yes.**

The split is directionally clean:

- Identity core = stable lookup/pointer contract inherited from v5.3.
- Indexed metadata = additional SQLite columns for query/display/lifecycle.
- sessionInfo = wrapper/runtime-owned mutable state.
- app_state = pure UI state.

However, a few fields are still muddy:

1. `working_dir`, `model`, `substrate`, `roles`, `cli_pid`, `status` appear as indexed metadata columns but are declared source-of-truth in sessionInfo. That is acceptable only if SQLite is explicitly described as an **index/cache** for those fields, not an authoritative metadata owner.
2. The text says “Fields like `display_name` and `roles` appear in both SQLite and sessionInfo. SQLite is authoritative for query/display. sessionInfo is authoritative for wrapper-managed runtime state.” `roles` cannot have two independent authorities without a merge rule. If App can edit roles and wrapper can also write roles, define precedence.
3. The SQL fragments in Section 5.1 and 5.2 are column lists, not a complete `CREATE TABLE`. That is fine for a conceptual spec, but the migration/contract doc should produce a concrete schema.

Recommended wording adjustment:

> Indexed metadata fields whose source of truth is sessionInfo are denormalized cache columns in SQLite. They are updated by wrapper/session_store synchronization and may be repaired from sessionInfo. SQLite is authoritative only for fields whose Source of Truth is SQLite.

### 3. Is the draft lifecycle sound?

**Yes, mostly.**

The lifecycle is now viable:

```text
draft -> pending -> confirmed
                 -> failed
draft -> orphaned
pending -> orphaned/failed
```

Strengths:

- Drafts have visible placeholders.
- App pre-populates known context.
- `launch_context.launch_params` gives the launcher a structured contract.
- Launch params become immutable after `pending`.
- Failed launches preserve evidence instead of deleting silently.
- Cleanup rules are explicit.

Remaining refinements:

1. **Status transition inconsistency:** Section 7.1 says `pending -> orphaned (timeout)`, while Section 7.5 says pending older than 5 minutes -> `failed`. Pick one. My recommendation: `pending` timeout should become `orphaned` if launcher did not start/claim, and `failed` if launcher reported/recorded an error. If the app cannot tell, use `orphaned` with `failureReason: timeout`.
2. **Draft write ordering:** Section 7.2 says create session directory and write initial sessionInfo; Section 10.2 says write registry row then sessionInfo. For crash repair, define the exact order and reconciliation. I recommend: create session_dir -> write sessionInfo with launch_context -> insert SQLite draft row -> emit signal. Or if SQLite first, startup repair must detect rows missing sessionInfo.
3. **Launch context location:** It is written to sessionInfo. Good. But Section 10.2 says launcher reads from sessionInfo or store. Prefer one canonical source: sessionInfo launch_context. SQLite may index selected launch fields, but launcher should not have two possible authorities.
4. **Idempotency:** Repeated `--tracking-id` launch attempts should be defined for draft/pending/failed/orphaned/confirmed states. Confirmed no-op is covered; failed/orphaned retry semantics need one sentence.

### 4. Any new contradictions introduced?

No new blocking contradiction. There are a few minor ambiguities and one moderate field-ownership ambiguity around mirrored roles/status metadata. Details below.

---

## Findings

## F01/N01 Resolution Assessment

### Finding ID-01 — F01/N01 is resolved
**Severity:** Positive finding

v5.4 explicitly supersedes v5.3 and directly addresses the identity contradictions called out in the v1.1 re-review. This is the right move: rather than warping UAI v1.1 around an older reference, v5.4 updates the identity source of truth and names the changes.

**Evidence:**

- Section 3.2: “Timestamp is UTC launch time. This is unchanged from v5.3.”
- Section 3.1: platform code table uses `cod` for `codex_cli`.
- Section 4.1: discriminated filenames are documented as “changed from v5.3,” with legacy fallback.
- Section 5.1: identity core preserves v5.3 contract.
- Section 5.3: `project_dir` immutable.

**Disposition:** Resolved.

---

## Identity Core vs Indexed Metadata

### Finding ID-02 — Identity core / indexed metadata split is correct, but mirror semantics need one more sentence
**Severity:** Minor / Major if not clarified before implementation

The split is good. But Section 5.2 creates columns for fields whose source of truth is later declared to be sessionInfo. That is acceptable if they are denormalized indexes, but the spec uses mixed language:

- “Indexed Metadata”
- “SQLite is authoritative for query/display”
- “sessionInfo is authoritative for wrapper-managed runtime state”

For fields like `working_dir`, `model`, `substrate`, `cli_pid`, and `status`, SQLite should be a cache/index, not an authority. For fields like `display_name`, `archived`, and `identity_status`, SQLite can be authoritative.

**Required cleanup:** Add a subheading in 5.2 or 5.3:

```text
Indexed metadata columns are divided into:
1. SQLite-owned metadata: display_name, identity_status, archived, created_at, parent_tracking_id.
2. Denormalized runtime index fields mirrored from sessionInfo: working_dir, model, substrate, roles, cli_pid, status.

For mirrored fields, sessionInfo is authoritative. SQLite values may be repaired from sessionInfo during reconciliation.
```

If `roles` is truly app-editable and wrapper-editable, define a merge/precedence rule.

### Finding ID-03 — `roles` has ambiguous ownership
**Severity:** Major

Section 5.3 says:

| roles | Wrapper / App | Yes | sessionInfo | JSON array, updatable |

Then the key distinction says sessionInfo is wrapper-owned, while app can update roles. That is a shared-authority smell.

Options:

1. Make `roles` app/session_store-owned, with wrapper reading it.
2. Make `roles` wrapper-owned, with app requesting role changes through launcher/session_store API that updates both SQLite and sessionInfo.
3. Split fields:
   - `launch_roles` immutable or app-owned launch config;
   - `active_roles` wrapper/status-owned runtime report.

Recommendation: **roles should be app/session_store-owned metadata**, not wrapper-owned runtime. The wrapper can consume roles at launch and mirror active role context in sessionInfo, but authoritative role assignment belongs to session metadata.

### Finding ID-04 — `status` is underspecified and may conflict with UAI’s independent state axes
**Severity:** Minor

v5.4 has a `status TEXT DEFAULT 'running'` metadata column and sessionInfo status. UAI v1.1 separately defines identity, terminal, runtime, and archive axes. To avoid semantic drift, define what this identity-spec `status` means.

Suggested wording:

> `status` in sessionInfo is the wrapper-reported process/lifecycle status, not the UAI renderer-derived RuntimeState. UAI may derive richer runtime states from terminal parsing and should not write them back to this field.

---

## Draft Lifecycle

### Finding ID-05 — Pending timeout maps inconsistently to `orphaned` vs `failed`
**Severity:** Minor

Section 7.1 lifecycle diagram says:

```text
pending -> orphaned (timeout)
```

Section 7.5 says:

```text
Pending older than 5 minutes with no transition to confirmed -> Mark failed
```

Pick one. Suggested distinction:

- `failed`: launcher started and reported a failure or wrote failure evidence.
- `orphaned`: no launcher claim/heartbeat/terminal/sessionInfo update before timeout.

This preserves “failed = known failed” and “orphaned = abandoned/incomplete.”

### Finding ID-06 — Draft creation write order should be fixed for crash recovery
**Severity:** Minor

Section 7.2 and 10.2 differ slightly in order. This matters because draft creation spans filesystem + SQLite.

Recommended canonical order:

1. Generate tracking_id.
2. Compute session_dir.
3. Create session_dir.
4. Write initial `sessionInfo.{uuid8}.json` with `identity_status: draft` and launch_context.
5. Insert SQLite row with `identity_status: draft`.
6. Emit SQLite signal.

Startup reconciliation then handles:

- sessionInfo exists but no SQLite row -> create/repair row or mark stray draft file.
- SQLite row exists but no sessionInfo -> mark draft damaged/orphaned and notify.

If you prefer SQLite first, specify inverse repair. Just make it deterministic.

### Finding ID-07 — Retry semantics for failed/orphaned drafts need one sentence
**Severity:** Minor

Confirmed IDs are no-op on launcher call. Good. But failed/orphaned retry is not defined.

Recommended:

> Retrying a failed/orphaned draft reuses the same tracking_id only if no terminal_session/cli_session_id was confirmed. Retry transitions identity_status to pending and appends retry metadata to launch_context. If any CLI identity was confirmed, create a new session instead.

---

## Signals and Synchronization

### Finding ID-08 — `sessionInfo` change detection by polling is acceptable but should include mtime/hash repair rule
**Severity:** Minor

Section 12.2 says app detects wrapper updates by direct observation, periodic mtime polling, and identity_status transitions. Good enough. Add one rule:

> If sessionInfo mtime changes, app reads and updates denormalized SQLite metadata fields whose source is sessionInfo via session_store.py, emitting `sessions.changed` if indexed values changed.

Otherwise the SQLite indexed metadata can go stale indefinitely.

### Finding ID-09 — `sessions.changed` path needs data_dir definition
**Severity:** Minor

Section 12.1 uses `{data_dir}/sessions.changed`, but the spec does not define `data_dir` in this document. v5.4 can either reference the canonical AI data dir or say it is configured by session_store.py.

Suggested:

> `data_dir` is the directory containing the session registry SQLite DB, currently `ai_general/data/sessions/` or the configured session data root.

---

## Compatibility / Migration

### Finding ID-10 — Backward compatibility claim is mostly sound, but v5.3 consumers that write sessionInfo need guidance
**Severity:** Minor

Readers are covered by fallback resolution. Writers are told MUST use discriminated names for new sessions. But existing v5.3 consumers that still write `sessionInfo.json` for a v5.4 session could create split files.

Add:

> v5.3 writers are supported for legacy sessions only. For v5.4 session directories, writers must resolve via `find_instance_file()` and write the discovered canonical file. If both discriminated and legacy files exist, discriminated wins and a repair warning is logged.

### Finding ID-11 — Migration test open item is correct and should be promoted to required acceptance
**Severity:** Suggestion

The open item “Add a migration test containing a v5.3 session, a v5.4 draft session, and a legacy v5.1 ID” should be a required acceptance criterion for approving implementation, not just an open item. This is the exact surface likely to rot.

---

## Minor Editorial / Precision Notes

1. Section 5.2 says `status TEXT DEFAULT 'running'` under “Lifecycle (wrapper-owned for running state, app-owned for archive).” Archive is a separate `archived` flag; keep `status` strictly wrapper-owned or split the line.
2. Section 5.3 says “Fields like `display_name` and `roles` appear in both SQLite and sessionInfo.” `display_name` in sessionInfo schema may be okay for convenience, but if SQLite is authoritative, sessionInfo copy should be explicitly a mirror.
3. Section 7.2 says “Most fields null” in status table but then draft creation populates many fields. Not harmful, but phrase as “identity/platform fields known, runtime fields null.”
4. Section 11 resolution order differs from older v5.3 lookup order? v5.3 purpose says lookup by tracking ID, CLI UUID, terminal name; rules did not specify order. v5.4 uses tracking -> terminal -> cli. Consider tracking -> cli_session_id -> terminal_session because terminal names are mutable and may collide/reuse. If terminal is operationally more common, keep order but mention exact matching and multiple terminal matches choose most recent.

---

## Approval Checklist

Before marking v5.4 final, I recommend these small edits:

- [ ] Add explicit denormalized-index wording for sessionInfo-sourced SQLite columns.
- [ ] Resolve `roles` authority.
- [ ] Clarify `status` meaning relative to UAI RuntimeState.
- [ ] Resolve pending timeout: `failed` vs `orphaned`.
- [ ] Make draft creation write order canonical and define repair behavior.
- [ ] Define failed/orphaned retry semantics.
- [ ] Add sessionInfo mtime -> SQLite index repair rule.
- [ ] Define `{data_dir}` for signal file.
- [ ] Add warning/repair rule if both `sessionInfo.{uuid8}.json` and `sessionInfo.json` exist.

None of these require rethinking the model.

---

## Final Assessment

v5.4 does what it needed to do: it removes the identity ambiguity that blocked UAI v1.1 approval. The UTC Tracking ID issue is fixed. The v5.3 core contract is preserved as an identity core rather than pretending the registry never expands. The discriminated filename change is now honest and backward-compatible. Draft lifecycle and launch_context are the right mechanism for app-initiated sessions.

**Final verdict:** `approve-with-minor-changes`

Once the minor ownership/transition wording is cleaned up, F01/N01 should be considered resolved.
