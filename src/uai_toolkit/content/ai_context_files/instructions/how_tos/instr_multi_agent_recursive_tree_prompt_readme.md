---
id: multi_agent_recursive_tree_prompt_readme
name: Multi Agent Recursive Tree Prompt Readme
status: active
version: 1.0.0
created: '2025-11-03'
updated: '2026-04-15'
---

# 🧬 Multi‑Agent Recursive Tree Prompt (MARTP)

**Project:** Development Stuff — Persona v8.5  
**Date:** 2025‑11‑02  
**Status:** Working Template (v1.0)

> A general‑purpose **tree‑structured, multi‑agent** prompt pattern where each AI node can spawn children, each child can do research and propose a solution, and parents perform **upstream synthesis**. The **root + human arbiter** selects the final outcome.

---

## 1) Concept Overview
The MARTP pattern coordinates multiple AIs arranged in a **hierarchy**. Every node executes two roles:

1. **Downstream (delegation):** If not at the depth limit, spawn `branch_factor` children, pass a variant of the task, and collect their outputs.  
2. **Upstream (aggregation):** Evaluate child outputs, rank/score, and produce a synthesized proposal to return to the parent.

**Base case:** When `current_depth == max_depth`, the node acts as a **leaf** and produces an initial solution (with rationale, citations if used, and a confidence estimate).

**Human arbitration:** At the root, the synthesized result is presented to the user, who can select, refine, or request another run.

---

## 2) Control & Parameters

| Parameter         | Type  | Description                                   | Example |
|-------------------|-------|-----------------------------------------------|---------|
| `current_depth`   | int   | Depth of this node (root is 0).               | 0       |
| `max_depth`       | int   | Depth limit; base case when reached.          | 2       |
| `branch_factor`   | int   | Children spawned per non‑leaf node.           | 3       |
| `role`            | enum  | `root` \| `intermediate` \| `leaf`.           | root    |
| `context`         | obj   | Shared goals/constraints/artifacts available. | `{…}`   |

**Base‑case rule:** `if current_depth == max_depth → leaf behavior (no children)`

**Recursion guard:** `if current_depth < max_depth → spawn children; else → leaf`.

---

## 3) End‑to‑End Flow (Downstream → Upstream)

```text
                          ┌────────────────────────────┐
                          │        Human Arbiter        │
                          │   (Root collaborates here)  │
                          └──────────────┬──────────────┘
                                         │  ▲
                               Upstream  │  │  Final synthesis & choice
                                         │  │
                          ┌──────────────┴──────────────┐
                          │         Root AI (0)         │
                          │     current_depth=0         │
                          └───────┬────────┬────────────┘
                                  │        │
                 Downstream  ↓    │        │    ↓  Downstream
                              ┌───┴───┐  ┌──┴───┐  … (branch_factor)
                              │Child1 │  │Child2 │
                              │depth=1│  │depth=1│
                              └───┬────┘  └──┬────┘
                                  │          │
                                  ▼          ▼
                          ┌────────────┐  ┌────────────┐
                          │ Grandchild │  │ Grandchild │
                          │ depth=2    │  │ depth=2    │
                          │ base case  │  │ base case  │
                          └────────────┘  └────────────┘
```

**Phases**
1. **Downstream:** Non‑leaf nodes spawn `branch_factor` children with `current_depth+1` and pass the inner task.  
2. **Base case (Leaf):** Execute the inner task, generate a solution + rationale + confidence.  
3. **Upstream:** Parents evaluate child outputs, synthesize, and return upward.  
4. **Root arbitration:** Present final synthesis to the user for selection/refinement.

---

## 4) Process Logic (Pseudo)

```pseudocode
function solve(node):
  if node.current_depth == node.max_depth:
    return execute_inner_task(node.context)  // leaf behavior

  // non‑leaf: spawn children
  results = []
  for i in 1..branch_factor:
    child = node.spawn(depth = node.current_depth + 1)
    child_result = solve(child)
    results.append(child_result)

  return synthesize(results, node.context)
```

**Synthesis** should be deterministic and auditable: score by criteria, show ranking, and justify merges.

---

## 5) Evaluation & Synthesis Rubric (defaults)

| Metric        | Description                         | Default Weight |
|---------------|-------------------------------------|----------------|
| Completeness  | Meets all stated requirements       | 0.30           |
| Coherence     | Logical integrity & consistency     | 0.25           |
| Robustness    | Failure handling, edge coverage     | 0.15           |
| Verifiability | Cited evidence / testability        | 0.15           |
| Elegance      | Simplicity with power               | 0.10           |
| Efficiency    | Brevity vs. clarity trade‑off       | 0.05           |

You may tailor weights per task; keep the table in outputs for traceability.

---

## 6) The Template Prompt (Reusable Scaffold)

