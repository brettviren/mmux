import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mmux.queue import line_stream, REMOTE_EVENTS_FILE


def _make_mock_proc(lines: list[bytes]):
    """Return a mock asyncio Process whose stdout yields the given lines."""
    async def _stdout_aiter():
        for line in lines:
            yield line

    async def _stderr_aiter():
        return
        yield  # make it an async generator

    mock_stdout = MagicMock()
    mock_stdout.__aiter__ = lambda self: _stdout_aiter()

    mock_stderr = MagicMock()
    mock_stderr.__aiter__ = lambda self: _stderr_aiter()

    mock_proc = AsyncMock()
    mock_proc.stdout = mock_stdout
    mock_proc.stderr = mock_stderr
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_proc.pid = 12345
    return mock_proc


@pytest.mark.asyncio
async def test_line_stream_yields_stripped_lines():
    payload = [
        json.dumps({"proto": "tmux", "schema": "SessionCreated", "ts": "1", "session": "s1"}).encode() + b"\n",
        json.dumps({"proto": "claude", "schema": "Notification", "ts": "2", "message": "hi"}).encode() + b"\n",
    ]
    mock_proc = _make_mock_proc(payload)

    with patch("mmux.ssh.asyncio.create_subprocess_exec", return_value=mock_proc):
        collected = []
        async for line in line_stream("user@host"):
            collected.append(line)

    assert len(collected) == 2
    assert not collected[0].endswith(b"\n")
    assert not collected[1].endswith(b"\n")
    assert json.loads(collected[0])["schema"] == "SessionCreated"
    assert json.loads(collected[1])["message"] == "hi"


@pytest.mark.asyncio
async def test_line_stream_terminates_on_empty():
    mock_proc = _make_mock_proc([])

    with patch("mmux.ssh.asyncio.create_subprocess_exec", return_value=mock_proc):
        collected = [line async for line in line_stream("host")]

    assert collected == []
    mock_proc.terminate.assert_called_once()
