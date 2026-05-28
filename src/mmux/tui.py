from __future__ import annotations
import logging
import subprocess
import time
from dataclasses import dataclass, field
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Tree, Static, RichLog
from textual.widgets.tree import TreeNode
from rich.text import Text

log = logging.getLogger(__name__)

ACTIVE_SECS = 30
SILENT_SECS = 300
TIMER_INTERVAL = 10.0


@dataclass
class PaneState:
    host: str
    session: str
    window: int
    pane: int
    last_activity_ts: float = 0.0
    last_silence_ts: float = 0.0
    closed: bool = False
    notification: str | None = None


@dataclass
class NodeData:
    host: str
    session: str | None = None
    pane: int | None = None


def _status(ps: PaneState, now: float,
            active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> tuple[str, str]:
    since_activity = now - ps.last_activity_ts if ps.last_activity_ts else float("inf")
    since_silence = now - ps.last_silence_ts if ps.last_silence_ts else float("inf")
    if ps.last_activity_ts and since_activity <= active_secs:
        return "●", "green"
    if ps.last_silence_ts and since_silence < since_activity:
        return "◎", "yellow"
    if since_activity <= silent_secs:
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
    if ps.closed:
        t.append(f"pane {ps.pane}  {light}  {_ago(last_ts, now)}", style="dim strike")
    else:
        t.append(f"pane {ps.pane}  ")
        t.append(light, style=color)
        t.append(f"  {_ago(last_ts, now)}", style="dim")
        if ps.notification:
            t.append("  [!]", style="bold magenta")
    return t


def _session_label(session: str, panes: list[PaneState], now: float, closed: bool = False) -> Text:
    light, color = _session_status(panes, now) if panes else ("○", "white")
    t = Text()
    if closed:
        t.append(f"▶ {session}  {light}", style="dim strike")
    else:
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
    BINDINGS = [("enter", "attach", "Attach")]

    def populate(self, states: list[PaneState]) -> None:
        self.clear()
        now = _now()
        by_host: dict[str, dict[str, list[PaneState]]] = {}
        for ps in states:
            by_host.setdefault(ps.host, {}).setdefault(ps.session, []).append(ps)

        for host, sessions in sorted(by_host.items()):
            host_node = self.root.add(host, data=NodeData(host=host), expand=True)
            for session, panes in sorted(sessions.items()):
                all_closed = all(p.closed for p in panes)
                label = _session_label(session, [p for p in panes if not p.closed], now, closed=all_closed)
                sess_node = host_node.add(label, data=NodeData(host=host, session=session), expand=True)
                for ps in sorted(panes, key=lambda p: p.pane):
                    sess_node.add_leaf(
                        _pane_label(ps, now),
                        data=NodeData(host=host, session=session, pane=ps.pane),
                    )

    def action_attach(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        d: NodeData = node.data
        if d.session is None:
            return
        cmd = ["ssh", "-t", d.host, f"tmux attach -t {d.session}"]
        if d.pane is not None:
            cmd[-1] += f" \\; select-pane -t {d.pane}"
        with self.app.suspend():
            subprocess.run(cmd)


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
    #notif-bar {
        height: 1;
        background: $panel;
        color: magenta;
        display: none;
    }
    #notif-bar.visible {
        display: block;
    }
    #notif-log {
        height: 8;
        border: tall $panel;
        display: none;
    }
    #notif-log.visible {
        display: block;
    }
    """

    def __init__(self, targets: list[str] | None = None,
                 active_secs: int = ACTIVE_SECS,
                 silent_secs: int = SILENT_SECS,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.targets = targets or ["localhost"]
        self._pane_states: dict[tuple[str, str, int, int], PaneState] = {}
        self._active_secs = active_secs
        self._silent_secs = silent_secs

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionTree("mmux", id="session-tree")
        yield Static("", id="notif-bar")
        yield RichLog(id="notif-log", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.targets == ["localhost"] and not self._pane_states:
            self.query_one(SessionTree).populate(_MOCK_DATA)
        for target in self.targets:
            self.run_worker(self._stream_target(target), exclusive=False)
        self.set_interval(TIMER_INTERVAL, self._refresh_tree)

    async def _stream_target(self, target: str, _backoff: float = 2.0) -> None:
        import asyncio
        try:
            await self.__stream_target_inner(target)
        except Exception as exc:
            log.warning("stream lost for %s: %s; retrying in %.0fs", target, exc, _backoff)
            await asyncio.sleep(_backoff)
            self.run_worker(
                self._stream_target(target, min(_backoff * 2, 60.0)),
                exclusive=False,
            )

    async def __stream_target_inner(self, target: str) -> None:
        import mmux.protos.tmux  # noqa: F401
        import mmux.protos.claude  # noqa: F401
        from mmux.protos import events
        from mmux.protos.tmux import (
            Activity, Silence,
            SessionCreated, SessionClosed,
            PaneCreated, PaneClosed,
        )
        from mmux.protos.claude import Notification

        async for obj in events(target):
            now = _now()

            if isinstance(obj, SessionClosed):
                keys = [k for k in self._pane_states if k[0] == target and k[1] == obj.session]
                for k in keys:
                    self._pane_states[k].closed = True
                self.call_from_thread(self._refresh_tree)
                self.set_timer(5, lambda ks=keys: self._remove_keys(ks))

            elif isinstance(obj, PaneCreated):
                key = (target, obj.session, obj.window, obj.pane)
                if key not in self._pane_states:
                    self._pane_states[key] = PaneState(target, obj.session, obj.window, obj.pane)
                else:
                    self._pane_states[key].closed = False
                self.call_from_thread(self._refresh_tree)

            elif isinstance(obj, PaneClosed):
                key = (target, obj.session, obj.window, obj.pane)
                if key in self._pane_states:
                    self._pane_states[key].closed = True
                    self.call_from_thread(self._refresh_tree)
                    self.set_timer(5, lambda k=key: self._remove_keys([k]))

            elif isinstance(obj, Activity):
                key = (target, obj.session, obj.window, obj.pane)
                ps = self._pane_states.get(key) or PaneState(target, obj.session, obj.window, obj.pane)
                ps.last_activity_ts = now
                self._pane_states[key] = ps
                self.call_from_thread(self._refresh_tree)

            elif isinstance(obj, Silence):
                key = (target, obj.session, obj.window, obj.pane)
                ps = self._pane_states.get(key) or PaneState(target, obj.session, obj.window, obj.pane)
                ps.last_silence_ts = now
                self._pane_states[key] = ps
                self.call_from_thread(self._refresh_tree)

            elif isinstance(obj, Notification):
                self.call_from_thread(self._handle_notification, target, obj.message, obj.session_id)

    def _handle_notification(self, target: str, message: str, session_id: str) -> None:
        # Try to correlate session_id to a known pane
        matched_key: tuple | None = None
        for key, ps in self._pane_states.items():
            if key[0] == target and session_id and session_id in ps.session:
                matched_key = key
                break

        if matched_key:
            self._pane_states[matched_key].notification = message
            self._refresh_tree()

        bar = self.query_one("#notif-bar", Static)
        bar.update(f"[!] {message}")
        bar.add_class("visible")

        log = self.query_one("#notif-log", RichLog)
        origin = f"[{target}/{session_id}]" if session_id else f"[{target}]"
        log.write(f"{origin} {message}")

    def _remove_keys(self, keys: list[tuple]) -> None:
        for k in keys:
            self._pane_states.pop(k, None)
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        self.query_one(SessionTree).populate(list(self._pane_states.values()))

    def action_reconnect(self) -> None:
        self._pane_states.clear()
        for target in self.targets:
            self.run_worker(self._stream_target(target), exclusive=False)

    def action_toggle_log(self) -> None:
        log = self.query_one("#notif-log", RichLog)
        if "visible" in log.classes:
            log.remove_class("visible")
        else:
            log.add_class("visible")


def run() -> None:
    MmuxApp().run()
