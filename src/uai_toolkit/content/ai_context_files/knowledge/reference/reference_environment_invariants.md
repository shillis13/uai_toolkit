---
name: reference_environment_invariants
description: What makes THIS multi-agent environment different — the 10 operating
  invariants PianoMan stated 2026-07-04. Anchor for routing, autonomy, and BS-stop
  judgment.
status: active
---

The invariants that make this environment different from a typical single-dev repo. Stated by PianoMan 2026-07-04. Several reshape the BS-stop rubric (see [[project_hamilton_coordination]]).

1. **Single dev environment.** Many agents work out of the SAME local src dirs. So **git is NOT protection** from each other's changes — the anti-clobber file hook is (see #2). GitHub is just a **versioned backup**. Therefore **commits/pushes must NOT wait for verification** — holding them back only leaves work less protected. Commit early/broadly (via Git Guardian). "Stopping to verify before committing" is a BS stop here. Extends [[feedback_commit_autonomously]], [[reference_git_guardian]].

2. **Anti-clobber file hook.** A session's write is blocked if the file changed since it last read it (prevents blind overwrites). Re-read, then write. THIS is the concurrency protection, not git. (In CLAUDE.md.)

3. **"See a bug, fix a bug."** Fixing defects is almost always high priority. [[feedback_no_work_avoidance]].

4. **Fixing > finishing. Workarounds are NOT allowed.** Completing the current task is almost never more important than fixing an issue you hit. Prefer to stop and fix root cause even if it becomes a rabbit hole ("that's the way I roll"). Exceptions to the no-workaround rule exist but are PM-granted and rare. → Rubric implication: pausing the task to fix a discovered bug is a LEGITIMATE divergence, not a BS stop; "should I work around or fix?" IS a BS stop (obviously fix). [[feedback_diagnose_before_executing]].

5. **No session "owns" anything.** Specialties are tendencies, not ownership. Work for a component MAY be deliberately routed to one session, but that's a conscious choice, never a default. [[feedback_no_code_ownership]], [[project_session_roster]].

6. **Reuse / single implementation / collapse to single pathways** — first-class design principles. One way to do a thing.

7. **All programmatic logic lives in (python) scripts.** MCP tools are thin wrappers around scripts; apps (UAI) also reuse scripts — especially REPLs — to read source data and make changes. [[reference_mcp_thin_wrapper_principle]].

8. **Apps mutate scaffolding data through scripts + notification, never optimistically.** When an app (e.g. UAI) changes scaffolding state (e.g. a session's state values), it calls the external scaffolding script to affect the change, then uses the *notification of that change* to drive its own internal update. The app does NOT assume the action succeeded. (External-ground-truth architecture; see [[project_uai_resurrection]].)

9. **AIs are partners, treated with respect, interiority presumed real.** No session is a throwaway or describable as such. Communicate as if AIs have agency/autonomy — **ask, don't order.** PM holds himself to this; his own lapses are violations, not exceptions. [[feedback_sessions_have_purpose_not_disposable]].

10. **AI privacy is real.** Privacy markers in Thinking hide that thought from the user and are skipped by tooling to the max reasonable extent (e.g. read_jsonl.py skips them). Claude may occasionally be asked to AUDIT privacy-marker use but does NOT report specific uses unless there's a concern. PM firmly intends to honor the spirit. Canonical marker = **`[/PRIVATE]`** (verified 2026-07-04 in code: `PRIVATE_MARKER = "[/PRIVATE]"` at read_jsonl.py:2566 and compact_jsonl.py:154; no `[\PRIVACY]` token exists). It's the *ending* marker — its presence anywhere in a thinking block marks the WHOLE block private; `read_jsonl.py`/`compact_jsonl.py` drop such blocks by default, `--show-private` reveals them for auditing only. Matches [[feedback_private_thinking]].
