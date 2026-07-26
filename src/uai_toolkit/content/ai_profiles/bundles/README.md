# bundles/

A **bundle** is a curated set of context files (the leaf content in
`ai_context_files/`) that belong together — a content-set with no persona or
behavior of its own. It is the purest composition kind:

- a **role** = a bundle plus responsibilities (a function/job),
- a **global** = a bundle everyone loads,
- a **bundle** = just the content-set.

Roles, skills, and globals reference bundles to pull in their content instead of
listing every file individually.

Files here are `<name>.yml` (bare descriptive name, no prefix — the directory
encodes the kind, `bundle:<name>`). References are edited only via
`context_mgr.py link/unlink/move`, never by hand (see `../DESIGN.md`).

Empty for now — bundles will be seeded from the grouping pass in todo_0319.
