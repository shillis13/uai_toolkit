"""Tests for session_ops.send_raw — the raw TTY-injection lane.

send_raw is the third TTY lane: raw, non-command turn-trigger (no sender wrapper,
not a slash command). Infra/orchestration-only. Must refuse command-like payloads
so it can't backdoor send_slash_command's gate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from uai_toolkit.session_mgmt import session_ops as SO  # noqa: E402


def test_send_raw_delivers_and_submits(monkeypatch):
    calls = []
    monkeypatch.setattr(SO, "write_to",
                        lambda name, text, press_enter=False, substrate=None:
                        calls.append((name, text, press_enter, substrate)))
    SO.send_raw("sess-A", "<<<SESSION RESUMED>>>2026-... <<<END SESSION RESUMED>>>")
    assert len(calls) == 1
    name, text, press_enter, _ = calls[0]
    assert name == "sess-A"
    assert text.startswith("<<<SESSION RESUMED>>>")
    assert press_enter is True            # it's a turn-trigger → must submit


def test_send_raw_refuses_leading_slash(monkeypatch):
    import pytest
    monkeypatch.setattr(SO, "write_to", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not send")))
    for payload in ("/compact", "  /clear", "/exit now"):
        with pytest.raises(ValueError):
            SO.send_raw("sess-A", payload)


def test_send_raw_allows_slash_not_at_start(monkeypatch):
    sent = []
    monkeypatch.setattr(SO, "write_to",
                        lambda name, text, press_enter=False, substrate=None: sent.append(text))
    SO.send_raw("sess-A", "use the path a/b/c and continue")   # internal slash is fine
    assert sent == ["use the path a/b/c and continue"]


def test_send_raw_passes_substrate(monkeypatch):
    got = {}
    monkeypatch.setattr(SO, "write_to",
                        lambda name, text, press_enter=False, substrate=None:
                        got.update(substrate=substrate, press_enter=press_enter))
    SO.send_raw("s", "hello", substrate="tmux")
    assert got["substrate"] == "tmux" and got["press_enter"] is True
