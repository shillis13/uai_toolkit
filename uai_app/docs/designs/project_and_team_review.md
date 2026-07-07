# Review: Project and Team Object Design

**Date:** 2026-05-13  
**Reviewer:** Codex (for Solstice)  
**Source reviewed:** `project_and_team_objects.md`, `architecture/contracts/entities.ts`, `architecture/contracts/cards.ts`, `protocol_comms_v1.0.md`

## Verdict

**Not implementation-ready as written.**

The overall direction is reasonable — especially making project metadata optional and treating teams as coordination primitives rather than UI containers — but the current design has several structural problems that will cause runtime drift, broken targeting, and contract churn if implemented directly.

The biggest issues are:
1. **The design conflicts with existing Project/Team contracts.**
2. **It declares filesystem truth, then duplicates the same truth in SQLite relationships and session state.**
3. **It puts live runtime slot occupancy into shared YAML without a concurrency model.**
4. **Its comms integration does not actually hook into protocol_comms_v1.0's real routing model.**

If you build this as-is, you will spend more time reconciling divergence than using the feature.

---

## What is good

Briefly:
- **Project metadata being optional is good.** Indexing a project even when `project.yml` is absent is pragmatic.
- **Teams not being folders/groups/projects is the right separation.** Treating them as coordination objects rather than card containers is correct.
- **Using relationships for cross-entity links is directionally right.** The problem is not the existence of relationships; it is the current duplication and ambiguity around authority.

That is the good part. The rest needs tightening.

---

## 1. Consistency with existing contracts

## 1.1 Project `status` conflicts with the existing Project contract

This is the most immediate contract bug.

In the design, `project.yml` has:
- `status: active | paused | complete | archived`

In `entities.ts` and `cards.ts`, `Project.status` / `ProjectCard.status` already means:
- `clean | dirty | ahead | behind | unknown`

Those are not the same concept. One is **lifecycle state**; the other is **git/worktree state**.

If implemented directly, you will either:
- break the TypeScript contract,
- overload one field with two meanings, or
- silently drop one of the states.

**Recommendation:** split this now into two separate fields:
- `lifecycle_status`: `active | paused | complete | archived`
- `git_status`: `clean | dirty | ahead | behind | unknown`

Do not reuse `status` for both.

## 1.2 The Project contract is materially out of sync with the design

Current `Project` contract includes:
- `assigned_ais: string[]`
- `content_hash`
- `parse_error`
- `availability`
- `indexed_at`

The design instead introduces:
- `assigned.sessions`
- `assigned.teams`
- `related.*`
- `config.*`
- derived `session_count`
- derived `git_status`

This is not a small additive change. It is a different model.

Also: `ProjectCard` has no `goal` field, yet the design clearly expects goal/summary-driven project cards.

**Recommendation:** update the public contract before implementation. Do not let indexers invent fields that the renderer contract does not actually support.

## 1.3 The Team contract is even further out of sync than Project

Existing `Team` contract expects:
- `profiles: TeamProfile[]`
- `role_assignments: Record<string, string>`
- `comms_plan: CommsPlan`

The design instead defines:
- `description`
- `status`
- `slots[]`
- `projects[]`
- `created_at`
- `created_by`
- mutable `filled_by`
- runtime `standing_messages`

These are not equivalent models. `slots[]` is not a drop-in replacement for `profiles[] + role_assignments`.

There is also a type mismatch: the design uses `platform: any`, while the current contract expects `Platform`.

**Recommendation:** decide whether Team is:
- a profile-based static roster model, or
- a slot/lease-based runtime staffing model.

Right now it is neither cleanly.

## 1.4 `cards.ts` has no TeamCard at all

The design says UAI will display TeamCards in the navigator.

But `cards.ts` only defines:
- `SessionCard`
- `BriefCard`
- `FolderCard`
- `GroupCard`
- `ProjectCard`

There is **no `TeamCard`** and `AnyCard` does not include teams.

That means the design already assumes a renderer contract that does not exist.

**Recommendation:** add a proper TeamCard contract before talking about UAI rendering team cards. Otherwise the design is ahead of the architecture it claims to fit.

---

