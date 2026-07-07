"""Tests for build_footer.py — footer assembly script.

TDD: Written before implementation. Tests cover:
- Brief footer format and fields
- Full footer format and fields
- Auto-cadence: turn 5 -> full, turn 6 -> brief
- Mode override: mode="full" always full regardless of turn count
- Missing context in store -> falls back to statusline file
- Ctx Used / Tokens removed from footers 2026-06-12 (context-anxiety mitigation)
- Custom format template from uai_toolkit.session_mgmt.store is used when present
- Tags appear in output
- Timestamp is local time
- Missing read_jsonl (subprocess fails) -> NA for Turn/Msgs
- Project name derived from path

Python 3.9 compatible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

# Ensure the parent package is importable
_SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from uai_toolkit.session_mgmt.store import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_dir(tmpdir, tracking_id):
    # type: (str, str) -> str
    """Create a temp session data dir with a seeded state file."""
    session_dir = os.path.join(tmpdir, tracking_id)
    os.makedirs(session_dir, exist_ok=True)
    return session_dir


def _seed_store(session_dir, tracking_id, overrides=None):
    # type: (str, str, dict | None) -> SessionStore
    """Create a SessionStore, persist defaults, and seed typical identity keys."""
    store = SessionStore(tracking_id=tracking_id, session_data_dir=session_dir)
    store.persist()
    # Seed identity keys (what ai_launcher normally does)
    defaults = {
        "session.display_name": "TestBot",
        "env.AI_TRACKING_ID": tracking_id,
        "env.AI_CLI_SESSION_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "env.AI_SESSION_PLATFORM": "claude_cli",
        "env.AI_PROJECT_DIR": "/Users/test/AI/ai_root",
        "context.used_pct": 42,
        "context.tokens": 85000,
    }
    if overrides:
        defaults.update(overrides)
    for k, v in defaults.items():
        try:
            store.set(k, v)
        except ValueError:
            # Some keys might not be in the namespace registry — skip
            pass
    return store


def _make_statusline(session_dir, tracking_id, used_pct=55, tokens=90000):
    # type: (str, str, int, int) -> str
    """Create a mock statusline file in the session dir."""
    uuid8 = tracking_id.split("_")[2] if len(tracking_id.split("_")) >= 4 else "abcd1234"
    filename = "statusline.{}.json".format(uuid8)
    filepath = os.path.join(session_dir, filename)
    data = {
        "context_window": {
            "used_percentage": used_pct,
            "total_tokens": tokens,
        },
        "cost": {"total_usd": 1.23},
    }
    with open(filepath, "w") as f:
        json.dump(data, f)
    return filepath


def _mock_read_jsonl_success(user_messages=5, message_count=42):
    # type: (int, int) -> mock.MagicMock
    """Return a mock for subprocess.run that returns successful read_jsonl summary."""
    result = mock.MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({
        "message_count": message_count,
        "user_messages": user_messages,
        "text_messages": 15,
        "assistant_messages": 10,
        "tool_calls": 17,
        "first_timestamp": "2026-04-30T10:00:00Z",
        "last_timestamp": "2026-04-30T12:00:00Z",
        "platform": "claude_cli",
        "first_message_preview": "Hello world...",
        "file_size_bytes": 12345,
    })
    return result


def _mock_read_jsonl_failure():
    # type: () -> mock.MagicMock
    """Return a mock for subprocess.run that simulates read_jsonl failure."""
    result = mock.MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = "Session not found"
    return result


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

TRACKING_ID = "20260430_120000_abcd1234_cla"


class TestBuildFooterBriefFormat:
    """Brief footer format and field tests."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_brief_footer_contains_expected_fields(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="design,footer",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        # Brief format line 1: timestamp | display_name | tracking_id | Ctx Used:XX% | Tokens:NNN | Turn:N
        assert "TestBot" in result
        assert TRACKING_ID in result
        # 2026-06-12: ctx/tokens removed from model-visible footers (context-anxiety mitigation)
        assert "Ctx Used:" not in result
        assert "Tokens:" not in result
        assert "Turn:" in result
        # Brief format line 2: Tags: ...
        assert "Tags: design,footer" in result

    def test_brief_footer_two_lines(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        lines = result.strip().split("\n")
        assert len(lines) == 3, "Brief footer should be separator + content + tags, got: {}".format(lines)


class TestBuildFooterFullFormat:
    """Full footer format and field tests."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_footer_contains_all_fields(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="arch,design",
                mode="full",
                session_data_dir=self.session_dir,
            )
        # Full format line 1: timestamp | display_name | tracking_id | cli_uuid
        assert "TestBot" in result
        assert TRACKING_ID in result
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result
        # Full format line 2: platform | project | Roles: | Turn: | Msgs: | Ctx Used: | Tokens:
        assert "claude_cli" in result
        assert "Roles:" in result
        assert "Turn:" in result
        assert "Msgs:" in result
        # 2026-06-12: ctx/tokens removed from model-visible footers (context-anxiety mitigation)
        assert "Ctx Used:" not in result
        assert "Tokens:" not in result
        # Full format line 3: Tags
        assert "Tags: arch,design" in result

    def test_full_footer_three_lines(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="full",
                session_data_dir=self.session_dir,
            )
        lines = result.strip().split("\n")
        assert len(lines) == 4, "Full footer should be separator + 2 content lines + tags, got: {}".format(lines)

    def test_full_footer_has_project_name(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="full",
                session_data_dir=self.session_dir,
            )
        # Project should be derived from /Users/test/AI/ai_root -> ai_root
        assert "ai_root" in result


class TestBuildFooterCadence:
    """Auto-cadence: full when turns % full_every == 0."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_turn_5_is_full(self):
        """Turn 5 should trigger full footer (5 % 5 == 0)."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                session_data_dir=self.session_dir,
            )
        # Full footer has cli_uuid on line 1
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in result
        # Full footer has Msgs
        assert "Msgs:" in result

    def test_turn_6_is_brief(self):
        """Turn 6 should be brief (6 % 5 != 0)."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=6)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                session_data_dir=self.session_dir,
            )
        # Brief footer does NOT have Msgs (only in full)
        assert "Msgs:" not in result
        # Brief footer is 2 lines
        lines = result.strip().split("\n")
        assert len(lines) == 3  # +1: FOOTER_SEPARATOR line

    def test_turn_10_is_full(self):
        """Turn 10 should trigger full footer (10 % 5 == 0)."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=10)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                session_data_dir=self.session_dir,
            )
        assert "Msgs:" in result


class TestBuildFooterModeOverride:
    """Mode override: explicit mode beats auto-cadence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mode_full_overrides_cadence(self):
        """mode='full' produces full footer even on a non-cadence turn."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="full",
                session_data_dir=self.session_dir,
            )
        assert "Msgs:" in result

    def test_mode_brief_overrides_cadence(self):
        """mode='brief' produces brief footer even on a cadence turn."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Msgs:" not in result
        lines = result.strip().split("\n")
        assert len(lines) == 3  # +1: FOOTER_SEPARATOR line


