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
    from mmux.config import load, _xdg_config
    ctx.ensure_object(dict)
    ctx.obj["cfg"] = load(config_path)
    ctx.obj["config_path"] = config_path or str(_xdg_config())
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


@main.group()
def container() -> None:
    """Manage container (podman/docker) integration."""


@container.command("hooks")
@click.option("--client", default=None, type=click.Choice(["podman", "docker"]),
              help="Container runtime (default from config or 'podman').")
@click.option("--home", "home", default=None, metavar="VOLUME:MOUNT",
              help="Home volume and mount point, e.g. myvolume:/home/user (from config if omitted).")
@click.option("--pmp", "pmp_mount", default=None, metavar="MOUNT",
              help="PMP mount point inside container (default from config or /run/mmux/pmp).")
@click.option("--name", "container_name", required=True, metavar="CONTAINER",
              help="Container name or image to use for priming.")
@click.argument("remotes", nargs=-1)
@click.pass_context
def container_hooks(ctx: click.Context, client: str | None, home: str | None,
                    pmp_mount: str | None, container_name: str,
                    remotes: tuple[str, ...]) -> None:
    """Prime a container with mmux claude hooks.

    Runs a short-lived CONTAINER on each REMOTE (default: localhost) that installs
    mmux-claude-hook and patches ~/.claude/settings.json on the home volume.

    After priming, add these flags to every real container run:

    \b
      -v VOLUME:MOUNT
      -v HOST_PMP_DIR:PMP_MOUNT[:Z]   (printed after a successful prime)
    """
    from mmux.container import prime_hooks, get_pmp_host_path, DEFAULT_PMP_MOUNT, DEFAULT_CLIENT
    cfg = ctx.obj["cfg"]
    targets = list(remotes) or ["localhost"]

    for target in targets:
        tcfg = next((t for t in cfg.targets if t.host == target), None)

        resolved_client = (
            client
            or (tcfg.container_client if tcfg and tcfg.container_client else None)
            or cfg.container_client
            or DEFAULT_CLIENT
        )
        resolved_home = home or (tcfg.container_home if tcfg else None)
        resolved_pmp_mount = (
            pmp_mount
            or (tcfg.container_pmp_mount if tcfg and tcfg.container_pmp_mount else None)
            or cfg.container_pmp_mount
            or DEFAULT_PMP_MOUNT
        )

        if not resolved_home:
            raise click.UsageError(
                f"--home is required (or set container_home in config for '{target}')"
            )

        click.echo(f"Priming {container_name} on {target} ...")
        try:
            prime_hooks(
                target, container_name,
                client=resolved_client,
                home=resolved_home,
                pmp_mount=resolved_pmp_mount,
            )
            host_pmp = get_pmp_host_path(target, cfg.queue_path)
            click.echo("  Done. Add to production container runs:")
            click.echo(f"    -v {resolved_home}")
            if host_pmp:
                z_flag = ":Z" if resolved_client == "podman" else ""
                click.echo(f"    -v {host_pmp}:{resolved_pmp_mount}{z_flag}")
            else:
                click.echo(f"    -v <host_pmp_dir>:{resolved_pmp_mount}")
                click.echo(f"  (run 'mmux install {target}' first to provision the PMP)")
        except Exception as exc:
            click.echo(f"  Failed on {target}: {exc}", err=True)


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
        config_path=ctx.obj.get("config_path"),
        queue_path=cfg.queue_path,
    ).run()
