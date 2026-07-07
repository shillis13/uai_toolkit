"""Tests for live-probe name-collision detection + store-aware op diagnostics.

Covers the machinery added after the 'Relay' incident, where two store records
shared a display/terminal name — one live, one dead — and shadowed each other so
the session became unaddressable and errored with a bare "does not exist".

Isolated: each test uses a temp SQLite DB and a MOCKED live-terminal probe, so
nothing here touches real tmux/zellij or the real session store. Python 3.9 ok.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uai_toolkit.session_mgmt.session_store import SessionStore  # noqa: E402
from uai_toolkit.session_mgmt import session_ops  # noqa: E402


def _mk_store(tmpdir):
    store = SessionStore(db_path=os.path.join(tmpdir, "sessions.db"))
    # Deterministic live probe: tests set store._fake_live to a dict of
    # {"tmux": set((server, name)), "zellij": set(name)}.
    store._fake_live = {"tmux": set(), "zellij": set()}
    store._get_live_terminal_sessions = lambda: store._fake_live  # type: ignore
    return store


def _mk_record(store, tmpdir, tracking_id, name, server="ai_root", substrate="tmux"):
    sdir = os.path.join(tmpdir, tracking_id)
    store.create(
        tracking_id=tracking_id, terminal_session=name, platform="claude_cli",
        display_name=name, substrate=substrate, tmux_server=server, session_dir=sdir,
    )


class TestLiveNameConflicts:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="collide_")
        self.store = _mk_store(self.tmp)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_live_collision_detected(self):
        _mk_record(self.store, self.tmp, "aaaa1111_x_cla", "Relay", server="default")
        # Mark that terminal live on the 'default' tmux server.
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        conflicts = self.store.live_name_conflicts(terminal_session="Relay", display_name="Relay")
        assert [c["tracking_id"] for c in conflicts] == ["aaaa1111_x_cla"]

    def test_excludes_self(self):
        _mk_record(self.store, self.tmp, "aaaa1111_x_cla", "Relay", server="default")
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        conflicts = self.store.live_name_conflicts(
            terminal_session="Relay", display_name="Relay",
            exclude_tracking_id="aaaa1111_x_cla",
        )
        assert conflicts == []

    def test_dead_record_not_a_conflict(self):
        # Record exists but is NOT in the live set → stale, not a conflict.
        _mk_record(self.store, self.tmp, "bbbb2222_y_cla", "Relay", server="ai_root")
        self.store._fake_live = {"tmux": set(), "zellij": set()}
        assert self.store.live_name_conflicts(display_name="Relay") == []

    def test_unrelated_name_no_conflict(self):
        _mk_record(self.store, self.tmp, "cccc3333_z_cla", "Relay", server="default")
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        assert self.store.live_name_conflicts(display_name="SomethingElse") == []

    def test_check_name_usage_reports_live_count(self):
        _mk_record(self.store, self.tmp, "dddd4444_w_cla", "Relay", server="default")
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        usage = self.store.check_name_usage("Relay")
        assert usage["live_active_count"] == 1
        assert "active_count" in usage  # legacy field preserved


class TestDiagnoseSessionReference:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="diag_")
        self.store = _mk_store(self.tmp)
        # Point session_ops' lazy singleton at our temp store.
        self._saved = session_ops._session_store
        session_ops._session_store = self.store

    def teardown_method(self):
        session_ops._session_store = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_name(self):
        diag = session_ops._diagnose_session_reference("NoSuchThing")
        assert diag["records"] == []
        assert "unknown" in diag["hint"].lower()

    def test_stale_exited_record(self):
        _mk_record(self.store, self.tmp, "eeee5555_s_cla", "GhostTest", server="ai_root")
        self.store._fake_live = {"tmux": set(), "zellij": set()}  # nothing live
        diag = session_ops._diagnose_session_reference("GhostTest")
        assert len(diag["records"]) == 1
        assert diag["records"][0]["live"] is False
        assert "stale" in diag["hint"].lower() or "exited" in diag["hint"].lower()

    def test_live_on_other_server(self):
        _mk_record(self.store, self.tmp, "ffff6666_l_cla", "Relay", server="default")
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        diag = session_ops._diagnose_session_reference("Relay")
        assert diag["records"][0]["live"] is True
        assert "is live" in diag["hint"].lower()

    def test_collision_flagged(self):
        # Two records share the name; only one is live.
        _mk_record(self.store, self.tmp, "1111aaaa_a_cla", "Relay", server="default")
        _mk_record(self.store, self.tmp, "2222bbbb_b_cla", "Relay", server="ai_root")
        self.store._fake_live = {"tmux": {("default", "Relay")}, "zellij": set()}
        diag = session_ops._diagnose_session_reference("Relay")
        assert len(diag["records"]) == 2
        assert "collision" in diag["hint"].lower() or "share this name" in diag["hint"].lower()
