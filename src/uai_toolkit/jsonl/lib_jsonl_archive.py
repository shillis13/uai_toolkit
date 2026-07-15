"""Shared archive-and-stub engine for resume-safe JSONL context paging.

Both offload_tool_results.py (tool_result.content / tool_use.input) and the
upgraded scrub_files.py (embedded images / PDFs / files) extract heavy content
into a portable, fork-safe per-session archive and leave a pointer stub in place;
`read_jsonl --resolve` rehydrates on the fly. This module is the common engine:
the portable Archive, the CAS write guard, recency-window protection, sizing/
rendering helpers, and a kind-aware rehydrate.

Manifest record kinds (one offload_manifest.jsonl per session archive):
  result        — a tool_result.content block            (locator: tool_use_id)
  input.<key>   — a tool_use.input[<key>] payload         (locator: tool_use_id)
  embed         — an image/pdf/file block in a message    (locator: line + path)

Portability (fork-safe): archive dir = <transcript_stem>.<ns>.<uuid8>.archive
(ns ∈ {offload, engram}; legacy dirs are <stem>.<uuid8>.archive). The archive_id
is "<ns>.<uuid8>" for namespaced dirs, so stubs embed only "<archive_id>/<slug>.txt"
— never an absolute path — and a forked copy resolves to its own archive. The
per-mechanism namespace keeps OFFLOAD and ENGRAM in separate dirs + manifests so
layering one on the other can never cross-contaminate (todo_0366).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

KEEP_LAST_TURNS = 5
MIN_BYTES = 512   # ~2x the ~265-char stub overhead, so offloading a block is net-positive
ARCHIVE_SUFFIX = ".archive"
MANIFEST_NAME = "offload_manifest.jsonl"
STUB_PREFIXES = (
    "[archived:", "[tool result stripped:", "[input archived:", "[input stripped:",
    "[embed archived:", "[embed stripped:",
    "[attachment archived:", "[attachment stripped:",
)


# ── low-level file safety ────────────────────────────────────────────────
def _fsync_path(path) -> None:
    """fsync a file's contents to stable storage (best-effort, power-loss safe)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _fsync_dir(path) -> None:
    """fsync a directory entry so child creates/renames are durable (best-effort)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    """True if a PID is live (signal 0 probe). Unknown/permission → assume alive."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _stat_sig(p: Path):
    """Size-only fingerprint for the compare-and-swap write guard.

    The transcript is append-only during a live session, so any external change
    we must not clobber always GROWS the file — size detects it. mtime was
    dropped (2026-06-19): it ticks without a content change (flushes/touches/FS
    granularity) and only produced false 'raced' skips, adding no detection
    power for appends.
    """
    try:
        return (p.stat().st_size,)
    except OSError:
        return None


def ensure_backup(jsonl_path: Path) -> bool:
    """Create a one-time .jsonl.bak (never overwrites an existing one)."""
    backup = jsonl_path.with_suffix(".jsonl.bak")
    if backup.exists():
        return True
    try:
        import shutil
        shutil.copy2(jsonl_path, backup)
        return True
    except OSError:
        return False


def atomic_write(jsonl_path: Path, content: str) -> bool:
    """Write content via temp file + os.replace (atomic)."""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(jsonl_path.parent), prefix=".jarch_tmp_", suffix=".jsonl")
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)                       # MAJOR 2: temp durable before swap
        finally:
            os.close(fd)
        os.replace(tmp_path, str(jsonl_path))
        _fsync_dir(jsonl_path.parent)          # MAJOR 2: rename durable (power-loss safe)
        return True
    except OSError:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        return False


# ── sizing / rendering ───────────────────────────────────────────────────
def wire_size(value) -> int:
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, ensure_ascii=False))


