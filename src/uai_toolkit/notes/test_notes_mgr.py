#!/usr/bin/env python3
"""Tests for notes_mgr — the Component 6 Notes backend (todo_0307/todo_0340).

No external deps beyond pytest; notes_mgr has a hand-rolled YAML subset, so the
round-trip parse/emit is part of what's under test. Every test gets an isolated
tmp root via the `root` fixture so nothing touches ai_general/work/notes/.

Run:  python3 -m pytest scripts/notes/test_notes_mgr.py -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from uai_toolkit.notes import notes_mgr as nm  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Point notes_mgr at an isolated tmp root for the duration of a test."""
    monkeypatch.setattr(nm, "CURRENT_ROOT", tmp_path)
    return tmp_path


# ── slug / numbering ─────────────────────────────────────────────────────────

def test_slugify_basics():
    assert nm.slugify("Fix Dropdown Hover!") == "fix_dropdown_hover"
    assert nm.slugify("  trailing/leading  ") == "trailing_leading"
    assert nm.slugify("UAI Tab #3") == "uai_tab_3"
    assert nm.slugify("!!!") == ""


def test_numbering_increments(root):
    a = nm.op_create("first")
    b = nm.op_create("second")
    assert a["id"].startswith("note_0001_")
    assert b["id"].startswith("note_0002_")


def test_numbering_never_reused_after_archive(root):
    a = nm.op_create("keep")
    nm.op_set_status(a["id"], "archived")
    # move the dir into archived/ to simulate archival layout
    archived = root / "archived"
    archived.mkdir()
    (root / a["id"]).rename(archived / a["id"])
    b = nm.op_create("next")
    assert b["id"].startswith("note_0002_")  # 0001 not reused


# ── create ───────────────────────────────────────────────────────────────────

def test_create_writes_expected_layout(root):
    r = nm.op_create("body text here", recipients=["Hamilton", "PM"],
                     source_tab="live-board", created_by="sess_abc")
    assert r["success"]
    d = root / r["id"]
    assert (d / "content.md").read_text().startswith("body text here")
    assert (d / "messages").is_dir()
    assert (d / "captures").is_dir()
    meta = nm.read_meta(d)
    assert meta["recipients"] == ["Hamilton", "PM"]
    assert meta["source_tab"] == "live-board"
    assert meta["created_by"] == "sess_abc"
    assert meta["status"] == "open"
    assert meta["resulted_in"] == []


def test_create_requires_text(root):
    assert nm.op_create("")["success"] is False
    assert nm.op_create("   ")["success"] is False


def test_create_slug_from_first_line(root):
    r = nm.op_create("A Clear Title\nmore detail below")
    assert "a_clear_title" in r["id"]


def test_create_explicit_name_overrides_slug(root):
    r = nm.op_create("ignored body for slug", name="custom slug source")
    assert "custom_slug_source" in r["id"]


def test_create_default_created_by_env(root, monkeypatch):
    monkeypatch.setenv("AI_TRACKING_ID", "env_tracking")
    r = nm.op_create("x")
    assert nm.read_meta(root / r["id"])["created_by"] == "env_tracking"


# ── messages + targets ───────────────────────────────────────────────────────

def test_add_message_numbering_and_header(root):
    n = nm.op_create("note")
    m1 = nm.op_add_message(n["id"], "pm", "first")
    m2 = nm.op_add_message(n["id"], "hamilton", "second")
    assert m1["message_id"] == "001"
    assert m2["message_id"] == "002"
    rd = nm.op_read(n["id"])
    assert [m["author"] for m in rd["messages"]] == ["pm", "hamilton"]
    assert rd["messages"][0]["body"] == "first"


def test_add_message_requires_author_and_body(root):
    n = nm.op_create("note")
    assert nm.op_add_message(n["id"], "", "body")["success"] is False
    assert nm.op_add_message(n["id"], "pm", "")["success"] is False


def test_reply_to_note_message_target(root):
    n = nm.op_create("note")
    nm.op_add_message(n["id"], "pm", "first")
    m2 = nm.op_add_message(n["id"], "hamilton", "re", reply_to="note_message:001")
    assert m2["reply_to"] == {"type": "note_message", "id": "001"}


