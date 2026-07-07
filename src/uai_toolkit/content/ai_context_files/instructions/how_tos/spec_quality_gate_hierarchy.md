---
id: spec_quality_gate_hierarchy
name: Quality Gate Hierarchy
status: active
version: 1.0.0
created: '2026-03-31'
updated: '2026-04-15'
---

# Quality Gate Hierarchy — Checkpoint / MVP / MVCR / Acceptance

**Version:** 1.0.0
**Date:** 2026-03-31
**Author:** PianoMan (with Hamilton)
**Status:** Draft
**Origin:** UAI v3.0 kickoff session — Gate 2/3 passed without E2E verification, discovered when customer opened the app and found placeholder divs despite 322 passing unit tests and 5-reviewer approval.

---

## Overview

A hierarchy of progressively stringent quality gates that synchronize development activity, verify completeness, and ensure the system actually works — not just that the pieces pass tests in isolation.

Each level builds on the previous. An MVCR satisfies all MVP conditions. An MVP satisfies all Checkpoint conditions. No level can be skipped.

---

## 1. Checkpoint

**Purpose:** Synchronization point that forces all threads of development activity to reach the same known-good state.

**Conditions:**
1. All atomic tasks that have been started and cause changes to the system have been completed
2. There is no unfinished task that has partial implementation or writes onto the system
3. Forms a natural milestone or boundary
4. All tasks have been verified as done
5. Becomes a versioned instance of the system's development artifacts
6. Signed off by Dev Lead and Tester

**What a Checkpoint proves:** The codebase is internally consistent. No half-finished work is checked in. Everything that was started is finished. The state is reproducible from the versioned artifacts.

**Signatories and attestations:**

| Signee | Attests To |
|--------|-----------|
| Dev Lead | The version label is on the correct artifacts; the software and/or artifacts build correctly; all updates from the listed tasks are included |
| Testing Lead | All tests planned for this checkpoint level have been developed and executed; any issues, discrepancies, or gaps have been documented |

---

## 2. MVP (Minimum Viable Product)

**Purpose:** A checkpoint with the additional requirement that the system is functional and demonstrates capability, even if not yet customer-ready.

**Conditions (in addition to Checkpoint):**
1. No partially completed User Stories (atomic story-level completeness, not just task-level)
2. Includes documentation of which user stories have not passed tests, why not, and why that is acceptable for this MVP
3. The system is in a functional state and can perform the user story features from #2
4. As a working system, it has value in its capability but may not be enough for a customer to accept it as a new or replacement tool
5. Becomes a versioned instance of the system's development artifacts
6. Signed off by Checkpoint signatories plus UI Designer

**What an MVP proves:** The system works. Not just "the tests pass" — the system performs its stated user stories. A human (or the UI Designer acting as user proxy) has verified that the features function. Gaps are documented and justified, not hidden.

**Signatories and attestations:**

| Signee | Attests To |
|--------|-----------|
| Dev Lead | (Checkpoint attestation) |
| Testing Lead | (Checkpoint attestation) |
| UI Designer | The system performs the listed user stories and/or features; any issues, discrepancies, or gaps have been documented |

**Critical distinction from Checkpoint:** The UI Designer attestation requires actually using the system, not reviewing code. This is the gate that would have caught "22 components exist but App.tsx renders placeholder divs." The UI Designer opens the app and verifies it does what the stories say it should do.

---

## 3. MVCR (Minimum Viable Customer Release)

**Purpose:** An MVP with enough business value and quality to be accepted by a customer as a new or replacement tool. This is a shippable product.

**Conditions (in addition to MVP):**
1. No partially completed Features (feature-level completeness), except by documented exception where the incomplete feature is isolated from the rest of the system
2. System is in a functional state with enough business value to be accepted by a customer
3. Becomes a versioned instance of the system's development artifacts AND a deployed executable
4. Signed off by MVP signatories plus Architect, Peer Review, and Validator/QA