def render_readable(value) -> str:
    """Human/model-readable rendering for the fault-in file."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                if item.get("type") == "text" or "text" in item:
                    parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    mt = (item.get("source") or {}).get("media_type", "image")
                    parts.append(f"[image omitted: {mt}]")
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, indent=2))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return json.dumps(value, ensure_ascii=False, indent=2)


def is_stub(value) -> bool:
    return isinstance(value, str) and value.lstrip().startswith(STUB_PREFIXES)


def sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]


# ── integrity (BLOCKER 1: reversibility is sacred) ────────────────────────
class BodyIntegrityError(Exception):
    """A stored archive body failed its content-hash check on read.

    write_body records sha8(render_readable(value)) at write time; read_exact
    recomputes it after reading and raises this if the on-disk body is
    corrupted, swapped, or copied from the wrong archive. `value` carries the
    decoded (but unverified) content so a DELIBERATE salvage path (allow_corrupt
    at the caller) can still use it while flagging it loudly. The default path
    must fail closed on this — a wrong body must NEVER restore silently.
    """

    def __init__(self, slug, expected, got, value):
        self.slug = slug
        self.expected = expected
        self.got = got
        self.value = value
        super().__init__(
            f"archive body {slug!r} integrity mismatch: "
            f"expected sha8={expected} got sha8={got} (corrupt/swapped body)")


def tokens(nbytes: int) -> int:
    return max(1, round(nbytes / 4))


# ── canonical turn-start predicate (SINGLE SOURCE OF TRUTH) ────────────────
def is_turn_start(rec: dict) -> bool:
    """Canonical predicate: does this record START a numbered turn?

    THE one boundary definition. A record starts a turn iff it carries a non-null
    ``promptSource`` field — i.e. it is a prompt actually SUBMITTED to the model
    (source-agnostic: ``typed`` / ``queued`` / ``system``). ``promptSource`` is the
    canonical "actually-submitted prompt" signal: it is present ONLY on genuine
    submitted prompts and absent on every piece of machinery —
    ``compact_boundary`` / ``isCompactSummary`` summaries, "continued from a
    previous conversation" continuation records, and client-injected ``isMeta``
    skill / system-reminder records all LACK it.

    This REPLACES the old structural heuristic (a top-level non-meta ``user``
    record whose content is not a ``tool_result``), which over-counted that
    machinery: on one stable transcript the heuristic reported 16 "turns" vs the 12
    real prompts ``promptSource`` reports (the 4 extras being an ``isCompactSummary``
    record + 3 continuation records that lack ``promptSource``). ``promptSource`` is
    the exact, non-heuristic signal.

    Every turn-numbering surface delegates HERE so the turn the user SEES in the
    context_stats histogram equals the turn the Offload engine ACTS on:
      * chain_skip._is_human_turn_start  (Offload/Summarize engine)
      * lib_context_analysis.is_human_prompt  (context_stats display)
      * human_turn_indices below  (recency-window authority; fallback path)
    """
    return isinstance(rec, dict) and rec.get("promptSource") is not None


# Back-compat alias: callers still import ``is_human_turn_start``. It IS the ONE
# canonical predicate now — a submitted prompt (non-null ``promptSource``).
is_human_turn_start = is_turn_start


# ── canonical RECORD classification (SINGLE SOURCE OF TRUTH) ──────────────
# What KIND of thing a raw JSONL record is. This is the message/record analogue
# of is_human_turn_start: every jsonl tool that needs to know "what is this
# record" delegates HERE so read_jsonl (per-message view), lib_context_analysis
# (per-block byte split + reclaim buckets) and chain_skip (offload eligibility)
# can never disagree on a record's identity — only on how they AGGREGATE it.
#
# The detection rules are read_jsonl's (the richest, most-correct upstream
# classifier — see platform_adapters/claude.classify_user_type, which now
# delegates to these predicates): a client-injected `isMeta` user record that
# carries a ``sourceToolUseID`` is a SKILL expansion (a 600KB skill dump is a
# `skill`, NOT `system_meta`); an ``origin.kind == "task-notification"`` record
# is an AGENT_RESULT (subagent notification); any other `isMeta` user record is
# generic INJECTED content (system-reminders, hook context). These are the exact
# structural markers that distinguish a 150k-token skill body from a ~2-token
# bookkeeping record — the conflation this classifier exists to prevent.

def _record_content_blocks(rec: dict) -> list:
    """message.content as a block list (a bare-string body -> one text block)."""
    msg = rec.get("message") if isinstance(rec, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def is_agent_result(rec: dict) -> bool:
    """Subagent / task notification injected into the user stream
    (``origin.kind == 'task-notification'``)."""
    if not isinstance(rec, dict):
        return False
    origin = rec.get("origin")
    return isinstance(origin, dict) and origin.get("kind") == "task-notification"


def is_skill(rec: dict) -> bool:
    """A skill expansion: client-injected meta (``isMeta``) carrying the
    ``sourceToolUseID`` of the tool call that expanded it. THE marker that keeps a
    600KB skill body out of the ~2-token ``system_meta`` bucket."""
    return isinstance(rec, dict) and bool(rec.get("isMeta")) and bool(rec.get("sourceToolUseID"))


def is_injected(rec: dict) -> bool:
    """Other non-human client-injected meta (system-reminders, hook additional
    context): ``isMeta`` without the skill/agent markers."""
    if not isinstance(rec, dict) or not rec.get("isMeta"):
        return False
    return not rec.get("sourceToolUseID") and not is_agent_result(rec)


def is_attachment(rec: dict) -> bool:
    return isinstance(rec, dict) and rec.get("type") == "attachment"


def is_tool(rec: dict) -> bool:
    """A record whose message.content is PURELY tool_use / tool_result blocks
    (an atomic tool cycle — Offload-skippable). A record mixing text with a
    tool_use is NOT a tool record (skipping it would drop the text)."""
    if not isinstance(rec, dict) or is_attachment(rec) or rec.get("type") == "system":
        return False
    if is_skill(rec) or is_injected(rec) or is_agent_result(rec):
        return False
    blocks = _record_content_blocks(rec)
    btypes = {b.get("type") for b in blocks if isinstance(b, dict)}
    return bool(btypes) and btypes <= {"tool_use", "tool_result"}


def classify_user_record(rec: dict) -> str:
    """Canonical kind for a *user-role* record: user | skill | agent_result |
    injected. This is exactly the logic read_jsonl's claude adapter uses to tag a
    user record (it delegates here). Precedence mirrors the adapter: agent-result,
    then skill, then generic injected, else a genuine human/user record."""
    if is_agent_result(rec):
        return "agent_result"
    if is_skill(rec):
        return "skill"
    if is_injected(rec):
        return "injected"
    return "user"


def classify_record(rec: dict) -> str:
    """Canonical RECORD-level kind — the one classifier all jsonl tools share.

    Returns one of:
      attachment | system | skill | agent_result | injected | tool | user | assistant

    ``skill`` / ``agent_result`` / ``injected`` are client-injected meta on the
    user stream (detected via isMeta / sourceToolUseID / origin — see the module
    predicates). ``tool`` is a record whose content is purely tool_use/tool_result
    (Offload-skippable). Everything else is a genuine ``user`` prompt, an
    ``assistant`` reasoning/text record, or a client ``system`` record."""
    if not isinstance(rec, dict):
        return "system"
    t = rec.get("type")
    if t == "attachment":
        return "attachment"
    if t == "system":
        return "system"
    # client-injected meta on the user stream (precedence per the claude adapter)
    if is_agent_result(rec):
        return "agent_result"
    if is_skill(rec):
        return "skill"
    if is_injected(rec):
        return "injected"
    # genuine conversation content
    blocks = _record_content_blocks(rec)
    btypes = {b.get("type") for b in blocks if isinstance(b, dict)}
    if btypes and btypes <= {"tool_use", "tool_result"}:
        return "tool"
    if t == "user":
        return "user"
    return "assistant"


# ── recency window (canonical human-turn classifier) ─────────────────────
def human_turn_indices(jsonl_path: Path, records: list) -> list:
    """0-indexed record positions of genuine human prompts, via read_jsonl.

    Falls back to the canonical is_turn_start() predicate (a submitted prompt —
    non-null promptSource) only if the canonical parser fails.
    """
    try:
        from uai_toolkit.jsonl import read_jsonl as rj
        msgs = rj.parse_session(jsonl_path)
        # m.source_line is the RAW 1-indexed JSONL line (m.line_number is only the
        # message ordinal — using it here was the recency-window bug). Map to the
        # raw 0-indexed record positions this module iterates.
        idx = sorted({m.source_line - 1 for m in msgs
                      if m.type == rj.MessageType.USER and m.source_line})
        if idx:
            return idx
    except Exception:
        pass
    # Fallback (read_jsonl unavailable): the ONE canonical predicate — a submitted
    # prompt (non-null promptSource). Machinery records (isCompactSummary /
    # continuation / isMeta) lack promptSource and so are correctly NOT counted.
    return [i for i, r in enumerate(records) if is_turn_start(r)]


def protect_from_index(jsonl_path: Path, records: list, keep_last_turns: int) -> int:
    """Index at/after which everything is protected verbatim (i >= this => keep)."""
    if keep_last_turns <= 0:
        return len(records)
    human = human_turn_indices(jsonl_path, records)
    if len(human) <= keep_last_turns:
        return 0
    return human[-keep_last_turns]


# ── namespaced archive-dir resolution (todo_0366) ─────────────────────────
# Two mechanisms page content into a per-transcript archive: OFFLOAD
# (offload_tool_results + scrub_files embeds) and ENGRAM (lib_engram
# consolidate/recall). They MUST NOT share one dir + manifest — layering offload
# on a consolidated transcript used to reuse the engram dir (stem-glob match) and
# append kind-less offload records into the engram manifest, corrupting rehydrate.
# Fix: namespace the dir per mechanism as <stem>.<ns>.<id>.archive, and make the
# archive_id "<ns>.<id>" so the portable stub ref (<archive_id>/<slug>.txt) still
# reconstructs the dir via read_jsonl's <stem>.<uuid8>.archive rule UNCHANGED.
KNOWN_NAMESPACES = ("offload", "engram")


def _manifest_ownership(manifest_path: Path) -> tuple[bool, bool]:
    """Peek a legacy manifest → (has_engram, has_offload).

    has_engram  = at least one kind=="engram" record.
    has_offload = at least one NON-engram record (offload result/input, embed,
                  toplevel, attachment, or a legacy kind-less offload record).
    Used to decide whether a legacy non-namespaced dir belongs to a given
    mechanism (back-compat resolution). Missing/empty manifest → (False, False).
    """
    has_engram = has_offload = False
    try:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and r.get("kind") == "engram":
                has_engram = True
            else:
                has_offload = True
    except OSError:
        pass
    return has_engram, has_offload


def resolve_archive_dir(base: Path, stem: str, namespace: str | None):
    """Resolve (archive_dir: Path, archive_id: str) for a transcript stem.

    A namespaced dir is <stem>.<ns>.<id>.archive with archive_id "<ns>.<id>".
    A legacy dir is <stem>.<bareid>.archive with archive_id "<bareid>".

    namespace=None (legacy engine callers): reuse the first existing dir of any
    shape, else mint a bare-id dir (pre-todo_0366 behaviour, unchanged).

    namespace in KNOWN_NAMESPACES:
      (b) reuse an existing <stem>.<ns>.*.archive for THIS mechanism;
      (c) else fall back to a legacy bare-id dir that BELONGS to this mechanism
          (manifest ownership check) so pre-namespacing archives still resolve;
      (d) else create a fresh <stem>.<ns>.<id>.archive.
    """
    prefix = f"{stem}."
    suffix = ARCHIVE_SUFFIX
    existing = sorted(base.glob(f"{prefix}*{suffix}")) if base.exists() else []
    namespaced: list = []   # (dir, archive_id) whose head == this namespace
    legacy: list = []       # (dir, archive_id) bare-id (no known-ns head)
    for d in existing:
        mid = d.name[len(prefix):-len(suffix)]
        head = mid.split(".", 1)[0]
        if "." in mid and head in KNOWN_NAMESPACES:
            if head == namespace:
                namespaced.append((d, mid))
            # else: another mechanism's namespaced dir → ignore
        else:
            legacy.append((d, mid))

    if namespace is None:
        if existing:
            d = existing[0]
            return d, d.name[len(prefix):-len(suffix)]
        new_id = uuid.uuid4().hex[:8]
        return base / f"{prefix}{new_id}{suffix}", new_id

    if namespaced:
        return namespaced[0]

    for d, aid in legacy:
        has_engram, has_offload = _manifest_ownership(d / MANIFEST_NAME)
        belongs = ((namespace == "engram" and has_engram and not has_offload)
                   or (namespace == "offload" and has_offload and not has_engram))
        if belongs:
            return d, aid

    new_id = uuid.uuid4().hex[:8]
    aid = f"{namespace}.{new_id}"
    return base / f"{prefix}{aid}{suffix}", aid


# ── archive store (portable, fork-safe) ──────────────────────────────────
class Archive:
    def __init__(self, jsonl_path: Path, dry_run: bool = False,
                 archive_dir: str | None = None, namespace: str | None = None):
        self.base = Path(archive_dir).expanduser() if archive_dir else jsonl_path.parent
        self.stem = jsonl_path.stem
        self.namespace = namespace
        self.dir, self.archive_id = resolve_archive_dir(self.base, self.stem, namespace)
        self.manifest = self.dir / MANIFEST_NAME
        self.dry_run = dry_run

    def ensure(self):
        if not self.dry_run:
            self.dir.mkdir(parents=True, exist_ok=True)

    def ref(self, slug: str) -> str:
        """Portable, fork-safe reference embedded in the stub (uuid8 + slug)."""
        return f"{self.archive_id}/{slug}.txt"

    def write_body(self, slug: str, value, meta: dict | None = None) -> tuple[str, dict]:
        """Persist a value under <slug>; return (portable_ref, manifest_record).

        slug examples: '<tool_use_id>.result', '<tool_use_id>.input.content',
        '<msg_uuid>.<n>.embed'. meta carries kind + locator fields.
        """
        readable = render_readable(value)
        is_plain = isinstance(value, str)
        rec = {
            "slug": slug,
            "ref": self.ref(slug),
            "bytes": wire_size(value),
            "sha8": sha8(readable),
            "exact_kind": "txt" if is_plain else "json",
        }
        if meta:
            rec.update(meta)
        if not self.dry_run:
            txt = self.dir / f"{slug}.txt"
            txt.write_text(readable, encoding="utf-8")
            _fsync_path(txt)                   # MAJOR 2: body durable before referenced
            if not is_plain:
                jsn = self.dir / f"{slug}.json"
                jsn.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                _fsync_path(jsn)
        return rec["ref"], rec

    def fsync_dir(self) -> None:
        """fsync the archive directory (durably commit newly created body files)."""
        if not self.dry_run:
            _fsync_dir(self.dir)

    @property
    def lock_path(self) -> Path:
        return self.dir / (MANIFEST_NAME + ".lock")

    @property
    def _lock_owner_path(self) -> Path:
        return self.lock_path / "owner.json"

    def _lock_is_stale(self, stale_after: float) -> bool:
        """MINOR 2: a held lock is stealable only if its owner PID is dead OR the
        lock mtime is older than `stale_after`. Missing/garbage owner metadata
        falls back to the mtime rule (back-compat with pre-owner lock dirs)."""
        try:
            meta = json.loads(self._lock_owner_path.read_text(encoding="utf-8"))
            pid = meta.get("pid")
            if isinstance(pid, int) and not _pid_alive(pid):
                return True            # holder is provably dead → safe to steal
        except (OSError, json.JSONDecodeError, ValueError):
            pass                       # no/garbage owner → fall through to mtime
        try:
            age = time.time() - self.lock_path.stat().st_mtime
            return age > stale_after
        except OSError:
            return False

    def _force_release_lock(self) -> None:
        try:
            self._lock_owner_path.unlink()
        except OSError:
            pass
        os.rmdir(self.lock_path)

    @contextmanager
    def manifest_lock(self, timeout: float = 10.0, poll: float = 0.05,
                      stale_after: float = 120.0):
        """Atomic mkdir-based lock around ALL manifest mutations.

        Reentrancy is NOT supported (mkdir lock); never nest. Owner metadata
        (pid, started_at) is written into the lock dir so a held lock is stolen
        ONLY if the holder PID is dead OR the lock is older than `stale_after`
        (MINOR 2). Keep held sections tiny. Released in finally.
        """
        if self.dry_run:
            yield
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + timeout
        acquired = False
        while True:
            try:
                os.mkdir(self.lock_path)
                acquired = True
                try:                   # record owner so others can judge staleness
                    self._lock_owner_path.write_text(
                        json.dumps({"pid": os.getpid(),
                                    "started_at": time.time()}),
                        encoding="utf-8")
                except OSError:
                    pass
                break
            except FileExistsError:
                if self._lock_is_stale(stale_after):
                    try:
                        self._force_release_lock()
                        continue
                    except OSError:
                        pass
                if time.time() > deadline:
                    raise TimeoutError(f"manifest lock timeout: {self.lock_path}")
                time.sleep(poll)
        try:
            yield
        finally:
            if acquired:
                try:
                    self._lock_owner_path.unlink()
                except OSError:
                    pass
                try:
                    os.rmdir(self.lock_path)
                except OSError:
                    pass

    def append_manifest(self, recs: list) -> bool:
        """Append manifest records under the manifest lock. Returns success."""
        if self.dry_run or not recs:
            return True
        try:
            with self.manifest_lock():
                with open(self.manifest, "a", encoding="utf-8") as f:
                    for r in recs:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_dir(self.dir)           # MAJOR 2: dir entry durable
            return True
        except (OSError, TimeoutError):
            return False

    def rewrite_manifest(self, recs: list) -> bool:
        """Atomically replace the whole manifest (temp file + os.replace).

        The CALLER must hold `manifest_lock()` (this method does not acquire it,
        to allow read-modify-write under a single lock).
        """
        if self.dry_run:
            return True
        content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs)
        tmp_path = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=str(self.dir),
                                            prefix=".manifest_tmp_", suffix=".jsonl")
            try:
                os.write(fd, content.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp_path, str(self.manifest))
            _fsync_dir(self.dir)              # MAJOR 2: manifest rename durable
            return True
        except OSError:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            return False

    def load_manifest(self) -> list:
        if not self.manifest.exists():
            return []
        out = []
        for line in self.manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def read_exact(self, rec: dict, *, verify: bool = True):
        """Resolve a manifest record to its exact original value.

        BLOCKER 1 (reversibility is sacred): after reading the body, recompute
        the content hash the SAME way write_body did — sha8(render_readable(
        value)) — and compare to the stored `sha8`. On mismatch raise
        BodyIntegrityError (fail closed): a corrupted / swapped / wrong-archive
        body must never restore silently. The raised error carries the decoded
        value so a deliberate salvage path (allow_corrupt at the caller) can
        still use it while flagging it. `verify=False` skips the check; a legacy
        record with no stored sha8 is also skipped (nothing to compare against).
        """
        slug = rec.get("slug")
        if slug is None:  # legacy offloader records (tool_use_id + field)
            slug = f'{rec["tool_use_id"]}.{rec["field"]}'
        if rec.get("exact_kind") == "json":
            value = json.loads((self.dir / f"{slug}.json").read_text(encoding="utf-8"))
        else:
            value = (self.dir / f"{slug}.txt").read_text(encoding="utf-8")
        expected = rec.get("sha8")
        if verify and expected is not None:
            got = sha8(render_readable(value))
            if got != expected:
                raise BodyIntegrityError(slug, expected, got, value)
        return value


# ── commit (CAS-guarded, byte-identical untouched lines) ─────────────────
def commit(jsonl_path: Path, raw_lines: list, records: list, dirty: set,
           sig0, sig1, backup: bool = True) -> str:
    """Write only changed records; leave untouched lines byte-identical.

    Returns 'nochange' | 'raced' | 'error' | 'ok'. CAS: refuses to write if the
    transcript changed under us between read and write (live append).
    """
    if not dirty:
        return "nochange"
    if sig0 != sig1 or _stat_sig(jsonl_path) != sig1:
        return "raced"
    if backup:
        ensure_backup(jsonl_path)
    # Compact separators match Claude Code's writer exactly, so a record whose
    # content is unchanged (e.g. a parentUuid restored on rehydrate) re-serializes
    # byte-for-byte — preserving the byte-exact gold standard. Default json.dumps
    # separators (", "/": ") would inject whitespace and break it.
    out = [json.dumps(records[i], ensure_ascii=False, separators=(",", ":")) if i in dirty else raw
           for i, raw in enumerate(raw_lines)]
    return "ok" if atomic_write(jsonl_path, "\n".join(out) + "\n") else "error"


# ── kind-aware rehydrate (restores any stubbed block) ────────────────────
def _nav_set(record: dict, path: list, value):
    cur = record
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value


def rehydrate(jsonl_path: Path, dry_run: bool = False, archive_dir: str | None = None,
              namespace: str | None = "offload") -> dict:
    """Restore every stubbed block from the archive manifest. Handles all kinds.

    Defaults to the "offload" namespace (the offload/embed family this engine
    rehydrate serves); engram records are never touched here (lib_engram owns
    them). Pass namespace=None only for legacy reuse-first resolution.
    """
    archive = Archive(jsonl_path, dry_run, archive_dir, namespace=namespace)
    recs = archive.load_manifest()
    if not recs:
        return {"restored": 0, "note": "empty or missing manifest"}

    sig0 = _stat_sig(jsonl_path)
    raw_text = jsonl_path.read_text(encoding="utf-8")
    sig1 = _stat_sig(jsonl_path)
    raw_lines = raw_text.splitlines()
    records = []
    for line in raw_lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append(line)

    # id-keyed (tool content) restores: last write wins
    by_id = {}
    embed_recs = []
    for r in recs:
        kind = r.get("kind")
        if kind == "engram":
            continue  # engram records belong to lib_engram; never rehydrated here
        if kind == "embed" or (kind is None and r.get("path") is not None):
            embed_recs.append(r)
        else:
            tid = r.get("tool_use_id", "")
            field = r.get("field") or (r.get("slug", "").split(".", 1)[1] if "." in r.get("slug", "") else "")
            by_id[(tid, field)] = r

    restored = 0
    dirty = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                key = (block.get("tool_use_id", ""), "result")
                if key in by_id and is_stub(block.get("content")):
                    block["content"] = archive.read_exact(by_id[key]); restored += 1; dirty.add(i)
            elif block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                for ik in list(block["input"].keys()):
                    key = (block.get("id", ""), f"input.{ik}")
                    if key in by_id and is_stub(block["input"].get(ik)):
                        block["input"][ik] = archive.read_exact(by_id[key]); restored += 1; dirty.add(i)

    # embed restores (line + path locator)
    for r in embed_recs:
        li = r.get("line")
        path = r.get("path")
        if li is None or path is None or li >= len(records):
            continue
        try:
            _nav_set(records[li], path, archive.read_exact(r))
            restored += 1
            dirty.add(li)
        except (KeyError, IndexError, TypeError):
            pass

    if dirty and not dry_run:
        status = commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=False)
        if status == "raced":
            return {"restored": 0, "raced": True}
    return {"restored": restored}


# ── canonical COMPACTION-INTERVAL model (SINGLE SOURCE OF TRUTH) ──────────
# The ONE enumeration + selection of compaction intervals, shared by every jsonl
# tool that is interval-aware — read_jsonl (line-range Message filter),
# context_stats (per-interval reclaim ledger) and the future turn_digest. This
# is the same single-source pattern as is_turn_start (turn counting) and
# classify_record (record kind): read_jsonl was the origin of this logic and now
# DELEGATES here (thin aliases) so the interval NUMBERING can never diverge
# across tools. The numbering is preserved EXACTLY:
#   interval 0 = prologue — raw lines 1 .. (first-compaction start_line - 1). May
#                be empty if the file opens with a compaction.
#   interval k (k = 1..N) = event k start_line .. (event k+1 start_line - 1)/EOF.
#   the LAST interval is the live/current region — `last` / `live`.
# Membership is LINE-RANGE based (a record's 1-indexed raw file line). This is the
# coarse, tool-agnostic partition; the finer BRANCH model below narrows an interval
# to its live parentUuid chain for the reclaim tools.

def _raw_line_count(jsonl_path) -> int:
    """Count raw lines in a JSONL file (1 line == 1 record)."""
    n = 0
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for _ in fh:
                n += 1
    except OSError:
        return 0
    return n


def find_compactions(jsonl_path) -> list:
    """Scan RAW lines for compaction events.

    Returns one dict per event, 1-indexed and in file order:
      {"index": k, "start_line": <earliest raw line of the event>,
       "summary_line": <raw line with isCompactSummary>,
       "timestamp": <ts or "">, "summary_chars": <len of the summary line>}
    """
    events: list = []
    prev_line_num = 0
    prev_obj = None
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                try:
                    obj = json.loads(line)
                except Exception:
                    obj = None
                if isinstance(obj, dict) and obj.get("isCompactSummary") is True:
                    start_line = i
                    if (
                        prev_obj is not None
                        and prev_line_num == i - 1
                        and prev_obj.get("type") == "system"
                        and prev_obj.get("subtype") == "compact_boundary"
                    ):
                        start_line = prev_line_num
                    events.append({
                        "index": len(events) + 1,
                        "start_line": start_line,
                        "summary_line": i,
                        "timestamp": obj.get("timestamp", "") or "",
                        "summary_chars": len(line.rstrip("\n")),
                    })
                prev_line_num, prev_obj = i, obj if isinstance(obj, dict) else None
    except OSError:
        return []
    return events


def compaction_intervals(jsonl_path) -> list:
    """Partition the raw file into compaction intervals (canonical).

    interval 0 = "prologue": raw lines 1 .. (first event start_line - 1). May be
    empty (end_line < start_line) if the file opens with a compaction.
    interval k (k=1..N) = event k start_line .. (event k+1 start_line - 1) or EOF.
    The LAST interval is the live/current region. With no events, interval 0
    spans the whole file.

    Returns [{"index": i, "start_line": s, "end_line": e, "is_prologue": bool}, ...].
    """
    events = find_compactions(jsonl_path)
    total = _raw_line_count(jsonl_path)
    if not events:
        return [{"index": 0, "start_line": 1, "end_line": total, "is_prologue": True}]

    intervals = [{
        "index": 0,
        "start_line": 1,
        "end_line": events[0]["start_line"] - 1,
        "is_prologue": True,
    }]
    for i, ev in enumerate(events):
        start = ev["start_line"]
        end = (events[i + 1]["start_line"] - 1) if i + 1 < len(events) else total
        intervals.append({
            "index": i + 1,
            "start_line": start,
            "end_line": end,
            "is_prologue": False,
        })
    return intervals


def select_intervals(spec: str, intervals: list):
    """Resolve an --interval SPEC against the file's intervals (canonical parser).

    SPEC grammar (shared by every interval-aware tool):
      * a single integer      — 0=prologue, 1..N
      * the words last / live — the final interval (current/live region)
      * negative indices      — OFFSET FROM live: -1 = one before live, -2 = two before, ...
                                (live itself is `live`/`last`, never a negative)
      * comma lists           — "1,3"
      * ranges                — "2-4"
    Returns (selected_intervals, None) or (None, error_message).
    """
    max_index = intervals[-1]["index"]
    valid = {iv["index"] for iv in intervals}
    chosen: list = []
    for token in spec.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token in ("last", "live"):
            chosen.append(intervals[-1]["index"])
        elif token.startswith("-"):
            # Negative = OFFSET FROM LIVE (the named anchor), NOT Python from-the-end indexing.
            # live == the last interval (index max_index); -1 = one BEFORE live (max_index-1),
            # -2 = two before, ... So a negative always steps back FROM live; live itself is
            # reachable as live/last/max_index, never as a negative.
            try:
                offset = int(token)               # e.g. -1, -2  (negative)
            except ValueError:
                return None, f"Invalid interval index: {token}"
            target = max_index + offset           # max_index + (-1) = one before live
            if target < 0:
                return None, (f"{token} steps past the oldest interval — only {max_index} "
                              f"interval(s) exist before live (0..{max_index})")
            chosen.append(target)
        elif "-" in token:
            lo_s, hi_s = token.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                return None, f"Invalid interval range: {token}"
            chosen.extend(range(lo, hi + 1))
        else:
            try:
                chosen.append(int(token))
            except ValueError:
                return None, f"Invalid interval token: {token}"

    bad = sorted({i for i in chosen if i not in valid})
    if bad:
        note = "no compactions in this file" if max_index == 0 else f"{max_index} compaction(s)"
        return None, (
            f"Requested interval(s) {bad} not available — file has intervals 0..{max_index} ({note})."
        )
    want = set(chosen)
    return [iv for iv in intervals if iv["index"] in want], None


def interval_line_ranges(selected: list) -> list:
    """[(start_line, end_line), ...] for a list of selected interval dicts."""
    return [(iv["start_line"], iv["end_line"]) for iv in selected]


def line_in_intervals(line: int, ranges: list) -> bool:
    """True if a 1-indexed raw file line falls inside any (lo, hi) range."""
    return bool(line) and any(lo <= line <= hi for lo, hi in ranges)


# ── canonical BRANCH model within an interval (SINGLE SOURCE OF TRUTH) ─────
# An interval's line-range is the COARSE partition; the branch model is the FINE
# one. Each /compact starts a fresh parentUuid=None root, so the records inside
# one interval form a small forest. Within that forest:
#   br0  = the LIVE branch — the tip->root parentUuid path that a --resume
#          actually reloads. This is EXACTLY the chain context_stats has always
#          walked for the current interval; making it br0 of the selected interval
#          is what lets context_stats be interval-aware without changing its
#          default behaviour (default interval = last, default branch = br0).
#   br1+ = rewind / dead-retry FORKS — sibling subtrees that end BEFORE the live
#          tip (an abandoned edit-and-retry, a rewound turn). They are off the
#          resumed chain and never count as live context.
# v1 fully POPULATES only br0; fork enumeration is a documented stub (the --branch
# flag, its live default, and the br0 concept exist and are shared NOW).
BRANCH_LIVE = 0


def records_with_lines(jsonl_path) -> list:
    """[(record, 1-indexed raw line), ...] for every non-blank JSONL line, file order.

    The shared loader for the branch model: interval membership is line-range based,
    so every branch helper needs each record's raw file line."""
    out: list = []
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    out.append((obj, i))
    except OSError:
        return []
    return out


