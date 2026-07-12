"""Engram layer: turn-consolidation disk-ops on top of lib_jsonl_archive.

An *engram* is a stored memory trace: the archived bytes of a consolidated
turn-range, plus a summary stub left in its place on the active chain. This
module adds two reversible disk-ops on top of the proven archive engine
(`lib_jsonl_archive.py`) — it imports the engine's primitives and only extends
it with a manifest lock + atomic manifest rewrite:

  consolidate(...)        page-out — the "Summarize" operation: archive a
                          turn-range, stub it, re-route the chain. Public alias:
                          `summarize(...)` (same signature; "consolidate" is
                          retained as the internal name for back-compat).
  rehydrate_engram(...)   exact inverse — the user-facing "Restore" operation:
                          restore the originals + pointers (byte-exact)

Terms
  Engram id    — durable unique id `<first_uuid8>.<uuid4hex8>` minted per
                 consolidation. ALL archive body slugs derive from it
                 (`engram.<engram_id>.<n>`), so a later consolidation that
                 starts at the same first_uuid NEVER overwrites an earlier
                 engram's bodies (the recursion / source-immutability fix).
  Turn         — one human prompt + everything up to (not incl.) the next human
                 prompt. Boundaries come from `_is_human_prompt` on the chain.
  Active chain — the path from the conversational leaf up through `parentUuid`.
                 The model only ever sees the active chain; off-chain records
                 are invisible. Leaf selection is policy-driven
                 (`select_active_leaf`) so trailing system/attachment/sidechain
                 records do not masquerade as the conversational leaf.
  Successor    — the first record of the NEXT human turn (its parentUuid is the
                 pointer we re-route).

Crash-recovery (two-phase commit): bodies are written, then a manifest record
is appended with state="prepared", then the transcript is committed, then the
manifest record is flipped to state="committed". recall/rehydrate act only on
committed records (or recover from the FULL restoration metadata embedded in the
stub itself). On a CAS race / error the record is flipped to "aborted" and the
prepared body files are deleted (collectable via memory_manager.py gc-archive).

Manifest: one `kind:"engram"` record per consolidation in the session archive's
offload_manifest.jsonl (flat locator fields + schema_version + engram_id + state).
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Make the engine importable whether or not the script dir is on sys.path.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from uai_toolkit.jsonl.lib_jsonl_archive import (  # noqa: E402  (sys.path tweak above)
    Archive, BodyIntegrityError, _stat_sig, commit, human_turn_indices,
    render_readable, sha8, tokens, wire_size,
)

ENGRAM_STUB_PREFIX = "[engram archived:"
ENGRAM_META_BEGIN = "<<<ENGRAM_META "
ENGRAM_META_END = " ENGRAM_META>>>"
SCHEMA_VERSION = 1
_META_TYPES = {"system", "attachment"}

# ── platform guard (PianoMan 2026-06-25) ──────────────────────────────────────
# Every consolidate/rehydrate/repair/gc op here is built around the CLAUDE JSONL
# shape (uuid/parentUuid trees, user/assistant records). MUTATING a non-Claude
# transcript (e.g. Codex's session_meta/response_item format) would corrupt it.
# Directive: Codex must NOT have dynamic-context-memory edits until her format is
# understood. So the WRITERS refuse any transcript positively detected as another
# platform. Read-only ops (chain_size/plan_eviction/recall) are unaffected.
# Detection uses platform_adapters.detect_platform (the canonical sniffer, per
# DESIGN.md — no direct JSONL parsing here).
try:
    from uai_toolkit.jsonl.platform_adapters import detect_platform as _detect_platform  # noqa: E402
except Exception:  # pragma: no cover
    _detect_platform = None


def _refuse_if_not_claude(jsonl_path) -> dict | None:
    """Return an error dict if the transcript is not Claude-format (so the caller
    propagates it), else None. detect_platform DEFAULTS to 'claude' when nothing
    matches, so only a positive non-Claude match (codex/gemini/agy/standardized)
    trips this — real Claude transcripts pass. Fails CLOSED if detection is
    unavailable: per the protective directive we refuse rather than risk editing a
    non-Claude transcript."""
    if _detect_platform is None:
        return {"error": "platform detection unavailable (platform_adapters import "
                "failed); refusing to mutate — cannot confirm Claude-format transcript"}
    try:
        plat = _detect_platform(jsonl_path)
    except Exception as e:
        return {"error": f"platform detection failed ({type(e).__name__}); "
                "refusing to mutate"}
    if plat != "claude":
        return {"error": f"refusing to mutate non-Claude transcript "
                f"(detected platform={plat!r}); lib_engram consolidate/rehydrate/"
                f"repair/gc is Claude-JSONL-only"}
    return None


# ── shared helpers ────────────────────────────────────────────────────────
def _load(jsonl_path: Path):
    """Read+parse a transcript with a CAS fingerprint, tolerating bad lines.

    Returns (sig0, sig1, raw_lines, records). Non-JSON lines are kept as their
    raw string so commit() can leave them byte-identical (engine convention).
    """
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
    return sig0, sig1, raw_lines, records


def _uuid_index(records: list) -> dict:
    return {r.get("uuid"): i for i, r in enumerate(records)
            if isinstance(r, dict) and r.get("uuid")}


def is_engram_stub(value) -> bool:
    return isinstance(value, str) and value.lstrip().startswith(ENGRAM_STUB_PREFIX)


def _content_of(rec):
    """Return rec.message.content (or the record itself for a non-message)."""
    if not isinstance(rec, dict):
        return rec
    msg = rec.get("message")
    return msg.get("content") if isinstance(msg, dict) else rec


def parse_stub_meta(text) -> dict | None:
    """Extract the machine-readable restoration block embedded in an engram stub.

    Returns the parsed dict (engram_id, range_uuids, next_uuid,
    orig_parent_of_next, bodies, schema_version, ...) or None. This is the
    transcript-only recovery path: even if the manifest is lost, the stub alone
    carries everything needed to recall/rehydrate.
    """
    if not isinstance(text, str):
        return None
    i = text.find(ENGRAM_META_BEGIN)
    if i < 0:
        return None
    j = text.find(ENGRAM_META_END, i)
    if j < 0:
        return None
    blob = text[i + len(ENGRAM_META_BEGIN):j]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _stub_summary(text: str) -> str:
    """The human summary portion of a stub (everything after the meta block)."""
    j = text.find(ENGRAM_META_END)
    if j < 0:
        return text
    rest = text[j + len(ENGRAM_META_END):]
    return rest[1:] if rest.startswith("\n") else rest


# ── slim inline bodies (todo_0363) ─────────────────────────────────────────
# The inline stub (embedded ENGRAM_META, which lives in live context) used to
# carry the FULL per-body manifest records — ~86% of it was metadata that is
# fully derivable from the top-level meta. We now store only the non-derivable
# fields inline (sha8 + exact_kind); the reader reconstructs the rest positionally
# from range_uuids/engram_id at read time (_hydrate_body). The on-disk manifest
# (engram_rec["bodies"]) is left FULL — it is the authoritative recovery ledger,
# not in context. Detection is STRUCTURAL (a body lacking "slug" ⇒ slim), never
# by schema_version, so old "fat" stubs keep working unchanged.
def _slim_bodies(bodies: list) -> list:
    """Reduce full per-body manifest records to the inline-stub minimum.

    Only sha8 (non-derivable) and exact_kind (do NOT assume 'json') survive;
    slug/ref/engram_id/engram_first/body_index/body_uuid/bytes are all
    reconstructable from top-level meta positionally (bodies[i] ⇄ range_uuids[i]).
    """
    return [{"sha8": b.get("sha8"), "exact_kind": b.get("exact_kind")}
            for b in (bodies or []) if isinstance(b, dict)]


def _hydrate_body(body, i: int, engram_id, engram_first, range_uuids) -> dict:
    """Normalize a per-body meta record to the FULL shape read_exact needs.

    Back-compat: a FAT body (pre-slim, carries "slug") is returned as-is. A SLIM
    body is rebuilt: slug = f"engram.{engram_id}.{i}" (matches the emit), exact_kind
    (default "json" if absent), body_uuid = range_uuids[i], plus engram_id/
    engram_first/body_index — merged with the body's own sha8 so the sha8/integrity
    and fail-closed checks still run.
    """
    if not isinstance(body, dict) or "slug" in body:
        return body
    range_uuids = range_uuids or []
    hydrated = {
        "slug": f"engram.{engram_id}.{i}",
        "exact_kind": body.get("exact_kind", "json"),
        "body_uuid": range_uuids[i] if i < len(range_uuids) else None,
        "engram_id": engram_id,
        "engram_first": engram_first,
        "body_index": i,
    }
    if body.get("sha8") is not None:
        hydrated["sha8"] = body["sha8"]
    return hydrated


# ── leaf / chain selection ────────────────────────────────────────────────
def _is_human_prompt(rec) -> bool:
    """Genuine human prompt heuristic (mirrors human_turn_indices fallback)."""
    if not (isinstance(rec, dict) and rec.get("type") == "user"
            and not rec.get("isSidechain")):
        return False
    content = _content_of(rec)
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def select_active_leaf(records: list, *, leaf_policy: str = "conversational"):
    """Choose the active leaf record. Returns (leaf_record, leaf_type, reason).

    'conversational' (default): skip isSidechain records and trailing
    system/attachment metadata; prefer the LAST non-sidechain user/assistant
    message. Real Claude transcripts frequently end in system records
    (stop_hook_summary, turn_duration) or, for subagents, isSidechain tails —
    the naive "last UUID record" leaf walks the wrong branch there.

    'raw': the last UUID record (legacy behaviour), exposed for diagnostics.
    """
    dict_recs = [r for r in records if isinstance(r, dict) and r.get("uuid")]
    if not dict_recs:
        return None, None, "empty"
    if leaf_policy == "raw":
        leaf = dict_recs[-1]
        return leaf, leaf.get("type"), "raw_last_uuid"
    for r in reversed(dict_recs):
        if r.get("isSidechain"):
            continue
        if r.get("type") in ("user", "assistant"):
            return r, r.get("type"), "conversational_leaf"
    for r in reversed(dict_recs):
        if not r.get("isSidechain") and r.get("type") not in _META_TYPES:
            return r, r.get("type"), "non_meta_leaf"
    leaf = dict_recs[-1]
    return leaf, leaf.get("type"), "fallback_last_uuid"


def _chain_records(records: list, *, leaf_uuid: str | None = None,
                   leaf_policy: str = "conversational"):
    """(chain_root_to_leaf, leaf_uuid, leaf_type, break_reason) from records."""
    by_uuid = {}
    for r in records:
        if isinstance(r, dict) and r.get("uuid"):
            by_uuid[r["uuid"]] = r              # last write wins (cf. _uuid_index)

    if leaf_uuid is not None:
        leaf = by_uuid.get(leaf_uuid)
        if leaf is None:
            return [], None, None, "leaf_not_found"
        leaf_type, reason = leaf.get("type"), "explicit_leaf"
    else:
        leaf, leaf_type, reason = select_active_leaf(records, leaf_policy=leaf_policy)
        if leaf is None:
            return [], None, None, reason

    chain = []
    seen = set()
    cur = leaf
    break_reason = "root"
    while isinstance(cur, dict) and cur.get("uuid"):
        u = cur["uuid"]
        if u in seen:
            break_reason = "cycle"
            break
        seen.add(u)
        chain.append(cur)
        parent = cur.get("parentUuid")
        if not parent:
            break_reason = "root"
            break
        if parent not in by_uuid:
            break_reason = "missing_parent"
            break
        cur = by_uuid[parent]
    chain.reverse()
    return chain, leaf.get("uuid"), leaf_type, break_reason


def active_chain(jsonl_path, leaf_uuid: str | None = None, *,
                 leaf_policy: str = "conversational") -> list:
    """Records on the ACTIVE chain, root..leaf order.

    Leaf is chosen by `select_active_leaf` (policy-driven) unless an explicit
    `leaf_uuid` is given. We walk UP via `parentUuid`, collecting each record
    until the parent is null/missing/cyclic, then reverse to root..leaf. This is
    the canonical "what the model actually carries" primitive: off-chain
    (orphaned) records are skipped, unlike file-order iteration.
    """
    _s0, _s1, _raw, records = _load(Path(jsonl_path))
    chain, _lu, _lt, _br = _chain_records(
        records, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
    return chain


# ── branch / fork analysis (MAJOR 5) ──────────────────────────────────────
def _children_map(records: list) -> dict:
    """parentUuid → [child uuid, ...] over dict records with a uuid."""
    kids: dict = {}
    for r in records:
        if isinstance(r, dict) and r.get("uuid"):
            kids.setdefault(r.get("parentUuid"), []).append(r["uuid"])
    return kids


def has_branch_points(records: list) -> bool:
    """True if ANY uuid has >1 child on the parsed records (a fork exists)."""
    return any(len(v) > 1 for k, v in _children_map(records).items() if k)


def _has_ambiguous_fork(records: list, first_uuid: str) -> bool:
    """True if first_uuid's forward path is genuinely ambiguous: some node in
    its subtree has >=2 child branches that EACH contain a human prompt, so the
    next-human-turn successor (and therefore the consolidation range) depends on
    which branch/leaf is chosen.

    Critically this IGNORES the off-chain engram-body branch that consolidate()
    itself creates (those bodies carry no human prompt), so re-consolidating an
    existing stub — engram-of-engrams — is NOT flagged as a fork.
    """
    by_uuid = {r["uuid"]: r for r in records
               if isinstance(r, dict) and r.get("uuid")}
    kids = _children_map(records)
    memo: dict = {}

    def subtree_has_human(u: str) -> bool:
        if u in memo:
            return memo[u]
        memo[u] = False                         # cycle guard (in-progress)
        rec = by_uuid.get(u)
        result = bool(rec is not None and _is_human_prompt(rec))
        if not result:
            for c in kids.get(u, []):
                if subtree_has_human(c):
                    result = True
                    break
        memo[u] = result
        return result

    stack = [first_uuid]
    seen = set()
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        ch = kids.get(u, [])
        if sum(1 for c in ch if subtree_has_human(c)) >= 2:
            return True
        stack.extend(ch)
    return False


def _live_stub_validates(records: list, engram_id: str,
                         expect_summary_sha8: str | None = None) -> bool:
    """True if SOME live record at any uuid is an engram stub carrying this
    engram_id (and, when given, whose summary hashes to expect_summary_sha8).
    The transcript-only proof that a `prepared` record actually committed."""
    for r in records:
        if not isinstance(r, dict):
            continue
        c = _content_of(r)
        if not is_engram_stub(c):
            continue
        m = parse_stub_meta(c)
        if m and m.get("engram_id") == engram_id:
            if expect_summary_sha8 and sha8(_stub_summary(c)) != expect_summary_sha8:
                continue
            return True
    return False


# ── manifest state helpers (all under the archive's manifest lock) ─────────
def _committed(rec: dict) -> bool:
    # records minted before schema_version 1 carry no state → treat as committed
    return rec.get("state", "committed") in ("committed", "partial")


def _set_manifest_state(archive: Archive, engram_id: str, state: str) -> bool:
    with archive.manifest_lock():
        recs = archive.load_manifest()
        changed = False
        for r in recs:
            if r.get("kind") == "engram" and r.get("engram_id") == engram_id:
                r["state"] = state
                changed = True
        if changed:
            return archive.rewrite_manifest(recs)
        return False


def _remove_manifest(archive: Archive, engram_id: str) -> bool:
    with archive.manifest_lock():
        recs = archive.load_manifest()
        kept = [r for r in recs
                if not (r.get("kind") == "engram"
                        and r.get("engram_id") == engram_id)]
        return archive.rewrite_manifest(kept)


def _delete_bodies(archive: Archive, bodies: list) -> None:
    for b in bodies or []:
        slug = b.get("slug")
        if not slug:
            continue
        for suffix in (".txt", ".json"):
            f = archive.dir / f"{slug}{suffix}"
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass


def _find_engram(manifest: list, *, engram_id: str | None = None,
                 first_uuid: str | None = None, prefer_engram_id: str | None = None,
                 prepared_ok=None):
    """Locate a committed engram record.

    MAJOR 1: when addressed by engram_id and only a `prepared` record exists
    (post-commit state-flip failure), fall back to it ONLY IF `prepared_ok` —
    a callable engram_id→bool that proves the live stub exists and validates —
    returns True. Otherwise prepared records are invisible (as before).
    """
    all_engs = [r for r in manifest if r.get("kind") == "engram"]
    engs = [r for r in all_engs if _committed(r)]
    if engram_id:
        for r in engs:
            if r.get("engram_id") == engram_id:
                return r
        if prepared_ok is not None:
            for r in all_engs:
                if (r.get("engram_id") == engram_id
                        and r.get("state") == "prepared"
                        and prepared_ok(engram_id)):
                    return r
        return None
    if prefer_engram_id:
        for r in engs:
            if r.get("engram_id") == prefer_engram_id:
                return r
    if first_uuid:
        matches = [r for r in engs if r.get("first_uuid") == first_uuid]
        return matches[-1] if matches else None
    return None


# ── consolidate (page-out, crash-recoverable) ─────────────────────────────
def consolidate(jsonl_path, first_uuid: str, summary_text: str, *,
                level: int = 0, volatile=None, dry_run: bool = False,
                leaf_uuid: str | None = None,
                leaf_policy: str = "conversational", repair: bool = False,
                through_uuid: str | None = None) -> dict:
    """Collapse the chain-native turn-range STARTING at `first_uuid` into a stub.

    Chain-native: the range is computed on the ACTIVE chain (not file order), so
    it matches exactly what `map` shows. `first_uuid` must be a human-turn start
    ON the active chain; the range runs through the record before the next human
    prompt on that chain. The successor (next human turn's first record) is
    re-pointed to first_uuid; the body between is archived off the active chain
    for a later byte-exact rehydrate. Only complete turns with a successor —
    never the live tail ("the present").

    SPAN: by default this consolidates exactly ONE human turn (first_uuid's). Pass
    `through_uuid` (another human-turn start at/after first_uuid on the chain) to
    consolidate the whole contiguous SPAN first_uuid..through_uuid into a SINGLE
    engram (one summary covering the arc). For per-turn memories instead, call this
    once per turn with through_uuid=None.

    Crash-recovery: bodies → manifest record state="prepared" → commit transcript
    → flip to "committed". The stub embeds FULL restoration metadata so recovery
    is possible even if the manifest is lost.

    Returns {"ok":True,"engram":<rec>,"orphaned":<n>} | {"error":..} |
    {"raced":True}. Honors dry_run (no writes; returns the would-be result).
    """
    jsonl_path = Path(jsonl_path)
    guard = _refuse_if_not_claude(jsonl_path)
    if guard:
        return guard
    volatile = list(volatile or [])

    sig0, sig1, raw_lines, records = _load(jsonl_path)
    uidx = _uuid_index(records)
    if first_uuid not in uidx:
        return {"error": f"first_uuid not found: {first_uuid}"}

    # Branch safety (MAJOR 5): a mutating range selection on a forked transcript
    # is ambiguous unless an explicit leaf is given or first_uuid is on a single
    # unforked forward path. Require leaf_uuid only when first_uuid actually has
    # a downstream branch (otherwise the segment/successor are deterministic).
    if leaf_uuid is None and has_branch_points(records) \
            and _has_ambiguous_fork(records, first_uuid):
        return {"error": "ambiguous: transcript has branch points and first_uuid "
                f"{first_uuid} has a downstream fork; pass leaf_uuid "
                "(CLI --leaf <uuid>) to choose which branch to consolidate"}

    # Chain-native range selection (MAJOR 3 / MINOR 2).
    chain, selected_leaf, _lt, _br = _chain_records(
        records, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
    chain_uuids = [r.get("uuid") for r in chain]
    if first_uuid not in chain_uuids:
        return {"error": f"first_uuid not on the active chain "
                f"(selected leaf {selected_leaf}): {first_uuid}"}
    ci = chain_uuids.index(first_uuid)
    if not _is_human_prompt(chain[ci]):
        return {"error": f"first_uuid is not a human-turn start: {first_uuid}"}

    # Span end: default to first_uuid's own turn (ti == ci). With through_uuid, the
    # span covers first_uuid..through_uuid; everything downstream operates on the
    # resulting `segment` regardless of length, so we only move where the successor
    # search begins (the next human turn AFTER the span end).
    ti = ci
    if through_uuid is not None:
        if through_uuid not in chain_uuids:
            return {"error": f"through_uuid not on the active chain: {through_uuid}"}
        ti = chain_uuids.index(through_uuid)
        if ti < ci:
            return {"error": "through_uuid precedes first_uuid on the chain"}
        if not _is_human_prompt(chain[ti]):
            return {"error": f"through_uuid is not a human-turn start: {through_uuid}"}

    nexti = next((j for j in range(ti + 1, len(chain))
                  if _is_human_prompt(chain[j])), None)
    if nexti is None:
        return {"error": "no successor; refusing to summarize the present"}

    segment = chain[ci:nexti]
    range_uuids = [r.get("uuid") for r in segment if isinstance(r, dict)]
    last_segment_uuid = range_uuids[-1] if range_uuids else first_uuid
    succ_rec = chain[nexti]
    next_uuid = succ_rec.get("uuid")
    orig_parent_of_next = succ_rec.get("parentUuid")
    if not repair and orig_parent_of_next != last_segment_uuid:
        return {"error": "successor.parentUuid does not chain to the segment tail "
                f"({orig_parent_of_next!r} != {last_segment_uuid!r}); "
                "pass repair=True to override"}

    total_bytes = sum(wire_size(r) for r in segment)
    tok = tokens(total_bytes)
    nturns = sum(1 for r in segment if _is_human_prompt(r))

    engram_id = f"{first_uuid[:8]}.{uuid.uuid4().hex[:8]}"
    fu8 = first_uuid[:8]

    # 1. Archive the FULL records of the whole range under the UNIQUE engram_id
    #    (so a later consolidation starting at the same first_uuid can never
    #    overwrite these bodies — the recursion / source-immutability fix).
    archive = Archive(jsonl_path, dry_run, namespace="engram")
    archive.ensure()
    bodies = []
    for n, rec in enumerate(segment):
        slug = f"engram.{engram_id}.{n}"
        _ref, mrec = archive.write_body(
            slug, rec,
            meta={"engram_id": engram_id, "engram_first": first_uuid,
                  "body_index": n,
                  "body_uuid": (range_uuids[n] if n < len(range_uuids) else None)})
        bodies.append(mrec)
    archive.fsync_dir()      # MAJOR 2: body files durable before they're referenced

    recall_ref = archive.ref(f"engram.{engram_id}.0")
    ts = datetime.now().isoformat(timespec="seconds")
    summary_sha8 = sha8(summary_text)

    # Embedded restoration metadata: the transcript-only recovery path (BLOCKER 2).
    # MAJOR 6: carry ALL non-derived manifest fields (turns/bytes/tokens/
    # summary_sha8/volatile/ts) so manifest-loss recall preserves volatile
    # warnings AND can still run the MAJOR 4 summary-hash check.
    embedded = {
        "schema_version": SCHEMA_VERSION,
        "engram_id": engram_id,
        "first_uuid": first_uuid,
        "range_uuids": range_uuids,
        "next_uuid": next_uuid,
        "orig_parent_of_next": orig_parent_of_next,
        "level": level,
        "turns": nturns,
        "bytes": total_bytes,
        "tokens": tok,
        "summary_sha8": summary_sha8,
        "volatile": volatile,
        "ts": ts,
        # SLIM (todo_0363): inline stub carries only the non-derivable per-body
        # fields; _hydrate_body reconstructs the rest. Manifest stays FULL below.
        "bodies": _slim_bodies(bodies),
    }
    header = (f"{ENGRAM_STUB_PREFIX} {fu8} · eng={engram_id} · turns {nturns} · "
              f"{tok} tok · recall→{recall_ref}]")
    stub = (f"{header}\n{ENGRAM_META_BEGIN}"
            f"{json.dumps(embedded, ensure_ascii=False)}{ENGRAM_META_END}\n"
            f"{summary_text}")

    engram_rec = {
        "kind": "engram",
        "schema_version": SCHEMA_VERSION,
        "engram_id": engram_id,
        "first_uuid": first_uuid,
        "range_uuids": range_uuids,
        "next_uuid": next_uuid,
        "orig_parent_of_next": orig_parent_of_next,
        "level": level,
        "turns": nturns,                           # human turns in the archived range
        "bytes": total_bytes,
        "tokens": tok,
        "summary_sha8": summary_sha8,
        "volatile": volatile,
        "bodies": bodies,                          # restoration metadata (for read_exact)
        "state": "prepared",
        "ts": ts,
    }
    orphaned = max(0, len(range_uuids) - 1)

    if dry_run:
        out = dict(engram_rec)
        out["state"] = "committed"
        return {"ok": True, "dry_run": True, "engram": out,
                "orphaned": orphaned, "stub": stub, "selected_leaf": selected_leaf}

    # 2. Durable pointer FIRST: append manifest record as "prepared" (atomic,
    #    fsync'd, locked). If this fails, abort before touching the transcript.
    if not archive.append_manifest([engram_rec]):
        _delete_bodies(archive, bodies)
        return {"error": "manifest append failed (state=prepared); transcript untouched"}

    # 3. Overwrite first_uuid's content with the stub (uuid/parentUuid kept).
    start = uidx[first_uuid]
    first_rec = records[start]
    msg = first_rec.get("message")
    if isinstance(msg, dict):
        msg["content"] = stub
    else:
        first_rec["message"] = {"role": first_rec.get("type", "user"), "content": stub}

    # 4. Re-point the successor's parent → first_uuid. Body is now off-chain.
    succ = uidx[next_uuid]
    records[succ]["parentUuid"] = first_uuid

    # 5. CAS-commit: only first_uuid and the successor changed.
    dirty = {start, succ}
    status = commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=True)
    if status == "ok":
        # MAJOR 1: the transcript is durably committed. If flipping the manifest
        # to "committed" fails (lock timeout / crash), DO NOT claim committed —
        # the live stub keeps recall/rehydrate-by-first_uuid working, and
        # repair-manifest can finish the flip. Surface it explicitly.
        if _set_manifest_state(archive, engram_id, "committed"):
            engram_rec["state"] = "committed"
            return {"ok": True, "engram": engram_rec, "orphaned": orphaned,
                    "selected_leaf": selected_leaf}
        engram_rec["state"] = "prepared"
        return {
            "ok": True, "engram": engram_rec, "orphaned": orphaned,
            "selected_leaf": selected_leaf,
            "manifest_state": "prepared", "recovered_by_stub": True,
            "warning": "transcript committed but manifest flip to 'committed' "
                       "failed; record left state=prepared. Recall/rehydrate by "
                       "first_uuid still work via the live stub; run "
                       "repair-manifest to finish the flip (enables --engram-id)."}
    # 6. Failure: mark aborted and reclaim the prepared body files (gc-collectable).
    _set_manifest_state(archive, engram_id, "aborted")
    _delete_bodies(archive, bodies)
    if status == "raced":
        return {"raced": True}
    return {"error": status}


def summarize(*args, **kwargs):
    """Public alias for :func:`consolidate` — the "Summarize" operation.

    The context-reclaim lever is user-facing-named *Summarize* (it summarizes a
    turn-range into a reversible summary stub). The historical internal name
    ``consolidate`` is retained (tests + in-flight callers import it), so this is
    a thin passthrough with the identical signature/return contract. Prefer
    ``summarize`` in new call sites; ``consolidate`` keeps working.
    """
    return consolidate(*args, **kwargs)


# ── rehydrate (undo on disk, fail-closed) ──────────────────────────────────
def rehydrate_engram(jsonl_path, first_uuid: str | None = None, *,
                     engram_id: str | None = None, dry_run: bool = False,
                     force: bool = False, force_partial: bool = False,
                     allow_corrupt: bool = False) -> dict:
    """Exact inverse of consolidate(): restore the archived range content,
    set the successor's parentUuid back to its original, and drop the engram
    manifest record. Record CONTENT round-trips byte-exactly. CAS-commit.

    Fail-closed (MAJOR 4): unless `force_partial`, refuses to mutate if any
    range record / next_uuid / archive body is missing. Handle validation
    (MAJOR 5): unless `force`, requires the live first_uuid record to be an
    engram stub carrying the SAME engram_id.

    Fail-closed on corruption (BLOCKER 1): a body whose stored sha8 no longer
    matches its on-disk content aborts the whole rehydrate by default — the
    transcript is left UNTOUCHED, no corrupt content is ever written. With
    `allow_corrupt` such a body is SALVAGED (written anyway) and flagged; with
    `force_partial` alone the corrupt body is SKIPPED (its stub is left in
    place) and the result is marked partial.
    """
    jsonl_path = Path(jsonl_path)
    guard = _refuse_if_not_claude(jsonl_path)
    if guard:
        return guard
    archive = Archive(jsonl_path, dry_run, namespace="engram")
    manifest_all = archive.load_manifest()

    sig0, sig1, raw_lines, records = _load(jsonl_path)
    uidx = _uuid_index(records)

    # Resolve the target engram: explicit engram_id wins; else the live stub's
    # embedded engram_id; else most-recent committed for first_uuid.
    live_meta = None
    if first_uuid and first_uuid in uidx:
        live_meta = parse_stub_meta(_content_of(records[uidx[first_uuid]]))
    eid = engram_id or (live_meta.get("engram_id") if live_meta else None)
    eng = _find_engram(manifest_all, engram_id=eid, first_uuid=first_uuid,
                       prepared_ok=lambda e: _live_stub_validates(records, e))
    if eng is None and live_meta:
        eng = live_meta                            # manifest lost → recover from stub
    if eng is None:
        return {"error": f"no engram for first_uuid={first_uuid} engram_id={engram_id}"}

    fu = eng.get("first_uuid") or first_uuid
    engram_id = eng.get("engram_id")

    # Handle validation (MAJOR 5).
    if not force:
        if fu not in uidx:
            return {"error": "first_uuid not in transcript; pass force=True"}
        live = _content_of(records[uidx[fu]])
        if not is_engram_stub(live):
            return {"error": "first_uuid is not a live engram stub; pass force=True"}
        m = parse_stub_meta(live)
        if not m or m.get("engram_id") != engram_id:
            return {"error": "live stub engram_id mismatch; pass force=True"}
        # MAJOR 4: enforce the stored summary hash — an edited stub summary must
        # not silently rehydrate. (eng may be the manifest record OR, on manifest
        # loss, the embedded meta — both now carry summary_sha8 via MAJOR 6.)
        if eng.get("summary_sha8") \
                and sha8(_stub_summary(live)) != eng["summary_sha8"]:
            return {"error": "live stub summary hash mismatch; pass force=True"}

    range_uuids = eng.get("range_uuids") or []
    bodies = eng.get("bodies") or []
    next_uuid = eng.get("next_uuid")

    # Fail-closed pre-checks (MAJOR 4): existence, counts, readability.
    problems = []
    missing = [bu for bu in range_uuids if bu not in uidx]
    if missing:
        problems.append(f"{len(missing)} range record(s) missing")
    if len(bodies) != len(range_uuids):
        problems.append(f"body count {len(bodies)} != range {len(range_uuids)}")
    if next_uuid not in uidx:
        problems.append("next_uuid missing")
    read_bodies = {}
    for n in range(len(range_uuids)):
        body = bodies[n] if n < len(bodies) else None
        if body is None:
            problems.append(f"body {n} has no metadata")
            continue
        # Back-compat: hydrate slim inline bodies (todo_0363). fu = eng first_uuid.
        body = _hydrate_body(body, n, engram_id, fu, range_uuids)
        try:
            read_bodies[n] = archive.read_exact(body)
        except BodyIntegrityError as e:
            tag = (f"body {n} INTEGRITY MISMATCH (expected {e.expected}, "
                   f"got {e.got}) — corrupt/swapped archive body")
            if allow_corrupt:
                problems.append(tag + " — SALVAGED (allow_corrupt)")
                read_bodies[n] = e.value       # write the corrupt body on purpose
            else:
                problems.append(tag)           # leave read_bodies[n] unset → skipped
        except (OSError, json.JSONDecodeError, KeyError):
            problems.append(f"body {n} unreadable")
    # BLOCKER 1: corruption fails closed the SAME as a missing body — abort
    # before any write so the transcript is untouched. force_partial skips the
    # bad body; allow_corrupt salvages it; with neither, this is fatal.
    if problems and not (force_partial or allow_corrupt):
        return {"error": "fail-closed: " + "; ".join(problems)}

    dirty = set()
    restored = 0
    for n, bu in enumerate(range_uuids):
        if bu not in uidx or n not in read_bodies:
            continue
        i = uidx[bu]
        orig = read_bodies[n]
        if records[i] != orig:
            records[i] = orig
            dirty.add(i)
        restored += 1

    if next_uuid in uidx:
        si = uidx[next_uuid]
        if isinstance(records[si], dict) and \
                records[si].get("parentUuid") != eng.get("orig_parent_of_next"):
            records[si]["parentUuid"] = eng.get("orig_parent_of_next")
            dirty.add(si)

    if dry_run:
        return {"ok": True, "dry_run": True, "restored": restored,
                "would_dirty": len(dirty), "partial": bool(problems)}

    status = commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=False)
    if status == "raced":
        return {"raced": True}
    if status not in ("ok", "nochange"):
        return {"error": status}

    full_success = not problems
    if full_success:
        if engram_id:
            _remove_manifest(archive, engram_id)
        return {"ok": True, "restored": restored}
    # force_partial path: keep the manifest record, mark it partial.
    if engram_id:
        _set_manifest_state(archive, engram_id, "partial")
    return {"ok": True, "restored": restored, "partial": True,
            "problems": problems}


# ── chain-aware measurement (Foundational fact #5) ────────────────────────
def chain_size(jsonl_path, leaf_uuid: str | None = None, *,
               leaf_policy: str = "conversational") -> dict:
    """Chain-aware ESTIMATE of the live context (MAJOR 6 — honest naming).

    These are content-byte heuristics, NOT "what the model actually carries":
    they ignore provider-side context management, compaction semantics, and any
    replay of system records. Breakdown:
      message_content_bytes — sum of message.content wire size (user/assistant)
      system_bytes          — full payload of trailing/inline system records
      attachment_bytes      — full payload of attachment records
      envelope_bytes        — JSON envelope overhead around message content
      content_bytes_estimate / content_tokens_estimate — message content only
    Also reports the selected leaf_uuid/leaf_type and chain_break_reason.
    """
    jsonl_path = Path(jsonl_path)
    _s0, _s1, _raw, records = _load(jsonl_path)
    total = sum(1 for r in records if isinstance(r, dict))

    chain, lu, lt, br = _chain_records(
        records, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
    message_content_bytes = system_bytes = attachment_bytes = envelope_bytes = 0
    for r in chain:
        full = wire_size(r)
        rtype = r.get("type")
        if rtype == "system":
            system_bytes += full
            continue
        if rtype == "attachment":
            attachment_bytes += full
            continue
        content = _content_of(r) if isinstance(r.get("message"), dict) else None
        if content is not None:
            mc = wire_size(content)
            message_content_bytes += mc
            envelope_bytes += max(0, full - mc)
        else:
            envelope_bytes += full

    cbe = message_content_bytes
    return {
        "chain_records": len(chain),
        "off_chain_records": total - len(chain),
        "message_content_bytes": message_content_bytes,
        "system_bytes": system_bytes,
        "attachment_bytes": attachment_bytes,
        "envelope_bytes": envelope_bytes,
        "content_bytes_estimate": cbe,
        "content_tokens_estimate": tokens(cbe) if cbe else 0,
        "leaf_uuid": lu,
        "leaf_type": lt,
        "chain_break_reason": br,
    }


# ── plan_eviction (size-aware admission control, ADVISORY / read-only) ─────
def plan_eviction(jsonl_path, *, need_tokens: int, keep_recent_turns: int = 3,
                  strategy: str = "oldest", leaf_uuid: str | None = None,
                  leaf_policy: str = "conversational") -> dict:
    """Recommend which chain-native human turns to consolidate to free
    ``need_tokens`` of live context. ADVISORY ONLY — this never writes, never
    consolidates; it returns a plan the caller may choose to enact.

    Candidate turns are the human turns ON the active chain that:
      * are NOT already engram stubs (already paged out — `is_engram_stub`),
      * HAVE a successor human turn (never the live tail — "the present"; same
        constraint consolidate() enforces before it will re-point),
      * fall OUTSIDE the most-recent ``keep_recent_turns`` window (the freshest K
        turns are never evicted — high-resolution recent context is protected).

    Each candidate's freeable tokens is the turn segment's restoration size
    (`tokens(sum(wire_size(r) for r in segment))`) — the SAME sizing
    consolidate() records as the engram's `tokens`, so the plan's numbers match
    what an actual page-out would free. Segments are chain-native (computed on
    the active chain, mirroring consolidate — NOT file-order
    human_turn_indices).

    Strategy tradeoff:
      "oldest"  (default) — evict oldest-first. Mirrors the memory recency
                  principle (consolidation depth ∝ age: old → gist, recent →
                  vivid). May take MORE evictions to hit the target, but every
                  eviction is of the least-relevant context.
      "largest" — evict the biggest segments first → FEWEST evictions to reach
                  the target (less paging thrash), but may drop large,
                  relatively-recent context that "oldest" would have kept vivid.

    Greedily selects candidates per the strategy until cumulative freeable
    >= need_tokens. If the candidate pool cannot reach the target, ALL
    candidates are returned with feasible=False and shortfall_tokens>0.

    Returns:
      need_tokens, strategy, keep_recent_turns,
      selected: [{first_uuid, turn_index, tokens}, ...]  (in eviction order),
      total_freed_tokens, chain_tokens_before, chain_tokens_after_est,
      feasible: bool, shortfall_tokens: int
    """
    if strategy not in ("oldest", "largest"):
        raise ValueError(f"unknown strategy: {strategy!r} (use 'oldest' or 'largest')")
    jsonl_path = Path(jsonl_path)
    _s0, _s1, _raw, records = _load(jsonl_path)
    chain, _lu, _lt, _br = _chain_records(
        records, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)

    # Chain-native human-turn positions: classify the chain records directly
    # (mirrors consolidate's range logic). human_turn_indices() returns
    # FILE-order positions that DON'T align with the chain list once off-chain
    # records exist — DO NOT use it here.
    human = [i for i, r in enumerate(chain) if _is_human_prompt(r)]
    n_turns = len(human)
    chain_tokens_before = tokens(sum(wire_size(r) for r in chain)) if chain else 0

    candidates = []  # oldest-first (chain order)
    for ordinal, pos in enumerate(human, start=1):   # 1-based turn index
        rec = chain[pos]
        content = _content_of(rec) if isinstance(rec.get("message"), dict) else None
        has_successor = ordinal < n_turns
        in_recent_window = ordinal > n_turns - keep_recent_turns
        if is_engram_stub(content) or not has_successor or in_recent_window:
            continue
        nexti = human[ordinal]                       # next human pos on the chain
        segment = chain[pos:nexti]
        seg_tokens = tokens(sum(wire_size(r) for r in segment))
        candidates.append({"first_uuid": rec.get("uuid"),
                           "turn_index": ordinal, "tokens": seg_tokens})

    if strategy == "largest":
        ordered = sorted(candidates, key=lambda c: c["tokens"], reverse=True)
    else:                                            # "oldest" — already oldest-first
        ordered = list(candidates)

    total_available = sum(c["tokens"] for c in candidates)
    feasible = total_available >= need_tokens

    selected = []
    total = 0
    if feasible:
        for c in ordered:
            if total >= need_tokens:
                break
            selected.append(c)
            total += c["tokens"]
    else:
        selected = list(ordered)                     # everything; still short
        total = total_available

    return {
        "need_tokens": need_tokens,
        "strategy": strategy,
        "keep_recent_turns": keep_recent_turns,
        "selected": selected,
        "total_freed_tokens": total,
        "chain_tokens_before": chain_tokens_before,
        "chain_tokens_after_est": chain_tokens_before - total,
        "feasible": feasible,
        "shortfall_tokens": max(0, need_tokens - total),
        # MAJOR 4: echo the branch the plan was computed on so a caller (and the
        # CLI) can confirm candidates came from the intended fork leaf.
        "leaf_uuid": _lu,
        "leaf_type": _lt,
        "chain_break_reason": _br,
    }


# ── recall (page-in: bring an engram into LIVE context, read-only) ─────────
def _truncate_bytes(text: str, n: int) -> str:
    """Truncate to <= n UTF-8 bytes, never splitting a multibyte char."""
    return text.encode("utf-8")[:n].decode("utf-8", "ignore")


def _render_record_for_recall(orig):
    """Render one archived record for RECALL — labeled by speaker, thinking marked.

    Recalled content lands in live context as a tool_result blob, so it must say WHO
    spoke and which parts were reasoning vs response, or it reads as an undifferentiated
    wall. Thinking `signature` blobs are dropped: a signature is the encrypted reasoning,
    inert once outside a live thinking block, so in a recalled tool_result it is pure dead
    weight. The ARCHIVE keeps signatures — byte-exact Restore is unaffected; only this
    model-facing render drops them. Recall of thinking thus yields the plaintext summary,
    never the (encrypted) reasoning.
    """
    if not isinstance(orig, dict):
        return str(orig)
    rtype = orig.get("type")
    if rtype not in ("user", "assistant"):
        # system / bridge / other meta records: show their top-level content, not a dict dump
        label = (rtype or "meta").capitalize()
        return f"{label}: {orig.get('content', '')}"
    role = "User" if rtype == "user" else "Assistant"
    content = _content_of(orig)
    if not isinstance(content, list):
        return f"{role}: {content}"
    lines = []
    for b in content:
        if not isinstance(b, dict):
            lines.append(f"{role}: {b}")
            continue
        t = b.get("type")
        if t == "text":
            lines.append(f"{role}: {b.get('text', '')}")
        elif t == "thinking":
            lines.append(f"{role} (thinking): {b.get('thinking', '')}")  # signature dropped
        elif t == "tool_use":
            inp = b.get("input", {})
            inp = ", ".join(f"{k}={v}" for k, v in inp.items()) if isinstance(inp, dict) else str(inp)
            lines.append(f"{role} (tool call → {b.get('name', '?')}): {inp[:200]}")
        elif t == "tool_result":
            c = b.get("content")
            lines.append(f"Tool result: {c if isinstance(c, str) else render_readable(c)}")
        else:
            lines.append(f"{role} [{t}]: {json.dumps(b)[:200]}")
    return "\n".join(lines)


def _render_bodies(archive: Archive, bodies: list, *, seen: set, depth: int,
                   engram_id=None, engram_first=None, range_uuids=None,
                   max_depth: int = 8, allow_corrupt: bool = False):
    """Render a body list to (text_parts, counted_human_turns, problems).

    MAJOR 3 (fail-closed): a missing/unreadable body file is NOT silently
    dropped — it is recorded in `problems` so recall() can refuse by default.
    Nested child-engram expansion follows the same rule: a child whose bodies
    are missing surfaces its problems up the call.

    BLOCKER 1 (fail-closed on corruption): a body whose stored sha8 no longer
    matches its on-disk content raises BodyIntegrityError. By default it is
    recorded as a problem and DROPPED (recall refuses by default). With
    allow_corrupt=True the corrupt body is SALVAGED (used anyway) and loudly
    flagged in problems.

    Recursion invariant: if a body is itself an engram stub, expand it via its
    EMBEDDED metadata so an engram-of-engrams (M → S_i → T_i) resolves all the
    way down to the original level-0 turns T_i.
    """
    parts = []
    counted = 0
    problems = []
    for n, body in enumerate(bodies or []):
        # Back-compat: hydrate slim inline bodies to the full shape read_exact
        # needs (fat bodies pass through unchanged). todo_0363.
        body = _hydrate_body(body, n, engram_id, engram_first, range_uuids)
        slug = body.get("slug") if isinstance(body, dict) else None
        try:
            orig = archive.read_exact(body)
        except BodyIntegrityError as e:
            tag = (f"body {slug or n} INTEGRITY MISMATCH (expected {e.expected}, "
                   f"got {e.got}) at depth {depth} — corrupt/swapped archive body")
            if not allow_corrupt:
                problems.append(tag)
                continue
            problems.append(tag + " — SALVAGED (allow_corrupt)")
            orig = e.value
        except (OSError, json.JSONDecodeError, KeyError):
            problems.append(f"body {slug or n} missing/unreadable (depth {depth})")
            continue
        if isinstance(orig, dict):
            if _is_human_prompt(orig):
                counted += 1
            content = _content_of(orig)
        else:
            content = orig
        if depth < max_depth and is_engram_stub(content):
            sub = parse_stub_meta(content)
            if sub and sub.get("engram_id") and sub["engram_id"] not in seen:
                seen.add(sub["engram_id"])
                sub_parts, sub_counted, sub_problems = _render_bodies(
                    archive, sub.get("bodies") or [],
                    seen=seen, depth=depth + 1, max_depth=max_depth,
                    engram_id=sub.get("engram_id"),
                    engram_first=sub.get("first_uuid"),
                    range_uuids=sub.get("range_uuids") or [],
                    allow_corrupt=allow_corrupt)
                parts.extend(sub_parts)
                counted += sub_counted
                problems.extend(sub_problems)
                if not sub_parts and not sub_problems:
                    problems.append(
                        f"nested engram {sub['engram_id']} expanded to nothing")
                continue
            if not sub or not sub.get("engram_id"):
                problems.append(f"nested stub at body {slug or n} has no "
                                "recoverable metadata")
        parts.append(_render_record_for_recall(orig))
    return parts, counted, problems


def recall(jsonl_path, first_uuid: str | None = None, *,
           engram_id: str | None = None, max_bytes=None,
           allow_historical: bool = False, allow_partial: bool = False,
           allow_corrupt: bool = False,
           leaf_uuid: str | None = None,
           leaf_policy: str = "conversational") -> dict:
    """Page an archived engram into the present as remembered-not-current text.

    Address by `engram_id` (durable) or by `first_uuid` (convenience: prefers the
    engram referenced by the LIVE stub at first_uuid). Read-only: the transcript
    is NOT modified — the caller surfaces `text` as a tool result.

    Recursion: nested engram stubs are expanded to level-0 (see _render_bodies).
    Validation (MAJOR 5): unless `allow_historical`, refuses if `first_uuid` is
    not on the active chain.

    Fail-closed (MAJOR 3): if ANY body (including nested child-engram bodies) is
    missing/unreadable, returns {"error":...,"problems":[...]} by default.
    `allow_partial=True` returns the partial text WITH a `problems` list and an
    explicit INCOMPLETE marker in the header.

    Fail-closed on corruption (BLOCKER 1): a body whose stored sha8 no longer
    matches its on-disk content (corrupted / swapped / wrong-archive body) is
    treated as a problem and fails closed by default — the corrupt content is
    NEVER surfaced silently. `allow_corrupt=True` deliberately SALVAGES such a
    body (uses it anyway) and flags it loudly in `problems` / the INCOMPLETE
    header, for on-purpose recovery of a known-damaged archive.

    Returns the recall payload. On no match: {"error": ...}. If `max_bytes` is
    given and the text exceeds it (in UTF-8 bytes), the FULL record is still
    returned plus a `truncated_preview` field (NIT 1: byte-accurate).
    """
    jsonl_path = Path(jsonl_path)
    archive = Archive(jsonl_path, namespace="engram")
    manifest_all = archive.load_manifest()

    prefer = None
    if not engram_id and first_uuid:
        # validate the handle is on the active chain (unless historical recall)
        chain = active_chain(jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
        chain_uuids = {r.get("uuid") for r in chain}
        on_chain = first_uuid in chain_uuids
        if not on_chain and not allow_historical:
            return {"error": f"handle {first_uuid} not on the active chain; "
                    "pass allow_historical=True to recall it anyway"}
        if on_chain:
            live = _content_of(next(r for r in chain if r.get("uuid") == first_uuid))
            m = parse_stub_meta(live) if is_engram_stub(live) else None
            if m and m.get("engram_id"):
                prefer = m["engram_id"]

    eng = _find_engram(
        manifest_all, engram_id=engram_id, first_uuid=first_uuid,
        prefer_engram_id=prefer,
        prepared_ok=(lambda e: _live_stub_validates(_load(jsonl_path)[3], e))
        if engram_id else None)
    if eng is None and first_uuid:
        # manifest lost → recover from the live stub's embedded metadata.
        # HIGH 2: honor the caller's explicit leaf here too — on a forked
        # transcript the default leaf may be a DIFFERENT branch than the one
        # the caller selected, so the embedded-stub recovery must walk the
        # SAME branch used for the initial validation above.
        fallback_chain = active_chain(
            jsonl_path, leaf_uuid=leaf_uuid, leaf_policy=leaf_policy)
        if first_uuid in {r.get("uuid") for r in fallback_chain}:
            live = _content_of(next(r for r in fallback_chain
                                    if r.get("uuid") == first_uuid))
            eng = parse_stub_meta(live) if is_engram_stub(live) else None
    if eng is None:
        return {"error": f"no engram for {engram_id or first_uuid}"}

    seen = set()
    if eng.get("engram_id"):
        seen.add(eng["engram_id"])
    parts, counted_turns, problems = _render_bodies(
        archive, eng.get("bodies") or [], seen=seen, depth=0,
        engram_id=eng.get("engram_id"), engram_first=eng.get("first_uuid"),
        range_uuids=eng.get("range_uuids") or [], allow_corrupt=allow_corrupt)

    # MAJOR 3 / BLOCKER 1: fail closed on missing/unreadable/corrupt bodies
    # unless explicitly overridden. allow_partial tolerates missing bodies (they
    # are dropped); allow_corrupt tolerates a hash-mismatched body (salvaged +
    # flagged). With neither, any problem is fatal — reversibility is sacred.
    if problems and not (allow_partial or allow_corrupt):
        return {"error": "fail-closed: missing/unreadable/corrupt engram bodies: "
                + "; ".join(problems), "problems": problems,
                "engram_id": eng.get("engram_id")}

    rendered = "\n".join(parts)

    turns = eng.get("turns")
    if turns is None:
        turns = counted_turns
    volatile = list(eng.get("volatile") or [])
    handle = eng.get("first_uuid") or first_uuid or eng.get("engram_id")
    fu8 = (handle[:8] if isinstance(handle, str) else handle) or ""
    ts = eng.get("ts", "?")

    marker = "INCOMPLETE " if problems else ""
    header = f"{marker}RECALLED MEMORY (engram {fu8}, {turns} turns, archived {ts}):"
    warn_lines = []
    if problems:
        warn_lines.append("⚠ INCOMPLETE — missing bodies: " + "; ".join(problems))
    if volatile:
        warn_lines.append("⚠ VOLATILE — re-verify before acting: "
                          + "; ".join(volatile))
    text = header + "\n" + "".join(w + "\n" for w in warn_lines) + rendered + "\n"

    nbytes = len(text.encode("utf-8"))
    out = {
        "ok": True,
        "handle": handle,
        "engram_id": eng.get("engram_id"),
        "turns": turns,
        "bytes": nbytes,
        "tokens": tokens(nbytes),
        "text": text,
        "volatile": volatile,
    }
    if problems:
        out["partial"] = True
        out["problems"] = problems
    if max_bytes is not None and nbytes > max_bytes:
        out["truncated_preview"] = _truncate_bytes(text, max_bytes)
    return out


# ── manifest repair (MAJOR 1) ──────────────────────────────────────────────
def repair_manifest(jsonl_path, *, dry_run: bool = False) -> dict:
    """Finish post-commit state flips that never completed (MAJOR 1).

    Scans live records for engram stubs, parses their ENGRAM_META, and flips a
    matching `prepared` manifest record to `committed` IFF the live stub exists
    AND validates (engram_id present and, when the record stores summary_sha8,
    the live stub summary hashes to it). This recovers durable --engram-id
    lookup after a transcript commit succeeded but the manifest flip failed.

    Returns {"repaired":[engram_id,...], "count":n, "skipped":[...]}.
    """
    jsonl_path = Path(jsonl_path)
    guard = _refuse_if_not_claude(jsonl_path)
    if guard:
        return guard
    archive = Archive(jsonl_path, dry_run, namespace="engram")
    _s0, _s1, _raw, records = _load(jsonl_path)

    live: dict = {}                       # engram_id → (stub_content, meta)
    for r in records:
        if not isinstance(r, dict):
            continue
        c = _content_of(r)
        if is_engram_stub(c):
            m = parse_stub_meta(c)
            if m and m.get("engram_id"):
                live[m["engram_id"]] = c

    repaired, skipped = [], []
    with archive.manifest_lock():
        recs = archive.load_manifest()
        changed = False
        for rec in recs:
            if rec.get("kind") != "engram" or rec.get("state") != "prepared":
                continue
            eid = rec.get("engram_id")
            content = live.get(eid)
            if content is None:
                skipped.append({"engram_id": eid, "why": "no live stub"})
                continue
            if rec.get("summary_sha8") \
                    and sha8(_stub_summary(content)) != rec["summary_sha8"]:
                skipped.append({"engram_id": eid, "why": "summary hash mismatch"})
                continue
            rec["state"] = "committed"
            changed = True
            repaired.append(eid)
        if changed and not dry_run:
            archive.rewrite_manifest(recs)

    return {"repaired": repaired, "count": len(repaired), "skipped": skipped}


# ── fat→slim converter (todo_0363) ─────────────────────────────────────────
def slim_engram_stubs(jsonl_path, *, dry_run: bool = False) -> dict:
    """Shrink the inline ENGRAM_META bodies[] of already-consolidated stubs.

    For each live engram stub, rebuild ENGRAM_META with SLIM per-body records
    (sha8 + exact_kind only), preserving the header and summary BYTE-EXACTLY —
    only the `bodies` field of the embedded JSON changes. The on-disk manifest is
    left untouched (it stays FULL), so recall/rehydrate remain byte-exact.

    Idempotent: a stub whose bodies are already slim (no body carries "slug") is
    left unchanged. CAS-committed with a one-time .jsonl.bak like the other
    mutators. Returns {"ok":True,"slimmed":n,"total_saved":bytes,"stubs":[...]}
    | {"raced":True} | {"error":..}.
    """
    jsonl_path = Path(jsonl_path)
    guard = _refuse_if_not_claude(jsonl_path)
    if guard:
        return guard

    sig0, sig1, raw_lines, records = _load(jsonl_path)
    dirty = set()
    per_stub = []
    total_saved = 0

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        content = _content_of(rec)
        if not is_engram_stub(content):
            continue
        mi = content.find(ENGRAM_META_BEGIN)
        mj = content.find(ENGRAM_META_END, mi) if mi >= 0 else -1
        if mi < 0 or mj < 0:
            continue
        try:
            meta = json.loads(content[mi + len(ENGRAM_META_BEGIN):mj])
        except json.JSONDecodeError:
            continue
        bodies = meta.get("bodies") or []
        # Idempotent: already slim ⇒ no body carries a "slug".
        if not any(isinstance(b, dict) and "slug" in b for b in bodies):
            continue

        meta["bodies"] = _slim_bodies(bodies)
        # Preserve header (prefix up to & incl. ENGRAM_META_BEGIN) and summary
        # (from ENGRAM_META_END onward) EXACTLY; only the JSON in between shrinks.
        prefix = content[:mi + len(ENGRAM_META_BEGIN)]
        suffix = content[mj:]
        new_content = prefix + json.dumps(meta, ensure_ascii=False) + suffix

        before = len(content.encode("utf-8"))
        after = len(new_content.encode("utf-8"))
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        msg["content"] = new_content
        dirty.add(i)
        per_stub.append({"engram_id": meta.get("engram_id"),
                         "uuid": rec.get("uuid"),
                         "bytes_before": before, "bytes_after": after,
                         "saved": before - after})
        total_saved += before - after

    if dry_run:
        return {"ok": True, "dry_run": True, "slimmed": len(per_stub),
                "total_saved": total_saved, "stubs": per_stub}
    if not dirty:
        return {"ok": True, "slimmed": 0, "total_saved": 0, "stubs": []}

    status = commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=True)
    if status == "raced":
        return {"raced": True}
    if status not in ("ok", "nochange"):
        return {"error": status}
    return {"ok": True, "slimmed": len(per_stub), "total_saved": total_saved,
            "stubs": per_stub}


# ── archive garbage collection (MAJOR 7 / MINOR 1) ─────────────────────────
def gc_archive(jsonl_path, *, dry_run: bool = False,
               grace_seconds: float = 60.0) -> dict:
    """List/remove unreferenced engram body files (aborted/orphan, not committed).

    Referenced = body slugs of committed/partial/prepared engram records. Files
    matching `engram.*` whose slug is not referenced are removed; aborted
    manifest records are dropped.

    MINOR 1 (gc race): the whole scan/remove/rewrite runs under manifest_lock,
    and body files modified within the last `grace_seconds` are SKIPPED — this
    closes the window where a consolidate() that has written bodies but not yet
    appended its `prepared` manifest record could have them reaped as orphans.
    """
    jsonl_path = Path(jsonl_path)
    guard = _refuse_if_not_claude(jsonl_path)
    if guard:
        return guard
    archive = Archive(jsonl_path, dry_run, namespace="engram")
    if not archive.dir.exists():
        return {"removed": [], "referenced": 0, "dropped_aborted": 0,
                "skipped_fresh": 0, "grace_seconds": grace_seconds,
                "note": "no archive dir"}

    now = time.time()

    def _scan():
        manifest = archive.load_manifest()
        referenced = set()
        aborted_ids = set()
        for e in manifest:
            if e.get("kind") != "engram":
                continue
            st = e.get("state", "committed")
            if st == "aborted":
                aborted_ids.add(e.get("engram_id"))
            else:  # committed / partial / prepared (in-flight) → keep their bodies
                for b in e.get("bodies") or []:
                    if b.get("slug"):
                        referenced.add(b["slug"])

        removed = []
        skipped_fresh = 0
        for f in sorted(archive.dir.glob("engram.*")):
            if f.suffix not in (".txt", ".json"):
                continue
            slug = f.name[: -len(f.suffix)]
            if slug in referenced:
                continue
            try:                          # MINOR 1 grace window
                if now - f.stat().st_mtime < grace_seconds:
                    skipped_fresh += 1
                    continue
            except OSError:
                continue
            removed.append(f.name)
            if not dry_run:
                try:
                    f.unlink()
                except OSError:
                    pass
        return manifest, referenced, aborted_ids, removed, skipped_fresh

    if dry_run:
        manifest, referenced, aborted_ids, removed, skipped_fresh = _scan()
    else:
        with archive.manifest_lock():     # MINOR 1: scan+remove+rewrite atomically
            manifest, referenced, aborted_ids, removed, skipped_fresh = _scan()
            if aborted_ids:
                kept = [r for r in manifest
                        if not (r.get("kind") == "engram"
                                and r.get("state") == "aborted")]
                archive.rewrite_manifest(kept)

    return {"removed": removed, "referenced": len(referenced),
            "dropped_aborted": len(aborted_ids), "skipped_fresh": skipped_fresh,
            "grace_seconds": grace_seconds}
