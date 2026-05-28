# mmux Plan

## Overview

`mmux` is a Python library and CLI for monitoring and interacting with tmux sessions (and
processes running inside them) on local and remote hosts.  It surfaces real-time events
from tmux hooks and Claude CLI hooks through a file-system queue (`mmuxq`), streams them
over SSH, and presents them in a Textual TUI.

```
Remote host                              Local machine
──────────────────────────────────       ────────────────────────────────
tmux hooks ──┐                           ssh user@host tail -f events.jsonl
             ├─→ mmuxq ──→ consumer ──→  ~/.local/state/mmux/events.jsonl ──→ parse
claude hooks─┘   queue      hook:                                              │
                             cat >> events.jsonl                               ↓
                                                                   async JSONL stream
                                                                               │
                                                                               ↓
                                                                       Textual TUI
```

Events are JSONL lines.  Every line carries `proto` and `schema` attributes that route
it to a Python dataclass in `mmux.protos.<proto>`.

---

## Directory layout on each remote (and localhost)

```
~/.local/
  bin/
    mmuxq               # copy of the mmuxq Bash script
    mmux-hook           # small helper: formats args → JSONL → PMP file
~/.local/state/mmux/
  queue/                # mmuxq QMP  (~/.local/state/mmux/queue)
    producers/
      0001/queue/       # tmux producer PMP  (path saved to ~/.local/state/mmux/tmux.pmp)
      0002/queue/       # claude producer PMP (path saved to ~/.local/state/mmux/claude.pmp)
    consumers/
      0001/queue/       # consumer CMP
      consumer-hook     # "cat "$MMUXQ_CMF" >> ~/.local/state/mmux/events.jsonl"
      consumer-hook-fail  # "remove"
  events.jsonl          # append-only consolidated event log; tailed by mmux
  tmux.pmp              # path to tmux producer PMP (written at install time)
  claude.pmp            # path to claude producer PMP
```

`mmuxq` is copied once to `~/.local/bin/mmuxq` and placed on `PATH` via `~/.profile` or
invoked with its full path.

---

## JSONL event format

Every line written to `events.jsonl` is a JSON object with at minimum:

```json
{"proto": "<proto>", "schema": "<ClassName>", "ts": "<unix-epoch-seconds>", ...fields...}
```

The `proto` and `schema` fields are removed before the remaining fields are passed to
the dataclass constructor.  Unknown proto/schema combinations are logged at DEBUG level
and skipped.  Time stamps are Unix Epoch Seconds.

---

## Proto: `tmux`

Dataclasses live in `mmux.protos.tmux`.

### Schemas

| Schema | tmux hook | Key fields |
|---|---|---|
| `Activity` | `alert-activity` | `session`, `window` (int), `pane` (int) |
| `Silence` | `alert-silence` | `session`, `window` (int), `pane` (int) |
| `SessionCreated` | `session-created` | `session` |
| `SessionClosed` | `session-closed` | `session` |
| `PaneCreated` | `after-new-window`, `after-split-window` | `session`, `window`, `pane` |
| `PaneClosed` | `pane-exited` | `session`, `window`, `pane` |

All schemas include `ts: str` (in Unix Epoch Seconds).

### Hook installation on remote

`mmux install` writes the following `tmux` global hook set via a remote `tmux source`
command (or added to `~/.tmux.conf`):

```tmux
set-hook -g alert-activity   "run-shell '~/.local/bin/mmux-hook tmux Activity   session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g alert-silence    "run-shell '~/.local/bin/mmux-hook tmux Silence    session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g session-created  "run-shell '~/.local/bin/mmux-hook tmux SessionCreated  session=#{session_name}'"
set-hook -g session-closed   "run-shell '~/.local/bin/mmux-hook tmux SessionClosed   session=#{session_name}'"
set-hook -g after-new-window "run-shell '~/.local/bin/mmux-hook tmux PaneCreated session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g after-split-window "run-shell '~/.local/bin/mmux-hook tmux PaneCreated session=#{session_name} window=#{window_index} pane=#{pane_index}'"
set-hook -g pane-exited      "run-shell '~/.local/bin/mmux-hook tmux PaneClosed  session=#{session_name} window=#{window_index} pane=#{pane_index}'"
```

