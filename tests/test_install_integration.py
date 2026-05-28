"""Integration test: install to localhost and verify directory structure.

Run with:  pytest tests/test_install_integration.py -m integration
Requires: ssh localhost (BatchMode), mmuxq in prototype/, tmux running.
"""
import json
import os
import subprocess
import pytest

pytestmark = pytest.mark.integration


def _ssh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-T", "localhost", "bash", "-c", cmd],
        capture_output=True, text=True, check=True,
    )


@pytest.fixture(scope="module")
def installed():
    from mmux.install import install, uninstall
    install("localhost")
    yield
    uninstall("localhost", purge=True)


def test_queue_directory_exists(installed):
    _ssh("test -d ~/.local/state/mmux/queue")


def test_events_file_exists(installed):
    _ssh("test -f ~/.local/state/mmux/events.jsonl")


def test_dispatcher_running(installed):
    _ssh("test -f ~/.local/state/mmux/queue/dispatcher.pid")
    pid = _ssh("cat ~/.local/state/mmux/queue/dispatcher.pid").stdout.strip()
    _ssh(f"kill -0 {pid}")


def test_pmp_files_written(installed):
    _ssh("test -s ~/.local/state/mmux/tmux.pmp")
    _ssh("test -s ~/.local/state/mmux/claude.pmp")


def test_helpers_installed_and_executable(installed):
    _ssh("test -x ~/.local/bin/mmux-hook")
    _ssh("test -x ~/.local/bin/mmux-claude-hook")


def test_tmux_hooks_set(installed):
    result = _ssh("tmux show-hooks -g alert-activity 2>/dev/null || true")
    assert "mmux-hook" in result.stdout


def test_claude_settings_has_notification_hook(installed):
    result = _ssh("cat ~/.claude/settings.json")
    cfg = json.loads(result.stdout)
    notifs = cfg.get("hooks", {}).get("Notification", [])
    commands = [
        h.get("command")
        for entry in notifs
        for h in entry.get("hooks", [])
    ]
    assert "~/.local/bin/mmux-claude-hook" in commands