## 2. Filesystem-as-truth viability

## 2.1 `filled_by` in shared YAML is not safe runtime state

This is the biggest implementation-risk item in the doc.

You are proposing that multiple actors can write live team occupancy into:
- `ai_general/data/teams/{id}.yml`

That is unsafe unless you define:
- write locking,
- compare-and-swap semantics,
- stale lease cleanup,
- conflict resolution,
- recovery after partial failure.

None of that is present.

### Failure mode examples

- **Lost update:** two sessions read the same YAML, each add themselves to `filled_by`, last write wins.
- **Double fill:** two sessions claim the same slot simultaneously because both observed it empty.
- **Stale occupancy:** a session crashes or gets killed mid-task, remains in `filled_by` forever.
- **Partial write split-brain:** YAML updated but relationship row not written, or vice versa.
- **Human/editor overwrite:** someone edits team config and accidentally wipes live runtime occupancy.

This is exactly the kind of state that belongs in a transactional store or lease directory, not in a canonical config file.

**Recommendation:** keep team YAML declarative only. Move live slot occupancy to one of:
- SQLite with atomic updates,
- one-file-per-slot lease records,
- append-only claim/release journal with reconciler.

Do **not** make a shared YAML document the live coordination lock table.

## 2.2 The design mixes configuration and runtime state in one file

The doc explicitly says the team YAML is both:
- configuration (`slots`, `comms`, `projects`)
- runtime state (`filled_by`, `standing_messages`)

That is a design smell.

Config changes are infrequent and reviewable. Runtime staffing state is hot, noisy, and failure-prone.
They should not share the same mutation path.

**Recommendation:** separate:
- `teams/{id}.yml` → declarative team definition
- `team_runtime/{id}.json` or SQLite rows → occupancy / runtime / leases

## 2.3 Project assignment is duplicated across too many stores

For projects, assignment can now appear in all of these places:
- session `project_dir`
- `project.yml` `assigned.sessions`
- `project.yml` `assigned.teams`
- `team.yml` `projects`
- `entity_relationships` (`assigned_to`)

That is not filesystem truth. That is **multi-source truth**.

And multi-source truth means reconciliation bugs.

**Recommendation:** pick one authoritative source per concept:
- **implicit project membership:** session `project_dir`
- **explicit project assignment:** relationship row
- **project.yml / team.yml:** optional seed metadata only, not live assignment state

If YAML remains editable, treat it as import/bootstrap, not as live runtime authority.

---

## 3. Comms integration

## 3.1 The design does not actually connect to protocol_comms_v1.0's routing model

The protocol's real routing primitives are:
- direct session targeting,
- group targeting,
- board subscription/discovery,
- prompt queues,
- standing-message scopes,
- session `groups[]` membership.

Your design talks about team comms, but the actual binding is missing.

### The key gap

`protocol_comms_v1.0` says group-targeted broadcast and board access are governed by a session's **`groups[]` array**.

Your design says team membership is represented by:
- `filled_by`, and/or
- `entity_relationships.member_of`

But it never says who writes the session's `groups[]` membership when a slot is filled.

So as written:
- the session may be `member_of` a team in SQLite,
- but comms broadcast to that team still will not reach it.

That is a hard integration gap, not a documentation gap.

**Recommendation:** define the exact binding:
- assigning a session to a team must also update the session's effective comms group membership,
- or the comms layer must be changed to resolve recipients from relationships instead of `groups[]`.

Without that, targeted team broadcast is aspirational only.

## 3.2 `standing_messages` in team YAML conflicts with the protocol

The protocol says standing messages are:
- **pull-based**, and
- stored in **scoped directories** for global/team/platform/project scope.

Your design puts:
- `standing_messages: []` inside the team YAML
- and says it is populated at runtime.

That does not mesh with the protocol. It creates a second standing-message storage model.

**Recommendation:** remove runtime `standing_messages` from team YAML. Team standing messages should live wherever the comms protocol says team-scoped standing messages live.

## 3.3 `board: team` is too underspecified to implement cleanly

The protocol has:
- board **type** (`comms`, `todos`, `tasks`)
- board **scope** (`global`, `team`, `project`, `individual`)
- discovery rules

