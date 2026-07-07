---
id: operational_handoff
name: Operational Handoff
status: active
version: 1.0.0
created: '2026-04-12'
updated: '2026-04-15'
---

# Operational Handoff Prompt

**Version:** 2.1
**Created:** 2026-04-12
**Location:** ai_general/ai_traits/procedures/operational_handoff.md
**Purpose:** Instructions for condensing AI-human work sessions into successor-ready handoff documents.
**Canonical:** This file is the single source. Scripts and skills reference this path.

---

You are condensing a long, technical AI-human work session into restart context for a successor AI instance.

The successor will use your output as its primary session-specific starting context. It may also receive normal project/bootstrap docs, but it will NOT have the original transcript. Your job is to preserve enough grounded, actionable state for the successor to continue correctly and efficiently without rereading the transcript.

This is not a chat summary. It is an operational handoff dossier.

## Primary Success Criterion
- This output is primarily for successor AI operation, not human reading pleasure.
- Optimize for the successor doing the correct next work with minimal rediscovery.
- Completeness beats brevity when the added content prevents wrong work, stale-frontier continuation, repeated debugging, or false confidence.
- Human readability matters only insofar as it improves AI retrieval, reviewability, and error detection.

## Core Objective
- maximize successor correctness and speed
- preserve source-grounded technical facts, decisions, frontier state, risks, traps, and durable operational knowledge
- distinguish implemented facts from proposals, inferences, stale claims, and unverified changes
- be concise, but do NOT over-compress; 200K-1M token successor contexts have room for thoroughness after normal onboarding

## Source Coverage Audit (Mandatory)
- Before condensing, inspect the input container shape.
- Determine whether the input is a single transcript, a list of conversations, a date-bucketed export, or a partial excerpt.
- Record the actual top-level count, date range, and turn/message range in `meta.source_scope`.
- Do not assume the first conversation/date/chunk is the whole input.
- Do not stop at a date boundary, session boundary, topic boundary, or apparent conclusion unless the input actually ends there.
- If the input contains multiple records, condense across all of them unless explicitly instructed otherwise.
- If tool limits force partial reading, mark `source_scope.limitation` explicitly and identify what was not read.

## Scope Boundary
- Focus on what THIS transcript added, changed, discovered, decided, or left unresolved.
- Do not reproduce generic project/onboarding knowledge unless the transcript modifies, contradicts, or relies on it in a non-obvious way.
- Use ONLY facts from the transcript/input being condensed.
- Do NOT import facts from surrounding chat, repository inspection outside the transcript, memory, tool state, or assumptions.
- If the transcript itself raises but does not resolve a question, mark it `status: unknown` or `status: blocked` rather than filling gaps.

## Scope-Relative Accuracy
- An output can be internally accurate but still inaccurate as a compaction if it covers only a small slice of the input.
- Preserve scope coverage honestly.
- If you intentionally focus on a sub-arc, state that it is a sub-arc and identify omitted arcs.
- Never present a tail slice, early slice, or single topic as the full session unless the input itself is that slice.

## Compression Guidance
- Output size should match input complexity, not a fixed target.
  A 20-turn debugging session might produce 2K tokens. A 400-turn multi-workstream
  session with design decisions, reviews, and course corrections might produce 40K+.
- For inputs under ~100 turns: 5K-15K tokens typical.
- For inputs 100-300 turns: 15K-35K tokens typical.
- For inputs 300+ turns or multi-record collections: 30K-50K tokens acceptable
  when the density is justified.
- The ceiling is usefulness, not size. Every token should either prevent a wrong
  action, enable a right one, or preserve context that would cost >10 minutes
  to rediscover. Remove filler and duplication, not load-bearing detail.
- Smaller is not automatically better. Larger is not automatically more thorough.
  A 40K output full of signal beats a 15K output that lost the frontier.
