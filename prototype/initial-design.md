This is an initial design for the mmuxq message queue.

# Overview

The mmuxq is a multi-producer, multi-consumer (MPMC) queue with these qualities:

- Persistence: the queue is comprised of a directory tree and messages are files.

- Simple: basic queue operation requires only a few traditional Unix command line tools. 

- Automated: operations can free run with inotify or other file notification mechanism.

- Robust: all produced messages go to all consumers, atomically and in production-time order.

- Prompt: a message is "pushed" from producer to consumer in (soft) real-time.

- Dynamic: producers and consumers may join to and part from the queue during its lifetime.

- Flexible: message content is unconstrained and may be larger than operating system I/O buffers.

# Design

The mmuxq design is described.

## State

A mmuxq queue is defined by a queue message path (QMP) directory name.  This rest of this design will use the path `/q`.  In practice, a more uniquely named path is expected. 

## Roles

The queue defines three roles.

Each *producer* registers with the queue and receives a unique *producer message path* (PMP) which is a directory in which the producer may freely write *producer message files* (PMFs).

Each *consumer* registers with the queue and receives a unique *consumer message path* (CMP) from which it may choose to freely read *consumer message files* (CMFs).  Alternatively it may register a *consumer message hook* (CMH) to process each new CMF and in which case it does not learn the CMP.

A single *dispatcher* implements the *message dispatch operation* (MDO) on each PMF to produce each CMF.  The life cycle and the MDO are described in the next two sections

## Dispatch life cycle

The dispatcher goes through this life cycle:

1. Checks if a dispatcher is already running for the queue and exits with a warning if one is found.

2. Writes its process ID to a `/q/dispatcher.pid` file used by other started dispatchers to check for existing instances.

3. Applies the MDO on each pre-existing PMF.  It does this one PMF at a time by finding the oldest PMF and dispatching it.  Once all existing PMFs are exhausted, it enters its watch phase.

4. The watch phase starts by the dispatcher registering an inotify-based mechanism to watch for new PMFs in any existing or future PMPs to apply the DMO a guaranteed serial manner.  This phase is robust against newly created or removed PMPs and CMPs.

## Message dispatch operation

The message dispatch operation (DMO) consists of a serial sequence of operations:

1) A hard-link is made from the PMF to a CMF for each registered consumer in order of their registration.

2) The PMF is removed from the PMP.

3) Every registered CMH is executed on its corresponding CMF and the CMF is removed. 

For consumers that did not register a CMH, the dispatcher performs no action on the corresponding CMF.

# Implementation details

The queue design allows for many implementations.  To describe details of implementation, assume a `mmuxq` CLI and a queue defined in `/q`.

The `mmuxq` command line program provides all queue management.  Producers and consumers use it participate in those roles.  The queue message path is given explicitly as `<QMP>` or if not provided it is implicitly taken to be the `.mmuxq` sub-directory of the current working directory.

After some use, the queue layout may look like:

```
/q/dispatcher.pid
/q/producers/<PID>/queue
/q/consumers/<CID>/queue
/q/consumers/<CID>/consumer-hook
```

The `<PID>` and `<CID>` are unique names for a producer or consumer, respectively.  The `.../queue/` is a PMP or a CMP.  Other paths are described below.

The command is composed of sub-commands described in the following subsections.

## Creation

A new queue is explicitly created with:

```
mmuxq init [<QMP>]
```

Create the QMP tree structure.  Assuming QMP is `/q` this structure looks like the following and may pre-exist

- `/q/producers` base directory holding PMP sub-directories
- `/q/consumers` base directory holding CMP sub-directories

## Dispatcher

```
mmuxq dispatcher [<QMP>]
```

Run the dispatcher life-cycle as a foreground process on a QMP.  The file `/q/dispatcher.pid` is used to hold a dispatcher process ID.

A dispatcher can run and managed as a background process with these commands

- `mmuxq start [<QMP>]` - assure a dispatcher is running, print warning to stderr and exit non-zero code if failure to start, print warning and exit with zero if already running (shared code with "status")
- `mmuxq status [<QMP>]` - print status to stdout (dispatcher.pid exists and points to a running process, it exists but no dispatcher is running, it does not exist).
- `mmuxq stop [<QMP>]` - stop a running dispatcher according to its process ID in dispatcher.pid or if not runing, print so to stderr.  

## Dispatch message operation

The DMO can be explicitly executed once with:

```
mmuxq dmo [<QMP>|<PMP>|<PMF>]
```

With no argument, the default QMP is assumed.  If a QMP is given, the oldest PMF of all PMPs is used.  If a PMP directory is given, its oldest PMF is used.  If a PMF is given, it is processed regardless of age.

This command may produce diagnostics on stderr.  It prints to stdout the PMF that was processed or an empty string if none.

## Registering

A producer or a consumer is registered with:

```
mmuxq [producer|consumer] [--hook cmd] [<QMP>]
```

This prints to stdout the PMP or CMP.  A consumer may provide CMH via `--hook`.

# Issues

This section holds known issues with the above design that need solution or better understanding.

## Start up race

During the transition between initial MDO application, when the inotify watch is being set and before notifications are ready, there is a brief time where a new PMF can be created.  How to assure this PMF is not neglected?

## Identification

The identifiers for producers and consumers must be unique to each category.  In principle, the `mmuxq` command to create them can be run multiple times concurrently so some care is needed to assure uniqueness.  The `PID` and `CID` strings need not be defined in a human-readable way, eg a hash on some unique information can be used.  The message dispatch operation requires ordered iteration of consumers and if the `CID` does not contain that order, something else needs to.

## Notification mechanism

How does the inotify mechanism work as the set of PMPs and the set of CMPs change?  Does the dispatcher need to reassert inotify watches when these sets changes?  If so, how?

