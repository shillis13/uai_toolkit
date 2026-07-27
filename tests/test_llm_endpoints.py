"""Endpoint-contract tests for the per-feature LLM client.

These stand up REAL local HTTP servers that speak the two wire protocols we
support, then drive the client against them:

  * ``anthropic`` kind -> POST {base_url}/v1/messages
      the shape Claude / Claude Code endpoints use
  * ``openai`` kind    -> POST {base_url}/v1/chat/completions
      the shape Codex / OpenAI-compatible endpoints use (also vLLM, Ollama,
      LM Studio, and a locally-hosted model server)

Local servers, not the vendors: the point is to prove our request shape and
response parsing match each protocol, and a test must never depend on network
access, credentials, or send anyone's data off the machine.

Also asserts the security posture: unconfigured means no request at all.
"""
from __future__ import annotations

import asyncio
import json
import os
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from uai_toolkit.llm import client as llm_client

pytest.importorskip("httpx", reason="the LLM client needs the [full] extra")

# What each fake endpoint should answer with.
ANTHROPIC_REPLY = "answer via the anthropic protocol"
OPENAI_REPLY = "answer via the openai protocol"


class _Recorder(BaseHTTPRequestHandler):
    """Serves both protocols and records what it received."""

    received: list = []          # (path, headers, parsed_body) per request

    def log_message(self, *_args):        # silence the test run
        pass

    def do_POST(self):                    # noqa: N802  (stdlib API)
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append((self.path, dict(self.headers), body))

        if self.path == "/v1/messages":                    # anthropic shape
            payload = {"content": [{"type": "text", "text": ANTHROPIC_REPLY}]}
        elif self.path == "/v1/chat/completions":          # openai/codex shape
            payload = {"choices": [{"message": {"role": "assistant",
                                                "content": OPENAI_REPLY}}]}
        else:
            self.send_response(404)
            self.end_headers()
            return

        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class _FastServer(HTTPServer):
    """HTTPServer without the startup reverse-DNS lookup.

    HTTPServer.server_bind() calls socket.getfqdn(), which can stall for ~35s on
    some network configurations and made this suite painful to run. We only ever
    talk to 127.0.0.1, so the resolved name is irrelevant.
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


@pytest.fixture()
def server():
    """A local HTTP server speaking both protocols. Yields its base_url."""
    _Recorder.received = []
    httpd = _FastServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Every test starts with NO endpoint configuration."""
    for var in list(os.environ):
        if var.startswith("AI_LLM_ENDPOINTS") or var in ("AI_ROOT", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)


def _write_config(tmp_path, feature, endpoints):
    path = tmp_path / "llm_endpoints.json"
    path.write_text(json.dumps({"features": {feature: {"endpoints": endpoints}}}))
    return str(path)


# ── the two endpoint protocols ────────────────────────────────────────────────

def test_openai_protocol_codex_shape(server, tmp_path, monkeypatch):
    """openai kind: posts to /v1/chat/completions and reads choices[].message."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "codex-like", "kind": "openai", "base_url": server,
         "model": "gpt-test", "api_key_env": "TEST_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    monkeypatch.setenv("TEST_KEY", "secret-token")

    out = llm_client.complete("mcp_prompt", "system prompt", "user text")

    assert out == OPENAI_REPLY
    path, headers, body = _Recorder.received[-1]
    assert path == "/v1/chat/completions"
    assert body["model"] == "gpt-test"
    # system + user must both be carried, in the OpenAI messages array
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    assert body["messages"][0]["content"] == "system prompt"
    assert body["messages"][1]["content"] == "user text"
    # credential comes from the NAMED env var, as a bearer token
    assert headers.get("Authorization") == "Bearer secret-token"


def test_anthropic_protocol_claude_shape(server, tmp_path, monkeypatch):
    """anthropic kind: posts to /v1/messages and reads the text content block."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "claude-like", "kind": "anthropic", "base_url": server,
         "model": "claude-test", "api_key_env": "TEST_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    monkeypatch.setenv("TEST_KEY", "secret-token")

    out = llm_client.complete("mcp_prompt", "system prompt", "user text")

    assert out == ANTHROPIC_REPLY
    path, headers, body = _Recorder.received[-1]
    assert path == "/v1/messages"
    assert body["model"] == "claude-test"
    # Anthropic carries the system prompt in its own field, not in messages
    assert body["system"] == "system prompt"
    assert body["messages"] == [{"role": "user", "content": "user text"}]
    # credential goes in x-api-key, and the version header is required
    assert headers.get("x-api-key") == "secret-token"
    assert headers.get("anthropic-version")


