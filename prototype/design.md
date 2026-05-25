# mmuxq Design

## General Design

### Concept

mmuxq is a multi-producer, multi-consumer (MPMC) message queue whose entire state is a
directory tree on a single filesystem.  Messages are files.  Delivery is performed by
a singleton dispatcher process.  Basic inspection and manipulation require only
standard Unix tools.

### Terminology

| Term | Abbreviation | Meaning |
|---|---|---|
| Queue message path | QMP | Root directory of one queue instance |
| Producer message path | PMP | Directory a producer writes messages into |
| Producer message file | PMF | One message written by a producer |
| Consumer message path | CMP | Directory the dispatcher delivers messages into |
| Consumer message file | CMF | One delivered copy of a PMF |
| Consumer message hook | CMH | Command the dispatcher runs on each new CMF |
| Message dispatch operation | MDO | The act of moving one PMF to all consumers |

### Directory layout

```
<QMP>/
  dispatcher.pid       # PID of running dispatcher; absent when stopped
  dispatcher.log       # stdout/stderr captured when running in background
  producers/
    0001/
      queue/           # PMP — producer writes PMFs here
    0002/
      queue/
  consumers/
    0001/
      queue/           # CMP — dispatcher deposits CMFs here
      consumer-hook    # optional: CMH command string (absent = no hook)
      consumer-hook-fail  # optional: hook failure mode (remove|keep|faildir)
      failed/          # present only when mode=faildir
    0002/
      queue/
```

Producer and consumer directories are named with a zero-padded four-digit counter
(`0001`, `0002`, …).  Lexicographic order of these names is the canonical registration
order used by the dispatcher when delivering to consumers.

### QMP resolution

Every command that operates on a queue accepts an optional explicit QMP path.
When no path is given, the queue is located in this priority order:

1. `MMUXQ_PATH` environment variable, if set.
2. Walk up from the current working directory toward the filesystem root, stopping
   at the first `.mmuxq` directory found.
3. Error — print a message to stderr and exit non-zero.

The `init` command is exempt: with no argument it creates `.mmuxq` in the current
directory without walking up.

### Producer registration

`mmuxq producer [<QMP>]` — allocates a new producer slot, creates its `queue/`
directory, and prints the PMP path to stdout.  The caller uses the PMP as a staging
area: it writes any file into the PMP and the dispatcher will deliver it.

**ID allocation** is done by attempting `mkdir <QMP>/producers/0001`, then `0002`,
and so on until one succeeds.  POSIX guarantees that `mkdir` is atomic, so concurrent
registrations produce unique IDs without any locking protocol.

### Consumer registration

`mmuxq consumer [--hook <CMD>] [--on-hook-fail <mode>] [<QMP>]` — allocates a new
consumer slot, creates its `queue/` directory, and prints the CMP path to stdout.

If `--hook` is provided, the command string is written to `consumer-hook` and the
consumer operates in *hook mode*: the dispatcher calls the CMH on each CMF and then
removes the CMF.  The `--on-hook-fail` mode controls what happens when the CMH exits
non-zero:

| Mode | Effect |
|---|---|
| `remove` (default) | CMF is deleted |
| `keep` | CMF remains in the CMP |
| `faildir` | CMF is moved to `<consumer-root>/failed/` |

Without `--hook`, the consumer operates in *direct mode*: CMFs accumulate in the CMP
and the consumer is responsible for reading and removing them.

### Deregistration

`mmuxq remove <path>` — removes a producer root (`<QMP>/producers/<id>`) or consumer
root (`<QMP>/consumers/<id>`).  Warns if pending messages remain.

### Message dispatch operation (MDO)

The MDO is executed serially and applies to exactly one PMF at a time.

1. **Snapshot** the current list of consumer directories, sorted by CID (= registration
   order).
2. **Hard-link** the PMF into each consumer's `queue/` directory as a CMF, using the
   same filename.  Hard links are used because they are atomic and consume no additional
   disk space.  The entire queue must reside on a single filesystem.  Existing links are
   silently ignored (EEXIST), which provides at-least-once re-delivery on restart.
