"""Remote install/uninstall logic for mmux."""
from __future__ import annotations
import json
import logging

from mmux import ssh

log = logging.getLogger(__name__)

MMUX_HOOK = r"""#!/usr/bin/env bash
# Usage: mmux-hook <proto> <schema> [key=value ...]
proto="$1"; schema="$2"; shift 2
pmp_file=~/.local/state/mmux/${proto}.pmp
pmp="$(cat "$pmp_file" 2>/dev/null)" || exit 0
ts="$(date -u +%FT%T.%3NZ)"
json=$(python3 -c "
import sys, json
_INT_KEYS = {'window', 'pane'}
d={'proto':'$proto','schema':'$schema','ts':'$ts'}
for kv in sys.argv[1:]:
    k,_,v=kv.partition('=')
    if k in _INT_KEYS:
        try: d[k]=int(v)
        except ValueError: d[k]=v
    else:
        d[k]=v
print(json.dumps(d))
" "$@")
fname="${ts//[:.]}$$"
printf '%s\n' "$json" > "$pmp/$fname"
"""

MMUX_CLAUDE_HOOK = r"""#!/usr/bin/env bash
pmp="$(cat ~/.local/state/mmux/claude.pmp 2>/dev/null)" || exit 0
ts="$(date -u +%FT%T.%3NZ)"
json=$(python3 -c "
import sys, json
data=json.load(sys.stdin)
out={'proto':'claude','schema':'Notification','ts':'$ts',
     'message':data.get('message',''),
     'session_id':data.get('session_id','')}
print(json.dumps(out))
")
fname="${ts//[:.]}$$"
printf '%s\n' "$json" > "$pmp/$fname"
"""

TMUX_HOOKS = """\
set-window-option -g monitor-activity on
set-window-option -g monitor-silence 30
set-hook -g alert-activity    "run-shell '~/.local/bin/mmux-hook tmux Activity   session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g alert-silence     "run-shell '~/.local/bin/mmux-hook tmux Silence    session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g session-created   "run-shell '~/.local/bin/mmux-hook tmux SessionCreated  session=#{session_name}'"
set-hook -g session-closed    "run-shell '~/.local/bin/mmux-hook tmux SessionClosed   session=#{session_name}'"
set-hook -g after-new-window  "run-shell '~/.local/bin/mmux-hook tmux PaneCreated session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g after-split-window "run-shell '~/.local/bin/mmux-hook tmux PaneCreated session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g pane-exited       "run-shell '~/.local/bin/mmux-hook tmux PaneClosed  session=#{session_name} window=#{window_index} pane=#{pane_index}'"
"""

CLAUDE_NOTIFICATION_HOOK = {
    "matcher": "",
    "hooks": [{"type": "command", "command": "~/.local/bin/mmux-claude-hook"}],
}

TMUX_HOOK_NAMES = (
    "alert-activity",
    "alert-silence",
    "session-created",
    "session-closed",
    "after-new-window",
    "after-split-window",
    "pane-exited",
)

_MMUX_REPO = "git+https://github.com/brettviren/mmux"


def _ssh(target: str, *cmd: str, input: str | None = None, check: bool = True):
    return ssh.run(target, *cmd, input=input, check=check)


def _mmuxq_path(queue_path: str) -> str:
    return f"{queue_path}/queue"


async def async_is_installed(target: str) -> bool:
    """Return True if mmuxq is available on *target*."""
    from mmux import ssh as _ssh_mod
    _, rc = await _ssh_mod.async_run(
        target, "bash", "-c",
        'PATH="$HOME/.local/bin:$PATH" command -v mmuxq >/dev/null 2>&1',
    )
    return rc == 0


async def async_is_running(target: str, queue_path: str = "~/.local/state/mmux") -> bool:
    """Return True if the mmuxq dispatcher process is alive on *target*."""
    from mmux import ssh as _ssh_mod
    pid_file = f"{queue_path}/queue/dispatcher.pid"
    _, rc = await _ssh_mod.async_run(
        target, "bash", "-c",
        f'pid=$(cat {pid_file} 2>/dev/null) && kill -0 "$pid" 2>/dev/null',
    )
    return rc == 0


def start(target: str, queue_path: str = "~/.local/state/mmux") -> None:
    """Start the mmuxq dispatcher on an already-installed *target*."""
    qmp = f"{queue_path}/queue"
    log.info("starting dispatcher on %s", target)
    _ssh(target, "~/.local/bin/mmuxq", "start", qmp, check=False)


