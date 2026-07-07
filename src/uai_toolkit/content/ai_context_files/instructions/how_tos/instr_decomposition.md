---
id: decomposition
name: Decomposition
status: active
version: 1.0.0
created: 2026-04-21
updated: 2026-04-21
---

# Decomposition — Method

Breaking large problems into independent pieces with clear boundaries between them.

## When to Use
- Problem is too large for a single agent/session/task
- Multiple people/agents need to work in parallel
- Scope is unclear and needs to be made concrete
- A todo item needs to become executable tasks

## Process

### 1. Identify the Natural Boundaries
Look for:
- **Data boundaries** — different data domains that don't need to share state
- **Functional boundaries** — distinct capabilities that serve different purposes
- **Temporal boundaries** — things that happen at different times or cadences
- **Audience boundaries** — different consumers with different needs

### 2. Test Independence
For each proposed piece, ask:
- Can this be understood without knowing the internals of the other pieces?
- Can this be changed without breaking the other pieces?
- Can this be built and tested independently?
- Can this be assigned to a different agent/worker?

If not, the boundary is in the wrong place.

### 3. Define Interfaces
For each boundary between pieces:
- What does piece A need from piece B? (inputs)
- What does piece B promise to piece A? (contract)
- What happens when the contract is violated? (error handling)

### 4. Determine Order
- Which pieces can be parallel? (no dependencies)
- Which must be sequential? (output of one feeds input of another)
- Which are the highest risk? (do those first — fail fast)

## Decomposition Smells
- **Too many pieces** — overhead exceeds benefit. 3-7 is usually right.
- **Pieces that always change together** — they're one piece wearing two hats.
- **Circular dependencies** — the boundary is wrong, not the implementation.
- **One huge piece and many tiny ones** — you decomposed the easy parts and left the hard part intact.
