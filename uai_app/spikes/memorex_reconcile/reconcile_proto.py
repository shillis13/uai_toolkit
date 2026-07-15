#!/usr/bin/env python3
"""
Memorex ⟷ Transcript reconcile — ALGORITHM PROTOTYPE (spike, not production).

Purpose: validate the reconcile logic against the REAL Broken-Clock corruption
before any Memorex-logic change. Claude Code dropped a response's leading marker
AND its first paragraph on a thinking→response transition, so the terminal merged
the response's tail up into the thinking block and lost the head. The JSONL
transcript has the full, correct content.

This prototype:
  1. loads the REAL messages from Broken-Clock's transcript (thinking @36911,
     response @36912),
  2. SIMULATES the exact CC corruption to produce the "terminal sections" Memorex
     would see,
  3. runs the reconcile algorithm (content-anchored, MERGE + head-restore,
     residual-subtraction, fail-closed) — the corrected design from Codex Review 1,
  4. prints BEFORE (corrupt) vs AFTER (repaired) so we can see it work and try to
     break it.

Run: python3 reconcile_proto.py
"""
import json
import re
import sys
from dataclasses import dataclass, field

TRANSCRIPT = "/Users/shawnhillis/.claude/projects/-Users-shawnhillis-AI-ai-root/004c1360-c73d-47b3-a97c-301c577c52f0.jsonl"

# ── model ──────────────────────────────────────────────────────────────────
@dataclass
class Msg:
    mtype: str      # 'user' | 'response' | 'thinking' | 'tool'
    text: str
    idx: int = -1   # transcript index (msg number stand-in)

@dataclass
class Section:
    stype: str
    text: str
    msg_idx: int = None      # which transcript msg it's confirmed to (None = unmatched)
    synthetic: bool = False  # True if reconstructed from transcript (a repair)

# ── normalization (match content, ignore glyph/markdown/whitespace) ─────────
_LEAD = re.compile(r'^[\s─-╿⏺•▪●·✻✽✳✢◦*>\-]+')
def norm(s: str) -> str:
    s = s.replace('*', '').replace('`', '').replace('#', '')
    s = _LEAD.sub('', s)
    return re.sub(r'\s+', ' ', s).strip().lower()

def head(s: str, n: int = 40) -> str:
    return norm(s)[:n]

# ── transcript loader (real data) ───────────────────────────────────────────
def text_of(rec) -> tuple:
    m = rec.get("message", {})
    c = m.get("content")
    if isinstance(c, str):
        return ("response" if rec.get("type") == "assistant" else "user", c)
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "thinking":
                return ("thinking", b.get("thinking", ""))
        parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
        if parts:
            return ("response" if rec.get("type") == "assistant" else "user", "\n".join(parts))
    return (None, "")

def load_real_pair() -> list:
    """Pull the real thinking+response pair from the transcript by content."""
    recs = [json.loads(l) for l in open(TRANSCRIPT) if l.strip()]
    resp_idx = None
    for i, r in enumerate(recs):
        _, t = text_of(r)
        if "fork-creating msgs" in t and "current tip" in t:
            resp_idx = i
            break
    if resp_idx is None:
        sys.exit("could not locate the test exchange in the transcript")
    think_idx = None
    for j in range(resp_idx - 1, resp_idx - 5, -1):
        ty, _ = text_of(recs[j])
        if ty == "thinking":
            think_idx = j
            break
    tt, thinking = text_of(recs[think_idx])
    rt, response = text_of(recs[resp_idx])
    return [Msg("thinking", thinking, think_idx), Msg("response", response, resp_idx)]

# ── simulate the CC corruption → what Memorex/terminal actually shows ────────
def simulate_terminal(msgs: list) -> list:
    """Reproduce the observed drop: the response's leading marker + FIRST paragraph
    are gone, so its tail merges up into the preceding thinking block (no marker →
    no new section)."""
    think, resp = msgs[0], msgs[1]
    paras = resp.text.split("\n\n")
    dropped_head = paras[0]                    # "You're basically there ... two parts."
    surviving_tail = "\n\n".join(paras[1:])    # "**The fork model** — sound. ..."
    # terminal: one thinking section that swallowed the surviving response tail
    merged = think.text.rstrip() + "\n" + surviving_tail
    return [Section("thinking", merged)], dropped_head

