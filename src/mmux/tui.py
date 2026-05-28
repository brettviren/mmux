from __future__ import annotations
import time
from dataclasses import dataclass, field
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Tree
from rich.text import Text

ACTIVE_SECS = 30
SILENT_SECS = 300


@dataclass
class PaneState:
    host: str
    session: str
    window: int
    pane: int
    last_activity_ts: float = 0.0
    last_silence_ts: float = 0.0


@dataclass
class NodeData:
    host: str
    session: str | None = None
    pane: int | None = None


def _status(ps: PaneState, now: float) -> tuple[str, str]:
    """Return (light, color) based on timestamps."""
    since_activity = now - ps.last_activity_ts if ps.last_activity_ts else float("inf")
    since_silence = now - ps.last_silence_ts if ps.last_silence_ts else float("inf")

    if ps.last_activity_ts and since_activity <= ACTIVE_SECS:
        return "●", "green"
    if ps.last_silence_ts and since_silence < since_activity:
        return "◎", "yellow"
    if since_activity <= SILENT_SECS:
        return "◎", "yellow"
    return "○", "white"


def _ago(ts: float, now: float) -> str:
    if not ts:
        return "never"
    diff = int(now - ts)
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    return f"{diff // 3600}h ago"


def _session_status(panes: list[PaneState], now: float) -> tuple[str, str]:
    lights = [_status(ps, now) for ps in panes]
    if any(l == "●" for l, _ in lights):
        return "●", "green"
    if any(l == "◎" for l, _ in lights):
        return "◎", "yellow"
    return "○", "white"


def _pane_label(ps: PaneState, now: float) -> Text:
    light, color = _status(ps, now)
    last_ts = max(ps.last_activity_ts, ps.last_silence_ts)
    t = Text()
    t.append(f"pane {ps.pane}  ")
    t.append(light, style=color)
    t.append(f"  {_ago(last_ts, now)}", style="dim")
    return t


def _session_label(session: str, panes: list[PaneState], now: float) -> Text:
    light, color = _session_status(panes, now)
    t = Text()
    t.append(f"▶ {session}  ")
    t.append(light, style=color)
    return t


_now = time.time
_MOCK_NOW = _now()

_MOCK_DATA: list[PaneState] = [
    PaneState("user@host1", "main", 0, 0, last_activity_ts=_MOCK_NOW - 10),
    PaneState("user@host1", "main", 0, 1, last_silence_ts=_MOCK_NOW - 5),
    PaneState("user@host1", "work", 0, 0, last_activity_ts=_MOCK_NOW - 500),
    PaneState("user@host1", "work", 0, 1, last_activity_ts=_MOCK_NOW - 480),
    PaneState("user@host2", "build", 0, 0, last_silence_ts=_MOCK_NOW - 90),
    PaneState("user@host2", "build", 0, 1, last_activity_ts=_MOCK_NOW - 600),
    PaneState("user@host2", "debug", 0, 0, last_activity_ts=_MOCK_NOW - 5),
    PaneState("user@host2", "debug", 0, 1, last_activity_ts=_MOCK_NOW - 15),
]


class SessionTree(Tree):
    def populate(self, states: list[PaneState]) -> None:
        self.clear()
        now = _now()
        by_host: dict[str, dict[str, list[PaneState]]] = {}
        for ps in states:
            by_host.setdefault(ps.host, {}).setdefault(ps.session, []).append(ps)

        for host, sessions in sorted(by_host.items()):
            host_node = self.root.add(host, data=NodeData(host=host), expand=True)
            for session, panes in sorted(sessions.items()):
                label = _session_label(session, panes, now)
                sess_node = host_node.add(label, data=NodeData(host=host, session=session), expand=True)
                for ps in sorted(panes, key=lambda p: p.pane):
                    sess_node.add_leaf(_pane_label(ps, now), data=NodeData(host=host, session=session, pane=ps.pane))


class MmuxApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "reconnect", "Reconnect"),
        ("l", "toggle_log", "Log"),
    ]

    CSS = """
    SessionTree {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, targets: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.targets = targets or ["localhost"]
        self._pane_states: dict[tuple[str, str, int, int], PaneState] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionTree("mmux", id="session-tree")
        yield Footer()

    def on_mount(self) -> None:
        if self.targets == ["localhost"] and not self._pane_states:
            self.query_one(SessionTree).populate(_MOCK_DATA)
        for target in self.targets:
            self.run_worker(self._stream_target(target), exclusive=False)

    async def _stream_target(self, target: str) -> None:
        import mmux.protos.tmux  # noqa: F401
        import mmux.protos.claude  # noqa: F401
        from mmux.protos import events
        from mmux.protos.tmux import Activity, Silence, SessionCreated, SessionClosed, PaneCreated, PaneClosed

        async for obj in events(target):
            now = _now()
            if isinstance(obj, (Activity, Silence, PaneCreated, PaneClosed)):
                key = (target, obj.session, getattr(obj, "window", 0), getattr(obj, "pane", 0))
                ps = self._pane_states.get(key) or PaneState(
                    target, obj.session,
                    getattr(obj, "window", 0),
                    getattr(obj, "pane", 0),
                )
                if isinstance(obj, Activity):
                    ps.last_activity_ts = now
                elif isinstance(obj, Silence):
                    ps.last_silence_ts = now
                self._pane_states[key] = ps
            self.call_from_thread(self._refresh_tree)

    def _refresh_tree(self) -> None:
        self.query_one(SessionTree).populate(list(self._pane_states.values()))

    def action_reconnect(self) -> None:
        self._pane_states.clear()
        for target in self.targets:
            self.run_worker(self._stream_target(target), exclusive=False)

    def action_toggle_log(self) -> None:
        pass


def run() -> None:
    MmuxApp().run()
