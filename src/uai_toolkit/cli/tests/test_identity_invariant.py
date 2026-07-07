"""Regression tests for the tracking-ID uuid8 ↔ cli_session_id invariant.

Covers the launcher-owned identity allocation added to keep, *by construction*,
``tracking_id``'s uuid8 component equal to ``cli_session_id[:8]`` for Claude —
and to keep that correspondence intact through the store-collision fallback path
(the original bug: a fresh fallback UUID diverged from the embedded uuid8).

Python 3.9 compatible. Pure-unit where possible; reserve_draft is exercised
against an isolated temp store so it never touches the real session DB.
"""

import sys
import uuid as _uuid
from pathlib import Path

import pytest

_CLI_DIR = Path(__file__).resolve().parent.parent
_SESSION_MGMT = _CLI_DIR.parent / "session_mgmt"
for _p in (str(_CLI_DIR), str(_SESSION_MGMT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from uai_toolkit.cli import lib_session_mgr as m  # noqa: E402


def _uuid8_of(tracking_id: str) -> str:
    # Test-only inspection of the (otherwise opaque) ID; production code must not.
    return tracking_id.split("_")[2]


class TestAllocateTrackingIdentity:
    def test_minted_uuid8_matches_chosen_uuid(self):
        tid, chosen = m.allocate_tracking_identity("claude_cli")
        assert _uuid8_of(tid) == chosen.replace("-", "")[:8]

    def test_seed_is_used_when_free(self):
        seed = str(_uuid.uuid4())
        tid, chosen = m.allocate_tracking_identity("claude_cli", seed)
        assert chosen == seed
        assert _uuid8_of(tid) == seed.replace("-", "")[:8]

    def test_collision_fallback_keeps_uuid8_and_uuid_in_lockstep(self, monkeypatch):
        # Force the first candidate to "collide" so a fresh UUID is chosen; the
        # returned uuid8 must still match the returned UUID (the core bug fix).
        calls = {"n": 0}
        real_get = m._store.get

        def fake_get(candidate):
            calls["n"] += 1
            return {"tracking_id": candidate} if calls["n"] == 1 else None

        monkeypatch.setattr(m._store, "get", fake_get)
        tid, chosen = m.allocate_tracking_identity("claude_cli")
        assert _uuid8_of(tid) == chosen.replace("-", "")[:8]
        assert calls["n"] >= 2  # proves the fallback path actually ran
        monkeypatch.setattr(m._store, "get", real_get)

    def test_explicit_seed_collision_raises_not_substitutes(self, monkeypatch):
        seed = str(_uuid.uuid4())
        monkeypatch.setattr(m._store, "get", lambda c: {"tracking_id": c})  # always collide
        with pytest.raises(RuntimeError):
            m.allocate_tracking_identity("claude_cli", seed, strict_seed=True)

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError):
            m.allocate_tracking_identity("bogus_cli")


class TestReserveDraft:
    @pytest.fixture
    def temp_store(self, tmp_path, monkeypatch):
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore(db_path=tmp_path / "sessions.db")
        monkeypatch.setattr(m, "_store", store)
        # Keep session-dir creation inside the temp area too.
        monkeypatch.setattr(m, "compute_session_dir", lambda tid, plat: str(tmp_path / tid))
        return store

    def test_claude_reserve_sets_matching_cli_session_id(self, temp_store):
        tid, cli = m.reserve_draft("claude_cli", display_name="t")
        row = temp_store.get(tid)
        assert cli and row["cli_session_id"] == cli
        assert _uuid8_of(tid) == cli.replace("-", "")[:8]
        assert row["identity_status"] == "draft"

    def test_codex_reserve_leaves_cli_session_id_null(self, temp_store):
        tid, cli = m.reserve_draft("codex_cli", display_name="t")
        row = temp_store.get(tid)
        assert cli is None
        assert not row.get("cli_session_id")
        assert row["identity_status"] == "draft"