`~/.local/bin/mmux-hook` is a small Bash script:

```bash
#!/usr/bin/env bash
# Usage: mmux-hook <proto> <schema> [key=value ...]
proto="$1"; schema="$2"; shift 2
pmp_file=~/.local/state/mmux/${proto}.pmp
pmp="$(cat "$pmp_file" 2>/dev/null)" || exit 0
ts="$(date -u +%FT%T.%3NZ)"
# Build JSON: proto, schema, ts, then key=value pairs
json=$(python3 -c "
import sys, json
d={'proto':'$proto','schema':'$schema','ts':'$ts'}
for kv in sys.argv[1:]:
    k,_,v=kv.partition('=')
    try: d[k]=int(v)
    except ValueError: d[k]=v
print(json.dumps(d))
" "$@")
fname="${ts//[:.]}$$"
printf '%s\n' "$json" > "$pmp/$fname"
```

Using `python3` for JSON serialisation avoids quoting nightmares.  The file name
(`ts + PID`) is unique enough for the dispatcher.

---

## Proto: `claude`

Dataclasses live in `mmux.protos.claude`.

### Schemas

| Schema | Claude hook event | Key fields |
|---|---|---|
| `Notification` | `Notification` | `message: str`, `session_id: str` |

Claude Code delivers hook data as JSON to the hook command's stdin.  The hook command
reads stdin and writes a JSONL file to the claude PMP.

### Hook installation on remote

`mmux install` appends to `~/.claude/settings.json` (merging into any existing config):

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {"type": "command", "command": "~/.local/bin/mmux-claude-hook"}
        ]
      }
    ]
  }
}
```

`~/.local/bin/mmux-claude-hook`:

```bash
#!/usr/bin/env bash
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
```

---

## Python package structure

```
src/mmux/
  __init__.py        # exports main() Click entry point
  cli.py             # Click command group + subcommands
  tui.py             # Textual App and widgets (mmux.tui module)
  queue.py           # SSH-based async event stream
  install.py         # remote install/uninstall logic
  protos/
    __init__.py      # REGISTRY dict, parse_line(), async events() generator
    tmux.py          # tmux dataclasses
    claude.py        # claude dataclasses
```

### `mmux.protos.__init__`

```python
from dataclasses import dataclass
from typing import Any
import json, logging

REGISTRY: dict[tuple[str, str], type] = {}

def register(proto: str, schema: str):
    def decorator(cls):
        REGISTRY[(proto, schema)] = cls
        return cls
    return decorator

def parse_line(line: bytes | str) -> Any | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logging.debug("bad JSON: %r", line)
        return None
    key = (data.get("proto"), data.get("schema"))
    cls = REGISTRY.get(key)
    if cls is None:
        logging.debug("unknown proto/schema: %s", key)
        return None
    fields = {k: v for k, v in data.items() if k not in ("proto", "schema")}
    try:
        return cls(**fields)
    except TypeError as e:
        logging.debug("dataclass mismatch for %s: %s", key, e)
        return None

async def events(target: str):
    """Async generator of parsed dataclass instances from a remote or local target."""
    from mmux.queue import line_stream
    async for line in line_stream(target):
        obj = parse_line(line)
        if obj is not None:
            yield obj
```

### `mmux.protos.tmux`

```python
from dataclasses import dataclass
from mmux.protos import register

@register("tmux", "Activity")
@dataclass
class Activity:
    ts: str
    session: str
    window: int
    pane: int

@register("tmux", "Silence")
@dataclass
class Silence:
    ts: str
    session: str
    window: int
    pane: int

@register("tmux", "SessionCreated")
@dataclass
class SessionCreated:
    ts: str
    session: str

@register("tmux", "SessionClosed")
@dataclass
class SessionClosed:
    ts: str
    session: str

@register("tmux", "PaneCreated")
@dataclass
class PaneCreated:
    ts: str
    session: str
    window: int
    pane: int

@register("tmux", "PaneClosed")
@dataclass
class PaneClosed:
    ts: str
    session: str
    window: int
    pane: int
