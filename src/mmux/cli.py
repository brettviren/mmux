from __future__ import annotations
import logging
import os
from pathlib import Path
import click

from mmux._version import __version__

_DEFAULT_LOG_FILE = os.path.join(os.path.expanduser("~"), ".cache", "mmux.log")


@click.group()
@click.version_option(version=__version__, prog_name="mmux")
@click.option("--debug", is_flag=True, help="Enable debug logging (shorthand for -L debug).")
@click.option("--config", "config_path", default=None, metavar="PATH",
              help="Config file (default: ~/.config/mmux/config.toml).")
@click.option("-l", "--log-file", "log_file", default=_DEFAULT_LOG_FILE, metavar="PATH",
              show_default=True, help="Log file path.")
@click.option("-L", "--log-level", "log_level", default="info", metavar="LEVEL",
              show_default=True, help="Logging level: debug, info, warning, error.")
@click.pass_context
def main(ctx: click.Context, debug: bool, config_path: str | None,
         log_file: str, log_level: str) -> None:
    level = logging.DEBUG if debug else getattr(logging, log_level.upper(), logging.INFO)
    log_path = Path(log_file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path)],
    )
    from mmux.config import load
    ctx.ensure_object(dict)
    ctx.obj["cfg"] = load(config_path)
    ctx.obj["log_file"] = str(log_path)


@main.command()
@click.option("--queue-path", default=None, show_default=True,
              help="Base directory for mmux state on the remote host.")
@click.option("--force", is_flag=True,
              help="Pass --force to uv tool install (overwrites existing binaries).")
@click.argument("targets", nargs=-1, required=True)
@click.pass_context
def install(ctx: click.Context, queue_path: str | None, force: bool,
            targets: tuple[str, ...]) -> None:
    """Install mmux on one or more remote TARGETS via uv tool install."""
    from mmux.install import install as do_install
    cfg = ctx.obj["cfg"]
    qp = queue_path or cfg.queue_path
    for target in targets:
        click.echo(f"Installing on {target} ...")
        try:
            do_install(target, queue_path=qp, force=force)
            click.echo(f"  Done: {target}")
        except RuntimeError as exc:
            click.echo(f"  Failed: {exc}")


@main.command()
@click.option(
    "--action",
    type=click.Choice(["stop", "purge", "remove"]),
    default="stop",
    show_default=True,
    help=(
        "stop: stop the dispatcher. "
        "purge: stop + delete queue state. "
        "remove: purge + uv tool uninstall mmux."
    ),
)
@click.argument("targets", nargs=-1, required=True)
def uninstall(action: str, targets: tuple[str, ...]) -> None:
    """Uninstall mmux from one or more remote TARGETS."""
    from mmux.install import uninstall as do_uninstall
    for target in targets:
        click.echo(f"Uninstalling ({action}) from {target} ...")
        do_uninstall(target, action=action)
        click.echo(f"  Done: {target}")


@main.command()
@click.option("--queue-path", default=None, help="Override remote queue path.")
@click.argument("targets", nargs=-1, required=True)
@click.pass_context
def status(ctx: click.Context, queue_path: str | None, targets: tuple[str, ...]) -> None:
    """Print one-line status for each remote TARGET."""
    import subprocess
    cfg = ctx.obj["cfg"]
    qp = queue_path or cfg.queue_path
    qmp = f"{qp}/queue"

    for target in targets:
        def _ssh(cmd: str) -> str:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-T", target, cmd],
                capture_output=True, text=True,
            )
            return r.stdout.strip() if r.returncode == 0 else ""

        # Remote version
        version = _ssh('PATH="$HOME/.local/bin:$PATH" mmuxq --version 2>/dev/null') or "unknown"

        # Dispatcher state
        pid = _ssh(f"cat {qmp}/dispatcher.pid 2>/dev/null")
        if pid:
            alive = _ssh(f"kill -0 {pid} 2>/dev/null && echo yes || echo no")
            disp = "running" if alive == "yes" else "stale pid"
        else:
            disp = "stopped"

        # Queue directory info
        if _ssh(f"test -d {qmp} && echo yes") != "yes":
            queue = "missing"
        else:
            np = _ssh(f"find {qmp}/producers -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' '") or "0"
            nc = _ssh(f"find {qmp}/consumers -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' '") or "0"
            queue = f"{qmp} Np={np} Nc={nc}"

        # Pending messages
        pending = _ssh(f"find {qmp}/producers -type f 2>/dev/null | wc -l") or "0"

        # Last event timestamp
        last_event = _ssh(
            f"tail -1 {qp}/events.jsonl 2>/dev/null | python3 -c "
            f"\"import sys,json; d=json.load(sys.stdin); print(d.get('ts','?'))\" 2>/dev/null"
        ) or "never"

        click.echo(
            f"{target}: version={version}  dispatcher={disp}"
            f"  queue={queue}  pending={pending}  last={last_event}"
        )


@main.command()
@click.option("--active-secs", default=None, type=int,
              help="Seconds until a pane transitions from active to newly-silent.")
@click.option("--silent-secs", default=None, type=int,
              help="Seconds until a pane transitions from newly-silent to long-silent.")
@click.argument("targets", nargs=-1)
@click.pass_context
def tui(ctx: click.Context, active_secs: int | None, silent_secs: int | None,
        targets: tuple[str, ...]) -> None:
    """Launch the mmux TUI, streaming events from TARGETS.

    TARGET format: [user@]host[:session-name].
    If no targets are given, config targets are used, falling back to localhost.
    """
    from mmux.tui import MmuxApp
    cfg = ctx.obj["cfg"]

    resolved: list[str] = list(targets) or [t.host for t in cfg.targets] or ["localhost"]
    MmuxApp(
        targets=resolved,
        active_secs=active_secs or cfg.active_secs,
        silent_secs=silent_secs or cfg.silent_secs,
    ).run()
