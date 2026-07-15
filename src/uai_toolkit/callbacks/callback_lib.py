"""
Callback library — business logic for delivering results to endpoints.

Endpoints are specified as URIs:
    file:///path/to/response.txt      — write to regular file
    fifo:///path/to/response.fifo     — write to named pipe (FIFO)
    prompt://target/session            — send via send_prompt.py

This module is the single source of truth for callback logic.
MCP servers import from here. CLI (callback.py) wraps this.
"""

import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote, quote

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402

SEND_PROMPT_SCRIPT = AI_ROOT / "ai_general/scripts/prompting/send_prompt.py"


_PLATFORM_TARGETS = {
    "claude_cli": "claude-cli",
    "codex_cli": "codex-cli",
    "gemini_cli": "gemini-cli",
    "antigravity_cli": "antigravity-cli",
    "grok_cli": "grok-cli",
}


def _ensure_session_mgmt_on_path():
    """Put ai_general/scripts/session_mgmt on sys.path so `lib_uri` and
    `session_store` import regardless of how the caller set up its path.

    Both parse_endpoint()'s uai:// branch and _resolve_uai_session() import from
    session_mgmt. Previously only _resolve_uai_session added the path — but
    parse_endpoint imports `lib_uri` BEFORE it calls _resolve_uai_session, so a
    caller that hadn't already seeded the path (e.g. send_prompt.py invoked from
    launchd) hit ModuleNotFoundError('lib_uri'), which surfaced as a misleading
    "target/endpoint required" and silently broke uai://session/<id> sends
    (meridian reflection, reflect_1 2026-07-03). Centralised + called up front."""
    sm_path = str(AI_ROOT / "ai_general/scripts/session_mgmt")
    if sm_path not in sys.path:
        sys.path.insert(0, sm_path)


def _resolve_uai_session(
    entity_id: str,
    submit: bool = True,
    force: bool = False,
    template: str = "",
) -> "Endpoint":
    """Resolve uai://session/<id> to a prompt:// Endpoint via session store."""
    _ensure_session_mgmt_on_path()
    from uai_toolkit.session_mgmt.session_store import SessionStore

    store = SessionStore()
    session = store.resolve(entity_id)
    if not session:
        raise ValueError(f"Session not found: {entity_id}")

    platform = session.get("platform", "")
    target = _PLATFORM_TARGETS.get(platform)
    terminal = session.get("terminal_session", "")
    if not target:
        raise ValueError(f"Platform '{platform}' not supported for prompt delivery")
    if not terminal:
        raise ValueError(f"Session {entity_id} has no terminal session")

    return Endpoint(
        scheme="prompt",
        path=target,
        session=terminal,
        template=template,
        submit=submit,
        force=force,
    )


# ── Data types ────────────────────────────────────────────────────────────

@dataclass
class CallbackResult:
    """Result of a callback execution attempt."""
    success: bool
    message: str
    endpoint_type: str = ""


@dataclass
class Endpoint:
    """Parsed callback endpoint."""
    scheme: str          # file, fifo, prompt, none
    path: str = ""       # file/fifo path, or prompt target
    session: str = ""    # for prompt:// — target session
    template: str = ""   # optional message template
    submit: bool = True  # for prompt:// — press Enter after send
    force: bool = False  # for prompt:// — send even if busy


# ── URI construction ──────────────────────────────────────────────────────

def make_endpoint_uri(
    scheme: str,
    path: str = "",
    session: str = "",
    template: str = "",
    submit: bool = True,
    force: bool = False,
) -> str:
    """Build a callback endpoint URI from parameters.

    Examples:
        make_endpoint_uri("file", path="/tmp/resp.txt")
            → "file:///tmp/resp.txt"

        make_endpoint_uri("fifo", path="/tmp/resp.fifo")
            → "fifo:///tmp/resp.fifo"

        make_endpoint_uri("prompt", path="claude-cli", session="abc123")
            → "prompt://claude-cli/abc123"

        make_endpoint_uri("none")
            → "none://"
    """
    if scheme == "none":
        return "none://"

    if scheme in ("file", "fifo"):
        if not path:
            raise ValueError(f"{scheme}:// requires path")
        encoded_path = quote(path, safe='/')
        return f"{scheme}://{encoded_path}"

    if scheme == "prompt":
        if not path:
            raise ValueError("prompt:// requires target as path")
        base = f"prompt://{path}"
        if session:
            base += f"/{session}"
        params = []
        if template:
            params.append(f"template={quote(template, safe='')}")
        if not submit:
            params.append("submit=false")
        if force:
            params.append("force=true")
        if params:
            base += "?" + "&".join(params)
        return base

    raise ValueError(f"Unknown scheme: {scheme}")


# ── URI parsing ───────────────────────────────────────────────────────────

