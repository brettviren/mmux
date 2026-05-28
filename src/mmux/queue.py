import asyncio
from collections.abc import AsyncGenerator

REMOTE_EVENTS_FILE = "~/.local/state/mmux/events.jsonl"


async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
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
