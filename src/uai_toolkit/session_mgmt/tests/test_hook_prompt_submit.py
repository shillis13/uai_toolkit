"""
Tests for hook_prompt_submit.py — UserPromptSubmit hook that caches context
data from the statusline into session state.

Tests run the hook as a subprocess (matching real hook invocation) and verify
state file contents afterward.
"""

import json
import os
import subprocess
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# Make store.py importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


# Path to the hook script under test
HOOK_SCRIPT = str(Path(__file__).resolve().parent.parent / "hook_prompt_submit.py")

# Python interpreter from MCP venv (same one running pytest)
PYTHON = sys.executable


def _make_statusline(session_dir, used_pct=32, cost_usd=12.50,
                     input_tokens=100, output_tokens=200,
                     cache_creation=300, cache_read=400):
    """Create a statusline JSON file in the session dir with discriminated name."""
    # Extract uuid8 from dir name
    parts = os.path.basename(session_dir).split("_")
    uuid8 = parts[2] if len(parts) >= 4 else "abcd1234"

    statusline = {
        "session_id": "fake-uuid-1234",
        "cost": {
            "total_cost_usd": cost_usd,
        },
        "context_window": {
            "used_percentage": used_pct,
            "remaining_percentage": 100 - used_pct,
            "context_window_size": 1000000,
            "current_usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        },
    }
    filename = "statusline.{}.json".format(uuid8)
    filepath = os.path.join(session_dir, filename)
    with open(filepath, "w") as f:
        json.dump(statusline, f)
    return filepath


def _make_statusline_jsonl(session_dir, used_pct=32, cost_usd=12.50,
                           input_tokens=100, output_tokens=200,
                           cache_creation=300, cache_read=400):
    """Create a statusline JSONL file (v5.3 append-only format)."""
    parts = os.path.basename(session_dir).split("_")
    uuid8 = parts[2] if len(parts) >= 4 else "abcd1234"

    # Simulate multiple lines (append-only) — last line is the current state
    old_entry = json.dumps({"context_window": {"used_percentage": 5}})
    current_entry = json.dumps({
        "session_id": "fake-uuid-1234",
        "cost": {"total_cost_usd": cost_usd},
        "context_window": {
            "used_percentage": used_pct,
            "remaining_percentage": 100 - used_pct,
            "context_window_size": 1000000,
            "current_usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        },
    })
    filename = "statusline.{}.jsonl".format(uuid8)
    filepath = os.path.join(session_dir, filename)
    with open(filepath, "w") as f:
        f.write(old_entry + "\n")
        f.write(current_entry + "\n")
    return filepath


def _run_hook(env_override=None, stdin_data=None):
    """Run the hook script as a subprocess and return the CompletedProcess."""
    env = os.environ.copy()
    # Remove any existing session env vars to isolate tests
    for key in ("AI_TRACKING_ID", "AI_SESSION_DIR"):
        env.pop(key, None)
    if env_override:
        env.update(env_override)

    result = subprocess.run(
        [PYTHON, HOOK_SCRIPT],
        input=stdin_data or '{"session_id": "fake"}',
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return result


def _read_state_from_dir(session_dir):
    """Read the state JSON file from a session dir and return the state dict."""
    for f in os.listdir(session_dir):
        if f.startswith("state.") and f.endswith(".json"):
            with open(os.path.join(session_dir, f)) as fh:
                data = json.load(fh)
            return data.get("state", {})
    return {}


class TestHookPromptSubmitValid:
    """Tests with valid statusline and env vars."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_140000_beef1234_cla"
        self.session_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_context_keys_written_to_store(self):
        """Hook reads statusline and writes context.* keys to state."""
        _make_statusline(self.session_dir, used_pct=45, cost_usd=8.75,
                         input_tokens=100, output_tokens=200,
                         cache_creation=300, cache_read=400)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0, "Hook should exit 0; stderr: " + result.stderr

        state = _read_state_from_dir(self.session_dir)
        assert state.get("context.used_pct") == 45
        assert state.get("context.tokens") == 1000  # 100+200+300+400
        assert state.get("context.cost_usd") == 8.75
        assert "context.updated_at" in state

    def test_token_count_is_sum_of_all_types(self):
        """context.tokens should be the sum of all token types in current_usage."""
        _make_statusline(self.session_dir,
                         input_tokens=10, output_tokens=20,
                         cache_creation=30, cache_read=40)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        assert state.get("context.tokens") == 100  # 10+20+30+40

    def test_updated_at_is_local_iso_timestamp(self):
        """context.updated_at should be a local ISO timestamp."""
        _make_statusline(self.session_dir)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        ts = state.get("context.updated_at", "")
        # Should parse as a datetime and not be UTC (has offset or no Z suffix)
        assert ts, "updated_at should not be empty"
        # Should be parseable
        parsed = datetime.fromisoformat(ts)
        assert parsed is not None

    def test_exit_code_is_zero(self):
        """Hook must always exit 0."""
        _make_statusline(self.session_dir)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0

    def test_existing_state_preserved(self):
        """Hook should not clobber existing state keys."""
        # Pre-create a state file with existing data
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id,
                             session_data_dir=self.session_dir)
        store.persist()
        store.set("session.display_name", "TestBot")

        _make_statusline(self.session_dir, used_pct=50)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        # Existing key preserved
        assert state.get("session.display_name") == "TestBot"
        # New key added
        assert state.get("context.used_pct") == 50


class TestHookPromptSubmitJSONL:
    """Tests with v5.3 JSONL statusline format (append-only, last line is current)."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_140000_beef9999_cla"
        self.session_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_last_line_of_jsonl(self):
        """Hook reads the last line of a .jsonl statusline (current v5.3 format)."""
        _make_statusline_jsonl(self.session_dir, used_pct=42, cost_usd=15.0,
                               input_tokens=1000, output_tokens=2000,
                               cache_creation=500, cache_read=300)
        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })
        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        assert state is not None, "State file should exist"
        assert state.get("context.used_pct") == 42
        assert state.get("context.tokens") == 3800  # 1000+2000+500+300
        assert abs(state.get("context.cost_usd", 0) - 15.0) < 0.01

    def test_jsonl_preferred_over_json(self):
        """When both .jsonl and .json exist, .jsonl is preferred (current format)."""
        # Create both — .jsonl has different values than .json
        _make_statusline_jsonl(self.session_dir, used_pct=77)
        _make_statusline(self.session_dir, used_pct=11)
        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })
        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        assert state.get("context.used_pct") == 77  # from .jsonl, not .json


