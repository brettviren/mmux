"""Read/write ~/.config/mmux/config.toml (XDG). CLI flags always win."""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TargetConfig:
    host: str
    sessions: list[str] = field(default_factory=list)


@dataclass
class ContainerConfig:
    client: str = ""
    pmp_mount: str = ""
    home_volume: str = ""
    home_mount: str = ""
    run_args: str = ""


@dataclass
class MmuxConfig:
    active_secs: int = 30
    silent_secs: int = 300
    queue_path: str = "~/.local/state/mmux"
    containers: dict[str, ContainerConfig] = field(default_factory=dict)
    targets: list[TargetConfig] = field(default_factory=list)


def resolve_container(cfg: MmuxConfig, nick: str) -> ContainerConfig:
    """Merge ``container.<nick>`` over ``container.default``, filling hardcoded fallbacks."""
    default = cfg.containers.get("default", ContainerConfig())
    named = cfg.containers.get(nick, ContainerConfig()) if nick != "default" else ContainerConfig()
    return ContainerConfig(
        client=named.client or default.client or "podman",
        pmp_mount=named.pmp_mount or default.pmp_mount or "/run/mmux/pmp",
        home_volume=named.home_volume or default.home_volume,
        home_mount=named.home_mount or default.home_mount,
        run_args=named.run_args or default.run_args,
    )


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
    ]
    for nick, ccfg in cfg.containers.items():
        lines.append(f"\n[container.{nick}]\n")
        if ccfg.client:
            lines.append(f'client = "{ccfg.client}"\n')
        if ccfg.pmp_mount:
            lines.append(f'pmp_mount = "{ccfg.pmp_mount}"\n')
        if ccfg.home_volume:
            lines.append(f'home_volume = "{ccfg.home_volume}"\n')
        if ccfg.home_mount:
            lines.append(f'home_mount = "{ccfg.home_mount}"\n')
        if ccfg.run_args:
            lines.append(f'run_args = "{ccfg.run_args}"\n')
    for t in cfg.targets:
        lines.append("\n[[targets]]\n")
        lines.append(f'host = "{t.host}"\n')
        if t.sessions:
            sessions_toml = "[" + ", ".join(f'"{s}"' for s in t.sessions) + "]"
            lines.append(f"sessions = {sessions_toml}\n")
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
    containers = {
        nick: ContainerConfig(
            client=c.get("client", ""),
            pmp_mount=c.get("pmp_mount", ""),
            home_volume=c.get("home_volume", ""),
            home_mount=c.get("home_mount", ""),
            run_args=c.get("run_args", ""),
        )
        for nick, c in raw.get("container", {}).items()
    }
    cfg = MmuxConfig(
        active_secs=defaults.get("active_secs", 30),
        silent_secs=defaults.get("silent_secs", 300),
        queue_path=defaults.get("queue_path", "~/.local/state/mmux"),
        containers=containers,
        targets=[
            TargetConfig(host=t["host"], sessions=t.get("sessions", []))
            for t in raw.get("targets", [])
        ],
    )
    return cfg
