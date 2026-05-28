"""Read ~/.config/mmux/config.toml (XDG). CLI flags always win."""
from __future__ import annotations
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TargetConfig:
    host: str
    sessions: list[str] = field(default_factory=list)


@dataclass
class MmuxConfig:
    active_secs: int = 30
    silent_secs: int = 300
    queue_path: str = "~/.local/state/mmux"
    targets: list[TargetConfig] = field(default_factory=list)


def _xdg_config() -> Path:
    import os
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "mmux" / "config.toml"


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
        targets=[
            TargetConfig(host=t["host"], sessions=t.get("sessions", []))
            for t in raw.get("targets", [])
        ],
    )
    return cfg