def parse_endpoint(uri: str) -> Endpoint:
    """Parse a callback endpoint URI into an Endpoint object.

    Accepts:
        file:///path/to/file
        fifo:///path/to/fifo
        prompt://target/session?template=...&force=true
        none://
        /path/to/file              (bare path → file://)
    """
    # Bare file path — treat as file://
    if uri.startswith("/"):
        return Endpoint(scheme="file", path=uri)

    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme == "none":
        return Endpoint(scheme="none")

    if scheme in ("file", "fifo"):
        # urlparse of file:///tmp/foo gives netloc="" path="/tmp/foo"
        filepath = unquote(parsed.netloc + parsed.path)
        if not filepath:
            raise ValueError(f"No path in {uri}")
        return Endpoint(scheme=scheme, path=filepath)

    if scheme == "prompt":
        target = parsed.netloc
        session = parsed.path.lstrip("/") if parsed.path else ""
        qs = parse_qs(parsed.query)
        template = qs.get("template", [""])[0]
        submit = qs.get("submit", ["true"])[0].lower() != "false"
        force = qs.get("force", ["false"])[0].lower() == "true"
        return Endpoint(
            scheme="prompt",
            path=target,
            session=session,
            template=template,
            submit=submit,
            force=force,
        )

    if scheme == "uai":
        # uai://session/<tracking_id>[/prompt]  — resolve to a prompt:// endpoint.
        # Action-aware (see lib_uri): only None/"prompt" execute as a prompt callback;
        # a non-prompt delivery action (message/notify-batched/…) must NOT silently
        # become a prompt send — reject it so the caller routes it through delivery.
        _ensure_session_mgmt_on_path()  # lib_uri lives in session_mgmt
        from uai_toolkit.session_mgmt.lib_uri import parse_uri
        p = parse_uri(uri)
        entity_type = p.entity_type or parsed.netloc
        entity_id = p.entity_id
        if entity_type != "session" or not entity_id:
            raise ValueError(f"Cannot resolve {uri} — expected uai://session/<id>")
        if p.action not in (None, "prompt"):
            raise ValueError(
                f"Cannot resolve {uri} as a callback — action '{p.action}' is a "
                f"delivery action, not an executable prompt callback. Route it "
                f"through the delivery/notification layer, not callback execution.")
        qs = parse_qs(parsed.query)
        submit = qs.get("submit", ["true"])[0].lower() != "false"
        force = qs.get("force", ["false"])[0].lower() == "true"
        template = qs.get("template", [""])[0]
        return _resolve_uai_session(entity_id, submit=submit, force=force, template=template)

    raise ValueError(f"Unknown scheme: {scheme}")


# ── Execution ─────────────────────────────────────────────────────────────

def execute(endpoint: Endpoint, message: str) -> CallbackResult:
    """Deliver a message to the given endpoint."""
    if endpoint.scheme == "none":
        return CallbackResult(success=True, message="no-op", endpoint_type="none")

    if endpoint.scheme in ("file", "fifo"):
        return _execute_file(endpoint, message)

    if endpoint.scheme == "prompt":
        return _execute_prompt(endpoint, message)

    return CallbackResult(
        success=False,
        message=f"Unknown scheme: {endpoint.scheme}",
        endpoint_type=endpoint.scheme,
    )


def execute_uri(uri: str, message: str) -> CallbackResult:
    """Parse URI and deliver. Convenience wrapper."""
    ep = parse_endpoint(uri)
    return execute(ep, message)


# ── Internal delivery implementations ─────────────────────────────────────

def _execute_file(endpoint: Endpoint, message: str) -> CallbackResult:
    """Write message to file or FIFO."""
    target_path = Path(endpoint.path)

    # For fifo://, verify it's actually a FIFO
    if endpoint.scheme == "fifo":
        if target_path.exists():
            if not stat.S_ISFIFO(target_path.stat().st_mode):
                return CallbackResult(
                    success=False,
                    message=f"Not a FIFO: {endpoint.path}",
                    endpoint_type="fifo",
                )
        else:
            return CallbackResult(
                success=False,
                message=f"FIFO does not exist: {endpoint.path}",
                endpoint_type="fifo",
            )

    try:
        content = message
        if endpoint.template:
            content = endpoint.template.replace("{message}", message)
        target_path.write_text(content)
        return CallbackResult(
            success=True,
            message=f"Written to {endpoint.path}",
            endpoint_type=endpoint.scheme,
        )
    except Exception as e:
        return CallbackResult(
            success=False,
            message=f"Write error: {e}",
            endpoint_type=endpoint.scheme,
        )


def _execute_prompt(endpoint: Endpoint, message: str) -> CallbackResult:
    """Send message via send_prompt.py."""
    if not SEND_PROMPT_SCRIPT.exists():
        return CallbackResult(
            success=False,
            message=f"send_prompt.py not found at {SEND_PROMPT_SCRIPT}",
            endpoint_type="prompt",
        )

    content = message
    if endpoint.template:
        content = endpoint.template.replace("{message}", message)

    cmd = [str(SEND_PROMPT_SCRIPT), "--target", endpoint.path, "--message", content]
    if endpoint.session:
        cmd.extend(["--session", endpoint.session])
    if endpoint.submit:
        cmd.append("--submit")
    if endpoint.force:
        cmd.append("--force")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode == 0:
            return CallbackResult(
                success=True,
                message=f"Prompt sent to {endpoint.path}",
                endpoint_type="prompt",
            )
        return CallbackResult(
            success=False,
            message=f"send_prompt.py failed (rc={proc.returncode}): {proc.stderr.strip()}",
            endpoint_type="prompt",
        )
    except subprocess.TimeoutExpired:
        return CallbackResult(
            success=False,
            message="send_prompt.py timed out",
            endpoint_type="prompt",
        )
    except Exception as e:
        return CallbackResult(
            success=False,
            message=f"send_prompt.py error: {e}",
            endpoint_type="prompt",
        )
