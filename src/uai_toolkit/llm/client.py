#!/usr/bin/env python3
"""Per-feature configurable LLM client.

WHY THIS EXISTS
    Several toolkit features can use a language model (code review, session
    assessment, summarization, ...). Each one must be configurable INDEPENDENTLY:
    different features want different models, and a site may want some enabled and
    others off. This module is the single place that decides where a given feature
    sends its request.

SECURITY POSTURE
    - No endpoint is built in. No default host, no assumed local port, and no
      endpoint synthesized from an ambient API key. Absent configuration, every
      feature resolves to an empty chain and does nothing.
    - `base_url` is required on every endpoint; there is no implicit destination.
    - Credentials are never stored in config — config names an ENVIRONMENT VARIABLE
      to read the key from (`api_key_env`).

SUPPORTED ENDPOINT KINDS
    "openai"    POST {base_url}/v1/chat/completions
                Works with a local OpenAI-compatible server (the local LLLM, vLLM,
                Ollama, LM Studio, llama.cpp) and with hosted OpenAI-compatible APIs.
    "anthropic" POST {base_url}/v1/messages

CONFIG
    Location, first match wins:
      1. $AI_LLM_ENDPOINTS                  (explicit path to the JSON file)
      2. $AI_ROOT/config/llm_endpoints.json (per-instance config)
    A single feature can also be pointed at its own file with
    $AI_LLM_ENDPOINTS_<FEATURE> (uppercased, e.g. AI_LLM_ENDPOINTS_QUALITY_GATE).

    Shape — see llm_endpoints.example.json:
      {"features": {"<feature>": {"endpoints": [ {endpoint}, ... ]}}}

    Endpoints are tried IN ORDER until one returns a usable answer, so a chain can
    read "try the local model first, fall back to a hosted one".

USAGE
    from uai_toolkit.llm import complete, is_configured
    if is_configured("session_assess"):
        text = complete("session_assess", SYSTEM_PROMPT, transcript_tail)
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

# The features that may use a model. Each is configured separately; a name absent
# from config means that feature is disabled.
FEATURES = (
    "quality_gate",          # Stop-hook response review
    "intent_check",          # Stop-hook "stated intent without action" check
    "session_assess",        # work: structured per-session assessment
    "session_summarize",     # work: free-text per-session summaries
    "consolidation_summary",  # jsonl: summarize a turn-range when compacting
    "mcp_prompt",            # MCP: ad-hoc prompt tool
)

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_TOKENS = 500
ENDPOINT_KINDS = ("openai", "anthropic")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROTECTED_BODY_KEYS = {"messages", "model", "max_tokens", "system"}


def _config_path(feature: str | None = None) -> Path | None:
    """Resolve the config file path, or None if no config is present."""
    if feature:
        per = os.environ.get(f"AI_LLM_ENDPOINTS_{feature.upper()}")
        if per:
            return Path(per).expanduser()
    explicit = os.environ.get("AI_LLM_ENDPOINTS")
    if explicit:
        return Path(explicit).expanduser()
    ai_root = os.environ.get("AI_ROOT")
    if ai_root:
        return Path(ai_root).expanduser() / "config" / "llm_endpoints.json"
    return None


def _valid_endpoint(raw: object) -> dict | None:
    """Return a normalized endpoint dict, or None when its schema is unsafe.

    Config is administrator-owned, but rejecting malformed entries here keeps the
    public ``complete()`` contract true: bad JSON values can disable one endpoint,
    never crash a hook or redirect a request through an implicit destination.
    """
    if not isinstance(raw, dict) or raw.get("enabled", True) is False:
        return None
    if "enabled" in raw and not isinstance(raw["enabled"], bool):
        return None

    kind = raw.get("kind", "openai")
    base_url = raw.get("base_url")
    model = raw.get("model")
    if kind not in ENDPOINT_KINDS or not isinstance(base_url, str) or not base_url.strip():
        return None
    try:
        parsed = urlsplit(base_url.strip())
    except ValueError:
        return None
    if (parsed.scheme not in ("http", "https") or not parsed.netloc
            or parsed.query or parsed.fragment or any(ch.isspace() for ch in base_url)):
        return None
    # Credentials belong in environment variables, never URL userinfo.
    if parsed.username is not None or parsed.password is not None:
        return None
    if not isinstance(model, str) or not model.strip():
        return None

    key_env = raw.get("api_key_env")
    if key_env is not None and (
        not isinstance(key_env, str) or not _ENV_NAME_RE.fullmatch(key_env)
    ):
        return None
    for key in ("timeout", "max_tokens"):
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(value) or value <= 0 or (key == "max_tokens" and not float(value).is_integer()):
            return None
    extra = raw.get("extra_body")
    if extra is not None and (
        not isinstance(extra, dict) or _PROTECTED_BODY_KEYS.intersection(extra)
    ):
        return None

    endpoint = dict(raw)
    endpoint["kind"] = kind
    endpoint["base_url"] = base_url.strip().rstrip("/")
    endpoint["model"] = model.strip()
    if "max_tokens" in endpoint:
        endpoint["max_tokens"] = int(endpoint["max_tokens"])
    return endpoint


def load_endpoints(feature: str) -> list[dict]:
    """Return the endpoint chain configured for `feature`, or [] if unconfigured.

    An empty list is the normal, safe state: the caller must treat it as
    "this feature is turned off" and skip its work.
    """
    if not isinstance(feature, str) or feature not in FEATURES:
        return []
    per_feature_path = os.environ.get(f"AI_LLM_ENDPOINTS_{feature.upper()}")
    path = _config_path(feature)
    if not path:
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    # A shared/global file MUST name the feature explicitly. Only the dedicated
    # AI_LLM_ENDPOINTS_<FEATURE> file may use the compact bare-list or top-level
    # {"endpoints": [...]} shape; otherwise one accidental global list would
    # enable every feature and violate the independent-config contract.
    feats = data.get("features") if isinstance(data, dict) else None
    if isinstance(feats, dict):
        entry = feats.get(feature) or {}
        eps = entry.get("endpoints") if isinstance(entry, dict) else entry
    elif per_feature_path:
        eps = data if isinstance(data, list) else (
            data.get("endpoints") if isinstance(data, dict) else None
        )
    else:
        eps = None

    if not isinstance(eps, list):
        return []
    # Keep only well-formed, enabled endpoints that name an explicit destination.
    return [ep for raw in eps if (ep := _valid_endpoint(raw)) is not None]


def is_configured(feature: str) -> bool:
    """True when `feature` has at least one usable endpoint configured."""
    return bool(load_endpoints(feature))


def _import_httpx():
    """httpx is an optional extra; absent it, every feature is simply unavailable."""
    try:
        import httpx  # noqa: PLC0415
        return httpx
    except ImportError:
        return None


def _auth_key(ep: dict) -> str | None:
    """Read this endpoint's credential from the env var the config names."""
    key_env = ep.get("api_key_env")
    return os.environ.get(key_env) if key_env else None