class TestHookPromptSubmitMissingStatusline:
    """Tests when statusline file is absent."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_140000_cafe5678_cla"
        self.session_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_error_on_missing_statusline(self):
        """Hook should exit 0 even with no statusline file."""
        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0

    def test_no_context_keys_without_statusline(self):
        """No context.* keys should be written if statusline is missing."""
        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        context_keys = [k for k in state if k.startswith("context.")]
        assert len(context_keys) == 0, "No context keys should exist without statusline"


class TestHookPromptSubmitMissingEnvVars:
    """Tests when required env vars are absent."""

    def test_missing_tracking_id(self):
        """Hook should exit 0 if AI_TRACKING_ID is not set."""
        tmpdir = tempfile.mkdtemp()
        try:
            result = _run_hook(env_override={
                "AI_SESSION_DIR": tmpdir,
            })
            assert result.returncode == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_missing_session_dir(self):
        """Hook should exit 0 if AI_SESSION_DIR is not set."""
        result = _run_hook(env_override={
            "AI_TRACKING_ID": "20260430_140000_dead0000_cla",
        })
        assert result.returncode == 0

    def test_both_env_vars_missing(self):
        """Hook should exit 0 if both env vars are missing."""
        result = _run_hook(env_override={})
        assert result.returncode == 0


class TestHookPromptSubmitMalformed:
    """Tests with malformed statusline data."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_140000_bad01234_cla"
        self.session_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_malformed_json_statusline(self):
        """Hook should exit 0 if statusline JSON is malformed."""
        uuid8 = "bad01234"
        filepath = os.path.join(self.session_dir, "statusline.{}.json".format(uuid8))
        with open(filepath, "w") as f:
            f.write("{not valid json!!!}")

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0

    def test_statusline_missing_context_window(self):
        """Hook should exit 0 if statusline has no context_window key."""
        uuid8 = "bad01234"
        filepath = os.path.join(self.session_dir, "statusline.{}.json".format(uuid8))
        with open(filepath, "w") as f:
            json.dump({"session_id": "test", "cost": {}}, f)

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0

    def test_statusline_empty_file(self):
        """Hook should exit 0 if statusline file is empty."""
        uuid8 = "bad01234"
        filepath = os.path.join(self.session_dir, "statusline.{}.json".format(uuid8))
        with open(filepath, "w") as f:
            pass  # empty file

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0

    def test_empty_stdin(self):
        """Hook should handle empty stdin gracefully."""
        _make_statusline(self.session_dir)

        result = _run_hook(
            env_override={
                "AI_TRACKING_ID": self.tracking_id,
                "AI_SESSION_DIR": self.session_dir,
            },
            stdin_data="",
        )

        assert result.returncode == 0

    def test_no_context_keys_on_malformed(self):
        """No context keys written when statusline is malformed JSON."""
        uuid8 = "bad01234"
        filepath = os.path.join(self.session_dir, "statusline.{}.json".format(uuid8))
        with open(filepath, "w") as f:
            f.write("garbage data")

        result = _run_hook(env_override={
            "AI_TRACKING_ID": self.tracking_id,
            "AI_SESSION_DIR": self.session_dir,
        })

        assert result.returncode == 0
        state = _read_state_from_dir(self.session_dir)
        context_keys = [k for k in state if k.startswith("context.")]
        assert len(context_keys) == 0
