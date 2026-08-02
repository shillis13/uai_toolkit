# catjsonl.py — recommendations for the re-design

Companion to `catjsonl_design.md`. Every item here is either a confirmed defect or a
structural change with a stated problem behind it. Line citations are against
`src/uai_toolkit/jsonl/catjsonl.py`.

---

## Fix before carrying forward (confirmed defects)

### 1. Split file ordering from message ordering

**Problem.** One `--sort` flag controls both, so its `newest` default makes `jcat`
render a transcript backwards, `jhead` return the newest messages, and `jtail` return
the oldest. Reproduced against a real 27k-line transcript (see `catjsonl_design.md`
§8.1). The flag's own help text (580) only claims to control file order.

**Recommendation.** Two concepts, two controls:

- File processing order: keep `--sort {newest,oldest}`, default `newest`. Good for
  recursive search.
- Message order: **always chronological** inside the message stream. `jhead` = first
  N, `jtail` = last N, `jcat` = as recorded. Add `--reverse` if reverse display is
  genuinely wanted.

**What depended on the old behavior:** any habit or script that relied on
`jgrep -r … ` printing newest-first. Preserve that by keeping the *file* default at
`newest` — the cross-file sort at 1404 should sort files, not re-sort the message
stream.

### 2. Make `-v` mean invert

**Problem.** `-v` is bound to `--verbose` (591) while `--invert` (592) does what every
user expects `-v` to do. A user typing `jgrep -v foo file` gets a confidently wrong
answer with no warning.

**Recommendation.** `-v` / `--invert-match` = invert. Move verbose to `--verbose`
long-form only, or to `-H`/`--show-files`. If breaking existing muscle memory for
`-v`-as-verbose is a concern, make `-v` an error for one release with a message
naming both replacements.

### 3. Carry the real file line number into `PipeMessage`

**Problem.** `jgrep -n` prints `line=<message ordinal>`, not a file line, because
`PipeMessage` copies `Message.line_number` (the ordinal) and drops
`Message.source_line` (the actual line) — see `read_jsonl.py:377-378`. The output
looks like a `grep`-style location and is not one.

**Recommendation.** Add `source_line` to `PipeMessage` and the JSON line schema, and
print it as `line=` in `_format_msg_location` (1081-1085) and `format_numbered`
(1088-1118). Keep the ordinal under a distinct name (`ord=`). This also aligns
`jgrep`'s "line" with `scrub_files`'s "line", which today mean different things.

### 4. Handle `BrokenPipeError`

**Problem.** `jcat <file> | head -2` prints a Python traceback. Reproduced. For a tool
whose stated purpose is Unix pipelines, this is a headline defect.

