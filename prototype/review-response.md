# Replies to Review of mmuxq Initial Design

## Summary

I reply to review issues keeping same outline and removing original text for
bevity.

---

## Typo

I have fixed

---

## Gaps and Ambiguities

### 1. Filesystem boundary constraint (critical)

The hard-link limitation is understood and accepted.  Nominal operation places the entire queue directory tree on the same file system.  If the user actively subverts this to break hard-links, the resulting undefined behavior is acceptable.

### 2. "Atomically" is undefined

The word atomic was meant to refer to how the MDO applies in its entirety to a single PMF.  The word "serially" is perhaps more suitable.  The concern that while the hard linking of the oldest PMF into the list of currently known CMPs is being performed a new consumer may register.  The next PMF may have existed before this new consumer was registered and as part of applying the DMO, a new list of CMPs that include the new one must be constructed and then iterated.

### 3. Late-joining consumers

Related to the "atomically" issue.  A PMF will only be linked to CMPs known at the start of a DMO application.  That PMF, like others before, are removed and a new consumer will not see their messages.  But a consumer that registered while a DMO was being applied will see the next PMF even if that PMF existed before the new consumer.

### 4. CMF lifecycle for non-hook consumers

It is up to the application of the CMH by `mmuxq` or the consumer (but not both) to manage the CMP contents.  In case of no hook and a inattentive consumer, the CMP will grow without bounds.  We can add to `mmuxq status` a check for disk usage between PMPs and CMPs. 


### 5. Message ordering across concurrent producers

Use mtime with a tie break on the PID part of the PMP path.

### 6. Dispatcher failure and in-flight messages

I think the hard-linking phase should be robust but we will allow the queue to have at-least-once behavior.  In the case of a crash during the linking loop, the link will remain for consumers that have registered a CMH (hooks execute after liking loop completes).  In the case of the consumers that manage their CMP directly, they may have processed and removed the link in which case rerunning the linking loop will give them the message a second time.  It is up to them to guard against this duplication.

### 7. CMH failure handling

The harness code that runs the CMH should emit a warning if the actual hook command fails (returns non-zero exit code).  The CMF should be either: removed, left in place, moved to a designated "failed" directory, depending on command line option that is given upon consumer registration.  Default is to remove the CMF.

### 8. Producer and consumer deregistration

Add a command:

```
mmuxq remove <path>
```

The `<path>` is eitehr a PMP or CMP.

For this to work with the consumer hooks case, we must also change the behavior of `mmuxq consumer --hook cmd` so that it prints the CMP to stdout.  

### 9. No message metadata

This limitation is acceptable but should be explicitly stated.

### 10. `mmuxq [producer|consumer]` syntax

The syntax was a faulty attempt to be brief.  Indeed, we want two commands:

```
mmuxq producer [<QMP>]
mmuxq consumer [--hook cmd] [<QMP>]
```

### 11. Hook mutability

For now, the hook (or lack of one) is immutable.  A consumer can be removed and re-added to effectively change the hook.  

---

## Issues Section — Analysis and Proposed Resolutions

### Issue: Start-up race

Inverting the setup (arm inotify -> process pre-existing -> begin consuming events) is good.

### Issue: Identification

#### Response

- A simpler alternative is an atomic counter using a lock file or `mkdir` (which is atomic on POSIX): the registering process tries `mkdir /q/consumers/0001`, increments until success. Simple, ordered, no timestamps needed — but requires a retry loop under contention.

Response: use this solution.

### Issue: Notification mechanism

**Problem:** As PMPs and CMPs are added or removed at runtime, how does the dispatcher keep its inotify watches current?

**Resolution:**

The dispatcher should maintain watches at two levels:

1. **Directory-level watch on `/q/producers/`:** Watch for `IN_CREATE|IN_DELETE` on subdirectories. When a new PMP appears, immediately add a file-level watch on it. When a PMP is removed, drop its watch.

2. **File-level watch on each PMP:** Watch for `IN_CLOSE_WRITE|IN_MOVED_TO` events (a producer writing a PMF should close-write or rename-into the PMP). On event, run MDO on the new PMF.

CMPs do not need inotify watching by the dispatcher — the dispatcher writes to them, it does not read from them. However, the dispatcher should re-read `/q/consumers/` at the start of each MDO to pick up any newly registered consumers. A watch on `/q/consumers/` for `IN_CREATE` is sufficient to invalidate a cached consumer list.

Most inotify libraries (Linux `inotify(7)`, Python `watchdog`, Go `fsnotify`) support this two-level pattern. The dispatcher's watch loop is a standard event loop that handles both directory-structural events and file-creation events.

Response: use this.

---

## Minor suggestions

- **`mmuxq dmo` output:** Printing an empty string when no PMF was processed is an unusual convention. Consider exit code 0 with no output (success, nothing to do) vs. exit code 0 with the PMF path (success, dispatched). Scripts can test `[ -n "$result" ]` either way, but the semantic is clearer with no-output-on-empty.

Response: okay.

- **`mmuxq status` detail:** Specifying three states (pid file present + process running, pid file present + process dead, pid file absent) is good. Add a fourth: dispatcher running but pid file absent (e.g., file deleted manually). Detection via `pgrep` or process enumeration.

Response: okay.

- **Dispatcher PID file cleanup:** The design does not say who removes `dispatcher.pid` when the dispatcher exits. The dispatcher should remove it on clean exit and `mmuxq stop` should remove it after sending SIGTERM.

Response: the dispatcher itself makes and should remove its own pid file.

- **Default QMP path:** Using `.mmuxq` as the default QMP anchored to CWD is convenient but fragile — callers must be careful about working directory. Consider also supporting a `MMUXQ_PATH` environment variable as a standard override.

Response: you have read my mind!  Yes, if no QMP is given on the command line, but `MMUXQ_PATH` is defined, use that.  If neither given AND a `.mmuxq` exists in the current working directory or in any parent up to the root directory, use it.  Never make a `.mmuxq` if one does not exist.  If no QMP is found, any command that needs it should exit with error code and error message to stderr.
