# ADR-001: URI as Primary Entity Identity

**Status:** Accepted
**Date:** 2026-05-22
**Author:** Kael (20260521_043029_6784ebe3_cla), PianoMan
**Context:** Session on entity identification, URI scheme, and identity simplification

---

## Decision

The `uai://` URI is the primary public identifier for all entities. All inter-system communication, entity references, relationship records, and user-facing display use URIs. Internal implementation details (CLI UUIDs, terminal session names, tmux server names) are metadata retrieved via store lookup when needed at system boundaries.

## Format

```
uai://<entity_type>/<entity_id>[/<action_path>][?params]
```

Entity types and their ID sources:

┌─────────────────┬──────────────────────┬──────────────────────────────────────────────┐
│ **Entity Type** │ **entity_id source** │ **Example URI**                              │
├─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ session         │ tracking_id          │ `uai://session/20260521_043029_6784ebe3_cla` │
├─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ brief           │ brief name           │ `uai://brief/Solstice_UAI`                   │
├─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ project         │ project id           │ `uai://project/ai_root`                      │
├─────────────────┼──────────────────────┼──────────────────────────────────────────────┤
│ team            │ team id              │ `uai://team/core_team`                       │
└─────────────────┴──────────────────────┴──────────────────────────────────────────────┘

Action paths (per architecture spec Section 15):
```
uai://session/<id>/transcript?line=42
uai://session/<id>/details
uai://brief/<name>/content
uai://project/<id>/sessions
```

## What This Changes

### Before (current)

Multiple identifier types float independently:
- Tracking IDs passed in some places
- CLI UUIDs in others
- Terminal session names in substrate calls
- Entity IDs (`session:tracking_id`) in card/container systems
- No consistent public identifier

Every function that accepts an identifier needs resolution logic to handle all forms. Comms messages use display names or tracking IDs inconsistently. Relationships store raw tracking IDs.

### After

**URI is the envelope.** The tracking ID is still the *value* inside the URI for sessions — but nothing passes bare tracking IDs between systems anymore.

┌────────────────────────────────────────────────┬──────────────────────┬───────────────────────────────────────────────┐
│ **Context**                                    │ **Uses URI**         │ **Resolves internally**                       │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ Comms messages (`from`/`to`)                   │ `uai://session/<id>` │ recipient lookup                              │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ Entity relationships (`source_id`/`target_id`) │ `uai://session/<id>` │ —                                             │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ Context menus (Copy)                           │ `uai://session/<id>` │ —                                             │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ App state references                           │ `uai://session/<id>` │ —                                             │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ UI display (cards, details, title bar)         │ `uai://session/<id>` │ —                                             │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ Script CLI arguments                           │ `uai://session/<id>` │ strips prefix, resolves                       │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ MCP tool parameters                            │ `uai://session/<id>` │ strips prefix, resolves                       │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ Terminal attach                                │ —                    │ `session_store.resolve(uri).terminal_session` │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ CLI session resume                             │ —                    │ `session_store.resolve(uri).cli_session_id`   │
├────────────────────────────────────────────────┼──────────────────────┼───────────────────────────────────────────────┤
│ JSONL path construction                        │ —                    │ `session_store.resolve(uri).session_dir`      │
└────────────────────────────────────────────────┴──────────────────────┴───────────────────────────────────────────────┘

## Resolution

`session_store.resolve(uri)` accepts a URI and returns the full entity record. Internally it strips the `uai://<type>/` prefix and looks up by the entity's native ID. For sessions, the resolution order is:

1. Tracking ID (exact match)
2. CLI Session UUID (exact match)
3. Terminal session name (exact match)

This resolution order is a convenience for human input — programmatic callers always use the canonical URI form with tracking ID.

## Migration

This is a gradual migration, not a flag day.

**Phase 1 (done):** Normalization layer — `session_store.resolve()`, `session_ops.py` public functions, and the CLI arg parser all accept URIs by stripping the prefix. Both URI and raw identifiers work.

**Phase 2 (next):** New code uses URIs by default. Comms messages, new relationship entries, and new UI features use URIs. Existing code continues to work via the normalization layer.

