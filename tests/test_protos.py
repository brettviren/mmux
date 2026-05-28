import json
import pytest
import mmux.protos.tmux  # noqa: F401 — registers tmux schemas
import mmux.protos.claude  # noqa: F401 — registers claude schemas
from mmux.protos import parse_line
from mmux.protos.tmux import Activity, Silence, SessionCreated, SessionClosed, PaneCreated, PaneClosed
from mmux.protos.claude import Notification


def _line(**kw) -> bytes:
    return json.dumps(kw).encode()


def test_activity():
    line = _line(proto="tmux", schema="Activity", ts="1000", session="main", window=0, pane=1)
    obj = parse_line(line)
    assert isinstance(obj, Activity)
    assert obj.session == "main"
    assert obj.window == 0
    assert obj.pane == 1
    assert obj.ts == "1000"


def test_silence():
    line = _line(proto="tmux", schema="Silence", ts="2000", session="work", window=1, pane=0)
    obj = parse_line(line)
    assert isinstance(obj, Silence)
    assert obj.session == "work"


def test_session_created():
    obj = parse_line(_line(proto="tmux", schema="SessionCreated", ts="3000", session="s1"))
    assert isinstance(obj, SessionCreated)
    assert obj.session == "s1"


def test_session_closed():
    obj = parse_line(_line(proto="tmux", schema="SessionClosed", ts="4000", session="s1"))
    assert isinstance(obj, SessionClosed)
    assert obj.session == "s1"


def test_pane_created():
    obj = parse_line(_line(proto="tmux", schema="PaneCreated", ts="5000", session="s1", window=2, pane=3))
    assert isinstance(obj, PaneCreated)
    assert obj.window == 2
    assert obj.pane == 3


def test_pane_closed():
    obj = parse_line(_line(proto="tmux", schema="PaneClosed", ts="6000", session="s1", window=2, pane=3))
    assert isinstance(obj, PaneClosed)


def test_notification():
    line = _line(proto="claude", schema="Notification", ts="7000", message="hello", session_id="abc")
    obj = parse_line(line)
    assert isinstance(obj, Notification)
    assert obj.message == "hello"
    assert obj.session_id == "abc"


def test_notification_default_session_id():
    line = _line(proto="claude", schema="Notification", ts="7000", message="hi")
    obj = parse_line(line)
    assert isinstance(obj, Notification)
    assert obj.session_id == ""


def test_unknown_proto_returns_none():
    line = _line(proto="unknown", schema="Whatever", ts="0")
    assert parse_line(line) is None


def test_unknown_schema_returns_none():
    line = _line(proto="tmux", schema="NoSuch", ts="0")
    assert parse_line(line) is None


def test_bad_json_returns_none():
    assert parse_line(b"not json at all") is None


def test_str_input():
    line = json.dumps({"proto": "tmux", "schema": "SessionCreated", "ts": "0", "session": "x"})
    obj = parse_line(line)
    assert isinstance(obj, SessionCreated)


def test_dataclass_mismatch_returns_none():
    # Missing required field 'session'
    line = _line(proto="tmux", schema="SessionCreated", ts="0")
    assert parse_line(line) is None
