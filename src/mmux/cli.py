from __future__ import annotations
import logging
import click


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(debug: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format="%(levelname)s %(message)s")


@main.command()
@click.option("--queue-path", default="~/.local/state/mmux", show_default=True,
              help="Base directory for the mmux state on the remote host.")
@click.argument("targets", nargs=-1, required=True)
def install(queue_path: str, targets: tuple[str, ...]) -> None:
    """Install mmux on one or more remote TARGETS."""
    from mmux.install import install as do_install
    for target in targets:
        click.echo(f"Installing on {target} ...")
        do_install(target, queue_path=queue_path)
        click.echo(f"  Done: {target}")


@main.command()
@click.option("--purge", is_flag=True,
              help="Also remove ~/.local/state/mmux entirely.")
@click.argument("targets", nargs=-1, required=True)
def uninstall(purge: bool, targets: tuple[str, ...]) -> None:
    """Uninstall mmux from one or more remote TARGETS."""
    from mmux.install import uninstall as do_uninstall
    for target in targets:
        click.echo(f"Uninstalling from {target} ...")
        do_uninstall(target, purge=purge)
        click.echo(f"  Done: {target}")


@main.command()
@click.argument("targets", nargs=-1)
def tui(targets: tuple[str, ...]) -> None:
    """Launch the mmux TUI, streaming events from TARGETS.

    TARGET format: [user@]host[:session-name].
    If no targets are given, localhost is used.
    """
    from mmux.tui import MmuxApp
    resolved = list(targets) if targets else ["localhost"]
    MmuxApp(targets=resolved).run()