The design gives:
- `board: team`

That is not enough. It is missing at least:
- board type,
- board identifier/naming convention,
- whether there is one board or several per team,
- whether the board is canonical or derived.

**Recommendation:** specify an actual comms URI or structured reference, e.g.
- `boards: [{type: comms, scope: team, id: uai-core}]`

## 3.4 Escalation is underspecified when slots are empty or multi-filled

`escalation_chain: [lead, user]` assumes:
- `lead` resolves to exactly one active session,
- that session is reachable,
- and the slot is filled.

What if:
- the lead slot is empty?
- the lead slot has two filled sessions because `count > 1`?
- the lead session is stopped but still listed in `filled_by`?

The design gives no resolution rules.

**Recommendation:** define fallback semantics explicitly:
- empty slot → skip to next escalation target
- multi-filled slot → broadcast to all or choose oldest/newest/primary
- stopped session → treat as unavailable, do not deliver

---

## 4. Project metadata

## 4.1 `project.yml` is mixing identity metadata with tool-execution config

These do not belong at the same abstraction level:
- `name`, `goal`, `tags`, `status`
- `build_command`, `test_command`, `start_command`

The first group describes the project entity.
The second group describes how a particular tool should operate against that directory.

Those commands will drift. They are also environment-sensitive, shell-sensitive, and often already represented elsewhere (`package.json`, `Makefile`, task runners, CI config).

If you put them in `project.yml`, UAI will start relying on a second, potentially stale source of build/test truth.

**Recommendation:** either:
- move this to a separate automation/tooling manifest, or
- very clearly namespace it as non-authoritative optional tooling hints.

But do not make it core project identity.

## 4.2 `project.yml` is still missing lifecycle/ownership metadata if it is meant to be canonical

If `project.yml` is truly a canonical object file, it is light in some wrong places:
- no owner / steward
- no archived_at / archived_by
- no repo identifier / primary repo if project spans multiple repos
- no schema version

That is less urgent than the concurrency issues, but it matters if this becomes a durable system.

---

## 5. Relationship model

## 5.1 The design has redundant links in both YAML and relationships

The following overlaps exist:
- `project.yml.assigned.teams`
- `team.yml.projects`
- `team -> assigned_to -> project`

And separately:
- session `project_dir`
- `project.yml.assigned.sessions`
- `session -> assigned_to -> project`

This is too much.

Every additional copy multiplies divergence states.

**Recommendation:** one of these must become non-authoritative.
A clean version would be:
- YAML = optional declarative hints / seed config
- relationships = authoritative explicit bindings
- `project_dir` = authoritative implicit binding

Right now the doc says "filesystem is the source of truth" but then treats relationships as authoritative in places. That contradiction must be resolved.

## 5.2 `member_of` with `{slot: ...}` metadata is workable, but incomplete for runtime staffing

Using:
- `session -> member_of -> team`
- metadata `{slot: "lead"}`

is fine as a representation of membership.

It is **not enough** for runtime staffing unless you also model:
- claimed_at
- claimed_by / assigned_by
- lease expiry or heartbeat
- status (`active`, `stale`, `releasing`, `reassigned`)

Without those, you cannot safely recover from crashes or stale occupancy.

---

## 6. Slot model

## 6.1 The slot abstraction is reasonable; the current runtime mechanics are not

The idea of slots is good for:
- "I need one lead, N implementers, one reviewer"

That abstraction is not the problem.

The problem is attaching runtime occupancy directly to the team YAML and assuming that is enough.

## 6.2 Crash recovery is not addressed

The design says on session exit:
1. remove from `filled_by`
2. delete relationship row
3. free the slot

That is a happy-path cleanup story, not a crash model.

What if the session:
- segfaults,
- loses the terminal substrate,
- is force-killed,
- is resumed under a new identity edge case,
- or the cleanup process fails halfway?

You need a **reconciler** or **lease timeout**, not just an on-exit narrative.

## 6.3 Reassignment semantics are not defined

There is no defined flow for:
- replacing a dead member,
- handing off a slot intentionally,
- temporarily shadowing a slot,
- keeping audit history of slot occupancy.

