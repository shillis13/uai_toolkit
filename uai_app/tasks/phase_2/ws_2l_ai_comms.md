---
task_id: ws_2l
task_type: implementation
created: 2026-05-08T00:00:00Z
status: staged
depends_on: []
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2L: AI Communications Integration

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Monorepo:** packages/shared/, packages/renderer-ui/, app/

## Objective

Integrate the AI Communication Protocol v1.0 into UAI, making the app a consumer of the messaging infrastructure. UAI displays, manages, and composes messages — the delivery infrastructure (hooks, queue directories, callback endpoints) is external.

## Protocol Reference

Read first: `ai_general/ai_traits/processes/30_protocols/versions/protocol_comms_v1.0.md`

Key sections for UAI:
- §4.3 Prompt Queue — per-session queue with delivery timing
- §4.3.5 Conversation Lock — user blocks automated delivery
- §4.3.8 User Visibility — queue management UI requirements
- §5 Message Schema — YAML message structure
- §5.1 Callback Endpoints — URI-based response delivery
- §7.2 Standing Messages — pull-based persistent messages

## What to Build

### Phase 1: Read-Only Visibility (start here)

1. **Prompt Queue IPC** — Main process reads `ai_comms/prompts_inbox/{session_tracking_id}/` directory, parses YAML queue entries, returns structured data via IPC
   - New IPC: `uai:comms:queue:list` — returns queue entries for a session
   - New IPC: `uai:comms:queue:count` — returns count per session (for badges)

2. **Queue display in right panel** — "Prompts" tab showing pending queue entries per active session
   - Entry shows: sender name, urgency, delivery timing, content preview, expiry
   - Color-coded by urgency (interrupt=red, prompt=blue, async=gray)

3. **Inbox IPC** — Read messages from inbox directory
   - New IPC: `uai:comms:inbox:list` — returns inbox messages
   - New IPC: `uai:comms:inbox:count` — for badges

4. **Inbox display** — "Messages" tab in right panel
   - Folders: Inbox, Sent, Archive (toggle buttons, same as UCI)
   - Message cards: type badge, sender, time, urgency, preview
   - Unread indicator

5. **Badge counts** — Tab badges on Prompts and Messages tabs showing pending/unread counts

### Phase 2: Management Actions

6. **Queue management** — Right-click on queue entry:
   - Change delivery timing (pre-prompt / post-prompt / postResponse)
   - Hold (set ready_for_delivery=false)
   - Release (set ready_for_delivery=true)
   - Remove from queue

7. **Conversation lock** — Per-session toggle
   - Check for lock file: `ai_general/data/comms/locks/{session_tracking_id}.lock`
   - Create/remove lock file from UI
   - Visual indicator on session card and tab when locked
   - Lock icon in title bar for active session

8. **Message actions** — Archive, mark read/unread

### Phase 3: Composition

9. **Send message** — Compose and send from UI
   - Recipient selector (session list, groups, broadcast scope)
   - Message type and urgency selection
   - Content editor
   - Attachment paths
   - Callback endpoint (auto-set for requests)

10. **Standing messages** — Query at bootstrap, display in a notification area or bottom panel

## Key Files

- Protocol: `ai_general/ai_traits/processes/30_protocols/versions/protocol_comms_v1.0.md`
- Queue storage: `ai_comms/prompts_inbox/{session_tracking_id}/`
- Lock storage: `ai_general/data/comms/locks/`
- Message scripts: `~/bin/ai/messages/` and `~/bin/ai/callbacks/`
- UCI reference: `ai_general/projects/unified_cli_interface/src/src/renderer/components/MessagingPanel.tsx`

## Validation

- `cd app && npx tsc --noEmit` — must pass
- `cd app && npx vitest run` — must pass
- Queue entries display correctly for sessions with pending prompts
- Inbox shows messages
- Badge counts update

## Done When

Phase 1: User can see pending prompt queue entries and inbox messages per session. Badge counts visible on tabs.
Phase 2: User can manage queue entries (hold/release/remove/change timing) and toggle conversation locks.
Phase 3: User can compose and send messages from the UI.
