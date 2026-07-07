"""Tests for session_mgr.py CLI — subprocess-based.

Calls session_mgr.py as a script via subprocess. Uses temp directories
for --data-dir. Python 3.9 compatible.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The script under test
SCRIPT = str(Path(__file__).resolve().parent.parent / "session_mgr.py")

# Python interpreter — use the same one running pytest
PYTHON = sys.executable

TRACKING_ID = "20260430_120000_abcd1234_cla"


def _run(args, env=None, expect_fail=False):
    """Run session_mgr.py with given args, return (stdout, stderr, returncode)."""
    cmd = [PYTHON, SCRIPT] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    if not expect_fail and result.returncode != 0:
        # Print stderr for debugging on unexpected failure
        print("STDERR:", result.stderr, file=sys.stderr)
    return result.stdout, result.stderr, result.returncode


class TestStateSetGet:
    """Test state_set and state_get roundtrip."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_store(self):
        """Initialize the store file by running state_list (which creates if needed)."""
        # We need to prime the store. Use state_set to create the file.
        _run(["state_set", TRACKING_ID, "init.key", "init_val", "--data-dir", self.data_dir])

    def test_set_and_get_roundtrip(self):
        """state_set then state_get returns the value."""
        stdout, stderr, rc = _run([
            "state_set", TRACKING_ID, "session.display_name", "TestBot",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["key"] == "session.display_name"
        assert result["value"] == "TestBot"
        assert result["changed"] is True

        stdout, stderr, rc = _run([
            "state_get", TRACKING_ID, "session.display_name",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] == "TestBot"

    def test_get_nonexistent_key(self):
        """state_get for a key that doesn't exist returns null."""
        self._init_store()
        stdout, stderr, rc = _run([
            "state_get", TRACKING_ID, "no.such.key",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] is None


class TestStateDelete:
    """Test state_delete subcommand."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_existing_key(self):
        """state_delete removes a key."""
        _run(["state_set", TRACKING_ID, "temp.key", "tempval", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_delete", TRACKING_ID, "temp.key",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["deleted"] is True

        # Verify it's gone
        stdout, _, _ = _run([
            "state_get", TRACKING_ID, "temp.key",
            "--data-dir", self.data_dir,
        ])
        assert json.loads(stdout)["value"] is None

    def test_delete_nonexistent_key(self):
        """state_delete on missing key returns deleted=false."""
        # Prime the store
        _run(["state_set", TRACKING_ID, "other", "val", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_delete", TRACKING_ID, "no.such.key",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["deleted"] is False


class TestStateIncrement:
    """Test state_increment and state_decrement subcommands."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_increment_new_key(self):
        """Increment on a nonexistent key initializes to 0 then adds."""
        stdout, stderr, rc = _run([
            "state_increment", TRACKING_ID, "counter",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] == 1

    def test_increment_with_amount(self):
        """Increment with --amount flag."""
        _run(["state_set", TRACKING_ID, "counter", "10", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_increment", TRACKING_ID, "counter", "--amount", "5",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] == 15

    def test_decrement(self):
        """state_decrement subtracts from a numeric key."""
        _run(["state_set", TRACKING_ID, "counter", "10", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_decrement", TRACKING_ID, "counter", "--amount", "3",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] == 7

    def test_decrement_default_amount(self):
        """state_decrement with no --amount decrements by 1."""
        _run(["state_set", TRACKING_ID, "counter", "10", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_decrement", TRACKING_ID, "counter",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert result["value"] == 9


class TestStateList:
    """Test state_list subcommand."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_all_keys(self):
        """state_list returns all keys."""
        # Use non-reserved namespace 'test.' to avoid reserved key validation
        _run(["state_set", TRACKING_ID, "test.FOO", "bar", "--data-dir", self.data_dir])
        _run(["state_set", TRACKING_ID, "test.BAZ", "qux", "--data-dir", self.data_dir])
        _run(["state_set", TRACKING_ID, "session.display_name", "Test", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_list", TRACKING_ID,
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert "test.FOO" in result
        assert "test.BAZ" in result
        assert "session.display_name" in result

    def test_list_with_prefix(self):
        """state_list with --prefix filters keys."""
        # Use non-reserved namespace 'test.' to avoid reserved key validation
        _run(["state_set", TRACKING_ID, "test.FOO", "bar", "--data-dir", self.data_dir])
        _run(["state_set", TRACKING_ID, "test.BAZ", "qux", "--data-dir", self.data_dir])
        _run(["state_set", TRACKING_ID, "session.display_name", "Test", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_list", TRACKING_ID, "--prefix", "test.",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert "test.FOO" in result
        assert "test.BAZ" in result
        assert "session.display_name" not in result


class TestStateRemove:
    """Test state_remove subcommand."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_remove_from_list_key(self):
        """state_remove removes values from a list key."""
        _run(["state_set", TRACKING_ID, "role", "assistant,architect", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "state_remove", TRACKING_ID, "role", "architect",
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert "architect" not in result["value"]
        assert "assistant" in result["value"]


class TestStateSeed:
    """Test state_seed subcommand."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seed_from_env(self):
        """state_seed populates env.* keys from environment variables."""
        env = os.environ.copy()
        env["SEED_VAR_A"] = "alpha"
        env["SEED_VAR_B"] = "beta"

        stdout, stderr, rc = _run([
            "state_seed", TRACKING_ID,
            "--vars", "SEED_VAR_A,SEED_VAR_B,SEED_VAR_MISSING",
            "--data-dir", self.data_dir,
        ], env=env)
        assert rc == 0
        result = json.loads(stdout)
        assert "SEED_VAR_A" in result["seeded"]
        assert "SEED_VAR_B" in result["seeded"]
        assert "SEED_VAR_MISSING" in result["missing"]

        # Verify the value was actually stored
        stdout2, _, _ = _run([
            "state_get", TRACKING_ID, "env.SEED_VAR_A",
            "--data-dir", self.data_dir,
        ], env=env)
        assert json.loads(stdout2)["value"] == "alpha"


class TestGetCtxUsed:
    """Test get_ctx_used subcommand."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_ctx_used_returns_json(self):
        """get_ctx_used returns context.* keys as JSON."""
        _run(["state_set", TRACKING_ID, "context.used_pct", "42", "--data-dir", self.data_dir])
        _run(["state_set", TRACKING_ID, "context.tokens", "180000", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "get_ctx_used", TRACKING_ID,
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        assert "context.used_pct" in result
        assert "context.tokens" in result

    def test_get_ctx_used_empty(self):
        """get_ctx_used returns empty dict when no context keys exist."""
        # Prime the store with a non-context key
        _run(["state_set", TRACKING_ID, "session.display_name", "X", "--data-dir", self.data_dir])

        stdout, stderr, rc = _run([
            "get_ctx_used", TRACKING_ID,
            "--data-dir", self.data_dir,
        ])
        assert rc == 0
        result = json.loads(stdout)
        # Should not have context keys
        context_keys = {k: v for k, v in result.items() if k.startswith("context.")}
        assert len(context_keys) == 0


class TestGetFooter:
    """Test get_footer subcommand (now wired to build_footer)."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_footer_returns_formatted_output(self):
        """get_footer returns a formatted footer with tags."""
        # Clear real env vars so build_footer uses store/tracking_id, not process env
        env = os.environ.copy()
        for key in ("AI_TRACKING_ID", "AI_CLI_SESSION_ID", "AI_SESSION_PLATFORM",
                     "AI_PROJECT_DIR", "AI_SESSION_DIR"):
            env.pop(key, None)
        result = subprocess.run(
            [sys.executable, SCRIPT, "get_footer", TRACKING_ID,
             "--tags", "test_tag", "--data-dir", self.data_dir],
            capture_output=True, text=True, env=env, timeout=30,
        )
        assert result.returncode == 0
        assert "Tags: test_tag" in result.stdout
        assert TRACKING_ID in result.stdout


class TestErrorHandling:
    """Test error conditions."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmpdir, TRACKING_ID)
        os.makedirs(self.data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_subcommand(self):
        """No subcommand produces non-zero exit."""
        stdout, stderr, rc = _run([], expect_fail=True)
        assert rc != 0

    def test_missing_tracking_id(self):
        """Missing tracking_id argument produces non-zero exit."""
        stdout, stderr, rc = _run(["state_get"], expect_fail=True)
        assert rc != 0

    def test_missing_key_for_get(self):
        """state_get without a key argument produces non-zero exit."""
        stdout, stderr, rc = _run(["state_get", TRACKING_ID], expect_fail=True)
        assert rc != 0

    def test_no_data_dir_and_no_sqlite(self):
        """Without --data-dir, if SQLite import fails, should error clearly."""
        # Set an env that ensures session_store.py won't be found in the devTree
        env = os.environ.copy()
        # Remove any path hints that might help resolve
        env.pop("AI_SESSION_DIR", None)

        stdout, stderr, rc = _run([
            "state_get", TRACKING_ID, "some.key",
        ], env=env, expect_fail=True)
        # Should fail with a helpful message about --data-dir
        assert rc != 0
        assert "data-dir" in stderr.lower() or "data_dir" in stderr.lower() or "resolve" in stderr.lower()
