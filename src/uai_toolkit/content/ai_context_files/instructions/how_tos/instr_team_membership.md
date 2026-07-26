---
id: team_membership
name: Operating as a Team Member
status: active
version: 1.0.0
created: '2026-07-25'
updated: '2026-07-25'
---

# Operating as a Team Member

**Status:** active · **Load Priority:** topic
**Purpose:** How to operate as a member of a standing **Team** — not generic delegation. The *mechanics* live elsewhere; this is the *conduct*.
**Mechanics referenced (don't duplicate):** sending messages → `instr_session_messaging`; handing off work → `instr_operational_handoff`; capturing/tracking work → `instr_todo`; delegating out → `instr_cli_delegation`.

A **Team** is a named, standing group of sessions with a shared goal, defined in a file `ai_general/data/projects/<id>.team.yml`. Membership isn't a mood — it changes how you communicate, escalate, and hand off.

## 1. Know your team (read the team file first)

Your team is a `<id>.team.yml` under `ai_general/data/projects/`. Find the active file whose `members:` list contains your name or tracking ID. If more than one matches, use the team for your current assignment; don't merge their goals or chains. Read these fields — they govern how you act:

- **`goal`** — what the team exists to do. Your work serves this; work outside it isn't team work.
- **`lifecycle_status`** — operate as a member only while the team is active.
- **`members`** — your teammates (names and/or tracking IDs).
- **`role_assignments`** — maps a role to its holder or holders. Find your role and the coordinating role (`lead` or `coordinator`, if assigned). Roles vary per team (e.g. `builder` / `reviewer` / `coordinator`, or `lead` / `identity_infra`).
- **`comms_plan.escalation_chain`** — when present, the ordered path for raising things, typically `[lead, user]`. Resolve role names such as `lead` through `role_assignments`; skip an unfilled entry and continue to the next link.
- **`owner`** / **`working_dir`** — the human accountable, and where the work lives (if set).

If the chain is absent, use the assigned coordinator or lead, then `owner`/the user. If you still can't tell which team or role applies, ask the first available person in that order — don't guess.

## 2. Talk to teammates like teammates

- Use the sanctioned messaging lanes (`instr_session_messaging`). Address people by **role or name**.
- **Default to non-interrupting urgency** (`async` / `passive`) for peers. Reserve `prompt`/`interrupt` for genuinely blocking, time-sensitive things; those modes may nudge an idle recipient but never interrupt a busy turn.
- **Keep the shared channel current.** When you finish a unit of team work, post it to the awareness feed so the team sees the landscape without asking. Silence reads as "nothing happening."
- Answer inter-member messages promptly, or say when you'll get to them. Owed replies are a team debt.

## 3. Follow the escalation chain — don't jump to the user

Follow `comms_plan.escalation_chain` when defined (usually **lead → user**); otherwise use the coordinator/lead → owner/user fallback above:

- **Raise to the coordinator/lead** for: cross-member coordination, priority or ordering conflicts, being blocked, or scope questions inside the team's goal. Their job is to unblock and sequence — use them.
- **Raise to the owner/user** only when the chain reaches them: it's outside the team's mandate, it's a high-risk or hard-to-undo decision the team coordinator can't own, or earlier links are unavailable and it's urgent.
- **Don't jump an available link.** Going around the team's coordinator to the user breaks the team's coordination model.

## 4. Hand off work cleanly

- **Never drop team work silently.** If you can't finish it, hand it off — to the next member or back to the coordinator/lead.
- **Leave a clean pickup:** current state, where the work lives (todo, files, branch), what's done, and the very next step. For anything substantial, write a proper handoff (`instr_operational_handoff`).
- If another member is waiting on your piece, tell them it's ready — don't make them discover it.

## 5. Pick up and report on team-owned work

Team work is tracked as **todos** (`instr_todo`). Team ownership is represented by the team's `uai://team/<id>` entry in the todo's `assigned.yml`, not by tags or parentage.

- **Claim before you start:** set the todo `In_Progress` and add your `uai://session/<tracking_id>` assignment, while retaining the team assignment, so no two members grab the same thing.
- **Report as you go:** keep the todo's status accurate (the cross-session landscape depends on it), and post to the feed at a natural cadence — when you finish a unit, hit a blocker, or the coordinator/lead asks for a standup.
- **Close the loop:** on completion, update the todo, post the result, and ping whoever owns **acceptance** for that work (often the coordinator/lead or the requesting session) — done isn't done until the customer has it.

## Member's checklist

- [ ] Read my active team's `.team.yml`; I know my role and the first available escalation link.
- [ ] Peer messages default to non-interrupting urgency; I keep the feed current.
- [ ] I follow the team's escalation chain/fallback and don't skip an available link.
- [ ] I claim team todos without removing their team assignment and keep their status live.
- [ ] I hand off with state + next step; I never drop team work silently.
- [ ] On completion I report and notify the acceptance owner.
