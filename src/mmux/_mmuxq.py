"""Entry point for the mmuxq command — runs the bundled bash script."""
from __future__ import annotations

import importlib.resources
import subprocess
import sys


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("--version", "-V"):
        from mmux._version import __version__
        print(__version__)
        sys.exit(0)

    ref = importlib.resources.files("mmux").joinpath("mmuxq")
    with importlib.resources.as_file(ref) as script_path:
        result = subprocess.run(["bash", str(script_path), *args])
    sys.exit(result.returncode)
