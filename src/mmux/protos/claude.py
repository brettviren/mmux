from dataclasses import dataclass
from mmux.protos import register


@register("claude", "Notification")
@dataclass
class Notification:
    ts: str
    message: str
    session_id: str = ""
    tmux_session: str = ""
    tmux_window: int = -1
    tmux_pane: int = -1