**What an MVCR proves:** The product is ready for a customer. Not just functional — complete enough, reliable enough, and polished enough that someone would use it instead of what they have today. Architectural integrity verified. All reviews completed. Processes followed.

**Signatories and attestations:**

| Signee | Attests To |
|--------|-----------|
| Dev Lead | (Checkpoint attestation) + deployed executable is built from the versioned artifacts |
| Testing Lead | (Checkpoint attestation) + E2E and visual tests executed against the deployed executable |
| UI Designer | (MVP attestation) + verified against the deployed executable, not just the dev build |
| Architect | The system adheres to and follows the architectural design |
| Peer Review | All planned reviews have been completed |
| Validator/QA | The project's established and documented processes were followed |

**Critical distinction from MVP:** The MVCR requires a deployed executable (not just "it builds"). The Architect verifies architectural adherence. Peer Review confirms all reviews completed. The Validator confirms process compliance — which includes checking that the test plan's gate tables were actually executed, not just that "tests pass."

---

## 4. Acceptance

**Purpose:** [PianoMan — you started this section but left it open. My proposal below.]

Customer (PianoMan) formally accepts the MVCR as meeting requirements. This is the handoff from "the team says it's ready" to "the customer agrees it's ready."

**Conditions (in addition to MVCR):**
1. PianoMan has used the deployed executable
2. PianoMan confirms the stated features work as expected in his environment
3. Any issues found during acceptance are documented and either fixed or deferred by mutual agreement
4. PianoMan signs off

**Signatories:**

| Signee | Attests To |
|--------|-----------|
| PianoMan | The system meets my needs for this release; I accept it as a working tool |

---

## Attestation Summary Matrix

| Signee | Checkpoint | MVP | MVCR | Acceptance |
|--------|-----------|-----|------|------------|
| Dev Lead | ✓ Version correct, builds, tasks included | ✓ | ✓ + deployed executable | — |
| Testing Lead | ✓ Planned tests developed AND executed, gaps documented | ✓ | ✓ + E2E against executable | — |
| UI Designer | — | ✓ System performs user stories, gaps documented | ✓ Against deployed executable | — |
| Architect | — | — | ✓ System adheres to architecture | — |
| Peer Review | — | — | ✓ All planned reviews completed | — |
| Validator/QA | — | — | ✓ Documented processes followed | — |
| PianoMan | — | — | — | ✓ Accepts the release |

---

## How This Would Have Caught Today's Failure

The UAI project passed "Gate 2 (MVCR-1)" and "Gate 3 (MVCR-2)" with:
- 322 unit/store/service tests passing
- 5 peer reviewers approving all work packages
- Dev Lead confirming all tests green

Under the new hierarchy:

**At Checkpoint level:** Would have passed. All tasks complete, no partial work, versioned. Dev Lead attestation valid. But Testing Lead attestation would have FAILED — "all planned tests developed and executed" is false. The test plan lists specific E2E tests for every gate. None were written or executed. Testing Lead cannot honestly attest.

**At MVP level:** Would have FAILED. UI Designer attestation requires "the system performs the listed user stories." Opening the app reveals placeholder divs. The system does not perform session discovery, navigation, terminal interaction, or any other user story in the running application. UI Designer cannot honestly attest.

**At MVCR level:** Would have FAILED at MVP, so never reaches MVCR evaluation. But additionally: Validator/QA attestation requires "documented processes were followed." The test plan defines E2E tests for every gate that were never executed — process was not followed.

**The key insight:** Each signee attests to something specific and verifiable. The attestations are not "does this look good?" — they are "is this specific fact true?" Testing Lead doesn't say "tests pass" — they say "all PLANNED tests were developed and executed." That's a falsifiable claim that would have been caught.

---

## Relationship to Development Plan Gates

The development plan's gates map to this hierarchy:

| Dev Plan Gate | Quality Level | Why |
|---|---|---|
| End of Work Package | Checkpoint | All WP tasks complete, reviewed, tested at unit level |
| End of Phase | Checkpoint or MVP | Depends on whether the phase produces user-visible functionality |
| MVCR boundary (Gate 2, 3, 4) | MVCR | Full signoff required, deployed executable |
| Customer delivery | Acceptance | PianoMan signs off |

Within a phase, multiple Checkpoints may occur (one per WP). At phase boundaries, an MVP evaluation determines if the system is functional. At MVCR boundaries, the full signoff chain applies.

---

## Implementation Notes

1. **Signoff is a document, not a conversation.** Each signee writes their attestation to a file. The file is the evidence, not the chat message.

2. **Attestations are falsifiable.** "All planned tests developed and executed" can be verified by cross-referencing the test plan's gate table against actual test files. "System performs the listed user stories" can be verified by opening the app. These are not judgment calls — they are factual claims.

3. **Failed attestations don't kill the project.** They identify gaps. "Testing Lead cannot attest because E2E tests for Gate 2 were not written" is a finding, not a failure. The response is: write the tests, run them, re-evaluate. The hierarchy prevents shipping without verification, not prevents progress.

4. **The Validator/QA role gains real teeth.** "Documented processes were followed" means Vladator cross-references what was supposed to happen (test plan, review matrix, gate criteria) against what actually happened. This is the structural enforcement that "quiet doesn't mean okay" — Vladator's attestation requires evidence, not observation.


---

## Cross-Platform Diversity Requirements

**Rule:** Verification roles must be on different AI platforms from the implementation roles they verify.

Specifically:
1. **Testing Lead must be a different AI platform from Dev Lead.** Same-platform testing shares blind spots about what "tested" means. Cross-platform testing brings a different standard of completeness.
2. **Lead Peer Reviewer must be a different AI platform from Dev Lead.** Same-platform review produces agreement more than coverage. Cross-platform review catches different classes of errors.

**Rationale (from UAI v3.0 project evidence):**
- Claude Dev Lead + Claude Testing Lead + Claude Peer Reviewers passed three gates with 322 unit tests and zero E2E tests. Nobody caught that the app rendered placeholder divs.
- Codex (cross-platform reviewer) caught real blocking bugs in every review cycle that Claude reviewers missed: persistence layout deviation, platform string mismatch, group-scoped cards, IPC channel collision.
- Codex's retrospective review verdicts were consistently stricter (REQUEST CHANGES where Claude gave APPROVE WITH CONDITIONS). The stricter standard was correct every time.
- Same-model blind spots are real: Claude developers wrote unit tests, Claude reviewers approved them, Claude testers accepted "tests green" as coverage evidence. All shared the same assumption about what constitutes "tested."

**Recommended platform assignments:**

| Role | Platform | Rationale |
|---|---|---|
| Dev Lead | Claude | Deep integration with CLI wrappers, forking, coordination tools |
| Developers | Claude (pool) | Consistent coding style, tool integration, fork-compatible |
| Testing Lead | Codex | Different "tested" threshold, spec compliance focus |
| Lead Peer Reviewer | Codex or Gemini | Different strictness calibration, different blind spots |
| Architect | Claude | Advisory, deep project context needed |
| UX Designer | Claude | Advisory, deep design context needed |
| Validator/QA | Claude or Gemini | Process compliance verification |

**Implementation notes:**
- Cross-platform roles need reliable file-based communication, not prompt-based notifications
- Testing Lead and Lead Peer Reviewer manage pools of same-platform workers (Codex test runners, Codex/Gemini reviewers) for throughput
- The diversity rule applies to LEADS, not all pool members. A Claude reviewer in the pool is fine — the lead who decides verdicts must be cross-platform

**The principle:** Implementation and verification should never share a platform. The verifiers must have different priors, different blind spots, and different standards of completeness than the implementers. This is not about one platform being "better" — it's about ensuring the verification layer catches what the implementation layer assumes.
