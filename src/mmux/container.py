"""Container (podman/docker) hook priming for mmux."""
from __future__ import annotations
import base64
import logging
import subprocess
from pathlib import Path

from mmux import ssh

log = logging.getLogger(__name__)

DEFAULT_CLIENT = "podman"
DEFAULT_PMP_MOUNT = "/run/mmux/pmp"


def _prime_script(pmp_mount: str) -> str:
    """Build the bash script that runs inside the container to install hooks."""
    from mmux.install import MMUX_CLAUDE_HOOK
    hook_b64 = base64.b64encode(MMUX_CLAUDE_HOOK.encode()).decode()
    lines = [
        "#!/usr/bin/env bash",
        "set -e",
        "mkdir -p ~/.local/bin ~/.local/state/mmux ~/.claude",
        f"printf '%s\\n' '{pmp_mount}' > ~/.local/state/mmux/claude.pmp",
        f"echo '{hook_b64}' | base64 -d > ~/.local/bin/mmux-claude-hook",
        "chmod +x ~/.local/bin/mmux-claude-hook",
        "python3 - << 'ENDOFPY'",
        "import json, pathlib",
        "p = pathlib.Path.home() / '.claude' / 'settings.json'",
        "cfg = json.loads(p.read_text()) if p.exists() and p.stat().st_size else {}",
        "cmd = '~/.local/bin/mmux-claude-hook'",
        "hook = {'matcher': '', 'hooks': [{'type': 'command', 'command': cmd}]}",
        "notifs = cfg.setdefault('hooks', {}).setdefault('Notification', [])",
        "if not any(any(h.get('command') == cmd for h in e.get('hooks', [])) for e in notifs):",
        "    notifs.append(hook)",
        "p.parent.mkdir(parents=True, exist_ok=True)",
        "p.write_text(json.dumps(cfg, indent=2))",
        "ENDOFPY",
        "",
    ]
    return "\n".join(lines)


def prime_hooks(
    target: str,
    container: str,
    *,
    client: str = DEFAULT_CLIENT,
    home: str,
    pmp_mount: str = DEFAULT_PMP_MOUNT,
) -> None:
    """Run a one-shot container on *target* that configures claude hooks on the home volume.

    *home* is a ``volume:mount`` string passed directly to ``-v`` (the PMP volume is
    not needed for priming — only the home volume).
    """
    script = _prime_script(pmp_mount)
    cmd = [client, "run", "--rm", "-i", "-v", home, container, "bash", "-s"]
    log.info("priming container %s on %s", container, target)
    if target == "localhost":
        result = subprocess.run(cmd, input=script, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"priming failed (rc={result.returncode}): {result.stderr.strip()}"
            )
    else:
        ssh.run(target, *cmd, input=script)
    log.info("priming complete: %s on %s", container, target)


def get_pmp_host_path(target: str, queue_path: str = "~/.local/state/mmux") -> str | None:
    """Return the claude PMP directory path on *target*, or None if not provisioned."""
    pmp_file = f"{queue_path}/claude.pmp"
    if target == "localhost":
        p = Path(pmp_file).expanduser()
        if p.exists():
            return p.read_text().strip() or None
        return None
    r = ssh.run(target, "cat", pmp_file, check=False)
    return r.stdout.strip() or None
