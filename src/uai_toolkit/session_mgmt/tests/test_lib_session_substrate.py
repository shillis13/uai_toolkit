"""Tests for substrate binary resolution fallbacks."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from uai_toolkit.session_mgmt import lib_session_substrate as substrate  # noqa: E402


def test_find_binary_uses_fallback_dir_when_path_is_missing(monkeypatch, tmp_path):
    candidate = tmp_path / "tmux"
    candidate.write_text("#!/bin/sh\nexit 0\n")
    candidate.chmod(0o755)

    monkeypatch.setattr(substrate.shutil, "which", lambda _name: None)
    monkeypatch.setattr(substrate, "_FALLBACK_BINARY_DIRS", (str(tmp_path),))

    result = substrate._find_binary("tmux")
    assert result == candidate


def test_require_binary_raises_clear_error_when_missing(monkeypatch):
    monkeypatch.setattr(substrate, "_find_binary", lambda _name: None)

    try:
        substrate._require_binary("tmux")
        raise AssertionError("Expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "common fallback locations" in str(exc)


def test_derive_tmux_server_name_uses_ai_root_basename():
    result = substrate.derive_tmux_server_name("/tmp/devTrees/AI_ROOT_uai-resurrection")
    assert result == "AI_ROOT_uai-resurrection"


def test_build_tmux_command_includes_server_flag():
    cmd = substrate.build_tmux_command(
        ["list-sessions", "-F", "#{session_name}"],
        tmux_bin="/opt/homebrew/bin/tmux",
        server_name="ai_root",
    )
    assert cmd[:3] == ["/opt/homebrew/bin/tmux", "-L", "ai_root"]


def test_build_tmux_command_omits_server_flag_for_legacy_default():
    cmd = substrate.build_tmux_command(
        ["list-sessions", "-F", "#{session_name}"],
        tmux_bin="/opt/homebrew/bin/tmux",
        server_name=None,
    )
    assert cmd == ["/opt/homebrew/bin/tmux", "list-sessions", "-F", "#{session_name}"]
