Codex review — `memorex_transcript_reconcile.md`

Verdict: **request changes before implementation**, but the right v1 shape is close: **MERGE-only, fail-closed, settled/converged, residual-subtraction repair**. I agree with PianoMan's simplification instinct: do not ship SPLIT recovery until a real split is captured.

## 1) Holes I think are still missing

### BLOCKER A — Raw size ceilings are not meaningful unless you first define the JSONL→Memorex projection
Hole #1's cumulative-size ceiling assumes transcript length and terminal-section length are comparable. They often are not:
- tool_result JSONL may be 2,000 lines while terminal shows a collapsed/summarized tool row;
- tool_use JSONL is JSON input while terminal shows `⏺ Bash(cmd)` / `⏺ Read(path)`;
- offloaded/stubbed tool payloads, private thinking stripping, dedup cleanup, ANSI stripping, wrapping, and collapsed sections all change displayed size.

Defeat case: `S` contains a tool marker plus a real assistant response tail, while `M+1` is a huge tool_result in JSONL that terminal summarized. Cumulative size overshoots immediately and terminates before the response, or consumes the wrong span. A size ceiling can be a sanity bound only after converting JSONL messages to the exact Memorex display projection. It cannot be the primary MERGE terminator.

### BLOCKER B — The repair wording still risks insert/double instead of residual subtraction
The doc says MERGE “replaces S body with clean tool_use, splices tool_result, splices response.” For the confirmed fold class, the assistant body is often already on-screen inside the contaminated tool section. If you splice JSONL without subtracting the unique residual slice from `S`, the body doubles. If you subtract the wrong slice, you eat real tool output.

Required invariant: repair is a pure view-model transform: **replace unique normalized residual slice(s) inside the contaminated section with synthetic msg-backed sections**. No unique residual -> no repair.

### HIGH C — first30 `contains` is too weak and can false-anchor
A first-30 substring can appear inside quoted output, code blocks, copied prior answers, repeated “Done — …” openings, common list headers, or tool output. `contains` anywhere in `S` is especially risky; it should be “near the projected section start after marker/header normalization,” plus uniqueness/monotonic-neighbor checks. If two candidates pass, leave unmatched.

New scenario: two adjacent/recent assistant messages both start `Done —` or `I checked...`; a corrupted merge lacks a clean re-align anchor, and the next clean section matches the wrong repeated prefix. The loop terminates early or late and splices over healthy content.

### HIGH D — top-of-buffer anchoring must handle mid-message buffer starts
Hole #4 says anchor to the buffer-top message, but tmux capture can start in the middle of a message, not at a marker. Existing Memorex can produce an orphan `cont` group when the marker scrolled off. If reconcile treats that partial head as a discrepancy, it will fabricate or replace messages above the buffer. v1 should ignore everything before the first full, uniquely matched section marker below buffer top.

### HIGH E — the transcript stream must be filtered to the exact displayable stream
`structured` can include types/records that Memorex does not render equivalently: meta/system/skill/agent_result/injected distinctions, thinking/private stripping, mixed assistant records, tool_use/tool_result pairs, possibly off-chain/dead records depending adapter behavior. The confirm loop says “for each complete transcript message M”; that is too broad. It must use a canonical “Memorex projection” stream: visible types only, in display order, with tool sections represented leniently or as spans.

### HIGH F — synthetic identity needs a replacement/suppression rule, not only `syn:msgId`
Keying synthetic sections by `msgId` avoids occurrence renumbering, but it does not by itself make the terminal’s later healthy render “replace” the synthetic section. A later terminal section will have a terminal key, not `syn:msgId`; without a msgId ownership map, both can coexist. Need an idempotency rule: once terminal content confirms msgId X, suppress/remove `syn:msgX`; once synthetic has repaired a contaminated terminal section, do not reapply on the next refresh.

## 2) Pressure-test of the two HIGH fills

### Hole #1 fill: cumulative-size ceiling
Useful as a guardrail, **not sufficient as termination**. It fails whenever projected terminal size != raw JSONL size, which is common for tools and collapsed/stripped/deduped content. It also fails with duplicated content: a doubled M can equal roughly M+M+1 and look like a real merge.

Recommended replacement: terminate MERGE on one of:
1. unique re-align anchor to the next expected projected message;
2. unique residual slice allocation inside the contaminated section for all repaired messages;
3. a small, explicitly whitelisted pattern for the known real fold shape.

If none holds, fail closed and log. Do not consume arbitrary messages merely because cumulative chars approach `S.length`.

### Hole #2 fill: peek next section first30 vs M+1
It is a good discriminator when positive, but it is not a proof of split when negative.

Defeats:
- next section is also corrupted/merged, or absent at live edge;
- M+1 has an ambiguous/common first30;
- M quotes or contains M+1’s opening text;
- M+1 is a tool section that does not fingerprint well;
- transcript lag means M+1 is not present yet;
- real split section begins with text that coincidentally matches M+1.

So: “next section matches M+1 => likely truncation; absorb nothing” is reasonable. “next section does not match M+1 => real split; absorb” is unsafe. If SPLIT is ever implemented, absorption needs positive proof that the next section is a continuation/residual of M and negative proof that it is not M+1. Otherwise log only.

## 3) SPLIT-less v1

I recommend shipping **SPLIT-less**.

Behavior for `S smaller than M` in v1:
- do not repair;
- do not treat S as a confirmed anchor;
- do not absorb the next section;
- log a high-detail anomaly frame with M/M+1 fingerprints, section text, line spans, contentEnd, activity state, transcript watermark.

Correctness risk: a real split remains visually imperfect. That is acceptable. The alternative false-positive SPLIT repair can eat a real next message and corrupt the settled view, which is worse. Since only S1 is confirmed real, v1 should repair only the confirmed MERGE/fold class.

## 4) Settled-only guard

Settled-only is necessary but **not sufficient** as stated. It prevents the obvious live-prompt false positive, but misses lag/snapshot races:

- terminal capture and JSONL read are different snapshots; tab-return can produce a redraw frame while JSONL is stale or advancing;
- “quiet” or “above contentEnd” is not the same as safe; an active response can have no visible output briefly;
- contentEnd itself is derived from the corruptible terminal buffer, so a boundary detection miss can mark live material as settled;
- the last settled-looking section adjacent to the live tail is exactly where JSONL lag is most likely.

Minimum guard I would require before surgery:
1. no active verb line / no responding state;
2. terminal sections and `contentEnd` stable across two refresh epochs, or one explicit completed-turn/Stop epoch;
3. transcript convergence: read_jsonl watermark/message count stable or advanced as expected across a bounded retry loop;
4. both bracketing anchors for the repair are strictly before contentEnd and not in the last N sections / last turn near the live tail;
5. generation token so older async transcript reads cannot patch a newer overlay;
6. repair only in the view model, never direct DOM append.

## Recommended v1 contract

- Build a Memorex-projected transcript stream first.
- Confirm anchors only with unique, type-compatible, monotonic content matches; first30 is a prefilter, not proof.
- Repair only confirmed MERGE/fold cases where a unique residual slice exists in the contaminated section.
- Drop SPLIT recovery for now; log smaller-than-M anomalies.
- Keep tools lenient unless/until there is a reliable projected representation for tool_use/tool_result.
- Exclude buffer-head partials and live-tail-adjacent sections.

Bottom line: the design is directionally right, but the two HIGH fills do not fully hold. The safe business logic is **MERGE-only + residual subtraction + convergence/settled state machine + fail-closed ambiguity**.
