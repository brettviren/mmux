"""Centralized SSH subprocess helpers — all stderr is routed to DEBUG logging.

Every call site that executes ssh or scp should use these helpers so that
connection banners and other stray client output never reach the terminal.
"""
from __future__ import annotations
import asyncio
import logging
import subprocess
from collections.abc import AsyncGenerator

log = logging.getLogger(__name__)

_BATCH = ("-o", "BatchMode=yes")


# ---------------------------------------------------------------------------
# Synchronous helpers (used by install.py)
# ---------------------------------------------------------------------------

def run(
    target: str,
    *cmd: str,
    input: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Non-interactive SSH command; stderr captured and emitted at DEBUG."""
    args = ["ssh", *_BATCH, "-T", target, *cmd]
    result = subprocess.run(args, input=input, capture_output=True, text=True, check=False)
    _log_stderr(target, result.stderr)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, args, result.stdout, result.stderr
        )
    return result


def scp(src: str, dst: str) -> None:
    """Copy a file via SCP; stderr captured and emitted at DEBUG."""
    args = ["scp", *_BATCH, "-q", src, dst]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    _log_stderr(f"scp:{dst}", result.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)


def attach(host: str, remote_cmd: str) -> int:
    """SSH with PTY (-t) for interactive use; stderr captured at DEBUG, not terminal."""
    args = ["ssh", "-t", host, remote_cmd]
    result = subprocess.run(args, stderr=subprocess.PIPE)
    _log_stderr(host, result.stderr.decode(errors="replace"))
    return result.returncode


# ---------------------------------------------------------------------------
# Async helpers (used by queue.py and tui.py)
# ---------------------------------------------------------------------------

async def async_run(target: str, *cmd: str) -> tuple[bytes, int]:
    """One-shot async SSH command; returns (stdout_bytes, returncode), stderr → DEBUG."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_BATCH, "-T", target, *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    _log_stderr(target, stderr.decode(errors="replace"))
    return stdout, proc.returncode


async def async_stream(target: str, *cmd: str) -> AsyncGenerator[bytes, None]:
    """Async SSH that yields stdout lines; stderr drained to DEBUG in background."""
    proc = await asyncio.create_subprocess_exec(
        "ssh", *_BATCH, target, *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    log.debug("ssh(%s) pid=%s", target, proc.pid)
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


async def _drain_stderr(proc: asyncio.subprocess.Process, target: str) -> None:
    async for line in proc.stderr:
        _log_stderr(target, line.decode(errors="replace"))


def _log_stderr(context: str, text: str) -> None:
    for line in text.splitlines():
        line = line.strip()
        if line:
            log.debug("ssh(%s): %s", context, line)
