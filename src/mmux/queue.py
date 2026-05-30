import logging
from collections.abc import AsyncGenerator

from mmux import ssh

log = logging.getLogger(__name__)

REMOTE_EVENTS_FILE = "~/.local/state/mmux/events.jsonl"


async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
    log.debug("tail -f %s:%s", target, REMOTE_EVENTS_FILE)
    async for line in ssh.async_stream(
        target, "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE
    ):
        log.debug("raw line from %s: %r", target, line[:120])
        yield line
