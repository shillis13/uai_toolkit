---
name: Design docs updated before implementation
description: Always incorporate review feedback into the design doc before writing
  code
status: active
---

Design documents must be updated to address review feedback before implementation begins.

**Why:** Code written against a design that has known contradictions or gaps inherits those problems. Fixing the design on paper is cheap; fixing it in code is expensive. The assessor v1 design had a detector/assessor contract contradiction that would have produced confused code if built as-is.

**How to apply:** When a design review comes back with "request changes," revise the design doc to address the findings, then proceed. Don't start building from a design that has known open issues — even if the reviewer said the direction is right.
