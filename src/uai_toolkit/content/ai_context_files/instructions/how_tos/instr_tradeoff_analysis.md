---
id: tradeoff_analysis
name: Tradeoff Analysis
status: active
version: 1.0.0
created: 2026-04-21
updated: 2026-04-21
---

# Tradeoff Analysis — Method

Structured approach to evaluating competing options. Makes the implicit explicit — name what's being gained AND what's being lost.

## When to Use
- Choosing between design approaches
- Evaluating technology options
- Prioritizing competing requirements
- Any decision where "it depends" is the initial answer

## Process

### 1. Define the Decision
One sentence: "We need to decide [X] because [Y]."

### 2. List Options (minimum 2, prefer 3)
For each option, document in one paragraph what it IS — not why it's good or bad yet.

### 3. Define Evaluation Criteria
What matters for THIS decision? Common criteria:
- Complexity (implementation effort)
- Maintainability (ongoing cost)
- Scalability (growth handling)
- Reversibility (can we change our mind?)
- Consistency (fits with existing patterns)
- User impact (who's affected and how)

### 4. Evaluate Each Option Against Each Criterion
Be specific. "Better performance" is not analysis. "Reduces query time from O(n) to O(1) for the lookup case, but adds 200 lines of index maintenance code" is analysis.

### 5. Name the Tradeoff
State explicitly: "Choosing A gives us [benefit] at the cost of [sacrifice]."
Every option sacrifices something. If you can't name the sacrifice, you haven't analyzed deeply enough.

### 6. Recommend with Rationale
"I recommend [option] because [the specific tradeoff it makes is the right one for our context]."

## Anti-Patterns
- Listing only pros (advocacy, not analysis)
- "Option A is better in every way" (you missed something)
- Analysis paralysis on two-way-door decisions
- Evaluating against criteria that don't matter for this decision
