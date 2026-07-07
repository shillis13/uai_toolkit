# Schema Evolution Guide

This document is the authoritative reference for evolving JSON Schemas (and the documents they describe) across the AI knowledge systems. It explains how to extend schemas safely, when to version, and how to communicate changes.

---

## 1. Overview

- **Purpose** – Schema evolution lets us add capabilities (new metadata, document sections, richer validation) without destabilizing existing digests, memories, or downstream tools.
- **Backward vs forward compatibility** – Backward-compatible changes allow old documents to keep validating under the new schema, while forward-compatible changes let new documents remain valid under an older schema. Most day-to-day work targets backward compatibility so existing assets keep working.
- **Breaking vs non-breaking changes** – A change is breaking when previously valid documents start failing validation or when downstream processors cannot interpret the new structure (even if validation passes). Everything else counts as non-breaking; treat them as additive refinements.

---

## 2. JSON Schema Composition Patterns

### `$ref`

Reuse a definition stored elsewhere (same file or another schema) to stay DRY.

```json5
{
  "$ref": "schema_base.json#/definitions/metadata"
}
```

### `$defs` (a.k.a. `definitions`)

Create a local library of fragments and reference them via `$ref`.

```json5
{
  "$defs": {
    "timestamp": {
      "type": "string",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
    }
  },
  "properties": {
    "created": {"$ref": "#/$defs/timestamp"}
  }
}
```

### `allOf`

Intersect multiple schemas (inheritance or mixins).

```json5
{
  "allOf": [
    {"$ref": "schema_base.json#/definitions/section"},
    {
      "properties": {
        "importance": {"type": "integer", "minimum": 1}
      }
    }
  ]
}
```

### `oneOf` / `anyOf`

Model polymorphic content. `oneOf` enforces exactly one branch, `anyOf` means at least one branch matches.

```json5
{
  "oneOf": [
    {
      "required": ["summary"],
      "properties": {"summary": {"type": "string"}}
    },
    {
      "required": ["items"],
      "properties": {
        "items": {"type": "array", "items": {"type": "string"}}
      }
    }
  ]
}
```

### External references

Use file URLs or absolute `$id` values when referencing other schema files.

```json5
{
  "$ref": "./schema_knowledge_digest.json#/properties/metadata"
}
```

**Best practices**

1. Prefer `$defs` + `$ref` over copying fragments to avoid drift.
2. When combining `allOf` and `$ref`, add `title`/`description` for clarity in validator errors.
3. For `oneOf`, use discriminators (e.g., `kind`) or mutually exclusive `required` sets to prevent ambiguous matches.

---

## 3. Backward-Compatible Changes

These keep previously valid documents valid. Document the change so producers and consumers know about new capabilities.

### Adding optional fields

Add the property under `properties` without listing it in `required`.

```json5
"metadata": {
  "properties": {
    "maintainer": {"type": "string"}
  }
}
```

### Adding new sections (digest schema)

Extend `patternProperties` with new `$ref`/`oneOf` branches while respecting `additionalProperties`.

```json5
"sections": {
  "patternProperties": {
    "^[a-z][a-z0-9_]*$": {
      "oneOf": [
        {"$ref": "#/$defs/textSection"},
        {"$ref": "#/$defs/bulletedSection"}
      ]
    }
  }
}
```

### Relaxing constraints

Increasing `maxLength`, widening enums, or loosening regex patterns is non-breaking but should be documented.

```json5
"status": {
  "enum": ["active", "archived", "draft", "sunset_pending"]
}
```

Validation behavior: JSON Schema validators ignore absent optional properties. New optional `oneOf/anyOf` branches do not affect existing instances unless `unevaluatedProperties`/`additionalProperties` rules block them. Always rerun validation suites to guard against regressions.

---

## 4. Breaking Changes

Use sparingly and coordinate with owners of dependent documents or tools.

| Change type | Why it breaks | Migration strategy |
| --- | --- | --- |
| Adding required fields | Existing documents lack the property and fail validation. | Stage as optional → populate → mark required. |
| Removing fields | Producers that still emit the property fail validation. | Deprecate, update producers, then remove. |
| Changing types | `string`→`object`, `array`→`string`, etc., invalidate documents and code. | Introduce new property (`foo_v2`) or a `oneOf` bridge. |
| Tightening constraints | Lower `maxLength`, narrower enums, stricter regex. | Audit data first, add linting, then tighten. |
| Making optional fields required | Special case of “adding required fields.” | Record usage metrics and roll out in two PRs. |

**Migration plan**

1. Audit existing documents (`rg`, `jq`, custom scripts) to measure impact.
2. Communicate the breaking intent via release notes and repo docs.
3. Provide transformation scripts or validation reports for downstream owners.
4. Tag schema versions (see §6) so consumers can pin to the last compatible release.

---

## 5. The `additionalProperties` Consideration

| Option | Behavior | When to choose |
| --- | --- | --- |
| `additionalProperties: true` | Allows unknown keys; maximizes extensibility. | Loose metadata blobs or future-friendly sections. |
| `additionalProperties: false` | Blocks unknown keys; strongest guarantees. | Deterministic renderers or security-sensitive payloads. |
| Per-object strategy | Mix strict and flexible rules with `patternProperties` or `unevaluatedProperties`. | Example below. |

```json5
{
  "patternProperties": {
    "^ext_": {"type": "string"}
  },
  "additionalProperties": false
}
```

Decide early and change only with strong justification. Moving from `true`→`false` is breaking; `false`→`true` is technically backward-compatible but can hide typos.

---

## 6. Versioning Strategies