def interval_live_chain(recs_lines: list, interval: dict) -> list:
    """br0 for one interval: the live tip->root parentUuid chain (root-first uuids).

    `recs_lines` is records_with_lines() output. Restricts to records whose raw
    line falls in the interval, finds the interval's conversational leaf (latest
    non-sidechain user/assistant, else the latest record), and walks parentUuid
    back to the interval's root — staying WITHIN the interval. Mirrors read_jsonl's
    current-interval chain walk so the two tools agree on what "the live branch"
    is. Returns [] for an empty interval."""
    lo, hi = interval["start_line"], interval["end_line"]
    sub = [(r, ln) for r, ln in recs_lines if r.get("uuid") and lo <= ln <= hi]
    if not sub:
        return []
    by = {r["uuid"]: r for r, _ in sub}
    leaf = None
    for r, _ln in sorted(sub, key=lambda x: -x[1]):
        if r.get("isSidechain"):
            continue
        if r.get("type") in ("user", "assistant") and r.get("uuid"):
            leaf = r["uuid"]
            break
    if leaf is None:
        leaf = max(sub, key=lambda x: x[1])[0].get("uuid")
    rev, cur, seen = [], leaf, set()
    while cur in by and cur not in seen:
        seen.add(cur)
        rev.append(cur)
        p = by[cur].get("parentUuid")
        if p not in by:
            break
        cur = p
    return rev[::-1]


