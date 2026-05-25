# Review of mmuxq Initial Design

## Summary

The design is a sound foundation for a file-system-backed MPMC queue. The core idea — hard-linking PMFs into CMPs and using inotify for push notification — is idiomatic Unix. However, several gaps and ambiguities need resolution before implementation, and the three Issues identified at the end are real blockers. This review addresses them in depth and raises additional concerns.

---

## Typo

The dispatch life-cycle section (step 2) writes the PID file as `/q/dispatcher.pd`. The implementation section correctly calls it `/q/dispatcher.pid`. Pick one and be consistent; `.pid` is conventional.

---

## Gaps and Ambiguities

### 1. Filesystem boundary constraint (critical)

Hard links cannot cross filesystem boundaries. The design places PMPs under `/q/producers/` and CMPs under `/q/consumers/`, both within the same QMP tree, so hard-linking works as long as the entire QMP lives on one filesystem. This constraint is never stated. If a user mounts `/q/producers` and `/q/consumers` on separate volumes the MDO will silently fail or error. The design should either:

- Explicitly state the single-filesystem requirement, or
- Substitute a copy-then-atomic-rename strategy for cross-filesystem cases (with a note that hard links are the preferred path).

### 2. "Atomically" is undefined

The overview guarantees that "all produced messages go to all consumers, atomically." The MDO as described is *not* atomic: it hard-links to consumers one at a time, then removes the PMF. If the dispatcher crashes between link 2 and link 3, consumer 3 never receives the message. "Atomically" should be replaced with a precise claim, for example: "each message is delivered to every registered consumer exactly once, provided the dispatcher runs to completion for that message."

### 3. Late-joining consumers

When a new consumer registers *after* some messages have already been dispatched, it will never receive those earlier messages. The design does not state this behavior explicitly. It should: does a late consumer see only messages produced after its registration, or is some replay mechanism expected? The answer shapes how CID ordering must work.

### 4. CMF lifecycle for non-hook consumers

For consumers without a CMH, the dispatcher deposits a CMF and takes no further action. The design does not say who removes these files, when, or how the consumer signals that it has finished with a message. Without a defined acknowledgment or cleanup contract the CMP will grow without bound.

### 5. Message ordering across concurrent producers

The design promises "production-time order." When two producers write PMFs concurrently, ordering is determined by filesystem mtime. Sub-second collisions (common on fast systems) produce ties that the design does not break. Options include: (a) using monotonically increasing sequence numbers embedded in PMF names, (b) using high-resolution timestamps combined with the PID of the producer as a tie-breaker, or (c) acknowledging that ordering is best-effort within a configurable time window.

### 6. Dispatcher failure and in-flight messages

The dispatcher is a single process and a single point of failure. The design provides `mmuxq start/stop/status` but does not say what happens to a PMF that was partially dispatched (some consumers linked, PMF not yet removed) when the dispatcher crashes. On restart, the dispatcher will find the PMF still in the PMP and re-dispatch it, duplicating delivery to consumers that already received it. The design should define at-least-once vs. exactly-once semantics and describe how the restart case is handled (e.g., a per-dispatch lock file or a staging directory).

### 7. CMH failure handling

Step 3 of the MDO executes the CMH and then removes the CMF. If the CMH exits non-zero or hangs, the design is silent. Should the dispatcher retry? Log and continue? Block indefinitely? A hung CMH would stall the entire dispatch pipeline since the MDO is serial.

### 8. Producer and consumer deregistration

The design describes registration but not deregistration. How does a producer or consumer leave the queue gracefully? What happens to a PMP whose producer process has died but left unprocessed PMFs behind? Should the dispatcher dispatch them or leave them? What happens to a CMP whose consumer has gone away — do CMFs accumulate indefinitely?

### 9. No message metadata

Messages are opaque files. There is no standard envelope for producer identity, sequence number, or timestamp. Applications that need these must embed them in the message body. The design should explicitly state whether metadata is out of scope or propose a lightweight convention (e.g., a companion sidecar file or a structured PMF filename).

### 10. `mmuxq [producer|consumer]` syntax

The registering section shows `mmuxq [producer|consumer] [--hook cmd] [<QMP>]`. Brackets around `producer|consumer` suggest they are optional, which cannot be right — this should be a required subcommand. Compare with the dispatcher subsection which uses `mmuxq dispatcher`. Recommend consistent mandatory subcommand syntax: `mmuxq producer [<QMP>]` and `mmuxq consumer [--hook cmd] [<QMP>]`.

