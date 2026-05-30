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


def _prime_script(pmp_mount: str, home_mount: str) -> str:
    """Build the bash script that runs inside the container to install hooks.

    Uses explicit paths (not ~) so the script is correct regardless of which
    shell user runs it (the priming run executes as root).
    """
    from mmux.install import MMUX_CLAUDE_HOOK
    hook_b64 = base64.b64encode(MMUX_CLAUDE_HOOK.encode()).decode()
    h = home_mount.rstrip("/")
    lines = [
        "#!/usr/bin/env bash",
        "set -e",
        f"mkdir -p {h}/.local/bin {h}/.local/state/mmux {h}/.claude",
        f"printf '%s\\n' '{pmp_mount}' > {h}/.local/state/mmux/claude.pmp",
        f"echo '{hook_b64}' | base64 -d > {h}/.local/bin/mmux-claude-hook",
        f"chmod +x {h}/.local/bin/mmux-claude-hook",
        "python3 - << 'ENDOFPY'",
        "import json, os, pathlib",
        f"p = pathlib.Path('{h}') / '.claude' / 'settings.json'",
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
    home_volume: str,
    home_mount: str,
    pmp_mount: str = DEFAULT_PMP_MOUNT,
) -> None:
    """Run a one-shot container on *target* that configures claude hooks on the home volume.

    The priming container runs as root so it can write to a fresh volume whose
    root directory is owned by root.  The PMP volume is not needed for priming.
    """
    script = _prime_script(pmp_mount, home_mount)
    cmd = [
        client, "run", "--rm", "-i",
        "--user", "root",
        "-e", f"HOME={home_mount}",
        "-v", f"{home_volume}:{home_mount}",
        container, "bash", "-s",
    ]
    log.info("priming container %s on %s", container, target)
    log.debug("prime cmd: %s", " ".join(cmd))
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
