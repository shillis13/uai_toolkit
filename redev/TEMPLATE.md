# Redevelopment Design Docs — standard

These documents are the **input to a re-design**, not a description of the current
code. The toolkit is being re-developed on Windows/WSL somewhere between a
**re-write** (reimplement the design) and a **re-develop** (re-design from scratch).

So the question every section answers is not *"what does this code do?"* but
**"what must the replacement get right, and what is it free to change?"**

## Terms

- **Port** — same implementation, changed only where the platform forces it.
- **Re-write** — reimplement the existing design from scratch.
- **Re-develop** — re-design from scratch. *We are between the last two.*
- **Essential** — behavior a replacement must preserve or something breaks.
- **Incidental** — an artifact of how this happened to get built; free to discard.

## Layout

    redev/<package>/_subsystem_design.md      one per directory — the forest
    redev/<package>/<script>_design.md        one per script — the trees
    redev/<package>/<script>_design_recs.md   only where there is something to change

## `_subsystem_design.md` — required sections

The re-design decisions live here. A per-script doc cannot tell you how a package
hangs together; this is the doc that can.

1. **Purpose** — what capability this package provides, in user-visible terms.
2. **Capabilities** — the discrete things it does. Behavior, not functions.
3. **Integration contracts** — what depends on this, what this depends on, and the
   shape of each boundary (CLI, import, file, subprocess, MCP tool, hook event).
   Be specific: a replacement has to satisfy these.
4. **Data & config** — every file, database, env var, and directory it reads or
   writes. Include formats and who else touches them. *State outlives code and is
   usually the hardest thing to change — treat it as the most durable constraint.*
5. **Design decisions & rationale** — what was decided and **why**. The why is what
   you need in order to re-decide. Cite the constraint that forced each one.
6. **Hard-won constraints** — bugs, limits, and surprises discovered the expensive
   way. **These must survive the re-design or they will be rediscovered.** Include
   the failure mode, not just the rule.
7. **User-interface conventions** — the shared human-facing behavior across this
   package: command naming, argument conventions, interactive vs non-interactive
   modes, output formats (human/JSON), colour, paging. **Where the scripts in this
   package disagree with each other, say so** — inconsistency is a finding, and one
   of the clearest things a re-design can fix.
8. **Persistence & state model** — the package's data as a whole: every store it
   owns, the format, the write discipline, who else touches it, and what the
   concurrency story is. **State outlives code**; a re-design can replace every line
   here and still be constrained by these files. Note anything that would require a
   migration versus what can change freely.
9. **Error-handling policy** — the package's convention for failure. Where it fails
   loudly, where it degrades, where it swallows. Note any exit-code contract callers
   depend on, and flag places where the convention is applied inconsistently.
10. **Essential vs incidental** — the single most important section for a re-design.
    Two lists, with reasons.
11. **Open questions for the re-design** — real forks, with the tradeoff on each side.

## `<script>_design.md` — required sections

1. **What it is for** — the job, in one short paragraph.
2. **Interface** — CLI arguments, public functions/classes, exit codes, output
   formats. What callers actually rely on.
3. **Integration** — who calls this and what it calls. Name the callers.
4. **Data & config** — files, env vars, databases it touches. Read, write, or both.
5. **How it works** — enough that someone could reimplement the behavior. Algorithms
   and control flow, not a line-by-line narration.
6. **User interface** — how a human interacts with it, if at all. Interactive prompt
   (REPL) behavior, terminal expectations (is a real TTY required? what happens over
   a pipe?), colour/formatting, paging, progress output, and what it does when the
   terminal is not interactive. Say which conventions are shared with sibling tools
   and which are this script's own — a re-design should keep one voice across the
   suite rather than reproduce per-tool accidents.
   *Also note where the tool is unusable in a shell idiom* (broken pipes, exit codes
   that defeat `&&`/`||`, output that cannot be piped).
7. **Persistence rules** — what this writes, and the rules it must obey when writing.
   Be precise, because this is the part a re-design most often gets wrong:
   - write discipline: atomic replace, append-only, in-place rewrite, temp+rename
   - concurrency: locking, compare-and-swap, or nothing (say "nothing" plainly)
   - ownership: who else writes the same file, and how conflicts are resolved
   - durability and recovery: backups, what survives a crash mid-write
   - retention: what is pruned, when, and whether deletion is recoverable
   - schema/versioning: how a format change is handled for existing data
8. **Error handling** — the failure contract. What it does on bad input, a missing
   dependency, an unreachable service, a partial write. Distinguish clearly:
   **fail loudly** (raise/exit non-zero) vs **degrade silently** (skip the feature)
   vs **swallow** (catch and continue as if fine). Note the exit codes callers rely
   on. *Silent degradation is the most dangerous and least visible pattern in this
   codebase — call it out wherever it appears, and say whether it is correct here.*
9. **Essential vs incidental** — what a replacement must preserve, and what is an
   accident of the current implementation.
10. **Platform notes** — anything OS-bound: paths, processes, signals, terminals,
    file locking, line endings, case sensitivity. Flag Windows/WSL implications.
    Use the repo's existing tiering (see `DESIGN.md`): **Tier A** portability fix
    inline, **Tier B** genuinely OS-divergent (belongs in `platform_compat/`),
    **Tier C** platform-impossible (degrade gracefully behind a capability flag).
11. **Risks & sharp edges** — where this bites. Concurrency, partial failure,
    ordering assumptions, silent degradation.

## `<script>_design_recs.md` — only when warranted

Do not write one per script out of habit. Write it when there is a real
recommendation, and say plainly what and why:

- what to change, and the problem it solves
- what to drop entirely, and what depended on it
- what to merge or split, and the seam
- known defects worth fixing in the re-design rather than carrying forward

## Rules for whoever writes these

- **Read the code.** Docstrings and READMEs are a starting point and are sometimes
  stale. Where a doc and the code disagree, say so explicitly — that disagreement is
  itself a finding.
- **Cite specifics.** `file.py:120` beats "somewhere in the file".
- **Do not invent rationale.** If you cannot tell why something is the way it is,
  write "rationale unknown — needs an owner's answer" rather than a plausible guess.
  A confident wrong "why" is worse than an admitted gap, because it will be re-decided
  on a false basis.
- **Flag work in flight.** If a subsystem is actively being changed, say so and name
  the todo/experiment, so the doc is not read as a settled design.
- **Plain language.** No coined terms. Expand any acronym on first use.
- **Say what you did not verify.** An honest gap is useful; a confident guess is not.

## Context worth knowing

- The shipped package is a **derived artifact**: `tools/materialize.py` regenerates
  `src/uai_toolkit/` from the live source tree. This `redev/` tree is **not** derived
  and is deliberately outside `src/` so it is neither overwritten nor packaged.
- Target platform is **WSL first** (Linux), native Windows second — see `DESIGN.md`
  for the two-phase plan and the Tier A/B/C taxonomy.
