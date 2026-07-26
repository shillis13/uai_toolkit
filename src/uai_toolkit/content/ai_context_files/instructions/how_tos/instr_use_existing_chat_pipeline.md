---
name: Use the existing chat history pipeline to access Web/Desktop conversations
description: Don't reinvent chat access — run the existing fetch/download pipeline
  scripts manually
status: active
---

When needing to access a Web UI or Desktop Claude conversation from CLI:

1. `ai_general/scripts/automation/fetch_chatHist_metaData.sh` — fetches chat registry metadata from Claude Desktop
2. `ai_general/scripts/chats/download_pending_chats.js -x` — downloads pending chats from the registry
3. These are the SAME scripts the daily 4:00 AM cron pipeline runs

**Why:** On 2026-05-20, Noctis was asked to retrieve a Desktop Claude conversation. Instead of running the existing pipeline scripts, he tried: Chrome CDP (not running), osascript (no accessibility), Keychain cookie decryption (triggered security prompts), and Hammerspoon screenshot-and-scroll (partially worked but painful). The answer was always: just run the fetch/download scripts that are already built and tested.

**How to apply:** When you need a Web/Desktop conversation, run the pipeline manually first. If the pipeline's daily run hasn't caught today's chats yet, trigger `fetch_chatHist_metaData.sh` then `download_pending_chats.js -x` to pull them down. Don't build new access paths when the existing one works.
