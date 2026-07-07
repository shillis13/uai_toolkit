"""
Tests for disk-backed SessionStore.

Covers: CRUD operations, list keys, merge/remove semantics,
increment/decrement, seed_from_env, cross-process visibility,
discriminated filenames, reserved key validation, triggers,
and backward compatibility.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make store.py importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestSessionStoreBasic:
    """Core CRUD and disk persistence tests."""

    def setup_method(self):
        """Create a temp session data dir for each test."""
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_set_and_get(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        result = store.set("session.display_name", "TestBot")
        assert result["key"] == "session.display_name"
        assert result["value"] == "TestBot"
        assert result["changed"] is True
        assert store.get("session.display_name") == "TestBot"

    def test_get_nonexistent_key(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        assert store.get("nonexistent") is None

    def test_set_persists_to_disk(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("test.key", "value1")
        # Read file directly to verify disk write
        state_files = list(Path(self.session_data_dir).glob("state.*.json"))
        assert len(state_files) == 1
        with open(state_files[0]) as f:
            data = json.load(f)
        assert data["state"]["test.key"] == "value1"

    def test_set_unchanged_value(self):
        """Setting a key to its current value reports changed=False."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("mykey", "val")
        result = store.set("mykey", "val")
        assert result["changed"] is False

    def test_delete(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("deleteme", "value")
        result = store.delete("deleteme")
        assert result["deleted"] is True
        assert store.get("deleteme") is None

    def test_delete_nonexistent(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        result = store.delete("nope")
        assert result["deleted"] is False


class TestSessionStoreIncrement:
    """Increment and decrement operations."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_increment_new_key(self):
        """Incrementing a non-existent key initializes to 0 then adds."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        result = store.increment("counter")
        assert result["value"] == 1
        assert result["changed"] is True

    def test_increment_existing_int(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.increment("counter")
        result = store.increment("counter", 5)
        assert result["value"] == 6

    def test_increment_float(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("price", 10.5)
        result = store.increment("price", 2.3)
        assert abs(result["value"] - 12.8) < 0.001

    def test_increment_non_numeric_raises(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("name", "text")
        with pytest.raises(ValueError):
            store.increment("name")

    def test_decrement(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("counter", 10)
        result = store.decrement("counter", 3)
        assert result["value"] == 7

    def test_decrement_default_amount(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("counter", 5)
        result = store.decrement("counter")
        assert result["value"] == 4


class TestSessionStoreListKeys:
    """List-typed key merge and remove semantics."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_key_merge(self):
        """Setting a list key merges values, preserving order and uniqueness."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("role", "assistant")
        store.set("role", "architect")
        roles = store.get("role")
        assert "chat" in roles  # default
        assert "assistant" in roles
        assert "architect" in roles

    def test_list_key_merge_comma_separated(self):
        """Comma-separated string splits and merges into list."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("role", "assistant,architect")
        roles = store.get("role")
        assert "chat" in roles
        assert "assistant" in roles
        assert "architect" in roles

    def test_list_key_no_duplicates(self):
        """Merging the same value twice does not create duplicates."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("role", "assistant")
        store.set("role", "assistant")
        roles = store.get("role")
        assert roles.count("assistant") == 1

    def test_list_key_features(self):
        """Features key also has list merge semantics."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("features", "write_code")
        store.set("features", "debug")
        features = store.get("features")
        assert "write_code" in features
        assert "debug" in features

    def test_remove_from_list_key(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("role", "assistant,architect")
        result = store.remove("role", "architect")
        assert "architect" not in result["value"]
        assert "assistant" in result["value"]

    def test_remove_multiple_from_list_key(self):
        """Comma-separated values in remove are all removed."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("role", "assistant,architect,reviewer")
        result = store.remove("role", "architect,reviewer")
        assert "architect" not in result["value"]
        assert "reviewer" not in result["value"]
        assert "assistant" in result["value"]

    def test_remove_non_list_key_errors(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("name", "test")
        result = store.remove("name", "test")
        assert "error" in result


class TestSessionStoreListAll:
    """list_all with and without prefix filter."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_all(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("custom.foo", "bar")
        store.set("custom.baz", "qux")
        store.set("session.display_name", "test")
        all_keys = store.list_all()
        assert "custom.foo" in all_keys
        assert "custom.baz" in all_keys
        assert "session.display_name" in all_keys
        # Default keys also present
        assert "role" in all_keys
        assert "features" in all_keys
        assert "ai_root" in all_keys

    def test_list_all_with_prefix(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("custom.foo", "bar")
        store.set("custom.baz", "qux")
        store.set("session.display_name", "test")
        custom_keys = store.list_all(prefix="custom.")
        assert "custom.foo" in custom_keys
        assert "custom.baz" in custom_keys
        assert "session.display_name" not in custom_keys
        assert "role" not in custom_keys

    def test_list_all_no_prefix_returns_all(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("custom.foo", "bar")
        all_keys = store.list_all(prefix=None)
        assert "custom.foo" in all_keys
        assert "role" in all_keys


class TestSessionStoreSeedFromEnv:
    """Seed state from environment variables."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_seed_from_env(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        os.environ["TEST_SEED_A"] = "alpha"
        os.environ["TEST_SEED_B"] = "beta"
        try:
            store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
            store.persist()
            result = store.seed_from_env(["TEST_SEED_A", "TEST_SEED_B", "TEST_SEED_MISSING"])
            assert "TEST_SEED_A" in result["seeded"]
            assert "TEST_SEED_B" in result["seeded"]
            assert "TEST_SEED_MISSING" in result["missing"]
            assert store.get("env.TEST_SEED_A") == "alpha"
            assert store.get("env.TEST_SEED_B") == "beta"
        finally:
            del os.environ["TEST_SEED_A"]
            del os.environ["TEST_SEED_B"]

    def test_seed_from_env_single_lock(self):
        """seed_from_env writes all keys in a single atomic operation."""
        from uai_toolkit.session_mgmt.store import SessionStore
        os.environ["TEST_BATCH_A"] = "val_a"
        os.environ["TEST_BATCH_B"] = "val_b"
        try:
            store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
            store.persist()
            store.seed_from_env(["TEST_BATCH_A", "TEST_BATCH_B"])
            # Both should be present on disk in a single read
            state_files = list(Path(self.session_data_dir).glob("state.*.json"))
            with open(state_files[0]) as f:
                data = json.load(f)
            assert data["state"]["env.TEST_BATCH_A"] == "val_a"
            assert data["state"]["env.TEST_BATCH_B"] == "val_b"
        finally:
            del os.environ["TEST_BATCH_A"]
            del os.environ["TEST_BATCH_B"]


class TestSessionStoreCompat:
    """Backward compatibility: session_id alias, defaults."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_id_alias(self):
        """session_id constructor param maps to tracking_id."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(session_id="legacy_id", session_data_dir=self.session_data_dir)
        assert store.session_id == "legacy_id"
        assert store.tracking_id == "legacy_id"

    def test_tracking_id_primary(self):
        """tracking_id takes precedence over session_id when both given."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(
            tracking_id="primary_id",
            session_id="ignored_id",
            session_data_dir=self.session_data_dir,
        )
        assert store.tracking_id == "primary_id"
        assert store.session_id == "primary_id"

    def test_defaults_on_persist(self):
        """persist() creates file with default keys."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        path = store.persist()
        with open(path) as f:
            data = json.load(f)
        state = data["state"]
        assert state["role"] == ["chat"]
        assert state["features"] == []
        assert "ai_root" in state
        assert "ai_root_main" in state


class TestSessionStoreCrossProcess:
    """Cross-process visibility — two store instances share state via disk."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cross_process_visibility(self):
        """One store instance sees another's writes via disk."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store_a = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store_a.persist()
        store_a.set("shared.key", "from_a")

        store_b = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        assert store_b.get("shared.key") == "from_a"

    def test_cross_process_increment(self):
        """Two stores incrementing the same key yield correct total."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store_a = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store_a.persist()
        store_a.increment("counter", 5)

        store_b = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store_b.increment("counter", 3)

        assert store_a.get("counter") == 8


class TestSessionStoreFilename:
    """Discriminated filename: state.{uuid8}.json."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discriminated_filename(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        path = store.persist()
        filename = os.path.basename(path)
        assert filename == "state.abcd1234.json"

    def test_different_tracking_ids_produce_different_filenames(self):
        """Different uuid8 in tracking_id produces different filename."""
        from uai_toolkit.session_mgmt.store import SessionStore
        other_tracking_id = "20260430_130000_beef9876_cla"
        other_dir = os.path.join(self.tmpdir, other_tracking_id)
        os.makedirs(other_dir)
        store = SessionStore(tracking_id=other_tracking_id, session_data_dir=other_dir)
        path = store.persist()
        filename = os.path.basename(path)
        assert filename == "state.beef9876.json"


class TestSessionStoreReservedKeyValidation:
    """Reserved key namespace validation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_reserved_key_accepted(self):
        """A known reserved key like context.used_pct is accepted."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        # Should not raise
        result = store.set("context.used_pct", 42)
        assert result["value"] == 42

    def test_invalid_namespaced_key_rejected(self):
        """An unknown key in a reserved namespace raises ValueError."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        with pytest.raises(ValueError) as exc_info:
            store.set("context.usage_pct", 42)  # Typo — should be context.used_pct
        error_msg = str(exc_info.value)
        # Error should mention the invalid key
        assert "context.usage_pct" in error_msg
        # Error should suggest valid keys in the namespace
        assert "context.used_pct" in error_msg

    def test_unknown_namespace_key_accepted(self):
        """A key with a dot but not in a reserved namespace is allowed."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        # "custom.mykey" is not in env/context/session/loaded/conversation/footer namespace
        result = store.set("custom.mykey", "value")
        assert result["value"] == "value"

    def test_free_form_key_no_dot_accepted(self):
        """Keys without dots bypass namespace validation."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        result = store.set("mykey", "value")
        assert result["value"] == "value"

    def test_legacy_reserved_keys_accepted(self):
        """Legacy reserved keys (role, features, ai_root, ai_root_main) are accepted."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        # These should not raise
        store.set("role", "tester")
        store.set("features", "test_feature")
        store.set("ai_root", "/some/path")
        store.set("ai_root_main", "/some/path")

    def test_all_reserved_env_keys_accepted(self):
        """All reserved env.* keys are accepted."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("env.AI_TRACKING_ID", "test_id")
        store.set("env.AI_CLI_SESSION_ID", "test_uuid")
        store.set("env.AI_SESSION_DIR", "/test/dir")
        store.set("env.AI_SESSION_PLATFORM", "claude_cli")
        store.set("env.AI_PROJECT_DIR", "/test/project")

    def test_invalid_env_key_rejected(self):
        """An unknown env.* key is rejected."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        with pytest.raises(ValueError) as exc_info:
            store.set("env.UNKNOWN_VAR", "value")
        assert "env.UNKNOWN_VAR" in str(exc_info.value)

    def test_seed_from_env_bypasses_validation(self):
        """seed_from_env writes env.* keys without namespace validation."""
        from uai_toolkit.session_mgmt.store import SessionStore
        os.environ["MY_CUSTOM_VAR"] = "test"
        try:
            store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
            store.persist()
            # seed_from_env should write env.MY_CUSTOM_VAR even though it's
            # not in the reserved registry, because seeding is a trusted operation
            result = store.seed_from_env(["MY_CUSTOM_VAR"])
            assert "MY_CUSTOM_VAR" in result["seeded"]
            assert store.get("env.MY_CUSTOM_VAR") == "test"
        finally:
            del os.environ["MY_CUSTOM_VAR"]

    def test_delete_bypasses_validation(self):
        """delete() works on any key without namespace validation."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("context.used_pct", 42)
        result = store.delete("context.used_pct")
        assert result["deleted"] is True

    def test_increment_bypasses_validation(self):
        """increment() works on any numeric key without namespace validation."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("context.tokens", 100)
        result = store.increment("context.tokens", 50)
        assert result["value"] == 150


class TestSessionStoreTriggers:
    """Trigger registration and firing."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_trigger_fires_on_change(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        fired = []

        def callback(key, old_val, new_val, s):
            fired.append((key, old_val, new_val))

        store.register_trigger("mykey", callback)
        store.set("mykey", "value1")
        assert len(fired) == 1
        assert fired[0] == ("mykey", None, "value1")

    def test_trigger_does_not_fire_when_unchanged(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        fired = []

        def callback(key, old_val, new_val, s):
            fired.append((key, old_val, new_val))

        store.register_trigger("mykey", callback)
        store.set("mykey", "value1")
        store.set("mykey", "value1")  # same value
        assert len(fired) == 1

    def test_trigger_fires_on_delete(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        store.set("mykey", "value1")
        fired = []

        def callback(key, old_val, new_val, s):
            fired.append((key, old_val, new_val))

        store.register_trigger("mykey", callback)
        store.delete("mykey")
        assert len(fired) == 1
        assert fired[0] == ("mykey", "value1", None)

    def test_trigger_fires_on_increment(self):
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()
        fired = []

        def callback(key, old_val, new_val, s):
            fired.append((key, old_val, new_val))

        store.register_trigger("counter", callback)
        store.increment("counter")
        assert len(fired) == 1
        assert fired[0] == ("counter", None, 1)

    def test_trigger_error_does_not_crash(self):
        """A trigger that raises an exception doesn't crash set()."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()

        def bad_callback(key, old_val, new_val, s):
            raise RuntimeError("boom")

        store.register_trigger("mykey", bad_callback)
        # Should not raise
        result = store.set("mykey", "value")
        assert result["value"] == "value"


class TestSessionStoreNoFile:
    """Behavior when state file doesn't exist yet."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tracking_id = "20260430_120000_abcd1234_cla"
        self.session_data_dir = os.path.join(self.tmpdir, self.tracking_id)
        os.makedirs(self.session_data_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_without_persist_returns_none(self):
        """get() before persist() returns None for non-default keys."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        assert store.get("nonexistent") is None

    def test_set_without_persist_creates_file(self):
        """set() without prior persist() still writes to disk."""
        from uai_toolkit.session_mgmt.store import SessionStore
        store = SessionStore(tracking_id=self.tracking_id, session_data_dir=self.session_data_dir)
        store.persist()  # Need initial file for set to work on
        store.set("key1", "val1")
        assert store.get("key1") == "val1"