3. **Remove** the PMF from the PMP.
4. For each consumer in hook mode, **execute** the CMH with the CMF path in the
   `MMUXQ_CMF` environment variable.  On success the CMF is removed.  On failure the
   configured `on-fail` mode is applied.

**Delivery semantics**: at-least-once.  If the dispatcher crashes between steps 2 and 3,
the PMF remains in the PMP.  On restart it is re-dispatched; consumers that already
received the message will receive it again.  Hook-less consumers should perform
filename-based deduplication if exactly-once semantics are required by the application.

**Message ordering**: PMFs are dispatched oldest-first by filesystem mtime.  When two
PMFs share the same mtime, the full path (which embeds the PMP directory name) is used
as a tie-breaker.

### Dispatcher lifecycle

The dispatcher is a singleton process for each QMP.  Its lifecycle:

1. Check `dispatcher.pid`; exit with a warning if a running dispatcher is found.
2. Write own PID to `dispatcher.pid`.
3. **Arm filesystem watch** on `producers/` and all existing PMP `queue/` directories
   *before* processing pre-existing PMFs.  This resolves the startup race: the OS
   buffers events that arrive during the drain phase, so nothing is missed.
4. **Drain pre-existing PMFs**: dispatch all PMFs currently in any PMP, oldest-first.
5. **Watch loop**: react to filesystem events.
   - File written (close-write or rename-into) in any PMP `queue/` → dispatch it.
   - New directory created under `producers/` → a new PMP has been registered.
     Re-arm the watch (adding the new directory) and drain any PMFs that arrived
     during the re-arm window.
6. On exit (clean or signal): remove `dispatcher.pid`.

### Manual dispatch

`mmuxq dmo [<path>]` executes exactly one MDO without running the full dispatcher
lifecycle.  The path argument is classified:

- File → PMF; dispatch it directly.
- Directory containing `producers/` and `consumers/` → QMP; dispatch the oldest PMF.
- Any other directory → PMP; dispatch its oldest PMF.
- No argument → resolve QMP, dispatch the oldest PMF across all producers.

Prints the dispatched PMF path to stdout, or nothing if no PMFs were available.

### Status reporting

`mmuxq status` identifies four dispatcher states:

1. **Running** — `dispatcher.pid` exists and the recorded PID is alive.
2. **Stale pid file** — `dispatcher.pid` exists but the process is dead.
3. **Not running** — `dispatcher.pid` is absent and no matching process is found.
4. **Running, pid file missing** — no `dispatcher.pid` but a dispatcher process is
   detected by process name scan.

Status output also includes the disk usage of `producers/` and `consumers/` and the
count of pending (undelivered) PMFs.

---

## Bash Implementation

### Files

```
prototype/
  mmuxq              # single executable Bash script
  test/
    helpers.bash     # bats setup/teardown shared across all test files
    init.bats
    registration.bats
    dmo.bats
    dispatcher.bats
    qmp_resolution.bats
    run_tests.sh     # test runner (invokes bats on all .bats files)
```

### Dependencies

| Tool | Purpose |
|---|---|
| `bash` ≥ 4.3 | Script interpreter |
| `argc` 1.23 | Argument parsing and subcommand dispatch |
| `inotifywait` | Filesystem event monitoring (from `inotify-tools`) |
| `find`, `sort`, `awk` | PMF enumeration and ordering |
| `ln`, `rm`, `mkdir` | Core dispatch operations |
| `mkfifo` | FIFO for inotifywait event stream |
| `nohup`, `disown` | Background dispatcher launch |
| `pgrep` | Orphaned dispatcher detection in `status` |
| `bats` 1.9 | Test runner |

### Argument parsing with argc

