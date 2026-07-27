# Security Questionnaire — uai_toolkit

Answers with the code evidence behind them, so each can be defended if challenged.
Reviewed 2026-07-27 against the tree at that date. Paths are relative to the repo root.

**Scope note.** Two things ship in this repository:

1. **`uai_toolkit`** (`src/uai_toolkit/`) — the Python package installed by pip. This is
   what the answers below cover.
2. **`uai_app/`** — source for an optional desktop app. It is **not** installed by pip and
   must be built separately with Node. Where it changes an answer, it is called out.

Not covered: the third-party AI CLIs (Claude Code, Codex, and similar) that this toolkit
manages. They are separate vendor products with their own network behavior.

---

## 1. Could the software enable traffic monitoring of the network?

**No.**

The package cannot observe network traffic. There is no packet capture, no raw or
promiscuous socket, and nothing that reads from a network interface.

**Evidence**

- No use of `SOCK_RAW`, `AF_PACKET`, `pcap`, `scapy`, or any capture library anywhere in
  the package.
- The only socket call in the entire package is `socket.socket(socket.AF_UNIX, ...)` in
  `src/uai_toolkit/session_mgmt/lib_session_substrate.py`. `AF_UNIX` is a **filesystem**
  socket — a special file used to bridge a local terminal session between two processes on
  the same machine. It has no network address and cannot receive network traffic.
- Nothing opens a network interface in any mode.

**Expect this false positive.** The transcript readers in
`src/uai_toolkit/jsonl/platform_adapters/` define functions named `sniff()`. These read the
first line of a **local log file** to determine which AI tool wrote it (Claude, Codex,
Gemini, Grok, or Antigravity format). The name is unfortunate; the function never touches a
network. An automated scanner keying on the word will flag it.

---

## 2. Does the software have AI capabilities?

**It ships no AI. It can optionally act as a client to an AI service the operator
configures, and does nothing of the kind out of the box.**

The distinction that matters to a reviewer:

- **Ships no model, no weights, no inference engine, no training code.** Nothing in this
  package can perform inference. Installing it adds no AI capability to a machine.
- **Contains an optional client to a model the operator supplies.** Five current features
  can use a language model if — and only if — an administrator configures an endpoint for that
  specific feature. **As shipped, no endpoint is configured for any of them, so none of
  them contacts anything.** See question 3 for the controls.
- **Every feature is configured separately** through one config file
  (`src/uai_toolkit/llm/` — client, and `llm_endpoints.example.json` for the shape). A
  site can enable one feature and leave the rest off, and can point each at a different
  model — a locally-hosted model, a hosted API, or nothing.

The active features, each independently switchable:

| Feature | What it would use a model for |
|---|---|
| `quality_gate` | review an assistant response at end of turn |
| `intent_check` | detect a turn that stated an intent but took no action |
| `session_assess` | structured per-session assessment for the work view |
| `session_summarize` | free-text per-session activity summaries |
| `consolidation_summary` | summarize a stretch of transcript when compacting |

The client also reserves the name `mcp_prompt` for a future prompt-only MCP tool. No
shipped tool consumes it today, so configuring that entry alone performs no work and opens
no connection. The former local-server MCP module was removed because it wrapped
non-vendored scripts and mixed prompts with model-server lifecycle controls.

**Suggested questionnaire wording**

> Ships no AI/ML models, inference engines, or training capability. Includes optional
> client features that can call a language-model service — each independently configurable
> and all disabled by default, inert unless an administrator supplies endpoint
> configuration for that specific feature. The model may be one hosted inside the
> organization's own network.

---

## 3. Could the software be used to transfer data outside of the network?

**Yes — via two paths, both requiring deliberate configuration by the operator. Neither
is active on a default install.**

### Path A — the optional model-backed features (all off by default)

The five active features listed under question 2 can send session content (prompt text, assistant
responses, or transcript excerpts — which may include source code) to a language model.
All of them route through one client, `src/uai_toolkit/llm/client.py`.

Controls, as of 2026-07-27:

- **No endpoint is built in.** No default host, no assumed local port, and no endpoint of
  any kind absent configuration. With no config file, every feature resolves to an empty
  chain, skips its work, and opens no connection. This is the default state of a fresh
  install.
- **No hardcoded destination anywhere in executable code.** `base_url` is required on every
  endpoint; one without it is rejected rather than falling back to an assumed host.
