"""Configurable LLM client for the toolkit.

Every toolkit feature that wants a language model calls through here, and every one
of them is configured SEPARATELY: each feature names its own endpoint chain, so a
site can point (say) session summarization at a local model while leaving code
review pointed at a hosted one — or leave either unconfigured.

Nothing is configured by default. With no config file, every feature resolves to an
empty chain and simply does not run, so the package makes no network connections
out of the box.

See client.py for the API and llm_endpoints.example.json for the config shape.
"""

from uai_toolkit.llm.client import (  # noqa: F401
    FEATURES,
    complete,
    complete_json,
    complete_with_endpoint,
    is_configured,
    load_endpoints,
)