def test_reply_to_todo_and_artifact_targets(root):
    n = nm.op_create("note")
    mt = nm.op_add_message(n["id"], "h", "x", reply_to="todo:todo_0007_foo")
    ma = nm.op_add_message(n["id"], "h", "y", reply_to="artifact:artifact_003")
    assert mt["reply_to"] == {"type": "todo", "id": "todo_0007_foo"}
    assert ma["reply_to"] == {"type": "artifact", "id": "artifact_003"}


def test_reply_to_turn_target_rich_shape(root):
    n = nm.op_create("note")
    m = nm.op_add_message(n["id"], "h", "about that turn",
                          reply_to="turn:sess_123:jsonl_abc:48")
    assert m["reply_to"] == {
        "type": "turn", "session": "sess_123",
        "transcript": "jsonl_abc", "turn": 48,
    }


def test_turn_target_requires_all_fields(root):
    n = nm.op_create("note")
    bad = nm.op_add_message(n["id"], "h", "x", reply_to="turn:only_session")
    assert bad["success"] is False
    assert "turn" in bad["error"].lower()


def test_invalid_target_type_rejected(root):
    n = nm.op_create("note")
    bad = nm.op_add_message(n["id"], "h", "x", reply_to="bogus:1")
    assert bad["success"] is False


def test_target_parsing_direct():
    assert nm._parse_target(None) is None
    assert nm._parse_target("todo:t1") == {"type": "todo", "id": "t1"}
    with pytest.raises(ValueError):
        nm._parse_target("noselon")  # no colon
    with pytest.raises(ValueError):
        nm._parse_target("turn:a:b")  # too few turn parts


# ── status / link-todo ───────────────────────────────────────────────────────

def test_set_status_valid_and_invalid(root):
    n = nm.op_create("note")
    ok = nm.op_set_status(n["id"], "resolved")
    assert ok["success"] and ok["status"] == "resolved" and ok["previous"] == "open"
    assert nm.op_set_status(n["id"], "bogus")["success"] is False


def test_edit_rewrites_body_only(root):
    n = nm.op_create("original body\nplus more", recipients=["PM"])
    nm.op_add_message(n["id"], "pm", "a thread comment")
    r = nm.op_edit(n["id"], "rewritten body\nsecond line")
    assert r["success"]
    rd = nm.op_read(n["id"])
    assert rd["content"] == "rewritten body\nsecond line\n"
    # thread is untouched by an edit
    assert [m["body"] for m in rd["messages"]] == ["a thread comment"]


def test_edit_requires_text_and_valid_note(root):
    n = nm.op_create("body")
    assert nm.op_edit(n["id"], "   ")["success"] is False
    assert nm.op_edit("note_9999_missing", "x")["success"] is False


def test_link_todo_appends_unique(root):
    n = nm.op_create("note")
    nm.op_link_todo(n["id"], "todo_0308_fix")
    r = nm.op_link_todo(n["id"], "todo_0308_fix")  # dup ignored
    assert r["resulted_in"] == ["todo_0308_fix"]
    r2 = nm.op_link_todo(n["id"], "todo_0309_other")
    assert r2["resulted_in"] == ["todo_0308_fix", "todo_0309_other"]


# ── captures ─────────────────────────────────────────────────────────────────

def test_add_capture_records_reference(root):
    n = nm.op_create("note")
    r = nm.op_add_capture(n["id"], "LiveBoard > session:Mullion",
                          "live-board", {"state": "idle", "ago": "2m"})
    assert r["success"]
    rd = nm.op_read(n["id"])
    assert len(rd["captures"]) == 1
    assert rd["captures"][0]["component_path"] == "LiveBoard > session:Mullion"
    assert rd["captures"][0]["data"]["state"] == "idle"


def test_create_with_inline_captures(root):
    r = nm.op_create("note", captures=[{
        "component_path": "WorkTab > todo_0287", "source_tab": "work",
        "data": {"status": "blocked"}}])
    meta = nm.read_meta(root / r["id"])
    assert meta["captures"][0]["component_path"] == "WorkTab > todo_0287"


# ── list / read ──────────────────────────────────────────────────────────────