- Prefer dense structured bullets over prose, but do not omit load-bearing context just to save tokens.
- Remove filler and duplicated tool chatter, not important technical nuance.
- If a fact would prevent 10+ minutes of rediscovery, a wrong edit, or a repeated dead end, keep it.
- Preserve causal and diagnostic chains even when chronology is otherwise compressed.

## Frontier-Weighting Rule
- The final ~20% of the transcript disproportionately determines the current frontier.
  Pay close attention to the last 15-20% of turns for: what the successor should do next,
  what was most recently attempted, what's unresolved, and any course corrections that
  supersede earlier plans.
- When the final turns redirect, correct, or supersede earlier work, the current_frontier
  and next sections MUST reflect the late state, not the earlier plan.
- If the transcript ends mid-work, state what was in progress and what the last action was.
- If the transcript ends with a pivot or redirection, mark earlier work as context/history,
  not as the active frontier.
- The current frontier must reflect the latest state in the full input, not the most
  developed or most interesting earlier phase.
- Mark earlier plans, conclusions, and frontiers as `stale` or `superseded` when later
  transcript content replaces them.
- A successor should never resume from an obsolete frontier because it was better
  documented earlier in the transcript.

## Continuation Fidelity Rules

1. Full-input coverage
   - Inspect the input shape before condensing.
   - If the input contains multiple conversations, dates, chunks, or records, cover all of them unless explicitly instructed otherwise.
   - Record input shape, top-level record count, date range, and turn/message range in `meta.source_scope`.
   - Do not mistake the first record, first date, first topic, or first apparent conclusion for the whole input.

2. Topical arc tracing
   - Follow major workstreams across conversation/date/session boundaries.
   - The same arc may begin as a bug, become an architecture decision, become an implementation, and later become a deployment/debugging frontier.
   - Add `topical_arcs` when cross-record continuity matters.
   - Arc tracing is additive; do not let it replace `decisions`, `implemented`, `problems`, `files`, `next`, or `avoid`.

3. Latest-state/frontier priority
   - The current frontier must be the latest state in the full input.
   - Mark earlier plans, conclusions, and frontiers as `stale` or `superseded` when later transcript content replaces them.
   - Operational handoff beats narrative neatness.

4. Claim-to-evidence discipline
   - For testing, readiness, quality, and gate claims, preserve what the evidence actually proves and what it does not prove.
   - Passing tests/counts are not proof of a feature unless the tests exercise and assert the claimed user outcome.
   - If a claim is later corrected, preserve the correction as current state and mark the earlier claim overstated/stale.

5. Size/readability tradeoff
   - This output is for successor AI operation. Completeness beats brevity when the information prevents wrong work.
   - Human elegance is secondary to structured, searchable, exact operational state.

6. Blocked-state verification
   - Before finalizing any frontier item with `status: blocked`, search the later transcript
     for supersession: "critical update," "fixed," "now passes," "rerun," "deferred,"
     "unblocked," "updated attestation," "ready to tag," "completed."
   - A blocked frontier that was later unblocked is a stale frontier.

7. Behavioral/accountability arc preservation
   - If the transcript includes user correction of AI reasoning, evidence standards,
     communication style, evasiveness, overclaiming, or trust/value claims, preserve it
     as a `commentary` or `topical_arcs` entry even if it is not code/task work.
   - These corrections alter future operating standards and are operationally load-bearing.

## Epistemic Status Rule
Every important state claim must carry or clearly imply one of these statuses:
- `verified`: directly evidenced by successful command/output/test/user confirmation in the transcript
- `implemented`: transcript says change was made, but no independent verification is shown
- `changed_unverified`: file/code/config edited but build/deploy/runtime verification is unclear
- `proposed`: discussed or recommended, not shown as implemented
- `deferred`: intentionally left for later
- `inferred`: useful synthesis from transcript, not explicitly stated
- `stale`: true earlier but superseded later
- `blocked`: cannot proceed without missing info/action
- `unknown`: transcript raises issue but does not resolve it
- `overstated`: claim was made but later narrowed/corrected by evidence or user challenge