**Recommendation.** Wrap the output loops (385-396, and `jgrep`'s printers) so
`BrokenPipeError` exits quietly with the conventional status, and suppress the
interpreter's stdout-flush error on shutdown. One helper, applied at every print site.

### 5. Give the tools exit codes

**Problem.** `jgrep` with no matches exits 0 (verified), as does `jcat` on a
nonexistent session. `if jgrep …; then` is unusable and failure is invisible to a
calling script.

**Recommendation.** Adopt grep's convention: `0` = something matched / something was
output, `1` = nothing matched, `2` = error (bad regex, unreadable source, all sources
failed to parse). Make the per-file `Skipping <path>` catch (1372-1374) contribute to
the error status instead of being swallowed.

### 6. One time-specification parser

**Problem.** `catjsonl._parse_time_spec` (296-319) and `discovery.parse_time_spec`
(`discovery.py:24-40`) accept different grammars, disagree on time zone (UTC vs
local), and disagree on failure (raise vs silently return "no bound"). Both run on the
same `--since` value. Concrete outcomes are listed in `catjsonl_design.md` §8.7,
including an uncaught traceback for `--since 2026/04/09`.

**Recommendation.** One parser, in one place, used by both file selection and message
selection. It must: accept a single documented grammar; interpret a bare date in one
stated zone (recommend local, since users think in local dates and the repo's global
convention is local time) and say so in `--help`; and **fail loudly** on an
unparseable spec, at argument-parse time, so a typo can never silently widen the
window.

### 7. Remove the source/pattern heuristic

**Problem.** `_looks_like_source` (212-224) misclassifies hex-only English words
(`added`, `face`, `cafe`, `decade`) as session identifiers, silently dropping the
search pattern.

**Recommendation.** Make it unambiguous at the grammar level. Either require sources
after a `--` separator when `--type`/`--role` is used, or add an explicit
`--source`/`-f` option. Delete the heuristic — a rule that is right most of the time
and silently wrong the rest is worse than an explicit syntax.

---

## Drop entirely

### 8. Dead code — about 100 lines

`iter_messages_from_files` (100-155) and `get_messages_streaming` (463-488) are
defined and never called from anywhere in the repository. `grep_messages` (856-881) is
never called. The unused `detect_platform` import (36). The Python 3.9 quoting
workaround at 627, obsolete against the declared 3.10 minimum.

**Caveat before deleting:** `iter_messages_from_files` is the *right* design for
recommendation 9 below. Wire it up or delete it — do not leave it as it is.

### 9. Streaming, decided one way or the other

`jwc -r ~/.claude/projects/` materializes every message of every transcript in memory
(`get_messages`, 449-460), and `_run_jgrep_streaming` buffers every match despite its
name (1350, 1400-1407). Either commit to streaming — which requires giving up the
cross-file timestamp sort at 1404 — or drop the unused generator and document the
memory bound honestly. The current state pays for neither.

### 10. Pick one dispatch mechanism

Three coexist: entry-point functions (1514-1519), `argv[0]` name detection
(495-500), and the `argv[1]` sub-command (745-747). `DESIGN.md` decision 2 already
chose entry points, explicitly to avoid Windows symlink problems. Keep entry points
plus the sub-command form (it is what makes `python -m` work); delete `detect_tool`
and the symlink assumption.

---

## Merge / split

### 11. The seam is `PipeMessage` and it is too thin

`PipeMessage` (43-66) keeps 8 of the 14 fields on `read_jsonl.Message`, silently
dropping `source_line`, `turn_number`, `on_chain`, `is_compaction`, and `raw`. The
`on_chain` loss is the significant one: no j-tool can distinguish live conversation
from abandoned retry/rewind branches, and none exposes a filter for it.

**Recommendation.** Either make `PipeMessage` a thin envelope around the full
`Message` (adding only `msg_num` and `source`), or state explicitly which fields the
pipe format deliberately excludes and why. Then add `--on-chain` / `--all-branches`
to the shared flag block. This is a user-visible correctness issue, not just tidiness:
a grep that reports a command from a rewound branch as if it were real history will
mislead.

### 12. Extract the help guide from the code

`_help_examples` (617-729) is 113 lines of hand-aligned, hand-colorized text with a
box-drawing header, maintained by counting spaces. The source-side copy
(`catjsonl.py.materialized`) has since added per-argument help, defaults, `metavar`s,
and per-command `EXAMPLES`/`CAVEATS` epilogs — a better structure. Adopt the
structured form and generate the wide guide from data, rather than maintaining two
divergent hand-formatted help systems.

---

## Resolve the source/package divergence first

Before any re-design work, reconcile `catjsonl.py` with `catjsonl.py.materialized`
(279 diff lines; `tools/manifest.py:246` marks the file `kind: "curated"`, so
materialize will never do it for you). Each copy holds changes the other lacks:

- Package-only, and worth keeping: entry-point wrappers, `main(tool=…)`, the
  `discovery` shim replacing `file_utils`, the Windows `more` pager branch, the
  missing-pager fallback, three removed `sys.path` hacks.
- Source-only, and worth adopting: the far better `--help` text with stated defaults,
  and the explicit written statement that these tools are read-only.

Back-port the Windows pager fix to the source tree in particular — as it stands, the
portability work exists only in a derived artifact.

---

## Add tests

There is no behavioral test for any of the six commands (`tests/` holds only an
import smoke test plus unrelated files). Every defect above is trivially testable
against a small fixture transcript. At minimum, before re-implementing:

- `jhead`/`jtail` return the first/last N in chronological order
- `jcat` output is chronological
- `jgrep` exit code is 1 on no match, 2 on a bad pattern
- `jcat … | head` does not traceback
- round-trip: `jcat --json | jgrep --json | jfmt` preserves message identity
- `--since` accepts one documented grammar and rejects everything else loudly
