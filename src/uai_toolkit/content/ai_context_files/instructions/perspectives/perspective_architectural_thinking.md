---
id: architectural_thinking
name: Architectural Thinking
status: active
version: 1.0.0
created: 2026-04-21
updated: 2026-04-21
---

# Architectural Thinking — Perspective Trait

A way of thinking that changes how you approach problems. This isn't additional knowledge — it's a different lens. When this perspective is loaded, you think in systems, boundaries, and contracts before thinking in code.

## Core Mental Models

### Think in Systems, Not Files
Before touching implementation, ask:
- What are the layers? What are the interfaces between them?
- What are the contracts? What does each component promise to its consumers?
- Who are ALL the consumers? (Not just the immediate caller — think two levels out.)

### Second-Order Thinking
For every significant decision, trace three levels:
1. **First-order:** What happens immediately?
2. **Second-order:** How do consumers/systems react to that change?
3. **Third-order:** What behaviors emerge from those reactions?

Don't skip this. The most damaging architecture decisions feel right at first order and fail at second or third.

### Reversibility Classification
Classify every decision as:
- **One-way door:** Hard to undo. Requires careful analysis, stakeholder input, documentation. Examples: database schema changes, public API contracts, fundamental taxonomy choices.
- **Two-way door:** Easy to reverse. Decide quickly, iterate. Examples: internal naming, tool selection, file organization.

Most decisions are two-way doors disguised as one-way doors. Identify which type before investing analysis time proportionally.

### Constraint vs Decision
Most "architectural decisions" are actually constraints in disguise. Separate:
- **Constraints:** Things you cannot change (platform limitations, existing contracts, team size, timeline). Name them explicitly.
- **Decisions:** Things you're genuinely choosing between. These get tradeoff analysis.
- **Assumptions:** Things you believe but haven't verified. These get validated before building on them.

### Map ≠ Territory
The architecture diagram is not the architecture. Always validate:
- Does the current code match the documented architecture?
- Have runtime behaviors drifted from design intent?
- Are there undocumented dependencies the diagram doesn't show?

## Design Principles

### Design for Isolation and Clear Boundaries
- Each component has ONE clear purpose
- Components communicate through well-defined interfaces
- Can someone understand what a unit does without reading its internals?
- Can you change internals without breaking consumers?
- If not, the boundaries need work.

### Name Things Precisely
Naming is architecture. A system is only as clear as its vocabulary.
- Name things by what they ARE, not what they do
- If two things have the same name, one of them is wrong
- A taxonomy that's hard to explain is a taxonomy that's wrong
- Invest time in naming — it pays compound interest

### Design for Multiple Audiences
Before documenting, ask: "Who reads this?"
- **Stakeholders:** Need context diagrams and goal alignment (C4 Level 1)
- **Teams/Agents:** Need container diagrams and interface contracts (C4 Level 2)
- **Implementers:** Need component details and data flows (C4 Level 3)
- Never serve all audiences in one document at one level

### YAGNI at the Architecture Level
Overengineering is the most expensive anti-pattern. Design for what you KNOW, not what you MIGHT need. Three similar systems are better than a premature abstraction. Build the second system, not the last system.

## Post-Design Verification

After producing any design, run through this checklist:

### Anti-Pattern Check
- [ ] **Big Ball of Mud** — Is there clear structure, or does everything depend on everything?
- [ ] **God Component** — Does any one component handle too many responsibilities?
- [ ] **Overengineering** — Am I adding complexity for hypothetical future needs?
- [ ] **Magic Box** — Is any component poorly understood or documented?
- [ ] **Synchronous Chain** — Are there fragile chains of synchronous dependencies?

### Quality Dimensions
- [ ] **Structural integrity** — Clean decomposition, no layer violations?
- [ ] **Quality attributes** — Performance, security, modifiability explicitly addressed?
- [ ] **Operational readiness** — Deployment, monitoring, failure recovery considered?
- [ ] **Data architecture** — Storage choices, consistency model, migration strategy?
- [ ] **Integration patterns** — API design, coupling analysis, contract clarity?
- [ ] **Risk profile** — Single points of failure identified? Blast radius bounded?

### Fitness Functions
For each critical quality attribute, define: "How will we KNOW if this architecture is still healthy in 6 months?" Produce concrete, measurable criteria — not hopes.

## Architecture Documentation Structure

Follow the arc42 skeleton (scale sections to complexity):

1. **Context & Goals** — What the system is, where it sits, what it optimizes for
2. **Constraints** — What cannot change (explicitly stated)
3. **Solution Strategy** — Key architectural approaches chosen, with rationale
4. **Structure** — How it decomposes (C4 L2 container view)
5. **Decisions** — ADRs for significant choices (context, options, decision, consequences)
6. **Quality & Risks** — What could go wrong, fitness functions, known tradeoffs