```

### `mmux.protos.claude`

```python
from dataclasses import dataclass, field
from mmux.protos import register

@register("claude", "Notification")
@dataclass
class Notification:
    ts: str
    message: str
    session_id: str = ""
```

---

## `mmux.queue` module

```python
import asyncio
from collections.abc import AsyncGenerator

REMOTE_EVENTS_FILE = "~/.local/state/mmux/events.jsonl"

async def line_stream(target: str) -> AsyncGenerator[bytes, None]:
    """
    Yield raw JSONL lines from ssh <target> tail -f ~/.local/state/mmux/events.jsonl.
    Always uses SSH, even for localhost.
    """
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", target,
        "tail", "-f", "-n", "+1", REMOTE_EVENTS_FILE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async for line in proc.stdout:
            yield line.rstrip(b"\n")
    finally:
        proc.terminate()
        await proc.wait()
```

`-n +1` ensures `tail` replays all existing lines from the start of `events.jsonl`
before following new ones, so the TUI can reconstruct current state on connect.

---

## `mmux.install` module

`install(target: str)` performs these steps over SSH (using `ssh -T` for non-interactive
commands and `sftp`/`scp` for file copies):

1. **Check** — `ssh target test -f ~/.local/state/mmux/queue/dispatcher.pid` to detect existing install.
2. **Copy mmuxq** — `scp prototype/mmuxq target:~/.local/bin/mmuxq && ssh target chmod +x ~/.local/bin/mmuxq`
3. **Copy helpers** — write `mmux-hook` and `mmux-claude-hook` via stdin pipe or here-doc.
4. **Init queue** — `ssh target ~/.local/bin/mmuxq init ~/.local/state/mmux/queue`
5. **Register producers** — run `mmuxq producer` twice, save paths to `tmux.pmp` / `claude.pmp`.
6. **Register consumer** — `mmuxq consumer --hook 'cat "$MMUXQ_CMF" >> ~/.local/state/mmux/events.jsonl'`
7. **Touch events file** — `ssh target touch ~/.local/state/mmux/events.jsonl`
8. **Start dispatcher** — `ssh target ~/.local/bin/mmuxq start ~/.local/state/mmux/queue`
9. **Install tmux hooks** — send `tmux source` commands via `ssh target tmux source /dev/stdin`.
10. **Install claude hooks** — read, merge, and write `~/.claude/settings.json`.

All steps are idempotent: re-running install on an already-set-up host is safe.

`auto_install(target: str)` is called by `mmux.queue.line_stream` when the initial SSH
connection gets a non-zero exit (events.jsonl missing or dispatcher not running).  It
calls `install(target)` then retries the stream.

---

## CLI commands

Entry point: `mmux` (defined in `pyproject.toml` as `mmux:main` → `mmux.cli.main`).

### `mmux install [--queue-path PATH] <target>...`

Installs mmuxq, helpers, hooks, and starts the dispatcher on one or more targets.
`<target>` is `user@host` or `host`.  `--queue-path` overrides `~/.local/state/mmux` (default).

### `mmux uninstall <target>...`

Stops the dispatcher, removes tmux hooks, removes claude hook entry from settings.json,
and (optionally with `--purge`) removes `~/.local/state/mmux/` entirely.

### `mmux tui [<target>...]`

Launches the Textual TUI.  `<target>` is `[user@]host[:session-name]`.  If no targets,
`localhost` is used.  If `:session-name` is omitted, all sessions on the host are shown.

Auto-install: before opening the event stream for each target, checks for the presence
of `~/.local/state/mmux/events.jsonl`.  If absent, runs `install()` automatically.

### `mmux status <target>...`

Prints a one-line status for each target: dispatcher running, pending messages, last
event timestamp.

---

## TUI design (`mmux.tui`)

Built with Textual.  The main widget is a `SessionTree` (subclass of `Tree`) that
organises nodes hierarchically:

```
┌─ mmux ──────────────────────────────────────────────────┐
│ user@host1                                               │
│   ▶ main         ● active           last: 0s ago        │
│       pane 0     ● active                               │
│       pane 1     ◎ newly silent     last: 42s ago       │
│   ▶ work         ○ long silent      last: 8m ago        │
│       pane 0     ○ long silent                          │
│                                                          │
│ user@host2                                               │
│   ▶ build        ◎ newly silent     last: 90s ago       │
│       pane 0     ◎ newly silent                         │
│ [ENTER] attach   [q] quit   [r] reconnect               │
└──────────────────────────────────────────────────────────┘
```

### Status lights

Tracked per pane using timestamps of the most recent `Activity` or `Silence` event:

| Light | Condition |
|---|---|
| `●` active | `Activity` event received within last 30 s |
| `◎` newly silent | `Silence` event received, or no activity for 30–300 s |
| `○` long silent | No `Activity` event for > 300 s |

Thresholds are configurable (CLI options `--active-secs` and `--silent-secs`).

The TUI ticks a timer every 10 s to re-evaluate and redraw status lights without
requiring a new event.

### Session/pane lifecycle

- `SessionCreated` / `PaneCreated` → add node to tree.
- `SessionClosed` / `PaneClosed` → mark node "closed" (dim), remove after 5 s.
- On connect, `tail -f -n +1` replays existing events so the TUI reconstructs current
  state from the event log.  The last known state of each pane is maintained in a
  `PaneState` dict keyed by `(host, session, pane)`.

### Claude notifications in TUI

When a `claude.Notification` arrives for a pane that can be correlated (by session
name matching a known tmux pane), a `[!]` badge appears next to that pane and the
notification message is shown in a footer bar.  If correlation fails, the notification
is shown in a global log panel (toggled with `l`).

### Keyboard bindings

| Key | Action |
|---|---|
| `ENTER` | Attach to selected session/pane |
| `q` | Quit |
| `r` | Reconnect / refresh all streams |
| `l` | Toggle notification log panel |
| `↑/↓` | Navigate tree |

### Attach flow

```python
async def action_attach(self) -> None:
    node = self.session_tree.cursor_node
    host, session = node.data.host, node.data.session
    pane = node.data.pane  # None if session node selected
    cmd = ["ssh", "-t", host, f"tmux attach -t {session}"]
    if pane is not None:
        cmd[-1] += f" \\; select-pane -t {pane}"
    with self.app.suspend():
        subprocess.run(cmd)
    # TUI resumes automatically after suspend() context exits
