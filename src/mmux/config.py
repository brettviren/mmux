"""Read/write ~/.config/mmux/config.toml (XDG). CLI flags always win."""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TargetConfig:
    host: str
    sessions: list[str] = field(default_factory=list)
    container_client: str = ""       # "podman" or "docker"; empty = use global default
    container_home: str = ""         # "volume:mount"; empty = not configured
    container_pmp_mount: str = ""    # container mount path; empty = use global default


@dataclass
class MmuxConfig:
    active_secs: int = 30
    silent_secs: int = 300
    queue_path: str = "~/.local/state/mmux"
    container_client: str = "podman"
    container_pmp_mount: str = "/run/mmux/pmp"
    targets: list[TargetConfig] = field(default_factory=list)


def _xdg_config() -> Path:
    import os
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "mmux" / "config.toml"


def save(cfg: MmuxConfig, path: str | Path | None = None) -> Path:
    """Write *cfg* back to TOML at *path* (default: XDG config location)."""
    p = Path(path) if path else _xdg_config()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "[defaults]\n",
        f"active_secs = {cfg.active_secs}\n",
        f"silent_secs = {cfg.silent_secs}\n",
        f'queue_path = "{cfg.queue_path}"\n',
        f'container_client = "{cfg.container_client}"\n',
        f'container_pmp_mount = "{cfg.container_pmp_mount}"\n',
    ]
    for t in cfg.targets:
        lines.append("\n[[targets]]\n")
        lines.append(f'host = "{t.host}"\n')
        if t.sessions:
            sessions_toml = "[" + ", ".join(f'"{s}"' for s in t.sessions) + "]"
            lines.append(f"sessions = {sessions_toml}\n")
        if t.container_client:
            lines.append(f'container_client = "{t.container_client}"\n')
        if t.container_home:
            lines.append(f'container_home = "{t.container_home}"\n')
        if t.container_pmp_mount:
            lines.append(f'container_pmp_mount = "{t.container_pmp_mount}"\n')
    with p.open("w") as f:
        f.writelines(lines)
    return p


def load(path: str | Path | None = None) -> MmuxConfig:
    p = Path(path) if path else _xdg_config()
    if not p.exists():
        return MmuxConfig()
    with p.open("rb") as f:
        raw = tomllib.load(f)
    defaults = raw.get("defaults", {})
    cfg = MmuxConfig(
        active_secs=defaults.get("active_secs", 30),
        silent_secs=defaults.get("silent_secs", 300),
        queue_path=defaults.get("queue_path", "~/.local/state/mmux"),
        container_client=defaults.get("container_client", "podman"),
        container_pmp_mount=defaults.get("container_pmp_mount", "/run/mmux/pmp"),
        targets=[
            TargetConfig(
                host=t["host"],
                sessions=t.get("sessions", []),
                container_client=t.get("container_client", ""),
                container_home=t.get("container_home", ""),
                container_pmp_mount=t.get("container_pmp_mount", ""),
            )
            for t in raw.get("targets", [])
        ],
    )
    return cfg