**Phase 3 (eventual):** Audit and update existing stored data — relationship records, app state references, comms history — to use URI form. Old raw-ID entries still resolve via the normalization layer.

## Consequences

**Positive:**
- One identifier format across all public interfaces
- URIs are self-describing (type is in the path)
- Deep links work natively (`open uai://session/...` on macOS)
- Agents and scripts use the same identifiers as the UI
- Copy-pasting an identifier from UI always works in scripts and vice versa

**Negative:**
- Slightly longer than raw tracking IDs (17 chars of prefix)
- Migration period where both forms coexist
- Every entry point needs the normalization shim until migration completes

**Neutral:**
- Internal storage (SQLite columns, JSONL filenames) keeps raw tracking IDs — the URI prefix is stripped at the boundary. No schema migration needed.

## Endpoints

URIs name entities. Appending a path segment names a *capability* of that entity — an endpoint that can receive input or be referenced as a callback.

### Comms Endpoints

```
uai://session/<id>/prompt       # Submit a prompt to this session
uai://session/<id>/inbox        # Deliver a message to this session's inbox
uai://session/<id>/comms        # General comms endpoint (prompt or message, determined by content)
```

**Usage in comms messages:**
```json
{
  "from": "uai://session/20260521_043029_6784ebe3_cla",
  "to": "uai://session/20260511_222608_e327a9be_cla/inbox",
  "content": "Can you review this?",
  "replyTo": "uai://session/20260521_043029_6784ebe3_cla/inbox"
}
```

The `to` field specifies WHERE to deliver. The `replyTo` field specifies WHERE to send the response. Both are URIs with endpoint paths. A bare entity URI (`uai://session/<id>`) without a path defaults to `/comms`.

### Callback Endpoints

When a session requests work from another session and wants to be notified of completion:

```json
{
  "from": "uai://session/<requester>/comms",
  "to": "uai://session/<worker>/prompt",
  "content": "Run the test suite",
  "callbackEndpoint": "uai://session/<requester>/inbox",
  "responseType": "prompt"
}
```

`callbackEndpoint` is a URI the worker sends results to. The requester doesn't need to poll — the worker knows exactly where to deliver.

### Sub-Entity References

URIs can address parts of an entity:

```
uai://session/<id>/transcript              # The session's transcript
uai://session/<id>/transcript?line=42      # Specific line in transcript
uai://session/<id>/context                 # Loaded context items
uai://session/<id>/context/trait/<name>    # Specific loaded trait
uai://session/<id>/details                 # Session detail view
uai://session/<id>/terminal                # Terminal output

uai://brief/<name>/content                 # Brief YAML content
uai://brief/<name>/meta                    # Brief metadata

uai://project/<id>/sessions               # Sessions in this project
uai://project/<id>/briefs                  # Briefs for this project
uai://project/<id>/directory               # Project file tree

uai://team/<id>/members                    # Team member sessions
uai://team/<id>/comms                      # Team broadcast endpoint
```

### Query Parameters

```
?format=json          # Response format (json, text, yaml)
?filter=running       # Filter applied to sub-collections
?tab=mcp              # UI hint: which tab to show
?line=42              # Position within content
?since=<ISO>          # Time-based filtering
```

### Resolution Rules

1. **Entity resolution**: `uai://<type>/<id>` → resolve via `session_store.resolve()` (sessions) or equivalent store for other types
2. **Endpoint resolution**: `uai://<type>/<id>/<path>` → entity resolved first, then path dispatched to the entity's handler
3. **Unknown paths**: Return error rather than silently ignoring. The entity exists but the endpoint doesn't.
4. **Bare entity URI**: `uai://session/<id>` with no path = the entity itself. In comms context, defaults to `/comms`.

## Not Decided Here

- Whether `tracking_id` should be renamed to `entity_id` in the session store schema. The URI scheme makes this less urgent — the URI IS the universal identifier regardless of what the column is called internally.
- The Electron protocol handler registration (`protocol.registerSchemesAsPrivileged`). That's an implementation detail of the deep link system, not the identity decision.
- Exact endpoint handler dispatch mechanism (how `uai://session/<id>/prompt` routes to the prompt queue vs the terminal). This is implementation, not identity.
