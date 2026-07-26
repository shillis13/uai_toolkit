#!/usr/bin/env python3
"""
Memorex reconcile — PERFORMANCE prototype (spike, not production).

PianoMan's concern is NOT correctness (the reconcile shape is proven 5/5 in
reconcile_proto.py) — it's **lag/latency and performance**. This prototype
answers that worry with MEASURED numbers on the REAL 71 MB / 39 K-record
transcript, by prototyping the three things that make reconcile cheap enough to
run under the live 10 s overlay refresh:

  1. INCREMENTAL TRANSCRIPT CACHE — the live overlay today re-reads + re-parses
     the ENTIRE JSONL every 10 s (~0.8 s, the dominant cost). Here the cache
     keeps a byte offset + head signature and on refresh reads ONLY the bytes
     appended since last time (seek -> parse new lines -> append with a
     continuing monotonic seq). Full rebuild happens ONLY on compaction/fork
     (file shrink or head-change). Stored seq also gives stable Msg #s (fixes
     the section-10 misnumbering) for free.

  2. LIGHT-META-ALL + HEAVY-CONTENT-TAIL — full message CONTENT (needed for
     content-anchoring) is kept only for the last RING messages (what can be on
     screen); older messages keep only light metadata (seq/type/ts). Bounds RAM
     to O(ring), not O(70 MB of history).

  3. BOUNDED-TAIL RECONCILE + O(n) RESIDUAL — reconcile matches the on-screen
     sections against the last-K metas only (never the 37 K history), and the
     residual-subtraction is O(n) (normalize once + a prefix-length index),
     replacing reconcile_proto._residual_after's O(n^2) growing-prefix re-norm.

Data-ownership note (UAI DESIGN.md #6): this is a READ-ONLY, re-derivable
in-memory cache of the external transcript; the JSONL stays ground truth and the
cache rebuilds on any file change. It never becomes a source of record.

Run: python3 cache_perf_proto.py
"""
import json
import os
import re
import shutil
import sys
import time
from bisect import bisect_left
from dataclasses import dataclass

# The real corpus. BC's transcript (the reconcile test data); fall back to the
# largest available if it moved.
PRIMARY = "/Users/shawnhillis/.claude/projects/-Users-shawnhillis-AI-ai-root/004c1360-c73d-47b3-a97c-301c577c52f0.jsonl"
SCRATCH = "/private/tmp/claude-502/-Users-shawnhillis-AI-ai-root/e2c44c31-1a0f-47bf-b3f9-20bf83a3c2ef/scratchpad"


def _pick_transcript() -> str:
    if os.path.exists(PRIMARY):
        return PRIMARY
    d = os.path.dirname(PRIMARY)
    cands = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl")]
    cands.sort(key=lambda p: os.path.getsize(p), reverse=True)
    if not cands:
        sys.exit("no transcript available to measure against")
    return cands[0]


# ── normalization (shared shape with reconcile_proto.norm) ───────────────────
_LEAD = re.compile(r'^[\s─-╿⏺•▪●·✻✽✳✢◦*>\-]+')


def norm(s: str) -> str:
    s = s.replace('*', '').replace('`', '').replace('#', '')
    s = _LEAD.sub('', s)
    return re.sub(r'\s+', ' ', s).strip().lower()


# ── message content extraction (compact form of reconcile_proto.text_of) ─────
def text_of(rec: dict) -> tuple:
    m = rec.get("message", {}) or {}
    c = m.get("content")
    role = "response" if rec.get("type") == "assistant" else "user"
    if isinstance(c, str):
        return (role, c)
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "thinking":
                return ("thinking", b.get("thinking", ""))
        for b in c:
            if isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result"):
                return ("tool", str(b.get("name") or b.get("content") or ""))
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        if parts:
            return (role, "\n".join(parts))
    return (rec.get("type") or "unknown", "")


# ── the cache ─────────────────────────────────────────────────────────────────
@dataclass
class Meta:
    seq: int
    mtype: str
    ts: str