The script uses the [argc](https://github.com/sigoden/argc) framework.  Each subcommand
is a Bash function preceded by `# @cmd`, `# @arg`, and `# @option` comment annotations.
argc parses `"$@"` and exports variables named `argc_<argname>`.

Optional positional arguments use the `*` suffix (`# @arg qmp*`), which makes the
variable an array; the value is accessed as `${argc_qmp[0]:-}`.  Required positional
arguments use `!` (`# @arg path!`).  Hyphenated option names are converted to
underscores: `--on-hook-fail` → `$argc_on_hook_fail`.

The final line of the script is:

```bash
eval "$(argc --argc-eval "$0" "$@")"
```

### ID allocation

```bash
_new_id() {
    local base="$1" n=1 id
    while true; do
        id="$(printf '%04d' "$n")"
        mkdir "$base/$id" 2>/dev/null && echo "$id" && return 0
        n=$(( n + 1 ))
        [[ "$n" -gt 9999 ]] && _die "ID space exhausted in $base"
    done
}
```

`mkdir` is atomic on POSIX filesystems.  Concurrent calls spin until one wins.

### Inotify event loop

The dispatcher opens a temporary FIFO in read-write mode (`exec 7<>"$fifo"`) before
starting `inotifywait`.  Opening both ends simultaneously avoids the blocking deadlock
that would occur if the shell opened only the read end while `inotifywait` had not yet
opened the write end.  The shell's write-end handle also prevents the read loop from
receiving EOF during the brief moments when `inotifywait` is being restarted after a
new PMP appears.

```bash
inotifywait -m "${watch_targets[@]}" \
    --format '%w%f'$'\t''%e' \
    -e close_write -e moved_to -e create \
    >&7 2>/dev/null &
```

Events are tab-separated (`%w%f\t%e`).  Filenames containing tabs are not supported.
The watch loop reads from fd 7:

```bash
while IFS=$'\t' read -r path event <&7; do
    if   [[ "$event" == *ISDIR*        ]]; then _arm_watch
    elif [[ "$event" == *CLOSE_WRITE*  || "$event" == *MOVED_TO* ]]; then
        [[ -f "$path" ]] && _mdo "$path" "$qmp"
    fi
done
```

`CLOSE_WRITE` fires when a producer closes a file it was writing.  `MOVED_TO` fires
when a producer atomically renames a file into the PMP (the preferred way to ensure
a PMF is complete before the dispatcher sees it).  `CREATE,ISDIR` fires when a new
producer registers, triggering `_arm_watch` to restart `inotifywait` with the updated
directory list.

### Signal handling

Bash's `set -e` means any unguarded non-zero exit causes the script to exit.  Two
pitfalls required explicit fixes:

- `(( n++ ))` evaluates to the *old* value of `n`; when `n` is zero this produces
  exit code 1 and triggers `set -e`.  All arithmetic increments use
  `n=$(( n + 1 ))`.
- `trap handler TERM` in bash runs the handler but then *continues* execution rather
  than exiting.  The correct pattern separates cleanup from termination:

  ```bash
  trap _dispatcher_cleanup EXIT   # cleanup on any exit
  trap 'exit 0' INT TERM          # signals trigger exit, which fires EXIT trap
  ```

### Background dispatcher launch

`mmuxq start` uses `nohup` and `disown` so the dispatcher survives the shell that
started it:

```bash
nohup bash "$script" dispatcher "$qmp" >> "$qmp/dispatcher.log" 2>&1 &
disown
```

`realpath "${BASH_SOURCE[0]}"` resolves the script's absolute path so `start` can
re-invoke the same script regardless of the caller's working directory.

### CMH execution

```bash
MMUXQ_CMF="$cmf" bash -c "$(< "$cdir/consumer-hook")"
```

The hook command string (stored verbatim in `consumer-hook`) is passed to a new `bash`
process.  The CMF path is injected via the `MMUXQ_CMF` environment variable rather than
as a positional argument to avoid quoting ambiguity.

### Known limitations of the Bash prototype

- PMF filenames must not contain tab characters (inotifywait format delimiter).
- Producer and consumer ID space is limited to 9999 entries per queue.
- `pgrep -f` matching in `mmuxq status` can produce false positives if another process
  happens to contain the QMP path in its command line.
- The `inotifywait` restart during new-PMP registration has a brief window (a few
  milliseconds) covered by `_dispatch_existing`; this is correct but adds latency for
  that one dispatch cycle.