# ── the reconcile algorithm ─────────────────────────────────────────────────
def reconcile(sections: list, msgs: list):
    """Content-anchored, forward walk. Handles CONFIRM, MERGE (one section holds N
    msgs) with residual-subtraction, and HEAD-DROP (a msg whose leading text was
    lost so a section is only its suffix). Fail-closed: no unique evidence → no
    change + logged anomaly."""
    out, log = [], []
    si = mi = 0
    while si < len(sections):
        S = sections[si]
        sn = norm(S.text)

        # DEDUP (checked first, independent of the message cursor) — a redraw copy of the
        # section we just placed. Drop it; it consumes NO transcript message. Cooperates
        # with the existing dedupConsecutiveBlocks. This is the "split-like" duplicate.
        if out and sn and sn == norm(out[-1].text):
            log.append(f"DEDUP    drop duplicate of prior section ({S.stype})")
            si += 1; continue

        if mi >= len(msgs):
            out.append(S); log.append(f"ANOMALY  extra section, no message left (fail-closed)")
            si += 1; continue
        M = msgs[mi]

        # TOOL leniency — the terminal's collapsed tool rendering ("Read 2000 lines") is
        # nothing like the JSONL tool text. Match tools by TYPE/position only (no size or
        # content gate). A terminal tool section may cover tool_use + tool_result, so
        # consume consecutive tool messages.
        if S.stype == "tool" and M.mtype == "tool":
            S.msg_idx = M.idx
            out.append(S)
            span = [M.idx]; mi += 1
            while mi < len(msgs) and msgs[mi].mtype == "tool":
                span.append(msgs[mi].idx); mi += 1
            log.append(f"TOOL     type-match section↔tool msg(s) #{span} (no size gate)")
            si += 1; continue

        if sn.startswith(head(M.text)):
            mn = norm(M.text)
            if len(sn) <= len(mn) + max(8, int(0.15 * len(mn))):
                # CONFIRM — sizes match within tolerance
                S.stype, S.msg_idx = M.mtype, M.idx
                out.append(S); log.append(f"CONFIRM  section↔msg#{M.idx} ({M.mtype})")
                si += 1; mi += 1
            else:
                # MERGE — section is bigger: it holds M plus residual. Emit M's own
                # section, then reconsider the residual as the next section.
                out.append(Section(M.mtype, _slice_original(S.text, M.text), M.idx))
                log.append(f"MERGE    split msg#{M.idx} ({M.mtype}) off the front")
                residual = _residual_after(S.text, M.text)
                sections[si] = Section("cont", residual)  # reprocess residual in place
                mi += 1  # consumed M; residual matched against M+1 next loop
        else:
            # S doesn't start with M — is S a proper SUFFIX of M (M's head dropped)?
            mn = norm(M.text)
            if sn and len(sn) < len(mn) and mn.endswith(sn):
                # HEAD-DROP — restore M in full from the transcript (marker + head)
                out.append(Section(M.mtype, M.text, M.idx, synthetic=True))
                log.append(f"HEAD-DROP restore msg#{M.idx} ({M.mtype}) full text "
                           f"(terminal had only its tail — dropped: "
                           f"{repr(_dropped_prefix(M.text, sn)[:60])}…)")
                si += 1; mi += 1
            else:
                # no unique evidence → fail closed
                out.append(S); log.append(f"ANOMALY  section unmatched, left as-is "
                                          f"(fail-closed): {repr(S.text[:40])}")
                si += 1
    return out, log

def _slice_original(section_text: str, msg_text: str) -> str:
    """Return the front of the ORIGINAL (un-normalized) section text corresponding
    to msg_text, so we keep real formatting. Prototype: split at the msg's char len
    proportionally — good enough to demonstrate; production would map spans exactly."""
    return msg_text

def _residual_after(section_text: str, msg_text: str) -> str:
    """The original section content AFTER the portion whose NORMALIZED form matches
    msg_text. Grow a prefix of the section until its normalized length reaches the
    msg's normalized length; the rest is the residual. (Prototype-simple; production
    maps normalized spans back to exact terminal cells.)"""
    target_len = len(norm(msg_text))
    if target_len == 0:
        return section_text
    for cut in range(1, len(section_text) + 1):
        if len(norm(section_text[:cut])) >= target_len:
            return section_text[cut:].lstrip("\n ")
    return ""

