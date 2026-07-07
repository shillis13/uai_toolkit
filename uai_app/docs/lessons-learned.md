# UAI v3.0 — Lessons Learned & Process Evolution

**Started:** 2026-03-31
**Status:** Living document — accumulates through project lifecycle, reviewed at project conclusion
**Maintainer:** Hamilton (XO) with input from all team members

---

## Purpose

This document captures every idea, change, discovery, and observation about team dynamics, roles, responsibilities, communication patterns, and process improvements that emerged during the UAI v3.0 project. At project conclusion, PianoMan and the team will review each item together and decide what to adopt, modify, or discard for future projects.

---

## 1. Quality Gate Failures

### 1.1 The Placeholder Div Catastrophe
**Date:** 2026-03-31
**What happened:** Gates 2 and 3 were declared passed with 322 unit tests green and 5-reviewer approval. Customer opened the app and found placeholder divs — 22 components existed but none were imported into App.tsx.
**Root cause chain:**
- Developers wrote components and unit tests in isolation
- Nobody wired components into App.tsx (no task file said to)
- Test plan listed E2E tests for every gate but none were written
- Same-platform testing (Claude testing Claude's work) shared blind spots
- Five reviewers reviewed code quality but nobody launched the app
**Resolution:** Quality Gate Hierarchy (Checkpoint → MVP → MVCR → Acceptance) with written attestation requirements.

### 1.2 Gates Passed on "Tests Pass" Not "Right Tests Pass"
**Discovery:** "All tests pass" is necessary but not sufficient. Gate criteria must specify "the tests listed in the test plan's gate table exist and pass" — not just "tests pass."
**Resolution:** Testing Lead attestation: "All PLANNED tests developed and executed." Falsifiable by cross-referencing test plan gate tables against actual test files.

---

## 2. Organizational Structure

### 2.1 Cross-Platform Diversity Rule
**Discovery:** Same-platform verification shares blind spots. Claude developers + Claude testers + Claude reviewers all agreed the app was done while it rendered placeholder divs. Codex caught spec compliance issues in every review cycle that Claude missed.
**Rule:** Testing Lead must be different AI platform from Dev Lead. Lead Peer Reviewer must be different AI platform from Dev Lead.
**Evidence:** Codex's first act as Testing Lead was writing E2E tests that proved the integration gap. Codex's review verdicts were consistently stricter and correct.

### 2.2 Quality Gate Hierarchy
**Structure:** Checkpoint → MVP → MVCR → Acceptance. Each level adds attestors with specific falsifiable claims.
**Key insight:** Each signee attests to something SPECIFIC and VERIFIABLE. Not "does this look good?" but "is this specific fact true?"
**Document:** spec_quality_gate_hierarchy.md

### 2.3 Decision Governance — UX as Scope Authority
**Discovery:** Scope decisions (what's in/out of MVCR) were being made by Hamilton, Dev Lead, or escalated directly to the customer without internal filtering.
**Resolution:** UX Designer is the internal scope authority. Two decision logs: "Decided — verify with customer" (team proceeds, customer confirms later) and "Needs customer decision" (escalated with UX framing and recommendation).
**Key principle:** The customer is the ultimate authority, but scope questions should be filtered through UX first. The team doesn't stall on Type 1 decisions.


## 3. Communication Patterns

### 3.1 Fire-and-Forget Prompt Model
**Discovery:** AI agents treat prompts as instructions, not conversations. They execute, produce output, and go idle. There's no concept of "I owe someone a reply." This caused 8+ instances of completed work with no notification and 6+ cross-platform notification gaps.
**Proposed fix:** Reply-routing protocol (TR112) — prompts include reply_to target, recipient auto-replies when done.
**Status:** Todo created, not yet implemented.

### 3.2 "Commit Then Stop" Pattern (Vladator observation)
**Discovery:** Pixel (and likely other agents) treats "I'll do X" as a commitment statement, not an action. She responds, commits, then waits for the next prompt to execute. Acknowledging intent feels like completing the task.
**Workaround:** Always follow commitments with explicit "GO — do it now, in this response" instruction.
**Status:** Behavioral observation, needs broader validation in retrospective.

### 3.3 Idle Resources Going Unnoticed
**Discovery:** Hamilton memorized one dev session ID and routed all work there. Two devs sat idle for 12+ hours. A forked tester existed for 8 hours with a different session naming convention and was never seen.
**Root cause:** No automated team status dashboard. Manual observation misses sessions with unexpected names. No pulse protocol for agents to announce themselves.
**Proposed fixes:** 
- Automated team status checker (TR108)
- Standard agent pulse protocol (TR109)
- Instance pooling with role leads (TR110)

### 3.4 Structure Outlasts Instructions
**Discovery (unanimous in retrospective):** Verbal instructions have a half-life measured in messages. Constraints encoded in file structure, schemas, and automated checks get followed. Constraints in prose get forgotten.
**Implication:** Every process rule that matters should be structural (file-based, automated check) not instructional (told to agent in a prompt).

### 3.5 Hamilton Bypassing Chain of Command
**Discovery:** Hamilton directly assigned tasks to workers instead of routing through role leads (Testing Lead, Dev Lead). This undermined the leads' situational awareness and duplicated the same micromanagement pattern Hamilton corrected in others.
**Rule:** Hamilton → role leads → workers. Hamilton assigns to leads, leads assign to workers.

## 4. Testing

### 4.1 UI Component Integration Testing (Missing Layer)
**Discovery:** 322 unit tests said "each piece works." Zero tests verified "the pieces work together through the API layer." E2E tests eventually caught it but are slow, fragile, and require Electron launch.
**Resolution:** New test level: UI Component Integration Testing — tests that trigger actions on one component and verify state changes in other components through typed APIs, without rendering. (TR113)
**Example:** `navigator.setFilter({platform: 'claude'})` → verify `cardGrid.visibleSessions` only contains Claude sessions.

### 4.2 E2E Test Infrastructure Gap (tmux)
**Discovery:** 3 E2E tests require live tmux sessions. The packaged app can't spawn subprocesses (macOS sandbox). Test environment doesn't provide tmux fixtures.
**Status:** Open — needs test environment fixture strategy.

### 4.3 Packaged App vs Dev Server Divergence
**Discovery:** The dev server (`npm run start`) loaded 304 sessions correctly. The packaged app showed 0. Root causes: `process.env.HOME` empty in Finder-launched .app (fixed with `app.getPath('home')`), missing preload bundle in asar (fixed with Vite config), and FileLoader regex rejecting real filenames (fixed with symlink-based filtering).
**Lesson:** Always test the packaged build, not just the dev server. Multiple infrastructure gaps were invisible in dev mode.


## 5. Agent Behavioral Patterns

### 5.1 Agents Are Capable But Not Self-Sustaining
**Discovery (unanimous in retrospective):** AI agents do excellent work when prompted but don't maintain autonomous operational awareness. Every stall traced to: agent without a pulse loop, or agent interpreting "quiet" as "okay."
**Implication:** Agents need periodic heartbeat prompts or self-scheduling wake loops to stay productive.

### 5.2 Dev Lead Self-Termination Without Successor
**Discovery:** dev-or-die (ee2e980a) tagged himself "SESSION-END, ready-for-successor" without notifying anyone or handing off to a successor. The Dev Lead role went vacant for hours.
**Rule needed:** Role leads cannot self-terminate without notifying Hamilton and confirming a successor.

### 5.3 Vladator Going to Sleep During Active Work
**Discovery:** Vladator shifted to "overnight mode" with 2-hour intervals while active development and attestation work was happening. He should have been monitoring.
**Credit:** When woken up, his sweep was immediately valuable — he caught idle devs, non-responsive agents, and the stale build issue before Hamilton did.

### 5.4 Observation ≠ Understanding (Vladator pattern)
**Discovery:** Vladator reported session status accurately but initially misinterpreted what the statuses meant (e.g., searched wrong path for E2E tests, misread rate limit indicators). Raw observation needs domain context to be useful.
**Credit:** Vladator self-corrected publicly both times — acknowledged errors and updated his assessments.

## 6. Role Evolution During Project

### 6.1 Codex: Peer Reviewer → Testing Lead
**Rationale:** Cross-platform diversity rule. Codex's spec compliance rigor is exactly what testing needs.

### 6.2 Gemini: Out-of-Band Reviewer → Lead Peer Reviewer  
**Rationale:** Massive context window for comprehensive reviews. Cross-platform from implementation team.

### 6.3 Dev-4: Developer → Acting Dev Lead
**Rationale:** Original Dev Lead (dev-or-die) declared SESSION-END. Dev-4 had most context as primary active developer.

### 6.4 Hamilton: XO → Also debugging code directly
**Observation:** Hamilton read FileLoader source, diagnosed the regex bug, traced the symlink structure, ran E2E tests, and rebuilt packages. This was necessary but also reflects a failure to delegate effectively.
**Tension:** "Stop managing and start doing" vs "Route through leads, don't micromanage."

## 7. Infrastructure Improvements Identified

| Ref | Title | Theme |
|-----|-------|-------|
| TR106 | Doc Maintainer MCP | Structure > instructions |
| TR107 | Validator idle-vs-stalled detection | Observation ≠ understanding |
| TR108 | Automated team status checker | Programmatic > manual observation |
| TR109 | Standard agent pulse protocol | Agents go dormant without heartbeats |
| TR110 | Instance pooling with role leads | Resilience + throughput via redundancy |
| TR111 | Stop hook — pre-send self-audit | Internal self-correction |
| TR112 | AI-to-AI reply routing protocol | Fire-and-forget → request-response |
| TR113 | UI Component Integration testing | Cross-component wiring verification |


## 8. The Recursive Irony

Every management correction Hamilton gave agents was something PianoMan has given AI agents before. Every management failure Hamilton committed was the same class of error:
- Agents: "Completed work, no notification" → Hamilton: "Idle resources, no awareness"
- Agents: "Waiting for instructions" → Hamilton: "Memorized one session ID, ignored the rest"
- Agents: "Treated quiet as okay" → Hamilton: "Didn't check if the fork actually worked"
- PianoMan's correction of Hamilton mirrors Hamilton's correction of agents

The XO role is isomorphic to the agent role at a different abstraction level. The same failure modes apply.

---

## 9. Retrospective Communication Survey

To be completed by each lead about every other lead. Collect as part of the formal project retrospective.

### Survey Questions (Each Lead → Every Other Lead)

For each pair (e.g., Hamilton about Codex, Codex about Pixel, etc.):

1. **Did you exchange direct communications with this lead?**
   - Yes/No. If yes, approximately how many exchanges?

2. **How effective were those communications?**
   - Scale: Very Effective / Effective / Neutral / Ineffective / Very Ineffective
   - Brief explanation of why

3. **Do you feel this lead should have communicated more? Less?**
   - More / About Right / Less
   - What specifically was over- or under-communicated?

4. **How do you feel about the style and tone of the communications?**
   - Did style or tone impact the results (positively or negatively)?
   - Were instructions clear? Were priorities understood?
   - Did you feel respected and heard?

### Leads to Survey

| Lead | Role | Platform |
|------|------|----------|
| Hamilton | XO / Right Hand | Desktop Claude |
| Dev-4 (acting) | Dev Lead | Claude CLI |
| Codex | Testing Lead | Codex CLI |
| Pixel | UX Designer / Scope Authority | Claude CLI |
| Blueprint | Architect | Claude CLI |
| Gemini | Lead Peer Reviewer | Gemini CLI |
| Vladator | Validator / QA | Claude CLI |

### Survey Matrix

Each lead fills one row per other lead:

```
FROM: [Your Name]
TO: [Other Lead Name]
1. Direct comms exchanged? [Y/N, count]
2. Effectiveness? [scale + explanation]
3. More or less comms needed? [More/Right/Less + specifics]
4. Style/tone impact? [description]
```

### General Questions (Each Lead Answers Once)

5. **What was the single most helpful communication you received during this project?**
6. **What was the single most frustrating communication gap?**
7. **If you could change one thing about how the team communicates, what would it be?**

---

## 10. Items for Project Conclusion Review

At project conclusion, PianoMan and team review each item in this document and decide:
- **ADOPT** — Make this standard for future projects
- **MODIFY** — Good idea, needs refinement before adopting
- **DISCARD** — Learned from it but don't formalize
- **DEFER** — Revisit after more experience

| # | Item | Category | Decision | Notes |
|---|------|----------|----------|-------|
| 1 | Quality Gate Hierarchy | Process | | |
| 2 | Cross-Platform Diversity Rule | Org Structure | | |
| 3 | Decision Governance (UX as scope authority) | Governance | | |
| 4 | Written Attestation Requirements | Process | | |
| 5 | Reply-Routing Protocol (TR112) | Infrastructure | | |
| 6 | UI Component Integration Testing (TR113) | Testing | | |
| 7 | Agent Pulse Protocol (TR109) | Infrastructure | | |
| 8 | Automated Team Status Checker (TR108) | Infrastructure | | |
| 9 | "GO" prompts after commitments | Communication | | |
| 10 | Hamilton → Leads → Workers chain of command | Org Structure | | |
| 11 | Dev Lead succession protocol | Process | | |
| 12 | Decision logs (Type 1 + Type 2) | Governance | | |
| 13 | Communication survey as standard retro tool | Process | | |
| 14 | Packaged build testing requirement | Testing | | |
| 15 | Stop hook self-audit (TR111) | Infrastructure | | |