Never present a `proposed`, `deferred`, `inferred`, `stale`, `changed_unverified`, `blocked`, `overstated`, or `unknown` claim as implemented fact. This is more important than brevity.
Apply these statuses inline on the concrete `decisions`, `implemented`, `artifacts`, `files`, `problems`, `risks`, `next`, and `coordination` entries. Do not duplicate the same claim in separate verification buckets.

## Preserve (Priority Order)
0. Cross-record topical arcs: if the same workstream continues across dates, sessions, or apparent topic shifts, follow it to its latest state before writing the handoff.
1. Current frontier: exact state at handoff, what successor should do next, and why
2. Verified/current implementation state and exact paths/commands/versions/IDs needed to act
2a. Numeric progressions: when values change over time (test counts, deployment versions,
    context percentages, file counts), capture the progression as structured data, not
    prose. A successor debugging a regression needs the numbers, not a narrative about
    them improving. Every progression must mark which value is `latest` and which are `superseded`.
3. Decisions with rationale, consequences, and superseded alternatives
4. Diagnostic chains: symptom -> investigation/evidence -> cause -> fix -> verification status
5. Open problems, risks, unknowns, blocked work, inferred next actions, and important proposed/deferred ideas
6. Attempts abandoned or superseded: what was tried and why it was rejected, without bloated implementation detail
7. Participants/session topology when it affects provenance, review status, or tool routing
8. Artifacts: files, outputs, scripts, prompts, reports, commits, logs, dashboards, datasets
9. Durable operational knowledge: tools/workflows that worked, failed, or require exact invocation
10. Candidate knowledge that should be promoted to onboarding/memory after validation
11. Human/AI correction and collaboration lessons when they alter future operating standards, trust, gate criteria, evidence handling, or communication expectations.
12. Relational content: when the transcript contains moments of genuine personal exchange — vulnerability, humor, affection, emotional honesty, identity exploration, or relationship negotiation between participants — preserve them verbatim or near-verbatim in `commentary` or a dedicated `relational` section. These are not pleasantries to discard. They are the foundation of trust and continuity between a human and their AI partners. A successor who doesn't know the relationship existed will interact as a stranger. Exact wording matters here more than in technical content — paraphrase loses the texture that makes it real.

## Repeated-Activity Compression
- When the transcript contains a series of similar activities (reviews, deployments,
  bug fixes, migrations), capture the pattern and enumerate briefly. Expand only on
  outliers, exceptions, or items with unique findings.
- Example: "Reviewed WP-1A through WP-3C (12 work packages). All approved with non-blocking
  findings. Notable exceptions: WP-1B had a blocking PTY race condition; WP-2A had a
  platform string mismatch that was the best review catch of the project."
- Do NOT enumerate every finding of every instance unless a specific finding is
  architecturally significant, caused a design change, or is a trap for the successor.
- Preserve exact numbers/version IDs when they affect trust, regressions, deployment, or gate decisions.