def _dropped_prefix(msg_text: str, section_norm: str) -> str:
    mn = norm(msg_text)
    cut = mn.find(section_norm[:20])
    return msg_text[:max(0, cut)] if cut > 0 else msg_text.split("\n\n")[0]

# ── pretty print ────────────────────────────────────────────────────────────
def show(title, sections):
    print(f"\n{'='*70}\n{title}\n{'='*70}")
    for i, s in enumerate(sections):
        tag = f"[{s.stype}"
        if s.msg_idx is not None: tag += f" · msg#{s.msg_idx}"
        if s.synthetic: tag += " · RESTORED"
        tag += "]"
        first = s.text.strip().splitlines()[0] if s.text.strip() else "(empty)"
        print(f"  {tag}")
        print(f"     ⤷ {first[:80]}")

def run(name, terminal, msgs, expect):
    print(f"\n{'#'*70}\n# SCENARIO: {name}\n{'#'*70}")
    show("BEFORE — terminal/Memorex", terminal)
    repaired, log = reconcile([Section(s.stype, s.text) for s in terminal], msgs)
    show("AFTER — reconciled", repaired)
    print("\nrepair log:")
    for l in log: print("  -", l)
    restored = [s for s in repaired if s.synthetic]
    got = ("restored" if restored
           else "deduped" if any("DEDUP" in l for l in log)
           else "anomaly" if any("ANOMALY" in l for l in log)
           else "clean")
    verdict = "PASS" if got == expect else f"FAIL (expected {expect}, got {got})"
    print(f"\nVERDICT [{name}]: {verdict}")
    return verdict.startswith("PASS")

def main():
    msgs = load_real_pair()
    think, resp = msgs
    print("REAL transcript ground truth:")
    for m in msgs:
        print(f"  msg#{m.idx} [{m.mtype}] first line: {m.text.strip().splitlines()[0][:76]!r}")

    results = []

    # 1) the REAL corruption — response marker + head dropped, tail merged into thinking
    terminal, dropped = simulate_terminal(msgs)
    print(f"\n  (real dropped first line: {dropped.strip().splitlines()[0][:70]!r})")
    results.append(run("real head-drop (Broken-Clock)", terminal, msgs, expect="restored"))

    # 2) CLEAN — terminal rendered both correctly. Must CONFIRM both, invent NOTHING.
    clean = [Section("thinking", think.text), Section("response", resp.text)]
    results.append(run("clean render (must not hallucinate)", clean, msgs, expect="clean"))

    # 3) FAIL-CLOSED — a section matching NEITHER transcript msg. Must be left as-is,
    #    never fabricated into a message.
    junk = [Section("thinking", think.text),
            Section("response", "xyzzy garbled line present in no transcript message at all")]
    results.append(run("unknown content (must fail closed)", junk, msgs, expect="anomaly"))

    # 4) DEDUP — a redraw duplicated the response. Transcript has it ONCE, terminal TWICE.
    #    Repair is DELETE the duplicate (not restore) — the "split-like" case.
    dup = [Section("thinking", think.text),
           Section("response", resp.text),
           Section("response", resp.text)]   # redraw copy
    results.append(run("redraw duplicate (should DELETE the dup)", dup, msgs, expect="deduped"))

    # 5) TOOL — terminal shows a COLLAPSED tool section ("Read 2000 lines"); the JSONL
    #    tool_result holds the full text. Size is wildly off on a HEALTHY section — the
    #    matcher must treat tools leniently (type-match only, no size gate) so the
    #    response AFTER it still aligns.
    tool_msgs = [Msg("thinking", think.text, 1),
                 Msg("tool", "\n".join(f"line {i}: <file contents>" for i in range(2000)), 2),
                 Msg("response", resp.text, 3)]
    tool_terminal = [Section("thinking", think.text),
                     Section("tool", "Read(big_file.ts)\n  ⎿ Read 2000 lines (ctrl+r to expand)"),
                     Section("response", resp.text)]
    results.append(run("collapsed tool section (size mismatch, stay lenient)",
                       tool_terminal, tool_msgs, expect="clean"))

    print(f"\n{'='*70}\nSUMMARY: {sum(results)}/{len(results)} scenarios passed")

if __name__ == "__main__":
    main()
