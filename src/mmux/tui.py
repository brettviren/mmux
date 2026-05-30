from __future__ import annotations
import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Tree, Static, RichLog
from textual.widgets.tree import TreeNode
from rich.text import Text

log = logging.getLogger(__name__)

ACTIVE_SECS = 30
SILENT_SECS = 300
TIMER_INTERVAL = 10.0

TMUX_PANE_FORMAT = "#{session_name}|#{window_index}|#{pane_index}|#{window_activity}|#{pane_current_path}|#{pane_current_command}"


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
    current_path: str = ""
    current_command: str = ""


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


def _session_status(panes: list[PaneState], now: float,
                    active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> tuple[str, str]:
    lights = [_status(ps, now, active_secs, silent_secs) for ps in panes]
    if any(l == "●" for l, _ in lights):
        return "●", "green"
    if any(l == "◎" for l, _ in lights):
        return "◎", "yellow"
    return "○", "white"


def _pane_label(ps: PaneState, now: float,
                active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> Text:
    light, color = _status(ps, now, active_secs, silent_secs)
    last_ts = max(ps.last_activity_ts, ps.last_silence_ts)
    t = Text()
    if ps.closed:
        t.append(f"pane {ps.pane}  {light}  {_ago(last_ts, now)}", style="dim strike")
    else:
        t.append(f"pane {ps.pane}  ")
        t.append(light, style=color)
        t.append(f"  {_ago(last_ts, now)}", style="dim")
        if ps.current_command:
            t.append(f"  {ps.current_command}", style="bold")
        if ps.current_path:
            t.append(f"  {ps.current_path}", style="dim")
        if ps.notification:
            t.append("  [!]", style="bold magenta")
    return t


def _session_label(session: str, panes: list[PaneState], now: float, closed: bool = False,
                   active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> Text:
    light, color = _session_status(panes, now, active_secs, silent_secs) if panes else ("○", "white")
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
    PaneState("user@host1", "main", 0, 0, last_activity_ts=_MOCK_NOW - 10,
              current_path="/home/user", current_command="bash"),
    PaneState("user@host1", "main", 0, 1, last_silence_ts=_MOCK_NOW - 5,
              current_path="/home/user/project", current_command="vim"),
    PaneState("user@host1", "work", 0, 0, last_activity_ts=_MOCK_NOW - 500,
              current_path="/home/user/work", current_command="python"),
    PaneState("user@host1", "work", 0, 1, last_activity_ts=_MOCK_NOW - 480,
              current_path="/home/user/work/tests", current_command="pytest"),
    PaneState("user@host2", "build", 0, 0, last_silence_ts=_MOCK_NOW - 90,
              current_path="/srv/app", current_command="make"),
    PaneState("user@host2", "build", 0, 1, last_activity_ts=_MOCK_NOW - 600,
              current_path="/srv/app/src", current_command="bash"),
    PaneState("user@host2", "debug", 0, 0, last_activity_ts=_MOCK_NOW - 5,
              current_path="/srv/app", current_command="gdb"),
    PaneState("user@host2", "debug", 0, 1, last_activity_ts=_MOCK_NOW - 15,
              current_path="/srv/app/src", current_command="bash"),
]


class SessionTree(Tree):
    BINDINGS = [
        ("enter", "attach", "Attach"),
        ("tab", "toggle_node", "Toggle"),
    ]

    show_root = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._collapsed: set[tuple] = set()
        self._tree_structure: frozenset = frozenset()
        # maps (host, session|None, pane|None) -> TreeNode for label-only updates
        self._node_map: dict[tuple, TreeNode] = {}

    def _node_key(self, node: TreeNode) -> tuple | None:
        """Return a stable key for a node, or None if it's a leaf (un-togglable)."""
        if node is self.root:
            return ()
        d: NodeData | None = node.data
        if d is None:
            return None
        if d.session is None:
            return (d.host,)
        if d.pane is None:
            return (d.host, d.session)
        return None  # pane leaves have no children to toggle

    def action_cursor_up(self) -> None:
        log.debug("cursor_up  before: line=%d focus=%s", self.cursor_line, self.has_focus)
        super().action_cursor_up()
        log.debug("cursor_up  after:  line=%d", self.cursor_line)

    def action_cursor_down(self) -> None:
        log.debug("cursor_down before: line=%d focus=%s", self.cursor_line, self.has_focus)
        super().action_cursor_down()
        log.debug("cursor_down after:  line=%d", self.cursor_line)

    def action_toggle_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        key = self._node_key(node)
        if key is None:
            return
        if key in self._collapsed:
            self._collapsed.discard(key)
            node.expand()
        else:
            self._collapsed.add(key)
            node.collapse()

    def populate(self, states: list[PaneState],
                 active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> None:
        new_structure = frozenset((ps.host, ps.session, ps.pane) for ps in states)
        if new_structure == self._tree_structure and self._node_map:
            # Structure unchanged: update labels in-place, cursor untouched.
            self._update_labels(states, active_secs, silent_secs)
            return

        self._tree_structure = new_structure
        self._node_map.clear()

        # Save cursor before the structural rebuild.
        cursor_key: tuple | None = None
        cn = self.cursor_node
        if cn is not None and cn is not self.root and cn.data is not None:
            d: NodeData = cn.data
            cursor_key = (d.host, d.session, d.pane)

        self.clear()
        if () in self._collapsed:
            self.root.collapse()
        else:
            self.root.expand()
        now = _now()
        by_host: dict[str, dict[str, list[PaneState]]] = {}
        for ps in states:
            by_host.setdefault(ps.host, {}).setdefault(ps.session, []).append(ps)

        cursor_target: TreeNode | None = None

        for host, sessions in sorted(by_host.items()):
            host_node = self.root.add(
                host, data=NodeData(host=host),
                expand=(host,) not in self._collapsed,
            )
            self._node_map[(host, None, None)] = host_node
            if cursor_key == (host, None, None):
                cursor_target = host_node
            for session, panes in sorted(sessions.items()):
                all_closed = all(p.closed for p in panes)
                label = _session_label(
                    session, [p for p in panes if not p.closed], now,
                    closed=all_closed, active_secs=active_secs, silent_secs=silent_secs,
                )
                sess_node = host_node.add(
                    label, data=NodeData(host=host, session=session),
                    expand=(host, session) not in self._collapsed,
                )
                self._node_map[(host, session, None)] = sess_node
                if cursor_key == (host, session, None):
                    cursor_target = sess_node
                for ps in sorted(panes, key=lambda p: p.pane):
                    leaf = sess_node.add_leaf(
                        _pane_label(ps, now, active_secs, silent_secs),
                        data=NodeData(host=host, session=session, pane=ps.pane),
                    )
                    self._node_map[(host, session, ps.pane)] = leaf
                    if cursor_key == (host, session, ps.pane):
                        cursor_target = leaf

        if cursor_target is not None:
            self.move_cursor(cursor_target)

    def _update_labels(self, states: list[PaneState],
                       active_secs: float = ACTIVE_SECS, silent_secs: float = SILENT_SECS) -> None:
        """Update node labels in-place without touching tree structure or cursor.

        Writes _label/_updates directly to avoid set_label's call_later(), which
        would post Callback messages into the pump and interleave with key events.
        A single self.refresh() at the end triggers one repaint instead of N.
        """
        now = _now()
        by_host: dict[str, dict[str, list[PaneState]]] = {}
        for ps in states:
            by_host.setdefault(ps.host, {}).setdefault(ps.session, []).append(ps)
        changed = False
        for host, sessions in by_host.items():
            for session, panes in sessions.items():
                all_closed = all(p.closed for p in panes)
                sess_node = self._node_map.get((host, session, None))
                if sess_node is not None:
                    sess_node._label = self.process_label(_session_label(
                        session, [p for p in panes if not p.closed], now,
                        closed=all_closed, active_secs=active_secs, silent_secs=silent_secs,
                    ))
                    sess_node._updates += 1
                    changed = True
                for ps in panes:
                    pane_node = self._node_map.get((host, session, ps.pane))
                    if pane_node is not None:
                        pane_node._label = self.process_label(
                            _pane_label(ps, now, active_secs, silent_secs)
                        )
                        pane_node._updates += 1
                        changed = True
        if changed:
            self.refresh()

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
        log.info("attaching: %s", " ".join(cmd))
        with self.app.suspend():
            result = subprocess.run(cmd)
            if result.returncode != 0:
                log.warning("attach exited with code %d", result.returncode)


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
        self._ever_had_real_data = False
        self._last_display_refresh: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        yield SessionTree("mmux", id="session-tree")
        yield Static("", id="notif-bar")
        yield RichLog(id="notif-log", highlight=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.targets == ["localhost"] and not self._pane_states:
            self.query_one(SessionTree).populate(_MOCK_DATA)
            self._last_display_refresh = _now()
        for target in self.targets:
            self.run_worker(self._stream_target(target), exclusive=False)
        self.set_interval(TIMER_INTERVAL, self._on_poll_timer)
        self.set_interval(1.0, self._on_display_timer)

    def _on_poll_timer(self) -> None:
        for target in self.targets:
            self.run_worker(
                self._fetch_pane_states(target),
                name=f"poll-{target}",
                exclusive=True,
            )

    def _on_display_timer(self) -> None:
        now = _now()
        if now - self._last_display_refresh >= self._display_interval(now):
            self._refresh_tree()

    def _display_interval(self, now: float) -> float:
        """Return how many seconds should elapse between display refreshes."""
        states = (
            list(self._pane_states.values())
            if self._pane_states
            else ([] if self._ever_had_real_data else _MOCK_DATA)
        )
        min_age = min(
            (now - max(ps.last_activity_ts, ps.last_silence_ts)
             for ps in states
             if ps.last_activity_ts or ps.last_silence_ts),
            default=float("inf"),
        )
        if min_age < 60:
            return 1.0
        if min_age < 3600:
            return 60.0
        return 3600.0

    async def _fetch_pane_states(self, target: str) -> None:
        """Query tmux list-panes directly for current activity timestamps."""
        # Pass as a single string so the remote shell doesn't interpret the
        # | separators in TMUX_PANE_FORMAT as pipes.
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "BatchMode=yes", target,
            f"tmux list-panes -a -F '{TMUX_PANE_FORMAT}'",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            log.debug("tmux list-panes on %s failed (rc=%d)", target, proc.returncode)
            return
        count = 0
        for raw in stdout.decode(errors="replace").splitlines():
            # Split with limit so pane_current_command (last field) may contain "|"
            parts = raw.split("|", 5)
            if len(parts) != 6:
                continue
            session, window_s, pane_s, activity_s, current_path, current_command = parts
            try:
                window = int(window_s)
                pane_num = int(pane_s)
            except ValueError:
                continue
            key = (target, session, window, pane_num)
            ps = self._pane_states.get(key) or PaneState(target, session, window, pane_num)
            if activity_s.isdigit():
                ps.last_activity_ts = float(activity_s)
            ps.current_path = current_path
            ps.current_command = current_command
            self._pane_states[key] = ps
            count += 1
        log.debug("polled %d panes from %s", count, target)
        if count:
            self._refresh_tree()

    async def _stream_target(self, target: str, _backoff: float = 2.0) -> None:
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

        # Bootstrap initial pane state from tmux before blocking on the event stream.
        await self._fetch_pane_states(target)

        log.debug("event stream started for %s", target)
        async for obj in events(target):
            now = _now()
            log.debug("tui received %r from %s", obj, target)

            if isinstance(obj, SessionCreated):
                self.run_worker(
                    self._fetch_pane_states(target),
                    name=f"poll-{target}",
                    exclusive=True,
                )

            elif isinstance(obj, SessionClosed):
                keys = [k for k in self._pane_states if k[0] == target and k[1] == obj.session]
                for k in keys:
                    self._pane_states[k].closed = True
                self._refresh_tree()
                self.set_timer(5, lambda ks=keys: self._remove_keys(ks))

            elif isinstance(obj, PaneCreated):
                key = (target, obj.session, obj.window, obj.pane)
                if key not in self._pane_states:
                    self._pane_states[key] = PaneState(target, obj.session, obj.window, obj.pane)
                else:
                    self._pane_states[key].closed = False
                self._refresh_tree()

            elif isinstance(obj, PaneClosed):
                key = (target, obj.session, obj.window, obj.pane)
                if key in self._pane_states:
                    self._pane_states[key].closed = True
                    self._refresh_tree()
                    self.set_timer(5, lambda k=key: self._remove_keys([k]))

            elif isinstance(obj, Activity):
                key = (target, obj.session, obj.window, obj.pane)
                ps = self._pane_states.get(key) or PaneState(target, obj.session, obj.window, obj.pane)
                ps.last_activity_ts = now
                self._pane_states[key] = ps
                self._refresh_tree()

            elif isinstance(obj, Silence):
                key = (target, obj.session, obj.window, obj.pane)
                ps = self._pane_states.get(key) or PaneState(target, obj.session, obj.window, obj.pane)
                ps.last_silence_ts = now
                self._pane_states[key] = ps
                self._refresh_tree()

            elif isinstance(obj, Notification):
                self._handle_notification(target, obj.message, obj.session_id)

    def _handle_notification(self, target: str, message: str, session_id: str) -> None:
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
        self._last_display_refresh = _now()
        tree = self.query_one(SessionTree)
        if self._pane_states:
            self._ever_had_real_data = True
            tree.populate(
                list(self._pane_states.values()),
                active_secs=self._active_secs,
                silent_secs=self._silent_secs,
            )
        elif self._ever_had_real_data:
            tree.populate([])
        else:
            tree.populate(_MOCK_DATA)  # age mock timestamps in real time

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
