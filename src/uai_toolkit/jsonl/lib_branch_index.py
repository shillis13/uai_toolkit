"""lib_branch_index — chain/branch-aware transcript topology (see DESIGN_branch_index.md).

A single APPEND-ORDER pass classifies each msg; O(1) per record, no child traversal,
no tool_use cache. Every exclusion here is backed by a resume probe or by offload's own
recorded data (2026-07-13/14 investigation), not a guess.

Five cases (in order), tip = the last-appended msg:
  1. R is a tool_result                       -> PAIRED      (never a branch: a tool_result
                                                 attaches back to its tool_use by tool_use_id,
                                                 so its parent is that tool_use, not the tip;
                                                 CC collects it by id, verified by resume probe)
  2. parentId is null                          -> ROOT        (segment start)
  3. parentId is a compaction summary          -> COMPACTION  (segment start = load boundary)
  4. R is an offload re-point (uuid in the     -> RECLAIM     (offload mutated parentId; NOT a
     reclaim set from offload's restore tokens)               branch. offload's token gives
                                                               {succ, old_parent, new_parent})
  5. parentId == tip                           -> LINEAR
  6. otherwise                                 -> VALID_FORK  (a genuine rewind/resume branch)

Attachments advance the tip like any msg (they are inline chain nodes, not leaves — verified).
Agent_records (client/UI records with no uuid) are skipped entirely.

Identity: a branch is keyed by its BIRTH msg_uuid (immutable). `seq` (append order) carries
ORDER; msg_uuid never does. leaf = the branch's current tip (advances every response; never an
identity). Membership on demand = an upward parentId walk (cheap, singular).
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any, Iterable

# ── classification reasons ─────────────────────────────────────────────────────────────
PAIRED = "paired"          # tool_result — not a branch
ROOT = "root"              # segment start (no parent)
COMPACTION = "compaction"  # segment start (compaction/load boundary)
RECLAIM = "reclaim"        # offload re-point — not a branch
LINEAR = "linear"          # ordinary continuation
VALID_FORK = "valid_fork"  # genuine rewind / resume branch

_SEGMENT_REASONS = frozenset({ROOT, COMPACTION, VALID_FORK})


# ── record predicates (a "msg" = a uuid-bearing record) ─────────────────────────────────
def is_msg(rec: dict) -> bool:
    return bool(rec.get("uuid"))


def is_attachment(rec: dict) -> bool:
    return rec.get("type") == "attachment"


def is_compaction(rec: dict) -> bool:
    return rec.get("isCompactSummary") is True


def _content(rec: dict) -> Any:
    m = rec.get("message")
    return m.get("content") if isinstance(m, dict) else None


def is_tool_result(rec: dict) -> bool:
    c = _content(rec)
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
    return False


def is_tool_use(rec: dict) -> bool:
    c = _content(rec)
    if isinstance(c, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in c)
    return False


# ── the index ───────────────────────────────────────────────────────────────────────────
class Segment:
    """One branch-segment start (birth). Keyed by birth_uuid (immutable)."""
    __slots__ = ("seq", "birth_uuid", "parent_id", "reason")

    def __init__(self, seq: int, birth_uuid: str, parent_id: str | None, reason: str):
        self.seq = seq
        self.birth_uuid = birth_uuid
        self.parent_id = parent_id
        self.reason = reason

    def as_dict(self) -> dict:
        return {"seq": self.seq, "birth_uuid": self.birth_uuid,
                "parent_id": self.parent_id, "reason": self.reason}

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Segment(seq={self.seq}, birth={self.birth_uuid[:8]}, reason={self.reason})"


class BranchIndex:
    """Incremental, append-order branch index. Build cold with `build(...)` or feed records
    one-at-a-time with `observe(...)` (the Stop-hook path). Offload co-maintains via
    `apply_offload_token(...)`."""

    def __init__(self, compaction_uuids: Iterable[str] = (),
                 reclaim_succ_uuids: Iterable[str] = ()):
        self.tip: str | None = None
        self.seq: int = 0
        self.seq_of: dict[str, int] = {}
        self.segments: list[Segment] = []
        self.reclaim: list[str] = []            # uuids re-pointed by offload
        self._comp: set[str] = set(compaction_uuids)
        self._repoint: set[str] = set(reclaim_succ_uuids)
        self._child_count: collections.Counter = collections.Counter()
        self._type_of: dict[str, str | None] = {}
        self._toolish: set[str] = set()   # tool_use / tool_result records (never a branch tip)

    # -- the O(1) per-record rule -------------------------------------------------------
    def observe(self, rec: dict) -> str:
        """Classify one record in append order. Returns its reason. Skips agent_records."""
        if not is_msg(rec):
            return "agent_record"
        u = rec["uuid"]
        p = rec.get("parentUuid")
        self.seq += 1
        self.seq_of[u] = self.seq
        self._type_of[u] = rec.get("type")
        if is_tool_use(rec) or is_tool_result(rec):
            self._toolish.add(u)
        if p:
            self._child_count[p] += 1

        if is_compaction(rec):          # keep the set current even on incremental feeds
            self._comp.add(u)

        reason = self._classify(rec, u, p)
        if reason in _SEGMENT_REASONS:
            self.segments.append(Segment(self.seq, u, p, reason))
        elif reason == RECLAIM:
            self.reclaim.append(u)
        self.tip = u
        return reason

    def _classify(self, rec: dict, u: str, p: str | None) -> str:
        if is_tool_result(rec):
            return PAIRED
        if p is None:
            return ROOT
        if p in self._comp:
            return COMPACTION
        if u in self._repoint:
            return RECLAIM
        if p == self.tip:
            return LINEAR
        return VALID_FORK

    # -- offload co-maintenance ---------------------------------------------------------
    def apply_offload_token(self, token: dict) -> None:
        """Consume a chain_skip restore token {kind, succ, old_parent, new_parent}. The
        re-pointed record `succ` is a reclaim edge, never a conversational fork. If `succ`
        was previously recorded as a VALID_FORK (e.g. cold-built before the token was known),
        demote it to reclaim."""
        succ = token.get("succ")
        if not succ:
            return
        self._repoint.add(succ)
        if succ not in self.reclaim:
            self.reclaim.append(succ)
        self.segments = [s for s in self.segments
                         if not (s.birth_uuid == succ and s.reason == VALID_FORK)]

    # -- queries (all cheap; membership via upward parentId walk on demand) --------------
    def valid_forks(self) -> list[Segment]:
        return [s for s in self.segments if s.reason == VALID_FORK]

    def leaves(self) -> list[str]:
        """Childless conversational endpoints (branch tips). Excludes attachments AND
        tool_use/tool_result records — an off-path tool record can be childless (parallel-tool
        debris) but is never a real branch tip."""
        return [u for u, t in self._type_of.items()
                if self._child_count[u] == 0 and t in ("assistant", "user", "system")
                and u not in self._toolish]

    def active_leaf(self) -> str | None:
        """The live tip = the childless conversational msg with the highest seq (last-written).
        `last-prompt.leafUuid` is a lagging hint (verified 2026-07-13), so we recompute."""
        lv = self.leaves()
        return max(lv, key=lambda u: self.seq_of[u]) if lv else None

    # -- cold build ---------------------------------------------------------------------
    @classmethod
    def build(cls, records: list[dict], offload_tokens: Iterable[dict] | None = None) -> "BranchIndex":
        comp = {r["uuid"] for r in records if r.get("uuid") and is_compaction(r)}
        repoint = {t["succ"] for t in (offload_tokens or []) if t.get("succ")}
        idx = cls(compaction_uuids=comp, reclaim_succ_uuids=repoint)
        for r in records:
            idx.observe(r)
        return idx


def active_chain(records: list[dict], leaf: str | None) -> list[str]:
    """Root->leaf msg_uuids along the parentId chain (the spine the model walks). NOTE: the
    model's full context also includes each on-chain tool_use's result collected by
    tool_use_id, which may lie off this spine (verified by resume probe)."""
    byu = {r["uuid"]: r for r in records if r.get("uuid")}
    rev, cur, seen = [], leaf, set()
    while cur and cur in byu and cur not in seen:
        seen.add(cur)
        rev.append(cur)
        cur = byu[cur].get("parentUuid")
    return rev[::-1]


# ── persistence / on-demand build (sidecar cached, keyed on file mtime+size) ─────────────
def sidecar_path(transcript_path) -> Path:
    p = Path(transcript_path)
    return p.parent / f"{p.stem}.branch_index.json"


def offload_token_path(transcript_path) -> Path:
    """Where chain_skip appends its re-point tokens (one JSON per line) for the index to
    consume. Kept beside the transcript, distinct from the .bak restore copy."""
    p = Path(transcript_path)
    return p.parent / f"{p.stem}.offload_tokens.jsonl"


def _load_records(transcript_path) -> list[dict]:
    out = []
    with open(transcript_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.strip() and line[0] == "{":
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _load_offload_tokens(transcript_path) -> list[dict]:
    """Re-point tokens for branch classification.

    Uses `chain_skip.effective_skip_tokens` so a rolled-back or uncommitted frame's
    children are NOT classified as reclaim edges — review probed exactly that and found
    three succ tokens still being consumed after a rollback. Falls back to the raw read if
    chain_skip is unavailable.
    """
    # ImportError ONLY — see lib_reclaim_history. A LedgerIntegrityError must propagate,
    # not silently downgrade to the raw view that the canonical reader exists to replace.
    try:
        import chain_skip
    except ImportError:
        chain_skip = None
    if chain_skip is not None:
        return chain_skip.effective_skip_tokens(transcript_path)
    tp = offload_token_path(transcript_path)
    if not tp.exists():
        return []
    toks = []
    for line in tp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                toks.append(json.loads(line))
            except Exception:
                pass
    return toks


def from_transcript(transcript_path, offload_tokens: Iterable[dict] | None = None) -> BranchIndex:
    """Cold-build the index from a transcript file. If offload_tokens is None, auto-loads any
    tokens chain_skip has recorded beside the transcript."""
    if offload_tokens is None:
        offload_tokens = _load_offload_tokens(transcript_path)
    return BranchIndex.build(_load_records(transcript_path), offload_tokens)


def authoritative_leaf(records: list[dict]) -> str | None:
    """The active leaf as EVERY other reclaim tool computes it — chain_skip / lib_context_analysis
    / memory_manager all go through lib_engram.select_active_leaf. The branch index must agree
    with them (a different leaf => a different active chain => inconsistent tools), so we defer
    to that one authority here rather than reinvent it. Falls back to BranchIndex.active_leaf()
    only if select_active_leaf is unavailable (e.g. a minimal test record set)."""
    try:
        from uai_toolkit.jsonl.lib_engram import select_active_leaf
        leaf, _t, _r = select_active_leaf(records)
        if leaf and leaf.get("uuid"):
            return leaf["uuid"]
    except Exception:
        pass
    return None


def report(idx: BranchIndex, active_leaf: str | None = None) -> dict:
    """The persistable / queryable summary of an index. `active_leaf` should be the
    authoritative_leaf(records) value; falls back to the index's heuristic if not supplied."""
    return {
        "segments": [s.as_dict() for s in idx.segments],
        "valid_forks": [s.as_dict() for s in idx.valid_forks()],
        "reclaim": list(idx.reclaim),
        "leaves": idx.leaves(),
        "active_leaf": active_leaf or idx.active_leaf(),
        "n_msgs": idx.seq,
    }


