# platform_adapters/common.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/common.py` (39 lines). Four small helpers shared
by the adapter family.

## 1. What it is for

Utilities that every adapter would otherwise duplicate: compact JSON serialization, timestamp
normalization, text-block joining, and a path substring test.

## 2. Interface

```python
compact_json(value: Any) -> str                       # common.py:9
normalize_timestamp(value: Any) -> str                # common.py:14
join_text_parts(parts: Iterable[Any]) -> str          # common.py:27
path_contains(path: Path, needle: str) -> bool        # common.py:38
```

Actual usage, verified by grep across both trees:

| function | used by |
|---|---|
| `compact_json` | `claude`, `codex`, `gemini`, `grok` (in `to_platform_text` and Grok's content flattening). **`agy` imports it and never calls it** (agy.py:13) |
| `normalize_timestamp` | all five |
| `join_text_parts` | `grok` only (grok.py:94) |
| `path_contains` | **nothing** — dead code |

Nothing outside `platform_adapters/` imports this module.

## 3. Integration

Imported by all five adapters (line 13 of each). Depends only on the standard library
(`json`, `datetime`, `pathlib`, `typing`).

## 4. Data & config

None. No files, no environment variables. `path_contains` calls `Path.resolve()`, which touches
the filesystem, but is unused.

## 5. How it works

- **`compact_json`** — `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`. Non-ASCII
  is preserved literally and whitespace is stripped, so re-emitted lines match what the platforms
  themselves write. `standardized_session._compact_json` (standardized_session.py:14) is a
  byte-identical duplicate of this function.
- **`normalize_timestamp`** (14-23) — three cases:
  - `None` → `""`
  - `int`/`float` → treated as an epoch; **if the value exceeds 1_000_000_000_000 it is divided
    by 1000** (milliseconds heuristic), then `datetime.fromtimestamp(...).isoformat()`, i.e.
    converted to **local time with no timezone marker**.
  - `str` → returned **unchanged**, whatever it contains. Claude's `2026-07-30T04:31:59.123Z` and
    a hand-written `"yesterday"` are treated identically.
  Anything else → `""`.
- **`join_text_parts`** (27-34) — from an iterable of blocks, keep the non-empty `text` value of
  each `dict`, join with newlines. Non-dict items are skipped silently.
- **`path_contains`** (38) — `needle in str(path.resolve())`.

## 6. Essential vs incidental

**Essential**

- Compact, `ensure_ascii=False` JSON. This is what makes `to_platform_text` byte-exact against
  the original transcript in the round-trip test.
- The millisecond-vs-second epoch heuristic in `normalize_timestamp`. Some platforms emit
  milliseconds; without the divisor the timestamp lands in the year 33658.
- Pass-through of string timestamps. The downstream consumer (`read_jsonl._ts_to_local`,
  read_jsonl.py:722) does the timezone conversion, and it expects to receive the original ISO
  string including its `Z` or offset. Normalizing here would destroy that information.

**Incidental**

- `path_contains` — never called.
- The exact shape of `join_text_parts` — a one-caller helper that Grok then wraps with more
  logic anyway (grok.py:91-104).
- Living in a module named `common`. Two of the four functions are effectively single-use.

## 7. Platform notes (Windows / WSL)

- **Tier A — `normalize_timestamp` produces naive local times from epochs.**
  `datetime.fromtimestamp(value).isoformat()` (common.py:20) yields no timezone offset, so a
  downstream `datetime.fromisoformat` treats it as local — correct by accident on the machine
  that parsed it, wrong if the value is ever compared against a `Z`-suffixed Claude timestamp.
  The two conventions coexist in one `Message.timestamp` field. Not OS-divergent, but it is the
  kind of latent bug a port surfaces.
- **Tier A — `path_contains` uses `Path.resolve()` and a raw substring test.** If it is revived
  (see the family recommendations), it must normalize separators or it will fail on native
  Windows exactly as the adapters' inline versions do.
- No process, signal, locking, or terminal dependencies. Nothing here is Tier B or C.

## 8. Risks & sharp edges

- **`normalize_timestamp("")` returns `""`, and so does `normalize_timestamp(None)`, and so does
  `normalize_timestamp({"t": 1})`.** Three different conditions collapse to one value, and every
  adapter uses the emptiness of the result as "this record has no timestamp"
  (e.g. claude.py:66-69). A malformed timestamp is indistinguishable from an absent one.
- **The millisecond threshold is a magic constant** (`1_000_000_000_000`, common.py:18). It is
  correct for any epoch after 2001 in seconds and any epoch before 33658 in milliseconds, so it
  works, but nothing documents the reasoning and it is duplicated: `read_jsonl._normalize_timestamp`
  (read_jsonl.py:713-719) implements the same heuristic with a different literal (`1e12`) and
  *without* the `None` case. Two copies, subtly different, both live.
- **String timestamps are never validated.** Whatever the platform wrote flows straight into
  `Message.timestamp`, into `group_by_day` (read_jsonl.py:486), and into sorting
  (read_jsonl.py:2553). `group_by_day` catches the parse failure and buckets under `"Unknown"`;
  `_sort_messages_by_ts` catches it and sorts as `datetime.min`. So a bad timestamp silently
  reorders a transcript rather than raising.
