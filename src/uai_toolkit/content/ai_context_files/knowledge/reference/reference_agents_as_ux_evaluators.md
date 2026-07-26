---
name: reference_agents_as_ux_evaluators
description: Method + report for using subagents as naive UX test users; reusable
  usability harness
status: active
---

Agents-as-UX-evaluators: spawn ≥2 subagents as naive "first-time users" of a tool, give them ONLY the launch command + the tool's `help` + a task script (forbid reading source), have each report per-task friction (1–5) + ranked problems. Same script across testers = cross-validation (issues both hit = high priority). First run (2026-06-17, on the aagm REPL) caught a root-cause bug + 5 friction points the author hadn't seen.

Full methodology, scenario-picking, prompt template, synthesis rubric, the v2 "interactive substrate terminal" improvement (run tool in a persistent session, agents drive via session_ops.py write-to/read-terminal), and how to extend to a UI (chrome-control/screeny + Nielsen heuristic walkthrough):
`$AI_ROOT/ai_general/research_and_reports/agents_as_ux_evaluators/README.md`

Relates to the A&A Game Manager build [[project_aa_game_architecture]].