def interval_branches(recs_lines: list, interval: dict) -> list:
    """Enumerate the branches within one interval. Branch 0 = live (br0).

    Returns [{"index": 0, "kind": "live", "uuids": [root..tip]}]. v1 populates
    ONLY the live branch.
    # TODO v1.1: full fork enumeration — walk every leaf whose subtree ends before
    # the live tip and emit each as br1, br2, ... (rewind / dead-retry forks).
    """
    live = interval_live_chain(recs_lines, interval)
    return [{"index": BRANCH_LIVE, "kind": "live", "uuids": live}]


def select_branches(spec, branches: list):
    """Resolve a --branch SPEC against an interval's branches (canonical parser).

    SPEC grammar: an integer or `brN` index (0 = live), the words `live`/`br0`,
    negatives (-1 = last), comma lists, and ranges. Default (None/empty) = the
    live branch (br0). Returns (selected_branches, None) or (None, error_message).
    Since v1 enumerates only br0, any request beyond br0 errors clearly rather than
    silently returning live."""
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        return [b for b in branches if b["index"] == BRANCH_LIVE], None
    valid = {b["index"] for b in branches}
    chosen: list = []
    for token in str(spec).split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token.startswith("br"):
            token = token[2:]
        if token in ("live", ""):
            chosen.append(BRANCH_LIVE)
        elif token.startswith("-"):
            try:
                chosen.append(branches[int(token)]["index"])
            except (ValueError, IndexError):
                return None, f"Invalid/out-of-range branch index: {token}"
        elif "-" in token:
            lo_s, hi_s = token.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                return None, f"Invalid branch range: {token}"
            chosen.extend(range(lo, hi + 1))
        else:
            try:
                chosen.append(int(token))
            except ValueError:
                return None, f"Invalid branch token: {token}"
    bad = sorted({i for i in chosen if i not in valid})
    if bad:
        return None, (
            f"Requested branch(es) {bad} not available — v1 enumerates only br0 (live). "
            f"# TODO v1.1: full fork enumeration."
        )
    want = set(chosen)
    return [b for b in branches if b["index"] in want], None


