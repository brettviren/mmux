# mmuxq Implementation Plan

## Overview

Implement `mmuxq` as a single Bash script using the `argc` argument-parsing framework.
Tests live in `test/*.bats` and are run via `test/run_tests.sh` using bats 1.9.

---

## File layout

```
prototype/
  mmuxq                   # main executable script
  test/
    helpers.bash          # shared bats setup/teardown
    init.bats
    registration.bats
    dmo.bats
    dispatcher.bats
    qmp_resolution.bats
    run_tests.sh
```

### Queue directory tree

```
<QMP>/
  dispatcher.pid           # PID of running dispatcher (absent when stopped)
  dispatcher.log           # stdout/stderr log for background dispatcher
  producers/
    0001/
      queue/               # PMP: producer writes PMFs here
    0002/
      queue/
  consumers/
    0001/
      queue/               # CMP: dispatcher writes CMFs here
      consumer-hook        # optional: CMH command string
      consumer-hook-fail   # optional: failure mode (remove|keep|faildir)
      failed/              # present only when mode=faildir
    0002/
      queue/
```

---

## Commands

| Command | Description |
|---|---|
| `mmuxq init [<QMP>]` | Create QMP directory structure |
| `mmuxq dispatcher [<QMP>]` | Run dispatcher lifecycle in foreground |
| `mmuxq start [<QMP>]` | Start dispatcher as background process |
| `mmuxq status [<QMP>]` | Report dispatcher state and disk usage |
| `mmuxq stop [<QMP>]` | Stop running dispatcher |
| `mmuxq dmo [<path>]` | Execute one MDO manually |
| `mmuxq producer [<QMP>]` | Register producer, print PMP |
| `mmuxq consumer [--hook <CMD>] [--on-hook-fail <mode>] [<QMP>]` | Register consumer, print CMP |
| `mmuxq remove <path>` | Deregister producer or consumer |

---

## Design decisions

### QMP resolution (all commands except `init`)

1. Explicit `<QMP>` argument on the command line
2. `MMUXQ_PATH` environment variable
3. Walk up from `$PWD` to `/` looking for `.mmuxq` directory
4. Error — print message to stderr and exit non-zero

`init` with no argument creates `.mmuxq` in `$PWD`.  It does not walk up.

### Producer/consumer ID generation

Use atomic `mkdir` with zero-padded 4-digit counter: try `mkdir <base>/0001`, increment
until success.  POSIX guarantees `mkdir` is atomic.  Sequential IDs encode registration
order so lexicographic sort of consumer directories gives dispatch order.

### Message dispatch operation (MDO)

Executed serially; at-least-once semantics:

1. Snapshot the current consumer list (sorted by CID = registration order).
2. Hard-link PMF → `<cdir>/queue/<pmf_name>` for each consumer (ignore EEXIST).
3. Remove PMF from PMP.
4. For each consumer with a registered CMH:
   - Execute CMH with `MMUXQ_CMF=<cmf>` in environment.
   - On exit 0: remove CMF.
   - On non-zero exit: emit warning to stderr; apply `consumer-hook-fail` mode
     (`remove` default, `keep`, or `faildir`).

Crash recovery: on dispatcher restart, any PMF still in a PMP is re-dispatched.
Consumers that already received it will get it again (at-least-once).  CMH-less
consumers should use filename-based deduplication if needed.

### Dispatcher lifecycle

1. Check `dispatcher.pid` — exit with warning if another dispatcher is running.
2. Write own PID to `dispatcher.pid`.
3. **Arm inotify watches BEFORE processing pre-existing PMFs** (startup race fix).
4. Dispatch all pre-existing PMFs oldest-first.
5. Enter watch loop: consume inotify events.
   - `CLOSE_WRITE` or `MOVED_TO` on a file in any PMP → dispatch it.
   - `CREATE,ISDIR` under `producers/` → new PMP registered; restart inotify with
     updated watch list and re-dispatch any pending PMFs.
6. On exit: remove `dispatcher.pid`.

### inotify watch strategy

Two-level watching via a single `inotifywait -m` process:

- Watch `producers/` (detects new PMP directories via `CREATE,ISDIR`).
- Watch each `<PMP>/queue/` directory (detects new PMFs).

On `CREATE,ISDIR`: kill inotifywait, restart with updated directory list, then
dispatch any PMFs that arrived during the restart window via `_dispatch_existing`.

Events are piped through a named FIFO opened in read-write mode (`<>`) to avoid
blocking before inotifywait connects.

### inotify event format

`--format '%w%f\t%e'` — tab-separated path and event string.  Tabs in filenames
are not supported (document as a limitation of the prototype).

### CMH execution

```bash
MMUXQ_CMF="$cmf" bash -c "$(cat "$cdir/consumer-hook")"
```

The CMH script accesses the CMF path via `$MMUXQ_CMF`.

### `mmuxq dmo` path disambiguation

- Path is a file → treat as PMF; derive QMP by walking up four levels.
- Path has `producers/` and `consumers/` subdirs → treat as QMP.
- Otherwise → treat as PMP (a `queue/` directory); derive QMP by walking up three levels.
- No argument → resolve QMP via standard algorithm, then dispatch oldest PMF.

### `mmuxq status` output

Four dispatcher states:
1. `running (pid N)` — pid file exists, process is alive.
2. `not running (stale pid file, pid N)` — pid file exists, process is dead.
3. `not running (no pid file)` — pid file absent, no matching process found.
4. `running (pid N, pid file missing)` — no pid file but `mmuxq dispatcher` process found.

Plus disk usage lines for `producers/` and `consumers/`, and count of pending PMFs.

### `mmuxq remove`

Accepts a PMP root (`producers/<id>`) or CMP root (`consumers/<id>`).  Warns if
pending messages exist.  Does a recursive remove of the directory.

---

## Testing

Tests use bats 1.9 (at `/home/bv/work/wct/noise/toolkit/test/bats/bin/bats`).

Each test file loads `test/helpers.bash` which provides:

- `setup` — create a temp QMP (`$MMUXQ_TEST_DIR`), set `MMUXQ_PATH`, set `MMUXQ` to
  the script under test.
- `teardown` — remove temp directory; kill any stray dispatcher processes.

Test files:
- `init.bats` — directory creation, idempotency.
- `registration.bats` — producer/consumer registration, sequential IDs, concurrent safety.
- `dmo.bats` — dispatch creates CMFs, removes PMF, executes hooks, ordering.
- `dispatcher.bats` — lifecycle, pid file, background start/stop/status.
- `qmp_resolution.bats` — arg > env > walk-up > error precedence.
