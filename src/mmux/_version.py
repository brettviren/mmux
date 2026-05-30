"""Version resolution: installed package metadata → git describe → unknown."""
from __future__ import annotations


def _compute() -> str:
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("mmux")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass
    import subprocess
    from pathlib import Path
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--dirty"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


__version__ = _compute()