# ── analysis (read-only region/token-mass map) ───────────────────────────
LARGE_INPUT_KEYS = {"content", "old_string", "new_string", "command", "text",
                    "body", "code", "source", "data", "input"}


MIN_SUMMARY_CHARS = 2000  # below this an isCompactSummary is a tiny marker, not a real summary


def compaction_boundaries(records: list, min_chars: int = 0) -> list:
    """0-indexed lines that are compaction summaries. Detects Claude's
    isCompactSummary flag and the 'continued from a previous conversation'
    continuation marker. With min_chars>0, returns only SUBSTANTIVE summaries
    (rendered text >= min_chars) — the live context starts at the last of those;
    tiny continuation markers (~700 chars) are excluded.
    """
    out = []
    for i, o in enumerate(records):
        if not isinstance(o, dict):
            continue
        m = o.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        txt = ""
        if isinstance(c, str):
            txt = c
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    txt += b["text"]
        is_summary = bool(o.get("isCompactSummary")) or ("continued from a previous conversation" in txt)
        if is_summary and len(txt) >= min_chars:
            out.append(i)
    return sorted(set(out))


def _image_vision_tokens(block: dict) -> int:
    """Estimate vision tokens for an image block ~ (w*h)/750 (Anthropic approx);
    flat 1500 fallback when dimensions can't be read. Header-only decode, cheap."""
    try:
        data = (block.get("source") or {}).get("data")
        if isinstance(data, str) and data:
            from uai_toolkit.jsonl import scrub_files
            dims = scrub_files.get_image_dimensions_from_base64(data)
            if dims:
                w, h = dims
                return max(1, int(w * h / 750))
    except Exception:
        pass
    return 1500