- **Presence of an API key is not enough.** An earlier version automatically added a vendor
  endpoint whenever `ANTHROPIC_API_KEY` was found in the environment. That is removed — a
  credential alone can no longer cause any connection. (Verified: with that variable set
  and no config, all six features remain disabled.)
- **Credentials are never stored in config.** Config names an *environment variable* to read
  the key from; the key itself is not written to the file.
- **Enabling is explicit, per-feature, and per-environment.** An administrator supplies a
  JSON config (at `$AI_ROOT/config/llm_endpoints.json`, or via `AI_LLM_ENDPOINTS`, or
  per-feature via `AI_LLM_ENDPOINTS_<FEATURE>`) naming — for each feature separately — the
  destination host, the model, and the credential variable. Enabling one feature does not
  enable any other.
- **Destinations are whatever the operator chooses**, including a model hosted entirely
  inside their own network, which keeps content on-premises.
- **The HTTP transport is optional.** Model calls require the `full` package extra
  (`pip install uai-toolkit[full]`, which supplies httpx). Without it, configured features
  return unavailable and make no connection.

### Path B — git push

`src/uai_toolkit/devTrees/push_dev_env.py` and `pr_dev_env.py` run `git push` to the remote
already configured in the operator's git checkout. This is ordinary developer tooling
transmitting to a destination the operator chose, and inherits whatever controls the git
remote and credentials already impose.

### Nothing else

No telemetry, analytics, crash reporting, update check, or license call-home. Inter-session
messaging is **file-based** on the local disk, not networked.

**Suggested questionnaire wording**

> Yes, in two administrator-controlled cases: (a) `git push` to a git remote the operator
> configures, and (b) optional AI-assisted features that transmit session content to an
> endpoint the administrator explicitly configures per feature. All such features are
> disabled by default, have no built-in destination, and make no connection absent that
> configuration; each may be pointed at an internally-hosted model to keep content on the
> network. The product sends no telemetry or analytics.

---

## 4. Does the system allow remote access?

**No.** The package opens no network port and provides no mechanism to reach the machine
from elsewhere.

**Evidence**

- **The MCP servers use standard input/output, not the network.** `mcp/knowledge/server.py`
  and `mcp/workflow/server.py` both use `stdio_server()`. They are launched as child
  processes and communicate over pipes. They bind no port and are not reachable off-host.
- **Terminal sessions use a filesystem socket.** Attaching to a running session goes through
  a Unix domain socket (`AF_UNIX`), which is a file governed by filesystem permissions. It
  has no network address. Reaching a session from another machine requires already having
  shell access to this one — obtained by some other means (for example SSH), which this
  software neither provides nor configures.
- **No listeners, no SSH, no bind to `0.0.0.0`** anywhere in the package.

### Disclosure — the optional desktop app

The desktop app in `uai_app/` (not installed by pip; built separately) starts Chrome
DevTools debugging on **port 9226, bound to the loopback interface** — see
`uai_app/app/main/index.ts`. This is a local debugging interface, not remote access, but it
should be disclosed, and one detail deserves attention:

1. Anything able to reach that port can drive the application, so it is a meaningful local
   control surface.
2. The app also sets `remote-allow-origins: '*'` (same file, next line), which **disables
   the browser's origin check** on that debug port. Loopback binding still prevents access
   from another machine, but with origin checking off, a web page loaded in a browser on
   **this** machine could attempt to connect to the port. That is a known attack pattern
   against exposed DevTools ports and is worth flagging on its own merits.
3. It would become remotely reachable if someone deliberately forwarded the port (for
   example over an SSH tunnel).

**Recommendation:** restrict `remote-allow-origins` to the specific origin the app needs, or
enable the debug port only in development builds. Tracked as a hardening item.

If the desktop app is not deployed, none of this applies.

---

## Summary

| Question | Answer |
|---|---|
| 1. Enable network traffic monitoring? | **No** — no capture capability; the only socket is a local filesystem socket |
| 2. Have AI capabilities? | **No AI ships**; one optional client to an external service, off by default |
| 3. Transfer data outside the network? | **Yes, if configured** — `git push`, and optional AI-assisted features that are disabled by default |
| 4. Allow remote access? | **No** — MCP uses stdio, terminals use a filesystem socket, no ports opened (see the desktop-app disclosure) |
