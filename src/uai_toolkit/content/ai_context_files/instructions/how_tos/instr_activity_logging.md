# Instruction: Activity Logging Protocol

**Version:** 1.2.0
**Created:** 2026-02-13
**Last Updated:** 2026-05-08
**Status:** active
**Priority:** high
**Applies To:** all AI instances
**Rubric:** TODO — needs a rubric for assessing compliance (see todo backlog)

## Purpose

All AI instances maintain an activity log describing what they're working on and why. This enables:
- Recovery from interruptions (last entry = where you were and what you were trying to accomplish)
- Coordination (Hamilton and peers can see what each session is doing)
- Debugging failures (see what was attempted and the reasoning behind it)
- Audit trails for review

## Core Principle

Log the narrative, not the mechanics. One entry should describe a goal, its motivation, and the outcome — not individual tool calls. A single entry might span many tool calls and multiple responses.

**Good:** `Investigating why Memorex fails on unicode tables — separator detection treats box-drawing chars as separators. Found root cause: 80% dash ratio check passes on table borders. Fixed by excluding corner/junction characters.`

**Bad:** `Read TerminalFormatOverlay.tsx. Edited line 450. Read again. Ran tests.`

## Format

```
{ISO_TIMESTAMP} | {what you're doing and why}
{ISO_TIMESTAMP} | {outcome or next step}
```

### Examples

```
2026-05-03T09:30:00 | Starting Memorex bug investigation — PianoMan reports unicode tables broken. Separator detection likely culprit since tables contain mostly dash characters.
2026-05-03T09:45:00 | Root cause found: box-drawing borders (┌──┬──┐) pass 80% dash ratio. Fix: exclude corner/junction chars from separator check. Unit test added.
2026-05-03T09:50:00 | Deployed v4.4.8. Tested via bgapp on Relay session — 104 sections detected, tables render correctly.
2026-05-03T10:00:00 | Moving to activity indicator latency issue — Memorex polls at 1s, user wants real-time spinner feedback.
```

### Granularity Guide

- **New entry when:** you start a new goal, switch tasks, reach a significant conclusion, or hit a blocker
- **Same entry continues when:** you're still working toward the same goal with intermediate steps
- **Don't log:** individual file reads, tool calls, internal reasoning, conversation turns (those are already in the transcript)

## Log Location

Activity logs live in the session directory:

```
{session_dir}/activity_log.txt
```

Where `{session_dir}` is the value of `$AI_SESSION_DIR`, typically:
`ai_general/data/sessions/{platform}/{YYYY}/{MM}/{tracking_id}/`

### In Task Context

When working on a formal task, ALSO log to: `{task_dir}/activity_log.txt`

## What to Log

### Always
- What you're trying to accomplish and why
- Significant decisions and their reasoning
- Outcomes of investigations or implementations
- Blockers encountered and how resolved (or not)
- Handoffs to or from other sessions
- Context that a successor or coordinator would need

### Skip
- Individual tool calls (already in transcript)
- Internal reasoning steps (just thinking)
- Conversation with user (already in chat)

## Interruption Detection

Last entry in the log = where the interruption occurred and what you were working on. A successor or resumed session can read the log and understand the state without reading the entire transcript.

## When to Start

Begin logging from your first substantive action in a session. The first entry should describe your overall assignment or goal.

## Maintenance

- **Retention:** Keep indefinitely — low volume, high value
- **Cleanup:** Manual archival as needed

## Related

- `spec_response_footer.latest.yml`
- `instr_operating_principles.latest.condensed.yml`
