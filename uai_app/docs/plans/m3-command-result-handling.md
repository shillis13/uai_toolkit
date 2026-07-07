# M3: Command Result Handling — Design Notes

**Status:** Implementation in progress (subagent dispatched 2026-04-26)
**Date:** 2026-04-25
**From:** PianoMan + session 20260425_234902_acd5d3bd_cla

## Problem

All six renderer call sites that dispatch commands via `window.uai.execute()` ignore the `CommandResult.ok` field. Failed commands silently succeed from the user's perspective — edit mode exits, menus close, prompt text clears, notes appear saved.

## Agreed Design

### Shared `executeCommand()` wrapper

Central wrapper that:
1. Builds the command envelope (id, type, payload, origin, timestamp)
2. Calls `window.uai.execute()`
3. Checks `ok` on the result
4. Routes failures to the appropriate feedback channel

### Component Error Handler API

UI components that dispatch commands expose an error handler so the wrapper can deliver contextual feedback to the specific UI element that triggered the command:

```tsx
const errorHandler = useCommandErrorHandler({
  fields: {
    notes: notesRef,
    displayName: nameRef,
  },
});

executeCommand('session.update', payload, {
  errorHandler,
  field: 'notes',
  onFailure: 'inline',
});
```

On failure, the error handler:
- Highlights the source field (red border)
- Shows hover-over text with the error message
- Clears error state on next user interaction with that field

### Failure Feedback Channels

The handler needs all of these available. The caller selects the appropriate channel, or the handler can decide based on context.

| Channel | When | Example | Status |
|---------|------|---------|--------|
| `inline` | Source field is known | Red border on notes field with error hover text | Implementing |
| `toast` | No source field, user should notice immediately | Archive failed, create session failed | Implementing |
| `statusbar` | Low-priority, ambient awareness | Background sync error | Not yet built |
| `log-panel` | Durable record, user can review later | Activity log entry in BottomPanel | Not yet built |
| `notification` | App-level alert, may persist until dismissed | Session launch failed | Not yet built |
| `log` | Console only, dev visibility | Debug/diagnostics | Implementing |
| `silent` | Fire-and-forget, nobody cares | Metrics write | Implementing |

The wrapper's `onFailure` parameter accepts any channel name. Unimplemented channels fall back to `toast` (or `log` if toast isn't available).

### Call Sites

| Component | Command | Failure Channel |
|-----------|---------|----------------|
| Navigator | `session.archive` | toast |
| Navigator | `session.update` (rename) | inline (name field) |
| Navigator | `session.create` | toast |
| ContextPanel | `session.update` (notes) | inline (notes field) |
| PromptBox | `prompt.send` | inline (prompt field) — don't clear text on failure |
| Workspace | `workspace.tabs.*` | toast |

### Implementation Notes

Initial implementation covers: toast, inline, log, silent.
Remaining channels (statusbar, log-panel, notification) are additive — adding them doesn't change the wrapper signature or existing call sites.
