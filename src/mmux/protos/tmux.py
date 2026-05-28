from dataclasses import dataclass
from mmux.protos import register


@register("tmux", "Activity")
@dataclass
class Activity:
    ts: str
    session: str
    window: int
    pane: int


@register("tmux", "Silence")
@dataclass
class Silence:
    ts: str
    session: str
    window: int
    pane: int


@register("tmux", "SessionCreated")
@dataclass
class SessionCreated:
    ts: str
    session: str


@register("tmux", "SessionClosed")
@dataclass
class SessionClosed:
    ts: str
    session: str


@register("tmux", "PaneCreated")
@dataclass
class PaneCreated:
    ts: str
    session: str
    window: int
    pane: int


@register("tmux", "PaneClosed")
@dataclass
class PaneClosed:
    ts: str
    session: str
    window: int
    pane: int