class TranscriptCache:
    """Incremental, append-only cache with compaction/fork detection.

    metas: light record for EVERY message (seq/type/ts) — stable identity.
    tail:  (seq, type, full_text) ring for the last `ring` messages — the only
           content the reconcile ever needs (older messages are off-screen).
    """

    HEAD_BYTES = 256

    def __init__(self, path: str, ring: int = 400):
        self.path = path
        self.ring = ring
        self.metas: list = []
        self.tail: list = []          # (seq, mtype, text) — last `ring`
        self._offset = 0              # byte offset past last complete line
        self._head_sig = b""
        self._seq = 0

    def _head(self) -> bytes:
        with open(self.path, "rb") as f:
            return f.read(self.HEAD_BYTES)

    def _ingest(self, fh) -> int:
        """Parse whole lines from fh starting at self._offset; return #new."""
        fh.seek(self._offset)
        chunk = fh.read()
        # Only parse up to the last newline — a trailing partial line (mid-write)
        # is held back until it completes.
        nl = chunk.rfind(b"\n")
        if nl < 0:
            return 0
        complete = chunk[:nl + 1]
        self._offset += len(complete)
        n = 0
        for line in complete.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            self._seq += 1
            mtype, txt = text_of(rec)
            ts = (rec.get("message", {}) or {}).get("timestamp") or rec.get("timestamp") or ""
            self.metas.append(Meta(self._seq, mtype, ts))
            self.tail.append((self._seq, mtype, txt))
            n += 1
        if len(self.tail) > self.ring:
            self.tail = self.tail[-self.ring:]
        return n

    def _full_rebuild(self) -> int:
        self.metas.clear()
        self.tail.clear()
        self._offset = 0
        self._seq = 0
        self._head_sig = self._head()
        with open(self.path, "rb") as f:
            return self._ingest(f)

    def refresh(self) -> tuple:
        """Return (mode, n_new, elapsed_s). mode in {full, incr, noop}."""
        t0 = time.perf_counter()
        size = os.path.getsize(self.path)
        if not self.metas:
            n = self._full_rebuild()
            return ("full", n, time.perf_counter() - t0)
        # Compaction / fork / rewrite -> file shrank or head changed -> rebuild.
        if size < self._offset or self._head() != self._head_sig:
            n = self._full_rebuild()
            return ("full", n, time.perf_counter() - t0)
        if size == self._offset:
            return ("noop", 0, time.perf_counter() - t0)
        with open(self.path, "rb") as f:
            n = self._ingest(f)
        return ("incr", n, time.perf_counter() - t0)


# ── O(n) residual (replaces reconcile_proto._residual_after O(n^2)) ──────────
def _norm_index(section_text: str) -> tuple:
    """Normalize once; return (norm_str, prefix_norm_len[]) where
    prefix_norm_len[i] = len(norm(section_text[:i])). Lets residual_after do a
    single bisect instead of re-normalizing a growing prefix each char.

    Mirrors norm(): strip a leading run of glyph/space chars, drop * ` #, lower,
    collapse whitespace runs to one space. prefix_len is monotonic non-decreasing
    so it is bisectable."""
    out = []
    prefix_len = [0] * (len(section_text) + 1)
    prev_space = True
    stripped_lead = False
    lead_set = set(" \t\n\r─╿⏺•▪●·✻✽✳✢◦*>-")
    for i, ch in enumerate(section_text):
        if not stripped_lead and (ch in lead_set):
            prefix_len[i + 1] = len(out)
            continue
        stripped_lead = True
        if ch in "*`#":
            prefix_len[i + 1] = len(out)
            continue
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                prev_space = True
            prefix_len[i + 1] = len(out)
            continue
        out.append(ch.lower())
        prev_space = False
        prefix_len[i + 1] = len(out)
    # norm() does a final .strip(); trailing spaces in `out` don't affect a
    # left-anchored prefix search, so we leave prefix_len as-is.
    return "".join(out).strip(), prefix_len


def residual_after_fast(section_text: str, msg_text: str) -> str:
    """O(n): find the smallest original cut whose normalized-prefix length
    reaches the message's normalized length, via one bisect over prefix_len."""
    target = len(norm(msg_text))
    if target == 0:
        return section_text
    _, prefix_len = _norm_index(section_text)
    cut = bisect_left(prefix_len, target)
    if cut >= len(section_text):
        return ""
    return section_text[cut:].lstrip("\n ")


def residual_after_slow(section_text: str, msg_text: str) -> str:
    """The reconcile_proto O(n^2) version, for the A/B timing comparison."""
    target_len = len(norm(msg_text))
    if target_len == 0:
        return section_text
    for cut in range(1, len(section_text) + 1):
        if len(norm(section_text[:cut])) >= target_len:
            return section_text[cut:].lstrip("\n ")
    return ""


# ── bounded-tail reconcile cost model ────────────────────────────────────────
def bounded_reconcile_cost(cache: TranscriptCache, n_sections: int) -> tuple:
    """Simulate the per-refresh reconcile: match `n_sections` on-screen sections
    against the last (2*n_sections) tail metas by content anchor. Returns
    (elapsed_s, window, matched). This is the ONLY matching the live overlay
    does — bounded by what's on screen, never by history length."""
    window = min(len(cache.tail), max(4, 2 * n_sections))
    tailslice = cache.tail[-window:]
    sections = [t[2] for t in cache.tail[-n_sections:]]
    t0 = time.perf_counter()
    anchors = {norm(txt)[:30]: seq for (seq, _mt, txt) in tailslice}
    matched = sum(1 for s in sections if norm(s)[:30] in anchors)
    return (time.perf_counter() - t0, window, matched)


# ── measurement ──────────────────────────────────────────────────────────────
def fmt_ms(s: float) -> str:
    return f"{s * 1000:.1f} ms"