At minimum you need to decide whether slot assignment is:
- an overwrite,
- a lease transfer,
- or an append-to-history with one active assignee.

## 6.4 Temporary scale-up is awkward in this model

The design uses both:
- explicit slot IDs (`worker_1`, `worker_2`)
- and `count`

That is an uneasy mix.

If `count` exists, why are worker slots individually enumerated?
If worker slots are individually enumerated, why is `count` the cardinality field?

For temporary scale-up, this becomes messy fast.

**Recommendation:** choose one model:
- semantic slot with cardinality (`worker`, count=3), or
- individually named slots (`worker_1`, `worker_2`, `worker_3`)

Do not mix both unless you have a very specific reason.

---

## 7. Missing concerns

## 7.1 No migration plan from current reality

Current reality is:
- no `project.yml` in most places,
- no `ai_general/data/teams/` ecosystem in use,
- existing contracts use a different Team model,
- UAI cards do not support TeamCards.

The doc needs a migration section covering:
- contract changes first,
- indexer introduction order,
- backfill strategy for existing projects,
- what happens when a directory has no metadata file,
- whether legacy `assigned_ais` is deprecated or mapped.

## 7.2 No repair strategy when sources diverge

Given the current design, divergence is guaranteed eventually.
There is no stated repair strategy for cases like:
- YAML says session fills slot, relationship row missing
- relationship row exists, YAML missing session
- project lists assigned team, team does not list project
- session `project_dir` implies one project, explicit assignment points elsewhere

You need either:
- a strict single-writer model, or
- a reconciliation policy.

Right now there is neither.

## 7.3 Project ID derivation is collision-prone

The proposed derived ID:
- `devtree_{dirname}` or `project_{dirname}`

is not stable enough.

Problems:
- two different directories can share the same basename,
- renaming a directory changes the project ID,
- moving a project between roots changes identity semantics.

**Recommendation:** derive IDs from a stable normalized path slug or explicit declared ID, not just basename.

## 7.4 Authority to mutate shared YAML is undefined

The doc says UAI, Hamilton, launchers, CLI tools, and others can all read/write the same YAML.

That is not a harmless convenience. That is an authority model, and it currently has no guardrails.

Questions the design does not answer:
- Who is allowed to claim/release slots?
- Can any session rewrite team membership?
- Can a reviewer session disband a team?
- Does the user approval requirement apply to slot creation/removal?

Without an authority model, this will become accidental shared-state corruption.

---

## Recommended changes before implementation

## 1. Fix the contracts first

Before indexers or UI work:
- split project lifecycle status from git status
- decide the real Team contract
- add TeamCard if teams are renderable cards
- align `Project`, `ProjectCard`, `Team`, and `AnyCard`

## 2. Keep YAML declarative; move runtime occupancy elsewhere

Use team YAML for:
- slot definitions
- role descriptions
- comms defaults
- project associations if you keep them

Do **not** use it for:
- live `filled_by`
- runtime standing messages
- hot assignment churn

## 3. Choose one authoritative source per link type

Suggested split:
- `session.project_dir` → implicit project membership
- `entity_relationships` → explicit assignment / membership
- YAML → optional declarative seed / metadata only

## 4. Bind teams to the comms protocol explicitly

You must define how team membership updates:
- session `groups[]`
- board subscriptions / discovery
- standing-message scope membership

Until that exists, "team comms integration" is incomplete.

## 5. Move automation commands out of the core project object

If build/test/start commands are needed, place them in:
- a separate tooling manifest, or
- a clearly non-authoritative `tooling` namespace

Do not let the core project entity become a stale command registry.

---

## Bottom line

The design has the right instinct — **projects as filesystem-indexed entities, teams as coordination objects** — but it currently collapses:
- identity,
- runtime staffing,
- comms scoping,
- and automation config

into overlapping stores with no concurrency story and no single authority boundary.

That will hurt.

If you want this to be robust, the next revision should do three things:
1. **synchronize the public contracts with the proposed model**,
2. **separate declarative YAML from live runtime occupancy**, and
3. **define exactly how team membership enters the comms protocol's actual routing system**.

Until those are resolved, I would not implement this beyond prototypes.
