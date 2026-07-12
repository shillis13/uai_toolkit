# CLI Launcher Design

## Canonical entrypoint

- `ai_launch.py` is the only public launcher entrypoint implementation.
- `claudeCli`, `codexCli`, and `geminiCli` are symlinks to `ai_launch.py`.
- No other script in this directory may call vendor CLI binaries directly.
- Higher-level facades such as `agent_ops_cli.py` must call the launcher entrypoints, not the vendor binaries.

## Layering

- `ai_launch.py`: thin entrypoint; platform detection only.
- `lib_orchestrator.py`: argument parsing and high-level launch flow.
- `lib_cli_wrapper.py`: vendor command construction.
- `lib_session_mgr.py`: tracking IDs, registry/session bookkeeping, transcript discovery.
- `lib_session_substrate.py` (in `../session_mgmt/`): managed terminal substrate implementation.

## Substrate isolation rule

Outside `lib_session_substrate.py` and other substrate modules under `session_mgmt/`, launcher code must not know substrate-specific terminology or command shapes.

That means:

- no `tmux` knowledge outside substrate
- no `zellij` knowledge outside substrate
- no PTY/TTY ownership logic outside substrate
- no substrate-specific command formatting outside substrate
- no substrate-specific environment variable names outside substrate

Upper layers may talk only in generic terms such as:

- terminal session
- substrate
- substrate context
- attach
- create session
- resume action
- direct foreground mode

If a launcher-layer change requires naming a specific multiplexer or terminal primitive, the boundary is wrong. Move that logic down into the substrate layer.

## Identity and registry

- `lib_session_mgr.py` owns tracking ID generation, launcher environment construction, registry writes, and transcript discovery.
- The launcher must print `TRACKING_ID=...`, `TERMINAL=...`, and `CLI_UUID=...` before returning control to non-interactive callers.
- The registry may preserve compatibility fields internally, but launcher-facing code uses generic names such as `terminal_session` and `substrate_context`.

## Flags

- Do not reuse retired short flags for different meanings.
- Managed terminal bypass is exposed as generic direct mode (`--direct` / `-i`), not substrate-specific naming.