def main():
    src = _pick_transcript()
    size_mb = os.path.getsize(src) / 1e6
    print(f"{'='*72}\nMemorex reconcile — PERFORMANCE prototype\n{'='*72}")
    print(f"corpus: {src}")
    print(f"        {size_mb:.1f} MB\n")

    # ── 1. COLD full parse (== today's per-10s cost) ─────────────────────────
    cache = TranscriptCache(src, ring=400)
    mode, n, el = cache.refresh()
    print(f"[1] COLD full parse   ({mode}): {n} messages in {fmt_ms(el)}")
    print(f"    -> this is the cost the live overlay pays EVERY 10 s today.")
    print(f"    metas held: {len(cache.metas)} (light)   tail content ring: {len(cache.tail)}")

    # ── 2. WARM no-op refresh (unchanged file) ───────────────────────────────
    mode, n, el = cache.refresh()
    print(f"\n[2] WARM no-op        ({mode}): {n} new in {fmt_ms(el)}  (stat + head compare)")
    print(f"    -> what the cache pays per 10 s when nothing was appended.")

    # ── 3. INCREMENTAL append (the live-tail case) ───────────────────────────
    os.makedirs(SCRATCH, exist_ok=True)
    tmp = os.path.join(SCRATCH, "perf_transcript.jsonl")
    shutil.copyfile(src, tmp)
    c2 = TranscriptCache(tmp, ring=400)
    _, base_n, base_el = c2.refresh()  # prime it (full)
    M = 8  # a burst of new messages between two 10 s ticks
    with open(tmp, "a") as f:
        for i in range(M):
            f.write(json.dumps({
                "type": "assistant",
                "timestamp": f"2026-07-15T16:0{i}:00",
                "message": {"content": [{"type": "text", "text": f"appended synthetic message {i} " * 20}]},
            }) + "\n")
    mode, n, el = c2.refresh()
    ratio = base_el / el if el > 0 else float("inf")
    print(f"\n[3] INCREMENTAL append ({mode}): parsed {n} NEW messages in {fmt_ms(el)}")
    print(f"    vs {fmt_ms(base_el)} for a full re-parse of the same file "
          f"-> ~{ratio:.0f}x cheaper per tick.")
    print(f"    seq continuity: last seq = {c2.metas[-1].seq} (stable Msg #, survives ticks)")

    # ── 3b. COMPACTION/FORK detection → correct full rebuild ─────────────────
    with open(tmp, "w") as f:  # rewrite (simulate compaction: smaller, new head)
        for i in range(50):
            f.write(json.dumps({
                "type": "user" if i == 0 else "assistant",
                "timestamp": "2026-07-15T16:30:00",
                "message": {"content": [{"type": "text", "text": f"post-compaction message {i}"}]},
            }) + "\n")
    mode, n, el = c2.refresh()
    print(f"\n[3b] COMPACTION/fork rewrite -> ({mode}) rebuild: {n} messages in {fmt_ms(el)}")
    print(f"    -> shrink/head-change forces a correct full rebuild; seq resets cleanly.")
    try:
        os.remove(tmp)
    except OSError:
        pass

    # ── 4. BOUNDED-TAIL reconcile cost (the per-refresh match) ───────────────
    print(f"\n[4] BOUNDED-TAIL reconcile match cost (on-screen sections only):")
    for nsec in (20, 50, 100):
        el, window, matched = bounded_reconcile_cost(cache, nsec)
        print(f"    {nsec:>3} sections vs {window:>3}-meta window: {fmt_ms(el):>9}  "
              f"({matched} anchored)")
    print(f"    -> reconcile scales with what's ON SCREEN, not the {len(cache.metas)} history.")

    # ── 5. O(n) vs O(n^2) residual on a large merged section ─────────────────
    print(f"\n[5] residual-subtraction: O(n) fast vs O(n^2) slow (a big merged section):")
    big = next((t[2] for t in reversed(cache.tail) if len(t[2]) > 4000), "x " * 3000)
    section = big + "\n\n" + ("residual tail sentence. " * 40)
    msg = big
    t0 = time.perf_counter(); r_fast = residual_after_fast(section, msg); t_fast = time.perf_counter() - t0
    t0 = time.perf_counter(); r_slow = residual_after_slow(section, msg); t_slow = time.perf_counter() - t0
    agree = norm(r_fast) == norm(r_slow)
    speed = t_slow / t_fast if t_fast > 0 else float("inf")
    print(f"    section len = {len(section)} chars")
    print(f"    O(n)   fast: {fmt_ms(t_fast)}")
    print(f"    O(n^2) slow: {fmt_ms(t_slow)}   -> fast is ~{speed:.0f}x cheaper")
    print(f"    outputs agree (normalized): {agree}")

    # ── verdict ──────────────────────────────────────────────────────────────
    print(f"\n{'='*72}\nLATENCY BUDGET (per 10 s tick, warm):")
    print(f"  no-op tick      : stat + head compare        (sub-ms)")
    print(f"  typical tick    : parse only NEW messages     (incr, ~{fmt_ms(el)}-class)")
    print(f"  reconcile match : bounded by on-screen size   (sub-ms at 100 sections)")
    print(f"  full reparse    : ONLY on compaction/fork      (rare, the old {fmt_ms(base_el)})")
    print(f"-> The 0.8 s-every-10 s cost collapses to a stat on quiet ticks and a")
    print(f"   new-records-only parse on active ones. Reconcile itself is not the")
    print(f"   bottleneck; the repeated full parse was.")


if __name__ == "__main__":
    main()