1. **Document-level** – Embed `metadata.version` (e.g., `1.1.0`) so digests announce their spec level.
2. **Schema-level** – Maintain `schema_knowledge_digest_v1.json`, `schema_knowledge_digest_v2.json`, etc., with a `schema_knowledge_digest.json` alias pointing to the latest.
3. **Git-based** – Tag commits (`schema-v1.4.0`) and rely on history. Consumers pin to tags/submodules.
4. **Hybrid** – Use both document-level versions and Git tags for maximum traceability (recommended).

Checklist:

- Increment versions whenever validation semantics change.
- Record the change in `CHANGELOG.md` or release notes.
- Keep JSON fixtures per version so downstream tests can pin examples.

---

## 7. Evolution Workflow

### Adding optional fields

1. Update the schema (add property, leave `required` untouched).
2. Add docs/examples for the new field.
3. Update producer code to emit it when applicable; default to existing behavior.
4. Run validators/CI against sample documents.
5. Communicate the addition in PR notes or release summaries.

### Breaking changes

1. **Design** – Document the rationale, impact, and migration.
2. **Branch** – Use a feature branch; duplicate schema file if versioning is required.
3. **Implement** – Apply schema edits plus transformation scripts/fixtures.
4. **Validate** – Run validators on historic documents to surface failures early.
5. **Migrate** – Update stored digests or share scripts with content owners.
6. **Communicate** – Announce timelines and provide upgrade instructions.

### Testing & validation

- Use `ajv`, `jsonschema`, or repo-specific validation tooling.
- Maintain positive and negative fixtures for every new rule.
- Add CI checks to ensure schemas remain valid (no dangling `$ref`, missing `$schema`, etc.).

### Communication & documentation

- Every schema PR must call out change type (breaking/non-breaking), impacted files, and migration steps.
- Update `README` or this guide when new patterns emerge.
- Notify stakeholders (e.g., Slack, Docs) when breaking changes ship.

---

## 8. Knowledge Digest–Specific Guidance

The current schema (`ai_general/schemas/schema_knowledge_digest.json`) structures a digest as:

```json5
{
  "metadata": {...},
  "table_of_contents": [...],
  "sections": {...},
  "footer": {...}
}
```

- **Extensibility** – `metadata` already supports optional `context`, `maintainer`, `version`, `related_*`. `sections` accepts arbitrary keys via `patternProperties` but limits the object shape to `heading` + `content` with `additionalProperties: false`. `footer` is optional but constrained.
- **Blocked areas** – New top-level objects beyond `metadata/table_of_contents/sections/footer` fail validation. Additional properties inside a section are currently disallowed.
- **Common evolution scenarios**
  1. Add metadata (e.g., `metadata.source_repo`, `metadata.tags`).
  2. Introduce new section payloads (lists, tables, metrics).
  3. Allow richer per-section metadata by loosening `additionalProperties` or adding `oneOf` branches.
  4. Expand `footer` analytics (e.g., `refresh_author`, `digest_size_bytes`).

**Recommended approach**

- For richer sections, replace the monolithic section object with `oneOf` specialized shapes instead of toggling `additionalProperties` to `true`.
- For new top-level structures (e.g., `attachments`), add optional properties so existing digests stay valid.
- When updating `table_of_contents`, keep the key pattern (`^[a-z][a-z0-9_]*$`) or adjust it in tandem with document updates.

---

## 9. Examples

### 9.1 Adding an optional `metadata.version` field (completed)

```diff
 "metadata": {
   "properties": {
     "version": {
       "type": "string",
       "pattern": "^\\d+\\.\\d+(\\.\\d+)?$",
       "description": "Semantic version number for this digest"
     }
   }
 }
```

- Status: merged in `schema_knowledge_digest.json`.
- Impact: documents without `version` stay valid; new digests can declare schema adherence.

### 9.2 Adding new section types

```json5
{
  "$defs": {
    "textSection": {
      "type": "object",
      "required": ["heading", "content"],
      "properties": {
        "heading": {"type": "string"},
        "content": {"type": "string"}
      },
      "additionalProperties": false
    },
    "listSection": {
      "type": "object",
      "required": ["heading", "items"],
      "properties": {
        "heading": {"type": "string"},
        "items": {
          "type": "array",
          "items": {"type": "string"}
        }
      },
      "additionalProperties": false
    }
  },
  "properties": {
    "sections": {
      "patternProperties": {
        "^[a-z][a-z0-9_]*$": {
          "oneOf": [
            {"$ref": "#/$defs/textSection"},
            {"$ref": "#/$defs/listSection"}
          ]
        }
      }
    }
  }
}
```

Backward-compatible because the original text sections still validate; new list sections become allowed.

### 9.3 Adding metadata fields

Optional `metadata.source_repo` example:

```json5
"source_repo": {
  "type": "string",
  "format": "uri",
  "description": "Canonical Git repository for this digest"
}
```

Steps: add the property → document it → update digests when the data exists.

### 9.4 Extending section properties

Add an optional `summary` string per section:

```json5
"sections": {
  "patternProperties": {
    "^[a-z][a-z0-9_]*$": {
      "type": "object",
      "required": ["heading", "content"],
      "properties": {
        "heading": {"type": "string"},
        "content": {"type": "string"},
        "summary": {"type": "string", "maxLength": 280}
      },
      "additionalProperties": false
    }
  }
}
```

This remains backward-compatible because `summary` is optional. If richer per-section metadata is needed, consider permitting keys with a known prefix (e.g., `^ext_`) or adding specialized `oneOf` branches rather than opening `additionalProperties` globally.

---

**Next steps** – Keep this guide updated whenever new evolution patterns or decisions arise. Treat it as the change log for schema practices in addition to the schemas themselves.
