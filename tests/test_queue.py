import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mmux.queue import line_stream, REMOTE_EVENTS_FILE


def _make_mock_proc(lines: list[bytes]):
    """Return a mock asyncio Process whose stdout yields the given lines."""
    async def _aiter():
        for line in lines:
            yield line

    mock_stdout = MagicMock()
    mock_stdout.__aiter__ = lambda self: _aiter()

    mock_proc = AsyncMock()
    mock_proc.stdout = mock_stdout
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()
    return mock_proc


@pytest.mark.asyncio
async def test_line_stream_yields_stripped_lines():
    payload = [
        json.dumps({"proto": "tmux", "schema": "SessionCreated", "ts": "1", "session": "s1"}).encode() + b"\n",
        json.dumps({"proto": "claude", "schema": "Notification", "ts": "2", "message": "hi"}).encode() + b"\n",
    ]
    mock_proc = _make_mock_proc(payload)

    with patch("mmux.queue.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        collected = []
        async for line in line_stream("user@host"):
            collected.append(line)

    assert len(collected) == 2
    assert not collected[0].endswith(b"\n")
    assert not collected[1].endswith(b"\n")
    assert json.loads(collected[0])["schema"] == "SessionCreated"
    assert json.loads(collected[1])["message"] == "hi"

    mock_exec.assert_called_once_with(
        "ssh", "-o", "BatchMode=yes", "user@host",
        "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    mock_proc.terminate.assert_called_once()
    mock_proc.wait.assert_called_once()


@pytest.mark.asyncio
async def test_line_stream_terminates_on_empty():
    mock_proc = _make_mock_proc([])

    with patch("mmux.queue.asyncio.create_subprocess_exec", return_value=mock_proc):
        collected = [line async for line in line_stream("host")]

    assert collected == []
    mock_proc.terminate.assert_called_once()