def resolve_live_chain(transcript_path) -> list[str]:
    """NEW branch-aware resolver (parallel to lib_cli_common.resolve_interval_branch's
    live/live chain_uuids, for the shadow-compare + eventual cutover). Returns the active
    branch's spine from the LAST on-chain compaction summary to the leaf — i.e. the live
    segment the model actually sees — computed on the parentId chain, never file lines.

    Contrast with the old resolver: it partitions RAW FILE LINES into intervals, so under
    branching a 'live interval' mixes msgs from different branches (verified). This walks the
    active chain and cuts at the compaction boundary ON that chain."""
    records = _load_records(transcript_path)
    leaf = authoritative_leaf(records)
    if not leaf:
        try:
            from chain_skip import leaf_uuid
            leaf = leaf_uuid(records)
        except Exception:
            leaf = None
    spine = active_chain(records, leaf)
    comp = {r["uuid"] for r in records if r.get("uuid") and is_compaction(r)}
    last_comp = max((i for i, u in enumerate(spine) if u in comp), default=None)
    return spine if last_comp is None else spine[last_comp:]


def get_or_build(transcript_path, refresh: bool = False) -> dict:
    """Return the index report, cached against BOTH transcript and reclaim ledger.

    The ledger is now authoritative for whether a framed re-point is committed or rolled
    back. Keying only on the transcript left a cached reclaim edge visible after a
    sidecar-only rollback until callers forced a refresh.
    """
    tp = Path(transcript_path)
    side = sidecar_path(tp)
    token_path = offload_token_path(tp)

    def _stat_key(path):
        try:
            st = path.stat()
            return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}
        except OSError:
            return None

    key = {"transcript": _stat_key(tp), "offload_tokens": _stat_key(token_path)}
    if side.exists() and not refresh:
        try:
            cached = json.loads(side.read_text())
            if cached.get("_key") == key:
                return cached
        except Exception:
            pass
    records = _load_records(tp)
    idx = BranchIndex.build(records, _load_offload_tokens(tp))
    rep = report(idx, active_leaf=authoritative_leaf(records))
    rep["_key"] = key
    try:
        side.write_text(json.dumps(rep))
    except Exception:
        pass  # read-only FS etc. — still return the fresh report
    return rep
