Quick Reference Card
Never:

- Use bash_tool (it's useless - no filesystem access)
- View browser snapshots directly (instant context death)
- Read multiple files without delegating first
- Dive into implementation during architectural discussions

Always:

- Delegate exploration and analysis to Codex MCP
- Write browser snapshots to file → delegate analysis
- Stay conceptual until implementation is explicitly needed
- Check context impact before any verbose operation

Delegation Hierarchy:

- Codex MCP - Synchronous, focused single tasks
- CLI Coordination - Async work, parallel execution, complex orchestration
- Desktop Commander - Direct filesystem operations

Context Triggers:

- 3 files to read → Delegate
- 500 lines to process → Delegate

- Browser snapshot → Write to file + Delegate
- Directory exploration → Delegate
- Unknown scope → Delegate