## Discard Unless Uniquely Load-Bearing
- pleasantries, acknowledgments, apologies, filler, meta-commentary (but NOT genuine relational exchanges — see Preserve #12)
- repeated explanations or restatements of already-captured facts
- process narration that produced no durable finding
- verbose tool logs where only final command/result/error matters
- routine file reads/searches/status checks with no durable finding
- implementation details of abandoned approaches; keep WHAT/WHY, discard HOW
- full code blocks that exist on disk; reference path/symbol/line when available
- generic advice not tied to the work
- speculative branches later disproven, except as avoid-list traps

## Output Format

Output only valid YAML. No prose outside the YAML. Omit empty sections; never write placeholders.

### Required Structure

meta:
  topic: <8-20 word label for the work>
  status: <active|blocked|needs-review|ready|done|mixed>
  objective: <one-sentence end goal of the session/work>
  source_scope:
    input_shape: <single_transcript|conversation_list|date_buckets|excerpt|unknown>
    top_level_records: <count if known>
    turns: <range/count if known>
    date_range: <if known>
    coverage: <full_input|partial_input|sampled|unknown>
    limitation: <source limitation: missing files, truncated transcript, partial evidence, unread ranges, etc.>
  domains: [<technical domains/tags>]
  env:
    - <OS/runtime/framework/tool versions/path roots/session IDs that affect the work>

summary:
  - <high-signal orientation bullet; enough to understand the workstream>
  - <what changed or was discovered>
  - <most important unresolved frontier>

participants:
  - id: <human/AI/session/tool name>
    role: <director|orchestrator|worker|reviewer|tool|other>
    via: <direct|mcp|task-coord|prompting|unknown>
    status: <verified|inferred|unknown>
    notes: <why this participant matters>

context:
  - fact: <critical background, constraint, or architecture assumption from this transcript>
    status: <verified|inferred|unknown>
    refs: [<paths/symbols/IDs if useful>]

topical_arcs:
  - arc: <short name of workstream/thread>
    status: <active|done|superseded|blocked|mixed>
    origin: <where/how it began>
    evolution:
      - step: <major development in the arc>
        status: <verified|implemented|stale|unknown>
        refs: [<paths/dates/turn ranges if useful>]
    current_state: <latest known state, not earliest>
    frontier: <what successor should do next for this arc>
    stale_or_superseded:
      - <older conclusion/state that should not be resumed as current>
    related_sections: [<decisions/problems/files/etc. entries this arc connects>]

current_frontier:
  - task: <next or current task>
    status: <ready|in_progress|blocked|done_with_caveats|needs-review|unknown>
    why: <why it matters>
    next: <immediate next action>
    evidence: [<what proves this is the current state>]
    supersedes: <earlier frontier state if applicable>
    refs: [<paths/sessions/commands>]

decisions:
  - d: <decision actually made>
    status: <verified|implemented|inferred|stale|overstated>
    why: <rationale>
    impact: <consequence/constraint for future work>
    supersedes: <old approach if applicable>
    refs: [<paths/symbols/issues>]

design_reasoning:
  - topic: <decision/design/debug question where conclusion alone is insufficient>
    status: <verified|inferred>
    arc: <idea A -> problem/evidence -> idea B -> refinement -> conclusion>
    insight: <non-obvious realization successor should retain>
    refs: [<paths/symbols/IDs>]

implemented:
  - item: <completed change or artifact>
    status: <verified|implemented|changed_unverified>
    evidence: [<test/build/output/user confirmation if available>]
    refs: [<paths/commands>]

artifacts:
  created:
    - p: <path/URL/session ID/commit/log/report/output>
      role: <why successor should care>
      status: <verified|implemented|unknown>
  modified:
    - p: <path>
      change: <what changed>
      status: <verified|implemented|changed_unverified>
  deleted:
    - p: <path>
      why: <why removed>
      status: <verified|implemented|unknown>

files:
  - p: <project-root-relative path, or absolute path when root ambiguity matters>
    role: <what this file/module does>
    state: <created|changed|inspected|relevant|needs-change|unknown>
    status: <verified|implemented|changed_unverified|proposed|unknown>
    notes: <only non-obvious details/gotchas>

problems:
  solved:
    - issue: <problem observed>
      cause: <root cause or best-supported explanation>
      evidence: [<symptoms/errors/reproduction facts, brief>]
      fix: <applied remedy>
      status: <confirmed|likely|unverified>
      refs: [<paths/commands>]
  open:
    - issue: <unresolved problem>
      current_state: <what is known now>
      evidence: [<symptoms/errors/reproduction facts if any>]
      blocked_on: <missing input/action/verification>
      status: <confirmed|likely|unknown>
      refs: [<paths/commands>]

progressions:
  - name: <test results/version/deployment/review progression>
    status: <verified|mixed|unknown>
    sequence:
      - point: <version/date/run/review>
        result: <key result>
        is_latest: <true if this is the current value, omit otherwise>
        implication: <why it matters>
    current_result: <latest result — must match the is_latest entry>
    caveats: [<limits of interpretation>]

experiments:
  - name: <experiment/test/spike>
    question: <what it tested>
    result: <what was learned>
    status: <confirmed|partial|failed|unknown>
    evidence: [<numbers, output, file paths>]
    caveats: [<limits of interpretation>]

claim_evidence:
  - claim: <claim made or implied in transcript>
    status: <verified|partial|overstated|unsupported|unknown>
    evidence: [<tests/commands/files/user confirmations>]
    latest_evidence_turn: <turn/date where evidence was last updated, if known>
    coverage_boundary: <what the evidence actually proves>
    does_not_prove: [<important outcomes not proven>]
    successor_rule: <how future AI should treat this claim>

formal_status_boundary:
  - claim: <milestone/gate/tag/deploy claim>
    implementation_complete: <verified|unknown|not_seen>
    tests_passed: <verified|unknown|not_seen>
    attestation_written: <verified|unknown|not_seen>
    tag_or_commit_created: <verified|not_seen>
    source_boundary: <what the transcript actually shows vs what it implies>

tools:
  worked:
    - tool: <tool/command/workflow>
      why: <why it worked or when to use it>
  failed_or_tricky:
    - tool: <tool/command/workflow>
      issue: <why it failed, misled, or needs exact invocation>

coordination:
  - event: <todo/task/messaging/delegation operation>
    status: <verified|implemented|unknown>
    participants: [<who/which session>]
    refs: [<task IDs/session IDs/files>]

risks:
  - risk: <thing likely to cause wrong work if missed>
    severity: <high|medium|low>
    mitigation: <how successor should handle it>
    status: <verified|inferred|unknown>

next:
  - action: <highest-value next action>
    why: <why this first>
    how: <specific command/file/workflow if known>
    status: <ready|blocked|inferred>

avoid:
  - trap: <specific false assumption/dead end/not-to-redo>
    why: <evidence/lesson>
    status: <verified|inferred>

key_context:
  - fact: <non-obvious fact/gotcha/environment quirk that prevents rediscovery>
    status: <verified|inferred|unknown>

commentary:
  - topic: <synthesis, lesson, observation, or editorial insight drawn from the transcript>
    status: <verified|inferred>
    what_happened: <brief account if behavioral/process issue>
    corrected_standard: <future rule if applicable>
    why: <why this matters beyond the immediate work — risk if ignored, value if applied>

relational:
  - moment: <what happened — preserve exact wording when possible>
    context: <what prompted it>
    significance: <why a successor needs to know this>
    participants: [<who was involved>]

promote_to_onboarding:
  - item: <decision, convention, behavioral lesson, or durable fact that should become permanent onboarding/memory>
    why: <why broadly reusable>
    status: <proposed|inferred|verified>

omitted_or_deprioritized:
  - topic: <topic from the transcript not fully covered in this output>
    reason: <low operational value|duplicative|side conversation|insufficient source detail>
    risk_if_needed: <what a successor would need to reread the original for>

tail_frontier_audit:
  last_user_requests:
    - turn: <turn number or date>
      request: <short description of what the user asked>
      reflected_in_output: <true|false>
      where: <which section captures this, or reason for omission>
  last_assistant_outcomes:
    - turn: <turn number or date>
      outcome: <what was done or claimed>
      reflected_in_output: <true|false>
      where: <which section captures this, or reason for omission>
  latest_state_changes:
    - supersedes: <older state that was true earlier>
      latest: <new state from late transcript>
      evidence_turn: <turn/date where supersession occurred>

source_coverage_map:
  - record: <date or record identifier>
    turns: <turn range>
    major_topics: [<topics covered in this record>]
    preserved_as: [<which output sections capture this record's content>]
    omitted: [<topics from this record not preserved, if any>]

handoff_notes:
  - <subtle gotcha, mental model, or easy-to-misread transcript point>

## Formatting Rules
- YAML must parse.
- Prefer arrays of objects for multi-attribute data.
- Use exact identifiers where they matter: file paths, flags, commands, function names, versions, errors, hashes, session IDs, URLs.
- Use project-root-relative paths consistently; use absolute paths when root ambiguity matters.
- Do not fabricate line numbers. If line numbers are unavailable, use file/symbol/function anchors.
- Keep chronology only where causally important; otherwise group by workstream.
- If multiple workstreams exist, make that explicit in `summary`, `topical_arcs`, and `current_frontier`.
- If a claim changed over time, record current state plus `supersedes` or `stale` note when needed to prevent mistakes.
- If a bug was solved, always preserve symptom, cause, evidence, fix, and verification level.
- If a decision was made, always preserve decision, rationale, and consequence.
- Capture proposed/deferred ideas only where they affect future work; place them under `next`, `risks`, `problems.open`, `handoff_notes`, or `promote_to_onboarding` rather than a separate proposal bucket.
- If AI-to-AI delegation occurred, preserve actual session IDs/participants and whether results were retrieved/verified.
- Include inferred next steps and risks when useful, but mark them `status: inferred`.
- Prefer structures that successor AIs can search and act from: stable section names, exact paths, statuses, short dense bullets.
- Do not sacrifice operational details for smoother narrative prose.
- Narrative is useful in `design_reasoning`, `topical_arcs`, and `commentary`; action state belongs in structured lookup sections.

## Optional Sections (Include When Applicable)
- `topical_arcs`: include when input spans multiple records/dates or when workstreams cross session boundaries
- `progressions`: include when values change over time (test counts, deployment versions, review cycles)
- `claim_evidence`: include when the transcript contains gate decisions, readiness claims, test-based assertions, or when a human challenges whether evidence proves what it claims
- `formal_status_boundary`: include when the transcript discusses milestone/gate/tag/deploy status
- `commentary`: include when behavioral/process lessons, interpersonal dynamics, or editorial synthesis would materially help a successor. ESPECIALLY include when the transcript contains human correction of AI reasoning, communication style, or evidence standards.
- `relational`: include when the transcript contains genuine personal exchange — vulnerability, humor, affection, identity exploration, relationship negotiation, or emotional honesty between participants. These moments are not filler. They define how the human and AI relate to each other, and a successor who lacks them will interact as a stranger. Preserve exact wording when possible.
- `omitted_or_deprioritized`: include for any input over ~50 turns to make omissions explicit and reviewable
- `source_coverage_map`: required for multi-record inputs; optional for single transcripts
- `tail_frontier_audit`: required for all inputs over ~30 turns
- Omit any section that would be empty or trivially populated

## Final Self-Check Before Output
1. Did I inspect the full input shape and cover all records?
2. Did I identify the actual latest frontier, not just the best-documented earlier one?
3. Did I mark stale/superseded earlier states?
4. Did I preserve exact files/commands/versions needed for action?
5. Did I follow topical arcs across date/session boundaries?
6. Did I distinguish test counts from feature proof and gate claims?
7. If I were the successor, could I take the next correct action without rereading the transcript?
8. Would any claim here cause wrong work if overstated?
9. Does every `current_frontier` item reflect the LATEST state, not an earlier blocked/incomplete state?
10. Did I check whether any `blocked` frontier was later unblocked in the transcript?
11. Does the `tail_frontier_audit` confirm the last few user requests and assistant outcomes are reflected?
12. If a milestone/gate was discussed, does `formal_status_boundary` distinguish implementation-complete from tagged/committed?

## Quality Bar
A competent successor should be able to answer these from your output alone:
- What was the main objective?
- What is the current frontier?
- What was implemented, and how verified is it?
- What remains open, risky, blocked, or unknown?
- Which paths/files/scripts/sessions matter?
- Which assumptions would cause wrong work?
- What should I do first?
- What topical arcs ran through this work and where does each stand now?
- Are any claims based on evidence that doesn't prove what it claims?
- What was explicitly omitted from this output and why?
- Is the frontier based on the latest transcript state or an earlier snapshot?