class TestBuildFooterFallback:
    """Graceful degradation: missing store data -> statusline -> NA."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_context_falls_back_to_statusline(self):
        """If context.* not in store, read from statusline file."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        # Seed store WITHOUT context keys
        store = SessionStore(tracking_id=TRACKING_ID, session_data_dir=self.session_dir)
        store.persist()
        try:
            store.set("session.display_name", "FallbackBot")
        except ValueError:
            pass
        try:
            store.set("env.AI_TRACKING_ID", TRACKING_ID)
        except ValueError:
            pass

        # Create statusline with context data
        _make_statusline(self.session_dir, TRACKING_ID, used_pct=77, tokens=150000)

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="fallback",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Ctx Used:" not in result
        assert "Tokens:" not in result

    def test_jsonl_statusline_with_current_usage(self):
        """Statusline JSONL with current_usage (v5.3 format) sums token counts."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = SessionStore(tracking_id=TRACKING_ID, session_data_dir=self.session_dir)
        store.persist()

        # Create a v5.3 JSONL statusline with current_usage (no total_tokens)
        uuid8 = TRACKING_ID.split("_")[2]
        filepath = os.path.join(self.session_dir, "statusline.{}.jsonl".format(uuid8))
        entry = json.dumps({
            "context_window": {
                "used_percentage": 33,
                "current_usage": {
                    "input_tokens": 5000,
                    "output_tokens": 3000,
                    "cache_creation_input_tokens": 1000,
                    "cache_read_input_tokens": 500,
                },
            },
        })
        with open(filepath, "w") as f:
            f.write(entry + "\n")

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="jsonl_test",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Ctx Used:" not in result
        assert "Tokens:" not in result

    def test_missing_statusline_gives_na(self):
        """If both store and statusline are missing, fields are NA."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = SessionStore(tracking_id=TRACKING_ID, session_data_dir=self.session_dir)
        store.persist()

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="na",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Ctx Used:" not in result
        assert "Tokens:" not in result

    def test_subprocess_failure_gives_na_for_turns(self):
        """If read_jsonl.py fails, Turn and Msgs are NA."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = _seed_store(self.session_dir, TRACKING_ID)

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_failure()):
            result = build_footer(
                TRACKING_ID,
                tags="no-jsonl",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Turn:NA" in result

    def test_subprocess_exception_gives_na_for_turns(self):
        """If subprocess.run raises an exception, Turn and Msgs are NA."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = _seed_store(self.session_dir, TRACKING_ID)

        with mock.patch("build_footer.subprocess.run", side_effect=FileNotFoundError("read_jsonl.py not found")):
            result = build_footer(
                TRACKING_ID,
                tags="no-script",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Turn:NA" in result

    def test_missing_display_name_uses_platform(self):
        """If display_name not set, falls back to platform name."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = SessionStore(tracking_id=TRACKING_ID, session_data_dir=self.session_dir)
        store.persist()
        try:
            store.set("env.AI_SESSION_PLATFORM", "claude_cli")
        except ValueError:
            pass

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "claude_cli" in result


class TestBuildFooterCustomFormat:
    """Custom format templates from uai_toolkit.session_mgmt.store."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_custom_brief_format(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        try:
            self.store.set("footer.format_brief", "{display_name} | Turn:{turns} | Tags: {tags}")
        except ValueError:
            pass

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="custom",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert result.strip() == "TestBot | Turn:3 | Tags: custom"

    def test_custom_full_every(self):
        """Custom full_every=3 changes cadence."""
        from uai_toolkit.session_mgmt.build_footer import build_footer

        try:
            self.store.set("footer.full_every", 3)
        except ValueError:
            pass

        # Turn 3 should be full with full_every=3
        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                session_data_dir=self.session_dir,
            )
        assert "Msgs:" in result


