# `knowledge` — the retrieval, memory, and history server

*Explanation / front matter. For the full, exhaustive tool list, see the [tool reference appendix](../../../docs/user_guide/reference/scaffolding/mcp-tools/knowledge.md).*

`knowledge` is one of this workspace's local **Model Context Protocol (MCP)** servers. MCP is the open standard that lets an AI assistant call external tools; each server here bundles a related set of tools that any connected assistant can invoke.

`knowledge` is what a session reads *from* and remembers *into*. A **session** here means one running command-line AI assistant — a single conversation with its own identity and terminal. It answers two kinds of question. First, "how do I do this / what do we know about that?" — it searches the workspace's curated guidance (its reference material, procedures, and how-to knowledge) and loads specific reference material on demand. Second, "what did I learn, and what happened before?" — it stores durable notes in **working memory** (a persistent per-session scratchpad that survives across conversations) and reads back the archived history of past sessions. It also runs the pipeline that condenses long raw chat transcripts into compact, reusable summaries.

An earlier separate "guidance" server has been folded into `knowledge`; its guidance-search and how-to tools now live here.

## When you'd reach for it

Reach for `knowledge` when a session needs information it does not already hold in its context, or when it needs to record something for later. Ask a plain-language question and get back the relevant guidance; load a specific reference file by name; jot a durable observation into working memory and search those notes later; look up what a previous session concluded; or hand a bloated transcript to the condensation pipeline to shrink it into a summary.

## Main capability groups

- **Knowledge and guidance retrieval** — natural-language search across Context Files (the workspace's reusable knowledge and instructions), skills (a packaged, loadable how-to procedure the assistant can pull in), and knowledge; "how do I…" lookups; loading specific reference material by name; and resolving configured reminders.
- **Working memory** — append, read, update, delete, and search a session's durable notes, plus memory statistics.
- **Session history** — find, list, read, and summarize the archived transcripts of past sessions.
- **Chat-history pipeline and condensation** — condense a transcript with configurable presets, check pipeline status and configuration, normalize records, and review or retry entries that were quarantined (set aside because they failed processing).
- **Raw file and transcript reads** — read a file, chunk a large file into pieces, and text-search across content.

## Full tool reference

The complete list of every tool, its parameters, and its one-line purpose lives in the generated appendix:
**[`knowledge` MCP tools](../../../docs/user_guide/reference/scaffolding/mcp-tools/knowledge.md)** (32 tools).

<!--
## Sources verified against
- ai_general/apps/mcps/knowledge/server.py — server name "knowledge"; docstring "consolidates knowledge-search, memory, chat-pipeline, jsonl, guidance"; sub-modules imported = knowledge_search, knowledge_memory, knowledge_chat_pipeline, knowledge_jsonl, knowledge_guidance; _handle_test shells to search_cli.py, memory_cli.py, guidance_cli.py
- ai_general/apps/mcps/knowledge/tools.yml — 32 tool definitions (authoritative tool list)
- ai_general/apps/mcps/knowledge/tools/ — module split matches capability groups
- ai_general/data/MCP.json — servers.knowledge (command_python)
- ai_general/docs/user_guide/reference/scaffolding/mcp-tools/knowledge.md — appendix (purposes: knowledge_how_to = NL search across traits/skills/knowledge; knowledge_get_context = load by reference; knowledge_condense_history = condense with presets)
Editorial: hand-written front matter; guidance-folded-in claim per server.py docstring. Audience = new outside human. Not git-committed.
-->
