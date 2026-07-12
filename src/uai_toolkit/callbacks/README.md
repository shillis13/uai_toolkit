# callbacks

Shared library and CLI for delivering callback responses to endpoint URIs. Used by MCP servers and CLI tools to close the response loop after async operations complete.

## Scripts

### callback_lib.py
Core business logic for the callback system. Defines the `Endpoint` dataclass and `CallbackResult` type, and implements delivery for three URI schemes: `file://` (write to a regular file), `fifo://` (write to a named pipe), and `prompt://` (send a prompt to a running CLI session via `send_prompt.sh`). Also provides `make_endpoint_uri` and `parse_endpoint` for constructing and parsing endpoint URIs. This module is the single source of truth — MCP servers import directly from here.

**Key types:**
- `Endpoint` — parsed endpoint with scheme, path, session, template, submit, force fields
- `CallbackResult` — success/failure result with message and endpoint type

### callback.py
CLI wrapper around `callback_lib.py`. Run manually or from scripts to deliver a message to any supported endpoint URI.

**Usage:**
```
callback.py --endpoint "file:///tmp/resp.txt" --msg "approved"
callback.py --endpoint "prompt://claude-cli/session_name" --msg "review complete"
callback.py --endpoint "fifo:///tmp/pipe" --msg "42"
callback.py --json --endpoint URI --msg MSG       # structured JSON output

callback.py make-uri --scheme file --path /tmp/resp.txt
callback.py make-uri --scheme prompt --target claude-cli --session abc123
callback.py parse-uri "prompt://claude-cli/abc123?submit=true"
```

Exit codes: 0 = delivered, 1 = failed.

## Dependencies

- `send_prompt.sh` at `$AI_ROOT/ai_general/scripts/prompting/send_prompt.sh` (required for `prompt://` scheme)
- Standard library only (`urllib.parse`, `subprocess`, `dataclasses`)

## Notes

The `prompt://` scheme delivers by calling `send_prompt.sh` with a 90-second timeout. The `fifo://` scheme verifies the target is actually a FIFO before writing. Bare file paths (starting with `/`) are treated as `file://` by the parser. MCP servers import `callback_lib` directly; `callback.py` is for shell/subprocess callers.