```

`App.suspend()` (Textual ≥ 0.47) hands the terminal back to the subprocess and restores
it on exit.

---

## Configuration

mmux reads `~/.config/mmux/config.toml` (XDG) or a path given by `--config`:

```toml
[defaults]
active_secs = 30
silent_secs = 300
queue_path = "~/.local/state/mmux"

[[targets]]
host = "user@myserver"
sessions = []   # empty = all sessions
```

CLI flags always override config file values.

---

## Implementation phases

### Phase 1 — proto layer and queue stream
- `mmux.protos`: registry, `parse_line`, all tmux and claude dataclasses.
- `mmux.queue`: `line_stream` (SSH `tail -f`).
- Tests: feed canned JSONL bytes; assert correct dataclass instances.

### Phase 2 — install
- `mmux.install`: all 10 install steps, idempotent.
- CLI: `mmux install` command.
- Integration test: install to localhost, verify directory structure.

### Phase 3 — TUI skeleton
- `mmux.tui`: Textual app, `SessionTree`, static mock data.
- CLI: `mmux tui` command wired to real event stream.
- Manual test: run against a real remote, verify events appear.

### Phase 4 — TUI event handling
- Wire live events into tree: lifecycle add/remove, status light updates, timer tick.
- Attach flow (ENTER key + `App.suspend()`).
- Claude notification badge and log panel.

### Phase 5 — polish
- Auto-install on connect.
- `mmux status` command.
- `mmux uninstall` command.
- Config file (`~/.config/mmux/config.toml`).
- `--active-secs` / `--silent-secs` CLI options.

---

## Dependencies

| Package | Purpose |
|---|---|
| `click` | CLI framework |
| `textual` | TUI framework |
| `pytest` + `pytest-asyncio` | Tests |

No additional SSH library is needed — all SSH operations use the system `ssh` binary.
