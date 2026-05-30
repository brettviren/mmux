from __future__ import annotations
import logging
import os
import shlex
from pathlib import Path
import click

from mmux._version import __version__

log = logging.getLogger(__name__)

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
@click.option("--nick", default="default", show_default=True,
              help="Container config nickname (container.<nick> section in config.toml).")
@click.option("--client", default=None, type=click.Choice(["podman", "docker"]),
              help="Container runtime (overrides config).")
@click.option("--home-volume", "home_volume", default=None, metavar="VOLUME",
              help="Home volume name (overrides config).")
@click.option("--home-mount", "home_mount", default=None, metavar="MOUNT",
              help="Home volume mount path inside the container (overrides config).")
@click.option("--pmp", "pmp_mount", default=None, metavar="MOUNT",
              help="PMP mount point inside container (overrides config).")
@click.option("--name", "container_name", required=True, metavar="CONTAINER",
              help="Container name or image to use for priming.")
@click.argument("remotes", nargs=-1)
@click.pass_context
def container_hooks(ctx: click.Context, nick: str, client: str | None,
                    home_volume: str | None, home_mount: str | None,
                    pmp_mount: str | None, container_name: str,
                    remotes: tuple[str, ...]) -> None:
    """Prime a container with mmux claude hooks.

    Runs a short-lived CONTAINER on each REMOTE (default: localhost) that installs
    mmux-claude-hook and patches ~/.claude/settings.json on the home volume.

    Container settings are read from [container.<nick>] in config.toml, with
    [container.default] as the base.  CLI flags override config values.

    After priming, add these flags to every real container run:

    \b
      -v HOME_VOLUME:HOME_MOUNT
      -v HOST_PMP_DIR:PMP_MOUNT[:Z]   (printed after a successful prime)
    """
    from mmux.container import prime_hooks, get_pmp_host_path
    from mmux.config import resolve_container
    cfg = ctx.obj["cfg"]
    targets = list(remotes) or ["localhost"]

    ccfg = resolve_container(cfg, nick)
    resolved_client = client or ccfg.client
    resolved_home_volume = home_volume or ccfg.home_volume
    resolved_home_mount = home_mount or ccfg.home_mount
    resolved_pmp_mount = pmp_mount or ccfg.pmp_mount

    if not resolved_home_volume or not resolved_home_mount:
        raise click.UsageError(
            "home_volume and home_mount are required; set them in "
            f"[container.{nick}] in config.toml or pass --home-volume / --home-mount"
        )

    for target in targets:
        click.echo(f"Priming {container_name} on {target} ...")
        try:
            prime_hooks(
                target, container_name,
                client=resolved_client,
                home_volume=resolved_home_volume,
                home_mount=resolved_home_mount,
                pmp_mount=resolved_pmp_mount,
            )
            host_pmp = get_pmp_host_path(target, cfg.queue_path)
            click.echo("  Done. Add to production container runs:")
            click.echo(f"    -v {resolved_home_volume}:{resolved_home_mount}")
            if host_pmp:
                z_flag = ":Z" if resolved_client == "podman" else ""
                click.echo(f"    -v {host_pmp}:{resolved_pmp_mount}{z_flag}")
            else:
                click.echo(f"    -v <host_pmp_dir>:{resolved_pmp_mount}")
                click.echo(f"  (run 'mmux install {target}' first to provision the PMP)")
        except Exception as exc:
            click.echo(f"  Failed on {target}: {exc}", err=True)


@container.command("list")
@click.pass_context
def container_list(ctx: click.Context) -> None:
    """List configured container sections with resolved settings."""
    from mmux.config import resolve_container
    cfg = ctx.obj["cfg"]
    if not cfg.containers:
        click.echo("No [container.*] sections configured.")
        return
    rows = []
    for nick in sorted(cfg.containers):
        r = resolve_container(cfg, nick)
        home = f"{r.home_volume}:{r.home_mount}" if r.home_volume and r.home_mount else "-"
        rows.append((nick, r.client, home, r.pmp_mount))
    w_nick = max(len(r[0]) for r in rows)
    w_client = max(len(r[1]) for r in rows)
    w_home = max(len(r[2]) for r in rows)
    for nick, client, home, pmp in rows:
        click.echo(f"{nick:<{w_nick}}  {client:<{w_client}}  {home:<{w_home}}  {pmp}")


@container.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@click.argument("nick")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def container_run(ctx: click.Context, nick: str, args: tuple[str, ...]) -> None:
    """Run a container with mmux volume mounts injected.

    Resolves [container.NICK] from config, prepends the home-volume and PMP
    volume flags, then exec's: CLIENT run <mmux-flags> [ARGS...]
    """
    import os
    from mmux.config import resolve_container
    from mmux.container import get_pmp_host_path
    cfg = ctx.obj["cfg"]

    if nick != "default" and nick not in cfg.containers:
        click.echo(f"warning: no [container.{nick}] section found; using defaults only", err=True)

    ccfg = resolve_container(cfg, nick)
    if not ccfg.home_volume or not ccfg.home_mount:
        raise click.UsageError(
            f"home_volume and home_mount must be set in [container.{nick}] or [container.default]"
        )

    mmux_flags = ["-v", f"{ccfg.home_volume}:{ccfg.home_mount}"]
    host_pmp = get_pmp_host_path("localhost", cfg.queue_path)
    if host_pmp:
        z_flag = ":Z" if ccfg.client == "podman" else ""
        mmux_flags += ["-v", f"{host_pmp}:{ccfg.pmp_mount}{z_flag}"]
    else:
        click.echo(
            "warning: claude PMP not found locally; run 'mmux install localhost' first",
            err=True,
        )

    extra = shlex.split(ccfg.run_args) if ccfg.run_args else []
    image = [ccfg.image] if ccfg.image else []
    cmd = [ccfg.client, "run"] + mmux_flags + extra + image + list(args)
    log.debug("container run: %s", " ".join(cmd))
    for h in logging.getLogger().handlers:
        h.flush()
    try:
        os.execvp(ccfg.client, cmd)
    except FileNotFoundError:
        raise click.ClickException(f"{ccfg.client!r} not found in PATH")


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
