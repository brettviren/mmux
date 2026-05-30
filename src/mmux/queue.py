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
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_bytes = await proc.communicate()
    if stderr_bytes:
        text = stderr_bytes.decode(errors="replace").strip()
        if text:
            log.debug("ssh(%s) test: %s", target, text)
    return proc.returncode == 0


async def _drain_stderr(proc: asyncio.subprocess.Process, target: str) -> None:
    async for line in proc.stderr:
        text = line.decode(errors="replace").rstrip()
        if text:
            log.warning("ssh(%s): %s", target, text)


async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
    if not await _events_file_exists(target):
        log.info("events file absent on %s; running auto-install", target)
        from mmux.install import install
        await asyncio.get_event_loop().run_in_executor(None, install, target)

    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", target,
        "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(_drain_stderr(proc, target))
    try:
        async for line in proc.stdout:
            yield line.rstrip(b"\n")
    finally:
        proc.terminate()
        try:
            await asyncio.shield(proc.wait())
        except (asyncio.CancelledError, Exception):
            pass
        stderr_task.cancel()
        try:
            await asyncio.shield(stderr_task)
        except (asyncio.CancelledError, Exception):
            pass
