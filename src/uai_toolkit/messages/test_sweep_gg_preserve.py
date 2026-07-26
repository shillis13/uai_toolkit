"""Stage-1 sweep preservation for sweep_expired.py (todo_0626).

An expired but UN-ACKED Git Guardian change request must be PRESERVED and surfaced,
never TTL-deleted — an expired un-acked request means work that may never have been
committed. Acked requests, advisories, and non-GG messages sweep as before.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import messages.sweep_expired as S  # noqa: E402

PAST = (datetime.now() - timedelta(days=1)).isoformat()


def _gg_content(kind="commit_request", todo="todo_0626"):
    return ("Git Guardian request:\n\n"
            "type: {}\nrepo: /r\nrequester: alice\ntodos:\n- {}\n"
            "files:\n- a.py\n".format(kind, todo))


def _write(path: Path, doc_lines: str):
    path.write_text(doc_lines)


def _msg_yaml(content, acked=False, frm="alice", to="gg"):
    ack = "acknowledgments:\n- by: gg\n  at: x\n" if acked else "acknowledgments: []\n"
    # content as a YAML block scalar so the embedded 'type:' isn't a top-level key
    body = "  " + content.replace("\n", "\n  ")
    return ("id: m1\nfrom: {}\nto: {}\nexpires_at: '{}'\nread_by: []\n{}"
            "content: |\n{}\n".format(frm, to, PAST, ack, body))


def _setup(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox" / "gg"
    prompts = tmp_path / "prompts" / "gg"
    standing = tmp_path / "standing"
    pending = tmp_path / "pending"
    for d in (inbox, prompts, standing, pending):
        d.mkdir(parents=True)
    monkeypatch.setattr(S, "SWEEP_DIRS", {
        "messages/inbox": tmp_path / "inbox",
        "prompts_inbox": tmp_path / "prompts",
        "standing_messages": standing,
        "pending_replies": pending,
    })
    monkeypatch.setattr(S, "DELIVERED_DIR", tmp_path / "delivered")  # absent -> skipped
    # neutralize the uri-mapping subprocess sweep (temp root has no session_store.py)
    monkeypatch.setattr(S, "_get_ai_root", lambda: tmp_path)
    return inbox, prompts, standing


def test_unacked_gg_request_preserved(tmp_path, monkeypatch):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    keep = inbox / "req_unacked.yml"
    _write(keep, _msg_yaml(_gg_content("commit_request"), acked=False))
    # a prompt-queue GG request too
    keep2 = prompts / "q_unacked.yml"
    _write(keep2, _msg_yaml(_gg_content("sync_request"), acked=False))

    S.sweep(dry_run=False)

    assert keep.exists(), "un-acked commit_request must NOT be deleted"
    assert keep2.exists(), "un-acked sync_request must NOT be deleted"


def test_acked_gg_request_swept(tmp_path, monkeypatch):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    gone = inbox / "req_acked.yml"
    _write(gone, _msg_yaml(_gg_content("commit_request"), acked=True))

    S.sweep(dry_run=False)

    assert not gone.exists(), "an ACKED gg request sweeps normally on TTL expiry"


def test_non_gg_and_advisory_swept(tmp_path, monkeypatch):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    plain = inbox / "plain.yml"
    _write(plain, _msg_yaml("just a normal chat message", acked=False))
    advisory = inbox / "advisory.yml"
    _write(advisory, _msg_yaml(_gg_content("advisory"), acked=False))

    S.sweep(dry_run=False)

    assert not plain.exists(), "non-GG expired message sweeps"
    assert not advisory.exists(), "GG advisory (non-change) sweeps"


def test_dry_run_never_deletes(tmp_path, monkeypatch):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    acked = inbox / "req_acked.yml"
    _write(acked, _msg_yaml(_gg_content(), acked=True))
    S.sweep(dry_run=True)
    assert acked.exists(), "dry-run deletes nothing"


def test_preserved_surfaced_on_stderr(tmp_path, monkeypatch, capsys):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    _write(inbox / "req.yml", _msg_yaml(_gg_content("commit_request"), acked=False))
    S.sweep(dry_run=False)
    err = capsys.readouterr().err
    assert "PRESERVED" in err and "commit_request" in err


def test_timezone_aware_expiry_is_preserved(tmp_path, monkeypatch):
    inbox, prompts, standing = _setup(tmp_path, monkeypatch)
    keep = inbox / "aware.yml"
    aware_past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    doc = _msg_yaml(_gg_content(), acked=False).replace(PAST, aware_past)
    _write(keep, doc)

    S.sweep(dry_run=False)

    assert keep.exists(), "timezone-aware expiry must compare safely and preserve"
