# notes.md structure convention — `##` = subtab, `###` = section

**Author:** Mullion · **Spec:** PianoMan (2026-07-02) · **Status:** implemented (v1.3.79)
**Applies to:** every todo's `notes.md`, rendered by the shared `TodoItemView`.

## The idea
A todo's `notes.md` is the human-readable **source of truth** for its user-authored
content, and its markdown structure maps 1:1 to the todo-item UI:

- `## <Subtab>` — a **subtab** (Contents · Activities · Links & Artifacts · Files)
- `### <Section>` — a **section** within that subtab
- body text under a `###` — that section's content

```markdown
## Contents
### Summary
Short description of the work.
### Decisions & Pivots
- Chose X over Y because Z.

## Activities
### Reviews
- LGTM — Relay.

## Links & Artifacts
### Related PRs
- #123
```

## User-authored vs system-generated
The convention owns **user-authored** content only. The view **interleaves
system-generated sections** (not in notes.md) at fixed spots:

| Subtab            | System (auto)                              | User (notes.md `###`)              |
|-------------------|--------------------------------------------|------------------------------------|
| Contents          | Parent path, Provenance (`origin.yml`)     | Summary, Description, Open Questions, Decisions … |
| Activities        | History (`history.log`), Comms             | Reviews …                          |
| Links & Artifacts | Children (todo graph), Artifacts (`data/`) | manual links …                     |
| Files             | folder tree (git view later)               | —                                  |

Metadata (`# Title`, `**Created:**`, `**Updated:**`, `**Status:**`, owner) is **stripped**
from notes bodies — it already lives in the header bars, never repeated in Contents.

## Back-compat
Existing todos use flat `##` for sections (no subtab layer). Detection: if **no** `##`
matches a canonical subtab name, the file is **legacy** → all its `##` sections render
under **Contents**. So old notes keep working unchanged; new/edited notes opt into the
subtab layout by using canonical `## Contents` / `## Activities` / … headings.

## Placeholders
When a todo hasn't authored `### Open Questions` / `### Decisions` / `### Reviews`, the
view shows a `sample · capture not wired` placeholder so the structure is visible. Authoring
the section replaces the sample with real content automatically.

## Editing (next)
Because everything user-authored lives in one file, a single **Edit** affordance on
`TodoItemView` can edit all sections at once (read view ⇄ textarea per `###`, or one notes
editor), saved via the `todo.writeNotes` command — structure-preserving. Provenance/History
stay read-only (system logs). Not yet built.

## Implementation
`parseStructured(md)` in `packages/renderer-ui/src/components/TodoItemView.tsx`:
returns `{ byTab: Record<Sub, Section[]>, structured: boolean }`. `##` sets the current
subtab (via `canonTab`), `###` opens a section, body accumulates. Unit-verified for both
structured and legacy inputs; live-verified on a scratch todo (routing to all three subtabs).