def analyze(jsonl_path: Path, keep_last_turns: int = KEEP_LAST_TURNS, min_bytes: int = MIN_BYTES) -> dict:
    """Read-only token-mass map by region — no file changes.

    Regions: pre_compaction (dead history, not sent) | live_offloadable
    (post-last-compaction, outside the recency window — the real lever) |
    live_protected (last N turns, left verbatim).
    """
    raw_lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    records = []
    for line in raw_lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({})

    all_boundaries = compaction_boundaries(records)
    sub_boundaries = compaction_boundaries(records, MIN_SUMMARY_CHARS)
    last_comp = sub_boundaries[-1] if sub_boundaries else 0   # live context starts at the last SUBSTANTIVE summary
    protect_from = protect_from_index(jsonl_path, records, keep_last_turns)
    human = human_turn_indices(jsonl_path, records)

    def _region(i):
        if i < last_comp:
            return "pre_compaction"
        if i < protect_from:
            return "live_offloadable"
        return "live_protected"

    def _blank():
        return {"lines": 0, "content_chars": 0, "off_results": 0, "off_inputs": 0,
                "off_chars": 0, "stubbed": 0, "off_embeds": 0, "embed_tokens": 0}
    reg = {"pre_compaction": _blank(), "live_offloadable": _blank(), "live_protected": _blank()}

    for i, o in enumerate(records):
        if not isinstance(o, dict):
            continue
        r = reg[_region(i)]
        r["lines"] += 1
        m = o.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if c is not None:
            r["content_chars"] += wire_size(c)
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                v = b.get("content")
                if is_stub(v):
                    r["stubbed"] += 1
                elif v is not None and wire_size(v) >= min_bytes:
                    r["off_results"] += 1
                    r["off_chars"] += wire_size(v)
            elif b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
                for k, vv in b["input"].items():
                    if k not in LARGE_INPUT_KEYS:
                        continue
                    if is_stub(vv):
                        r["stubbed"] += 1
                    elif wire_size(vv) >= min_bytes:
                        r["off_inputs"] += 1
                        r["off_chars"] += wire_size(vv)
            elif b.get("type") == "image":
                # Embeds cost VISION tokens (dimension-based), NOT chars — tally
                # them separately so they aren't conflated with off_tokens (Codex #4).
                src = b.get("source") or {}
                data = src.get("data") if isinstance(src, dict) else None
                if isinstance(data, str) and data and not is_stub(data):
                    r["off_embeds"] += 1
                    r["embed_tokens"] += _image_vision_tokens(b)

    for r in reg.values():
        r["content_tokens"] = tokens(r["content_chars"]) if r["content_chars"] else 0
        r["off_tokens"] = tokens(r["off_chars"]) if r["off_chars"] else 0

    return {
        "total_lines": len(records),
        "human_turns": len(human),
        "compaction_boundaries": [b + 1 for b in all_boundaries],       # all markers, 1-indexed
        "substantive_boundaries": [b + 1 for b in sub_boundaries],       # real summaries only
        "last_compaction_line": (last_comp + 1) if sub_boundaries else None,
        "protect_from_line": protect_from + 1,  # 0-indexed record -> 1-indexed human line (Codex #3)
        "keep_last_turns": keep_last_turns,
        "min_bytes": min_bytes,
        "regions": reg,
    }
