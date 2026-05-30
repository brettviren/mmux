import asyncio
import logging
from collections.abc import AsyncGenerator

from mmux import ssh

log = logging.getLogger(__name__)

REMOTE_EVENTS_FILE = "~/.local/state/mmux/events.jsonl"


async def _events_file_exists(target: str) -> bool:
    _, rc = await ssh.async_run(target, "test", "-f", REMOTE_EVENTS_FILE)
    return rc == 0


async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
    if not await _events_file_exists(target):
        log.info("events file absent on %s; running auto-install", target)
        from mmux.install import install
        await asyncio.get_event_loop().run_in_executor(None, install, target)

    log.debug("tail -f %s:%s", target, REMOTE_EVENTS_FILE)
    async for line in ssh.async_stream(
        target, "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE
    ):
        log.debug("raw line from %s: %r", target, line[:120])
        yield line