def install(target: str, queue_path: str = "~/.local/state/mmux", *, start_dispatcher: bool = True) -> None:
    qmp = f"{queue_path}/queue"

    # 1. Install the mmux package via uv (provides both mmux and mmuxq commands).
    log.info("running uv tool install on %s", target)
    result = _ssh(
        target, "uv", "tool", "install", "--upgrade", _MMUX_REPO,
        check=False,
    )
    if result.returncode != 0:
        lines = "\n".join(
            line for line in (result.stdout + result.stderr).splitlines() if line.strip()
        )
        raise RuntimeError(
            f"uv tool install failed on {target} (rc={result.returncode}):\n{lines}"
        )

    # 2. Write helper scripts via SSH stdin.
    for name, content in [("mmux-hook", MMUX_HOOK), ("mmux-claude-hook", MMUX_CLAUDE_HOOK)]:
        log.info("writing %s on %s", name, target)
        _ssh(target,
             "bash", "-c", f"cat > ~/.local/bin/{name} && chmod +x ~/.local/bin/{name}",
             input=content)

    # 3. Init queue (idempotent: mmuxq init is safe to re-run).
    log.info("initialising queue on %s", target)
    _ssh(target, "mkdir", "-p", queue_path)
    _ssh(target, "~/.local/bin/mmuxq", "init", qmp, check=False)

    # 4. Register tmux and claude producers (idempotent via fixed .pmp files).
    for proto in ("tmux", "claude"):
        pmp_file = f"{queue_path}/{proto}.pmp"
        result = _ssh(target, "test", "-s", pmp_file, check=False)
        if result.returncode != 0:
            log.info("registering %s producer on %s", proto, target)
            pmp = _ssh(target, "~/.local/bin/mmuxq", "producer", qmp).stdout.strip()
            _ssh(target, "bash", "-c", f"cat > {pmp_file}", input=pmp)

    # 5. Register consumer with cat hook (idempotent: check consumer 0001 exists).
    # Note: we write the hook file directly via stdin rather than using
    # `mmuxq consumer --hook <cmd>`, because SSH joins list args with spaces on
    # the remote shell, causing `>>` in the hook command to be interpreted as a
    # redirect, corrupting events.jsonl with the consumer path.
    consumer_dir = f"{qmp}/consumers/0001"
    result = _ssh(target, "test", "-d", consumer_dir, check=False)
    if result.returncode != 0:
        log.info("registering consumer on %s", target)
        events_file = f"{queue_path}/events.jsonl"
        _ssh(target, "mkdir", "-p", f"{consumer_dir}/queue")
        _ssh(target,
             "bash", "-c", f"cat > {consumer_dir}/consumer-hook",
             input=f'cat "$MMUXQ_CMF" >> {events_file}\n')

    # 6. Touch events.jsonl.
    events_file = f"{queue_path}/events.jsonl"
    _ssh(target, "touch", events_file)

    # 7. Start dispatcher (idempotent: mmuxq start warns if already running).
    if start_dispatcher:
        log.info("starting dispatcher on %s", target)
        _ssh(target, "~/.local/bin/mmuxq", "start", qmp, check=False)

    # 8. Install tmux hooks.
    log.info("installing tmux hooks on %s", target)
    _ssh(target, "tmux", "source", "/dev/stdin", input=TMUX_HOOKS, check=False)

    # 9. Merge Notification hook into ~/.claude/settings.json.
    log.info("patching ~/.claude/settings.json on %s", target)
    result = _ssh(target, "cat", "~/.claude/settings.json", check=False)
    try:
        cfg = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
    except json.JSONDecodeError:
        cfg = {}

    hooks = cfg.setdefault("hooks", {})
    notifs = hooks.setdefault("Notification", [])
    if not any(
        any(h.get("command") == "~/.local/bin/mmux-claude-hook" for h in entry.get("hooks", []))
        for entry in notifs
    ):
        notifs.append(CLAUDE_NOTIFICATION_HOOK)
        new_cfg = json.dumps(cfg, indent=2)
        _ssh(target, "bash", "-c", "cat > ~/.claude/settings.json", input=new_cfg)

    log.info("install complete on %s", target)


def uninstall(target: str, queue_path: str = "~/.local/state/mmux", action: str = "stop") -> None:
    """Run uninstall action on *target*.

    Actions are cumulative:
      stop   — stop the mmuxq dispatcher process.
      purge  — stop + remove tmux hooks + remove Claude hook + delete queue directory.
      remove — purge + remove helper scripts + uv tool uninstall mmux.
    """
    qmp = f"{queue_path}/queue"

    # Always: stop the dispatcher.
    log.info("stopping dispatcher on %s", target)
    _ssh(target, "~/.local/bin/mmuxq", "stop", qmp, check=False)

    if action in ("purge", "remove"):
        # Remove tmux hooks.
        log.info("removing tmux hooks on %s", target)
        unhook_cmds = "\n".join(f"set-hook -gu {name}" for name in TMUX_HOOK_NAMES)
        _ssh(target, "tmux", "source", "/dev/stdin", input=unhook_cmds, check=False)

        # Remove Notification hook from ~/.claude/settings.json.
        log.info("patching ~/.claude/settings.json on %s", target)
        result = _ssh(target, "cat", "~/.claude/settings.json", check=False)
        if result.returncode == 0 and result.stdout.strip():
            try:
                cfg = json.loads(result.stdout)
            except json.JSONDecodeError:
                cfg = {}
            notifs = cfg.get("hooks", {}).get("Notification", [])
            filtered = [
                entry for entry in notifs
                if not any(h.get("command") == "~/.local/bin/mmux-claude-hook"
                           for h in entry.get("hooks", []))
            ]
            if filtered != notifs:
                cfg.setdefault("hooks", {})["Notification"] = filtered
                _ssh(target, "bash", "-c", "cat > ~/.claude/settings.json",
                     input=json.dumps(cfg, indent=2))

        # Delete queue directory tree.
        log.info("purging %s on %s", queue_path, target)
        _ssh(target, "rm", "-rf", queue_path, check=False)

    if action == "remove":
        # Remove helper scripts.
        log.info("removing helper scripts on %s", target)
        for name in ("mmux-hook", "mmux-claude-hook"):
            _ssh(target, "rm", "-f", f"~/.local/bin/{name}", check=False)

        # Uninstall the package via uv.
        log.info("running uv tool uninstall on %s", target)
        _ssh(target, "uv", "tool", "uninstall", "mmux", check=False)

    log.info("uninstall (%s) complete on %s", action, target)