def test_anthropic_without_credential_makes_no_request(server, tmp_path, monkeypatch):
    """A configured anthropic endpoint with no key must skip, not send unauthed."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "claude-like", "kind": "anthropic", "base_url": server,
         "model": "claude-test", "api_key_env": "ABSENT_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)

    assert llm_client.complete("mcp_prompt", "system", "user") is None
    assert _Recorder.received == []


# ── chain behavior across the two protocols ───────────────────────────────────

def test_chain_falls_back_between_protocols(server, tmp_path, monkeypatch):
    """A dead first endpoint falls through to a live one of the other kind."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        # nothing listens here
        {"name": "down", "kind": "openai", "base_url": "http://127.0.0.1:1",
         "model": "m", "timeout": 1},
        {"name": "up", "kind": "anthropic", "base_url": server,
         "model": "claude-test", "api_key_env": "TEST_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    monkeypatch.setenv("TEST_KEY", "k")

    assert llm_client.complete("mcp_prompt", "system", "user") == ANTHROPIC_REPLY


# ── security posture ──────────────────────────────────────────────────────────

def test_unconfigured_sends_nothing(server):
    """No config -> no request, for every feature."""
    for feature in llm_client.FEATURES:
        assert llm_client.is_configured(feature) is False
        assert llm_client.complete(feature, "system", "user") is None
    assert _Recorder.received == []


def test_api_key_alone_configures_nothing(monkeypatch):
    """An ambient credential must never synthesize an endpoint."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-enable-anything")
    for feature in llm_client.FEATURES:
        assert llm_client.is_configured(feature) is False


def test_features_are_isolated(server, tmp_path, monkeypatch):
    """Configuring one feature must not enable any other."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "only", "kind": "openai", "base_url": server, "model": "m"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)

    assert llm_client.is_configured("mcp_prompt") is True
    for other in (f for f in llm_client.FEATURES if f != "mcp_prompt"):
        assert llm_client.is_configured(other) is False


def test_endpoint_without_base_url_is_rejected(tmp_path, monkeypatch):
    """No implicit destination: an endpoint missing base_url is dropped."""
    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "no-host", "kind": "anthropic", "model": "m",
         "api_key_env": "TEST_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    monkeypatch.setenv("TEST_KEY", "k")

    assert llm_client.load_endpoints("mcp_prompt") == []
    assert llm_client.complete("mcp_prompt", "system", "user") is None


# ── the MCP tool on top of the client ─────────────────────────────────────────

def test_mcp_tool_uses_configured_endpoint(server, tmp_path, monkeypatch):
    """sessions_reason_on_text routes through mcp_prompt's configured endpoint."""
    pytest.importorskip("mcp.types", reason="MCP tool needs the [mcp] extra")
    from uai_toolkit.mcp.sessions.tools import sessions_local_llm as tool

    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "codex-like", "kind": "openai", "base_url": server, "model": "m"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)

    out = asyncio.run(tool.call_tool("sessions_reason_on_text",
                                     {"prompt": "summarize", "input_text": "hello"}))
    assert out[0].text == OPENAI_REPLY


def test_mcp_tool_unconfigured_is_a_notice_not_a_call(server):
    """Unconfigured: the tool explains itself and sends nothing."""
    pytest.importorskip("mcp.types", reason="MCP tool needs the [mcp] extra")
    from uai_toolkit.mcp.sessions.tools import sessions_local_llm as tool

    out = asyncio.run(tool.call_tool("sessions_reason_on_text",
                                     {"prompt": "summarize", "input_text": "hello"}))
    assert "no endpoint configured" in out[0].text.lower()
    assert _Recorder.received == []


def test_mcp_file_read_is_bounded_before_sending(server, tmp_path, monkeypatch):
    """The file tool reads/sends only its declared character cap."""
    pytest.importorskip("mcp.types", reason="MCP tool needs the [mcp] extra")
    from uai_toolkit.mcp.sessions.tools import sessions_local_llm as tool

    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "codex-like", "kind": "openai", "base_url": server, "model": "m"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    source = tmp_path / "large.txt"
    source.write_text("x" * (tool.MAX_FILE_CHARS + 50))

    out = asyncio.run(tool.call_tool(
        "sessions_reason_on_file", {"prompt": "inspect", "file_path": str(source)},
    ))

    assert out[0].text == OPENAI_REPLY
    _path, _headers, body = _Recorder.received[-1]
    sent = body["messages"][1]["content"]
    assert sent == "x" * tool.MAX_FILE_CHARS + "\n...[truncated]"


def test_mcp_list_models_is_configuration_only(server, tmp_path, monkeypatch):
    """Listing configured models must not probe or contact the endpoint."""
    pytest.importorskip("mcp.types", reason="MCP tool needs the [mcp] extra")
    from uai_toolkit.mcp.sessions.tools import sessions_local_llm as tool

    cfg = _write_config(tmp_path, "mcp_prompt", [
        {"name": "configured", "kind": "openai", "base_url": server,
         "model": "m", "api_key_env": "TEST_KEY"},
    ])
    monkeypatch.setenv("AI_LLM_ENDPOINTS", cfg)
    monkeypatch.setenv("TEST_KEY", "never-display-this")

    out = asyncio.run(tool.call_tool("sessions_list_models", {}))

    assert "configured" in out[0].text
    assert server in out[0].text
    assert "never-display-this" not in out[0].text
    assert _Recorder.received == []


def test_mcp_tool_offers_no_server_lifecycle_tools():
    """The local-server lifecycle tools must NOT be advertised here."""
    pytest.importorskip("mcp.types", reason="MCP tool needs the [mcp] extra")
    from uai_toolkit.mcp.sessions.tools import sessions_local_llm as tool

    names = {t["name"] for t in tool.tools()}
    assert names == {"sessions_reason_on_text", "sessions_reason_on_file",
                     "sessions_list_models"}
    for gone in ("sessions_server_start", "sessions_server_stop",
                 "sessions_server_status", "sessions_switch_model"):
        assert gone not in names