def _api_url(base: str, resource: str) -> str:
    """Accept either a host root or an OpenAI-style base already ending in /v1."""
    return f"{base}{resource if base.endswith('/v1') else '/v1' + resource}"


def _call_openai(httpx, ep: dict, system: str, user: str,
                 max_tokens: int) -> str | None:
    """POST to an OpenAI-compatible /v1/chat/completions endpoint."""
    base = str(ep["base_url"]).rstrip("/")
    headers = {"content-type": "application/json"}
    key = _auth_key(ep)
    if ep.get("api_key_env") and not key:
        return None      # never transmit content when configured auth is absent
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": ep["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": ep.get("max_tokens", max_tokens),
    }
    if ep.get("extra_body"):
        # Schema validation excludes prompt/model/token fields from this extension.
        body.update(ep["extra_body"])
    with httpx.Client(timeout=ep.get("timeout", DEFAULT_TIMEOUT)) as client:
        r = client.post(_api_url(base, "/chat/completions"), json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content")
    return content if isinstance(content, str) else None


def _call_anthropic(httpx, ep: dict, system: str, user: str,
                    max_tokens: int) -> str | None:
    """POST to an Anthropic /v1/messages endpoint."""
    key = _auth_key(ep)
    if not key:
        return None      # configured but no credential present -> skip, don't error
    base = str(ep["base_url"]).rstrip("/")
    headers = {
        "x-api-key": key,
        "anthropic-version": ep.get("api_version", "2023-06-01"),
        "content-type": "application/json",
    }
    body = {
        "model": ep["model"],
        "max_tokens": ep.get("max_tokens", max_tokens),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=ep.get("timeout", DEFAULT_TIMEOUT)) as client:
        r = client.post(_api_url(base, "/messages"), json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
    parts = data.get("content") or []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            return text if isinstance(text, str) else None
    return None


_CALLERS = {"openai": _call_openai, "anthropic": _call_anthropic}


def complete_with_endpoint(feature: str, system: str, user: str, *,
                           max_tokens: int = DEFAULT_MAX_TOKENS) -> tuple[str, dict] | None:
    """Send one prompt and return ``(text, endpoint_metadata)``, or None.

    Returns None — never raises — when the feature is unconfigured, httpx is not
    installed, every endpoint fails, or a credential is missing. Callers treat
    None as "no answer available" and carry on.
    """
    if (not isinstance(system, str) or not isinstance(user, str)
            or isinstance(max_tokens, bool) or not isinstance(max_tokens, int)
            or max_tokens < 1):
        return None
    try:
        endpoints = load_endpoints(feature)
    except Exception:
        return None
    if not endpoints:
        return None
    try:
        httpx = _import_httpx()
    except Exception:
        return None
    if httpx is None:
        return None

    for ep in endpoints:
        caller = _CALLERS.get(ep["kind"])
        if caller is None:
            continue
        try:
            out = caller(httpx, ep, system, user, max_tokens)
        except Exception:
            continue          # try the next endpoint in the chain
        if isinstance(out, str) and out.strip():
            return out, dict(ep)
    return None


def complete(feature: str, system: str, user: str, *,
             max_tokens: int = DEFAULT_MAX_TOKENS) -> str | None:
    """Send one prompt for ``feature``; return model text, or None. Never raises."""
    result = complete_with_endpoint(feature, system, user, max_tokens=max_tokens)
    return result[0] if result else None


def complete_json(feature: str, system: str, user: str, *,
                  max_tokens: int = DEFAULT_MAX_TOKENS) -> dict | None:
    """`complete`, but parse the reply as JSON (tolerating code fences)."""
    text = complete(feature, system, user, max_tokens=max_tokens)
    if not text:
        return None
    body = text.strip()
    if body.startswith("```"):                       # strip a ```json fence
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(body[start:end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
