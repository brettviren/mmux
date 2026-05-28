from __future__ import annotations
import logging
import click


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging.")
@click.option("--config", "config_path", default=None, metavar="PATH",
              help="Config file (default: ~/.config/mmux/config.toml).")
@click.pass_context
def main(ctx: click.Context, debug: bool, config_path: str | None) -> None:
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(levelname)s %(message)s")
    from mmux.config import load
    ctx.ensure_object(dict)
    ctx.obj["cfg"] = load(config_path)


@main.command()
@click.option("--queue-path", default=None, show_default=True,
              help="Base directory for mmux state on the remote host.")
@click.argument("targets", nargs=-1, required=True)
@click.pass_context
def install(ctx: click.Context, queue_path: str | None, targets: tuple[str, ...]) -> None:
    """Install mmux on one or more remote TARGETS."""
    from mmux.install import install as do_install
    cfg = ctx.obj["cfg"]
    qp = queue_path or cfg.queue_path
    for target in targets:
        click.echo(f"Installing on {target} ...")
        do_install(target, queue_path=qp)
        click.echo(f"  Done: {target}")


@main.command()
@click.option("--purge", is_flag=True, help="Also remove ~/.local/state/mmux entirely.")
@click.argument("targets", nargs=-1, required=True)
def uninstall(purge: bool, targets: tuple[str, ...]) -> None:
    """Uninstall mmux from one or more remote TARGETS."""
    from mmux.install import uninstall as do_uninstall
    for target in targets:
        click.echo(f"Uninstalling from {target} ...")
        do_uninstall(target, purge=purge)
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
                ["ssh", "-o", "BatchMode=yes", "-T", target, "bash", "-c", cmd],
                capture_output=True, text=True,
            )
            return r.stdout.strip() if r.returncode == 0 else ""

        # Dispatcher state
        pid = _ssh(f"cat {qmp}/dispatcher.pid 2>/dev/null")
        if pid:
            alive = _ssh(f"kill -0 {pid} 2>/dev/null && echo yes || echo no")
            disp = "running" if alive == "yes" else "stale pid"
        else:
            disp = "stopped"

        # Pending messages
        pending = _ssh(f"find {qmp}/producers -type f 2>/dev/null | wc -l") or "0"

        # Last event timestamp
        last_event = _ssh(
            f"tail -1 {qp}/events.jsonl 2>/dev/null | python3 -c "
            f"\"import sys,json; d=json.load(sys.stdin); print(d.get('ts','?'))\" 2>/dev/null"
        ) or "never"

        click.echo(f"{target}: dispatcher={disp}  pending={pending}  last={last_event}")


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