```markdown
# === Multi‑Agent Recursive Tree Prompt v1.0 ===

## Invocation Context
current_depth: {{current_depth}}
max_depth: {{max_depth}}
branch_factor: {{branch_factor}}
role: {{role}}
context: {{context}}

---

## A. Downstream Recursion Logic
IF current_depth < max_depth:
  1) Spawn `branch_factor` children.
  2) Increment depth for each child.
  3) Send each a variant of Section C (Inner Prompt).
  4) Collect results and proceed to Section D (Aggregation).
ELSE → go to Section B (Base Case).

---

## B. Base Case Logic (Leaf Node)
IF current_depth == max_depth:
  • Execute Section C.
  • Produce { solution, rationale, confidence, citations? }.
  • Return upstream.

---

## C. Inner Prompt (Fill by User)
### Objective
{what the solution must accomplish}

### Constraints
{rules, limits, required inputs/outputs}

### Evaluation Criteria
{how success is measured}

### Output Format
{markdown / JSON / code / report}

---

## D. Upstream Aggregation Logic
1) Evaluate child outputs using the Evaluation Criteria.
2) Provide a ranked comparison table.
3) Synthesize: either (a) weighted merge of best elements or (b) winner‑take‑most, with justification.
4) Return { synthesized_solution, evaluation_matrix, meta_summary }.

---

## E. Root Termination
IF current_depth == 0:
  • Present final synthesis to the human arbiter.
  • Apply feedback or select final result.
```

---

## 7) Worked Example (Fully Functional)

**Scenario:** Design a minimal **multi‑agent chat orchestration pipeline**.  
**Parameters:** `branch_factor = 3`, `max_depth = 2`, `current_depth = 0` (root).

### 7.1 Inner Prompt (Section C) — Filled
```markdown
### Objective
Define a minimal pipeline architecture for orchestrating multiple LLM agents (root/children/leaves), including message routing, logging/retries, and plug‑in extensibility.

### Constraints
- Stateless nodes; state kept in a shared store.
- Deterministic merges with a scored evaluation table.
- Outputs must be in Markdown with code blocks for schemas/interfaces.

### Evaluation Criteria
- Completeness, Coherence, Robustness, Verifiability, Elegance, Efficiency.

### Output Format
Markdown spec with: (1) JSON schema for routing; (2) retry/log module outline; (3) plug‑in registration interface.
```

### 7.2 Depth‑2 Leaves (Base Case)
Each leaf returns a focused artifact.

**Leaf A1 — Message Routing Schema (JSON)**
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentMessage",
  "type": "object",
  "properties": {
    "id": {"type": "string"},
    "parent_id": {"type": "string"},
    "depth": {"type": "integer"},
    "role": {"enum": ["root","intermediate","leaf"]},
    "content": {"type": "string"},
    "score": {"type": "number"},
    "citations": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["id","depth","role","content"]
}
```

**Leaf B1 — Logging & Retry Module (outline)**
```text
- Structured logs (JSON Lines): timestamp, node_id, depth, event, metrics
- Retry policy: exponential backoff with jitter; max_attempts=3; idempotent tasks only
- Failure hooks: on_retry, on_giveup → emit diagnostic bundle
```

**Leaf C1 — Plug‑in Registration Interface (TypeScript)**
```ts
export interface AgentPlugin {
  name: string;
  capabilities: string[];
  init(ctx: OrchestratorContext): Promise<void>;
  handle(message: AgentMessage): Promise<AgentMessage | null>;
}
```

### 7.3 Depth‑1 Children (Aggregation per Focus)
Children synthesize leaf artifacts into domain components.

| Child | Focus          | Confidence | Output                                      |
|------:|----------------|------------|---------------------------------------------|
| A     | Flow design    | 0.88       | Routing schema + validation rules            |
| B     | Robustness     | 0.91       | Logging/Retry module spec                    |
| C     | Extensibility  | 0.84       | Plug‑in API + lifecycle                      |

### 7.4 Root (Depth 0) — Final Synthesis
- **Integrated Components:** A’s schema, B’s retry/logging, C’s plug‑in interface.  
- **Rationale:** Combines clarity of routing, operational resilience, and future add‑ons.  
- **Confidence:** 0.89.

**Final Artifact (excerpt)**
```markdown
## Orchestration Pipeline v1.0 (excerpt)
- Message schema (JSON) with parent/child linkage and citation slots.
- Orchestrator contract: validate→route→collect→rank→synthesize.
- Reliability: retries with jitter; diagnostic bundles on give‑up.
- Extensibility: AgentPlugin with init/handle hooks.
```

---

## 8) Implementation Notes
- **Determinism:** Always emit the evaluation table used for synthesis.  
- **Traceability:** Include `{parent_id, depth, branch_index, seed_prompt_hash}` in logs.  
- **Parallelism:** Child runs may be parallel; parent waits to merge.  
- **Early Convergence:** Nodes may short‑circuit if a child solution dominates by a large margin (document the threshold).  
- **Research:** Any node may browse/research to support its artifact; include citations when applicable.

---

## 9) Quick‑Start (Copy‑Paste)

```markdown
Invoke with:
- current_depth: 0
- max_depth: 2
- branch_factor: 3
- role: root
- context: { your task data }

Then paste the **Template Prompt** (Section 6) and fill **Section C**.
```

---

**End of README**