def test_list_filters_by_status_and_recipient(root):
    a = nm.op_create("a", recipients=["Hamilton"])
    b = nm.op_create("b", recipients=["PM"])
    nm.op_set_status(b["id"], "resolved")
    open_notes = nm.op_list(status="open")["notes"]
    assert {n["id"] for n in open_notes} == {a["id"]}
    ham = nm.op_list(recipient="Hamilton")["notes"]
    assert {n["id"] for n in ham} == {a["id"]}


def test_list_summary_is_first_line(root):
    nm.op_create("Summary line\nsecond line")
    notes = nm.op_list()["notes"]
    assert notes[0]["summary"] == "Summary line"


def test_read_missing_note_errors(root):
    assert nm.op_read("note_9999")["success"] is False


def test_resolve_note_by_number_and_id(root):
    n = nm.op_create("note")
    assert nm.resolve_note_dir("1").name == n["id"]
    assert nm.resolve_note_dir(n["id"]).name == n["id"]
    with pytest.raises(ValueError):
        nm.resolve_note_dir("404")


# ── YAML subset round-trip (the hand-rolled emitter/parser) ──────────────────

def test_yaml_roundtrip_nested_and_lists():
    data = {
        "id": "note_0001",
        "recipients": ["Hamilton", "PM"],
        "captures": [
            {"file": "captures/capture_001.yml", "component_path": "A > B"},
        ],
        "nested": {"k": "v", "n": 3},
        "empty": [],
        "flag": True,
        "nullable": None,
    }
    parsed = nm.parse_yaml(nm.dump_yaml(data))
    assert parsed["id"] == "note_0001"
    assert parsed["recipients"] == ["Hamilton", "PM"]
    assert parsed["captures"][0]["component_path"] == "A > B"
    assert parsed["nested"] == {"k": "v", "n": 3}
    assert parsed["empty"] == []
    assert parsed["flag"] is True
    assert parsed["nullable"] is None


def test_yaml_preserves_zero_padded_ids():
    # message/target ids must keep leading zeros (not be coerced to int)
    parsed = nm.parse_yaml(nm.dump_yaml({"id": "001", "turn": 48}))
    assert parsed["id"] == "001"   # stays a string
    assert parsed["turn"] == 48    # real int


def test_yaml_roundtrip_deeply_nested_tree():
    # A captured ViewportNode tree: dicts containing lists of dicts that
    # themselves contain state maps + action lists. This is the shape that
    # exposed the list-item indentation-flattening bug.
    tree = {
        "id": "app", "visible": True, "label": "UAI",
        "state": {"activeTab": "live-board"},
        "children": [
            {
                "id": "tabs", "visible": True, "label": "Workspace",
                "children": [
                    {
                        "id": "live-board", "visible": True, "label": "Live Board",
                        "state": {"rows": 12, "needs": 2},
                        "actions": [
                            {"id": "refresh", "command": "work.landscape", "label": "Refresh"},
                        ],
                        "children": [],
                    },
                ],
            },
        ],
        "timestamp": "2026-06-30T23:50:00-04:00",
    }
    parsed = nm.parse_yaml(nm.dump_yaml(tree))
    assert parsed == tree  # byte-for-byte structural round-trip
    deep = parsed["children"][0]["children"][0]
    assert deep["state"] == {"rows": 12, "needs": 2}
    assert deep["actions"][0]["command"] == "work.landscape"


def test_capture_deep_tree_via_ops(root):
    tree = {"id": "app", "visible": True, "label": "UAI",
            "children": [{"id": "tab", "visible": True, "state": {"k": "v"},
                          "children": [{"id": "leaf", "visible": True,
                                        "state": {"deep": 1}, "children": []}]}]}
    n = nm.op_create("cap")
    nm.op_add_capture(n["id"], "UAI", "live-board", tree)
    rd = nm.op_read(n["id"])
    got = rd["captures"][0]["data"]
    assert got["children"][0]["children"][0]["state"] == {"deep": 1}


def test_message_header_roundtrip():
    header = {"id": "002", "author": "hamilton",
              "reply_to": {"type": "note_message", "id": "001"}}
    front = nm.dump_yaml(header).rstrip("\n")
    text = f"---\n{front}\n---\n\nbody here\n"
    parsed_header, body = nm.parse_message_header(text)
    assert parsed_header["author"] == "hamilton"
    assert parsed_header["reply_to"]["type"] == "note_message"
    assert body.strip() == "body here"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
