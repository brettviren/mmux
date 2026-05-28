from dataclasses import dataclass, field
from mmux.protos import register


@register("claude", "Notification")
@dataclass
class Notification:
    ts: str
    message: str
    session_id: str = ""