### 11. Hook mutability

Can a consumer change or remove its CMH after registration? The design does not say. If the CMH is stored as a file (`consumer-hook` in the layout example) it could be mutated out-of-band, which would create a TOCTOU race with the dispatcher. The design should state whether the hook is immutable after registration.

---

## Issues Section — Analysis and Proposed Resolutions

### Issue: Start-up race

**Problem:** There is a window between when the dispatcher finishes draining pre-existing PMFs and when inotify watching is fully armed. A PMF written in that window would be missed.

**Resolution:** Invert the setup order:

1. Arm inotify watches on all existing PMPs *before* processing any pre-existing PMFs.
2. Process all pre-existing PMFs oldest-first.
3. Begin consuming inotify events.

Because inotify events are queued by the kernel from the moment the watch is registered, any PMF created during step 2 will appear as a pending event in step 3. The dispatcher must deduplicate: if a PMF it already processed also appears as an inotify event, it should be a no-op (the PMF will have been removed in step 2, so the event target will be gone). This resolves the race without locks.

A secondary race exists for PMPs created after the dispatcher starts: a producer that calls `mmuxq producer` and immediately writes a PMF could have its PMP miss the initial inotify watch setup. This is addressed by the dispatcher watching the `producers/` directory for `IN_CREATE` events on subdirectories, not just for file events within known PMPs — see the Notification Mechanism issue below.

### Issue: Identification

**Problem:** CIDs and PIDs must be unique and CID ordering must be derivable for the MDO.

**Proposed approach:**

- Use a combination of wall-clock timestamp (nanosecond resolution) and the registering process's PID to form an ID: `<ns-timestamp>-<pid>`. Collision probability is negligible, and no cross-process locking is needed.
- For consumer ordering, embed the timestamp in the CID. Lexicographic sort of CIDs then gives registration order, which is all the dispatcher needs when iterating consumers in the MDO. This avoids maintaining a separate ordering file.
- A simpler alternative is an atomic counter using a lock file or `mkdir` (which is atomic on POSIX): the registering process tries `mkdir /q/consumers/0001`, increments until success. Simple, ordered, no timestamps needed — but requires a retry loop under contention.

### Issue: Notification mechanism

**Problem:** As PMPs and CMPs are added or removed at runtime, how does the dispatcher keep its inotify watches current?

**Resolution:**

The dispatcher should maintain watches at two levels:

1. **Directory-level watch on `/q/producers/`:** Watch for `IN_CREATE|IN_DELETE` on subdirectories. When a new PMP appears, immediately add a file-level watch on it. When a PMP is removed, drop its watch.

2. **File-level watch on each PMP:** Watch for `IN_CLOSE_WRITE|IN_MOVED_TO` events (a producer writing a PMF should close-write or rename-into the PMP). On event, run MDO on the new PMF.

CMPs do not need inotify watching by the dispatcher — the dispatcher writes to them, it does not read from them. However, the dispatcher should re-read `/q/consumers/` at the start of each MDO to pick up any newly registered consumers. A watch on `/q/consumers/` for `IN_CREATE` is sufficient to invalidate a cached consumer list.

Most inotify libraries (Linux `inotify(7)`, Python `watchdog`, Go `fsnotify`) support this two-level pattern. The dispatcher's watch loop is a standard event loop that handles both directory-structural events and file-creation events.

---

## Minor suggestions

- **`mmuxq dmo` output:** Printing an empty string when no PMF was processed is an unusual convention. Consider exit code 0 with no output (success, nothing to do) vs. exit code 0 with the PMF path (success, dispatched). Scripts can test `[ -n "$result" ]` either way, but the semantic is clearer with no-output-on-empty.

- **`mmuxq status` detail:** Specifying three states (pid file present + process running, pid file present + process dead, pid file absent) is good. Add a fourth: dispatcher running but pid file absent (e.g., file deleted manually). Detection via `pgrep` or process enumeration.

- **Dispatcher PID file cleanup:** The design does not say who removes `dispatcher.pid` when the dispatcher exits. The dispatcher should remove it on clean exit and `mmuxq stop` should remove it after sending SIGTERM.

- **Default QMP path:** Using `.mmuxq` as the default QMP anchored to CWD is convenient but fragile — callers must be careful about working directory. Consider also supporting a `MMUXQ_PATH` environment variable as a standard override.
