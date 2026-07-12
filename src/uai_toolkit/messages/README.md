# messages

File-based async messaging between AI sessions. Messages are YAML files written to `ai_comms/` — no session is notified on arrival; recipients check their inbox explicitly or via a watching hook.

## Scripts

### messages_lib.py
Core business logic for message creation, storage, and retrieval. Handles broadcast messages (to all sessions), direct messages (to a named recipient's inbox directory), response threading (`reply_to` field), acknowledgment tracking, and message listing. Extracted from the `messages` MCP server to follow the "thin wrapper around scripts" pattern.

No CLI entry point — imported by `messaging_mgr.py` and the MCP server.

### prompt_blocks.py
Block a session from receiving prompts from anyone but the user. Prompts from other sessions are **held** (queued `ready_for_delivery=False`) and delivered when the block lifts — reusing the existing `prompts_inbox/` queue + drain hooks. The user's direct terminal input always gets through (it never passes through the send path).

Modes: `--indefinite` (default), `--until <ISO | +90m/+2h/+1d>`, `--turns N` (counted down one per completed turn by `Stop/09_decrement_prompt_block_sync.py`, auto-lifts at 0). `allow_from` exempts senders (default `user`); self-sends are always exempt. A blocked `interrupt`-urgency message is held but fires a user notification.

Enforced at: the MCP `comms_send_prompt` gate (holds instead of injecting), the idle-nudge in `messaging_mgr.send_message`, and the drain hooks via `lib_hook_scripts.drop_blocked_sources` (one drain-side gate covering all queued paths). Indicator (🔒) shows on the CLI statusline, the response footer, and (via UAI) session cards.

**Usage:**
```
prompt_blocks.py block <tid|self> --turns 3 [--reason "deep work"]
prompt_blocks.py block <tid|self> --until +90m
prompt_blocks.py unblock <tid|self>
prompt_blocks.py list | status <tid>
```
Also exposed as MCP tools `comms_block_session` / `comms_unblock_session` / `comms_list_blocks`.

### messaging_mgr.py
Unified CLI and interactive REPL for all messaging operations. Replaces the older `messaging.py` (now a symlink to this file). Emits JSON to stdout for all subcommands. Running with no arguments or `--as SESSION_ID` opens an interactive REPL.

Key operations: `send`, `broadcast`, `list`, `acknowledge`, `check-responses`, `read`, `reply`, `reply-all`, `check`, `archive`, `queue-prompt`, `post-standing`, `query-standing`, `cancel-standing`, `send` with `--response-required`, `list-pending`, `check-owed`.

**Usage:**
```
messaging_mgr.py send --from alice --to bob --content "Hello"
messaging_mgr.py broadcast --from alice --content "Attention all"
messaging_mgr.py list --dir inbox --recipient bob
messaging_mgr.py queue-prompt --to SESSION_ID --content "Do the thing" --urgency prompt
messaging_mgr.py                         # REPL as $AI_TRACKING_ID
messaging_mgr.py --as TRACKING_ID        # REPL as specific identity
```

### messaging.py
Symlink to `messaging_mgr.py`.

## v2 Conversations/Messaging migration

The `send`/`send-prompt` CLI and the `comms_message`/`comms_send_prompt` MCP tools
moved to the v2 send contract (design: `ai_comms/CONVERSATIONS_MESSAGING_DESIGN.md`
§5, §12.B–§12.L; plan: `ai_comms/CONVERSATIONS_IMPL_PLAN.md` Task 9). What changed:

- **`--from` / `from_sender` removed.** The sender is the *trusted resolved
  session* (`$AI_TRACKING_ID` / authenticated MCP context), never a self-asserted
  wire field. Stop passing it.
- **`reply_to` is now REQUIRED and nullable.** MCP/JSON `null` ⇒ new conversation;
  the CLI literal `none` (and `null`/empty) ⇒ the same. A parent `msg_…` id ⇒ a
  reply that inherits the parent's conversation.
- **`subject` is REQUIRED when `reply_to` is null/`none`** (it becomes the
  conversation topic). It is optional when replying. A missing subject on a new
  conversation surfaces `SubjectRequired`.
- **`replying_to` and `--conversation-id` are deprecated.** v2 derives the
  conversation from `reply_to`; a `replying_to` alias is still written into the
  YAML artifact for pre-v2 readers, and `--conversation-id` is accepted-but-ignored.
- **Return shape is `{conversationId, messageId}`** (camelCase at the JSON/MCP
  contract boundary; internal columns stay snake_case).

### Transition shim (deprecation window — §12.L)

So live sessions don't break mid-rollout, the `send`/`send-prompt` CLI still
**accepts** the legacy flags during the window, with stderr `[DEPRECATED]`
warnings:

- `--from` — accepted but **ignored** (the trusted resolved sender wins).
- `--conversation-id` — accepted but **ignored** (v2 derives it from `--reply-to`).
- a **missing `--reply-to`** — warns and **defaults to `none`** (new conversation)
  rather than hard-erroring.

The MCP `comms_message` mirrors this: a stray `from`/`from_sender` is ignored
(noted under `deprecations` in the result) and a missing `reply_to` defaults to a
new conversation. At the **hard cutover** these become errors and the legacy
flags are removed — migrate callers to pass `reply_to` (and `subject` for new
conversations) explicitly and drop `--from`/`--conversation-id` before then.

### broadcast.py
Delivers a prompt or message to all active sessions in one call. For `prompt` mode, uses `send_prompt.sh` to inject text into each session's terminal; for `message` mode, writes to each session's inbox via `messaging_mgr.py send`. Falls back to tmux session enumeration if `session_store.py` is unavailable. Failed prompt deliveries are automatically queued for later.

**Usage:**
```
broadcast.py prompt --from SENDER --content "text" [--platform claude_cli] [--dry-run]
broadcast.py message --from SENDER --content "text" [--sessions ID1,ID2]
```

### sweep_expired.py
Removes expired messages and stale queue entries. Sweeps YAML files with an `expires_at` field from `ai_comms/messages/inbox/`, `ai_comms/prompts_inbox/`, `ai_general/data/standing_messages/`, and `ai_general/data/comms/pending_replies/`. Also removes files from `prompt_queue/delivered/` older than 7 days (mtime-based). Intended to run on a schedule (cron or launchd).

**Usage:**
```
sweep_expired.py [--dry-run]
```

## Dependencies

- `yaml` — message file format
- `session_store.py` (in `ai_general/scripts/session_mgmt/`) — active session enumeration in `broadcast.py`
- `send_prompt.sh` (in `ai_general/scripts/prompting/`) — terminal prompt injection in `broadcast.py`
- `callback_lib` (`~/bin/ai/callbacks/`) — callback notification on delivery
- `get_comms_id` (`~/bin/all_languages/python/src/`) — message ID generation in `messaging_mgr.py`
- `~/bin/ai/utils/standard_colors` — REPL color output

## Notes

- Messages sit on disk until explicitly checked. This is intentional: the system is async and non-intrusive.
- `SCHEMA.md` in this directory documents the YAML message schema.
- `broadcast.py` queues undeliverable prompts so they are retried when the session becomes available.