class TestBuildFooterTags:
    """Tags always appear in output."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tags_in_brief(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="alpha,beta,gamma",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        assert "Tags: alpha,beta,gamma" in result

    def test_tags_in_full(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="delta,epsilon",
                mode="full",
                session_data_dir=self.session_dir,
            )
        assert "Tags: delta,epsilon" in result


class TestBuildFooterTimestamp:
    """Timestamp is local time."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_timestamp_is_local(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=3)):
            result = build_footer(
                TRACKING_ID,
                tags="time",
                mode="brief",
                session_data_dir=self.session_dir,
            )
        # The footer's first field is a timestamp. Verify it matches today's local date.
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        assert date_str in result, "Footer should contain today's local date"


class TestBuildFooterProjectName:
    """Project name derived from AI_PROJECT_DIR path."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_from_path(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = _seed_store(self.session_dir, TRACKING_ID, overrides={
            "env.AI_PROJECT_DIR": "/Users/test/AI/my_project",
        })

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="proj",
                mode="full",
                session_data_dir=self.session_dir,
            )
        assert "my_project" in result

    def test_missing_project_gives_na(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        store = SessionStore(tracking_id=TRACKING_ID, session_data_dir=self.session_dir)
        store.persist()

        # Clear AI_PROJECT_DIR so the missing-project path is actually exercised
        # (previously this test passed via the unrelated "Ctx Used:NA" substring)
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            os.environ.pop("AI_PROJECT_DIR", None)
            result = build_footer(
                TRACKING_ID,
                tags="proj",
                mode="full",
                session_data_dir=self.session_dir,
            )
        # Project should show NA when not set
        assert " | NA | Roles:" in result


class TestBuildFooterOptionalFields:
    """Docs, MSlots, Artifacts are omitted if not set in full mode."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = _make_session_dir(self.tmpdir, TRACKING_ID)
        self.store = _seed_store(self.session_dir, TRACKING_ID)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_optional_fields_omitted_when_not_set(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="full",
                session_data_dir=self.session_dir,
            )
        # Line 3 should still have Tags but optional fields before it should be clean
        # The line should not have empty "Docs: |" or "MSlots: |" patterns
        last_line = result.strip().split("\n")[-1]
        assert "Tags: test" in last_line

    def test_optional_fields_present_when_set(self):
        from uai_toolkit.session_mgmt.build_footer import build_footer

        try:
            self.store.set("loaded.docs", "3")
        except ValueError:
            pass
        try:
            self.store.set("loaded.mslots", "5")
        except ValueError:
            pass
        try:
            self.store.set("conversation.artifacts", "2")
        except ValueError:
            pass

        with mock.patch("build_footer.subprocess.run", return_value=_mock_read_jsonl_success(user_messages=5)):
            result = build_footer(
                TRACKING_ID,
                tags="test",
                mode="full",
                session_data_dir=self.session_dir,
            )
        assert "Docs:3" in result
        assert "MSlots:5" in result
        assert "Artifacts:2" in result
