# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
uv run pytest          # run all tests
uv run mmux --help     # smoke-test the CLI
```

Tests live in `tests/`.  `test_protos.py` uses canned JSONL bytes; `test_install_integration.py` is an integration test that requires a live localhost SSH setup.

## Architecture Overview

`mmux` monitors tmux sessions on remote (and local) hosts and presents them in a
Textual TUI.  Events flow through a filesystem queue (`mmuxq`) on each remote host and
are streamed to the local machine over SSH.

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

### Python package (`src/mmux/`)

| Module | Role |
|---|---|
| `cli.py` | Click entry point; `mmux install/uninstall/status/tui` subcommands |
| `tui.py` | Textual `App` + `SessionTree` widget; event → pane state → tree render |
| `queue.py` | `line_stream(target)` — async generator; SSH `tail -f events.jsonl` |
| `install.py` | 10-step idempotent remote install/uninstall over SSH |
| `protos/__init__.py` | `REGISTRY`, `parse_line()`, `events()` async generator |
| `protos/tmux.py` | `Activity`, `Silence`, `SessionCreated/Closed`, `PaneCreated/Closed` |
| `protos/claude.py` | `Notification` (message + session_id) |
| `config.py` | Loads `~/.config/mmux/config.toml` |

### JSONL event format

Every line in `events.jsonl` is a JSON object with at minimum:

```json
{"proto": "tmux", "schema": "Activity", "ts": "2024-01-01T00:00:00.000Z", "session": "main", "window": 0, "pane": 1}
```

`proto` + `schema` route to a registered dataclass; unknown combinations are logged at
DEBUG and skipped.

### mmuxq — the filesystem queue (`prototype/mmuxq`)

A single Bash script implementing an MPMC queue whose entire state is a directory tree.
Key concepts:

- **QMP** (queue message path) — root dir of one queue instance
- **PMP** (producer message path) — dir a producer writes message *files* into
- **CMP** (consumer message path) — dir the dispatcher delivers copies into
- **CMH** (consumer message hook) — shell command run on each new file; `mmuxq` uses it to `cat >> events.jsonl`
- Dispatcher is a singleton process per QMP; uses `inotifywait` to watch for new PMFs
- Dispatch is atomic via hard-links (POSIX `ln`); delivery semantics are at-least-once
- ID allocation uses `mkdir` atomicity for lock-free concurrent registration

Remote directory layout written by `mmux install`:

```
~/.local/bin/mmuxq                          # the queue binary
~/.local/bin/mmux-hook                      # formats tmux hook args → JSONL → PMP
~/.local/bin/mmux-claude-hook               # reads Claude hook stdin → JSONL → PMP
~/.local/state/mmux/
  queue/                                    # QMP
    dispatcher.pid / dispatcher.log
    producers/0001/queue/                   # tmux PMP
    producers/0002/queue/                   # claude PMP
    consumers/0001/queue/                   # consumer CMP
  events.jsonl                              # append-only; tailed by mmux
  tmux.pmp                                  # path to tmux PMP (written at install)
  claude.pmp                                # path to claude PMP
```

### TUI pane states

Each pane is tracked by `(host, session, window, pane)` key in `MmuxApp._pane_states`.
Status lights are re-evaluated on every event and on a 10-second timer tick:

| Light | Condition |
|---|---|
| `●` green | `Activity` event within last `active_secs` (default 30 s) |
| `◎` yellow | `Silence` event received, or no activity for 30–300 s |
| `○` white | No activity for > `silent_secs` (default 300 s) |

### Logging

All logging goes to `~/.cache/mmux.log` (file only — never stderr, which would corrupt
the Textual TUI display).  CLI options on the `mmux` group:

- `-l/--log-file PATH` — override log file (default `~/.cache/mmux.log`)
- `-L/--log-level LEVEL` — set level (default `info`)
- `--debug` — shorthand for `-L debug`

SSH subprocess stderr is captured and routed through the Python logger (WARNING level)
rather than discarded.

## Conventions & Patterns

- `uv run` is the project's Python runner (not `python` directly).
- All SSH calls use `BatchMode=yes` (no interactive prompts) and the system `ssh` binary.
- `mmux install` is idempotent: safe to re-run against an already-configured host.
- `auto_install`: `queue.line_stream` calls `install()` automatically when `events.jsonl`
  is absent on the remote.
- Proto registration is done via the `@register("proto", "Schema")` decorator in each
  `protos/*.py` module; the module must be imported before `parse_line` can decode it.
  The TUI imports both proto modules at stream startup to ensure registration.
