---
task_id: ws_2f
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: []
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2F: Tags Integration End-to-End

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Make tags work end-to-end: load them into the session model, wire the TagPicker UI, enable tag filtering in Navigator.

## What Already Exists

- `tag.add`, `tag.remove`, `tag.toggle` commands in command-handlers.ts (call session_store.py add_tag/remove_tag)
- `TagBadge` component in `src/renderer/components/tags/TagBadge.tsx`
- `TagPicker` component in `src/renderer/components/tags/TagPicker.tsx`
- `useTagStore()` in `src/renderer/stores/tag-store.ts`
- `getTagsForSession()` helper in `src/main/session-store.ts` (exists but never called)
- `Session.tags` field in the type (always `[]` currently)
- `session_store.py` supports `add_tag`, `remove_tag`, `get_tags` subcommands via `card_tags` table

## What to Build

1. **Load tags into Session model** — In `mapSession()` or `listSessions()`, populate `Session.tags` from `session_store.py get_tags`. Either call per-session or add a batch endpoint.

2. **Wire TagPicker in ContextPanel** — Connect TagPicker to `tag.add`/`tag.remove` commands via `executeCommand()`

3. **Tag filtering in Navigator** — Add tag filter chips or search-by-tag capability in the filter toolbar

4. **Tag display on cards** — Show TagBadge components on session cards in CardListView (may need to update SessionCardVisual or BaseCardView)

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- Tags load from SQLite and display on session cards
- TagPicker can add/remove tags
- Navigator can filter by tag

## Done When

User can add/remove tags on sessions, see them on cards, and filter by tag in Navigator.
