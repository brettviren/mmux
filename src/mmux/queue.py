import asyncio
import logging
from collections.abc import AsyncGenerator

log = logging.getLogger(__name__)

REMOTE_EVENTS_FILE = "~/.local/state/mmux/events.jsonl"


async def _events_file_exists(target: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", "-T", target,
        "test", "-f", REMOTE_EVENTS_FILE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
    if not await _events_file_exists(target):
        log.info("events file absent on %s; running auto-install", target)
        from mmux.install import install
        await asyncio.get_event_loop().run_in_executor(None, install, target)

    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", target,
        "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async for line in proc.stdout:
            yield line.rstrip(b"\n")
    finally:
        proc.terminate()
        await proc.wait()
