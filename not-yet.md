This is "mmux" the monitoring multiplexer, a Python package providing a Python library and user interface programs for monitoring and interacting with processes run locally or on remote hosts.

Monitoring information is provided to mmux by JSONL (newline-delimited JSON
objects) files appended to a file

, creating and attaching to tmux sessions.  A general purpose 

In addition, other applications can provide their own monitoring information and actions.

TUI:




I want to radically change the design of "bsdb" but want to explore the implications first.  Here is an outline of the new design:

1. The `bsdb.tmux.monitor.loop()` will replaced by a single, general purpose async function `bsdb.feeds.file()` that will, via SSH to each remote, run effectively (or literally?) a persistent `tail -f` on a single file.  The file will assume to be constantly appended to with JSONL (newline terminated JSON objects).

2. Each JSONL object will have "proto" and "schema" attributes.  The "proto" names a `bsdb.protos.<proto>` module and the "schema" names a message type provided in that module.

3. A `bsdb.protos.tmux` will provide a set of dataclasses providing schema objects.  Two of classes will be `Activity` and `Silence` which are analogous to the old `SessionInfo` but which hold information related to tmux `alert-activity` and `alert-silence` hooks, respectively.  Schema related to other tmux hooks may be added in the future.

4. A `bsdb.protos.claude` will likewise provide schema relevant to claude hooks.

5. The `bsdb.protos.<proto>.connect_script` string will provide bash shell code that will be executed on the remote just prior to entering the `tail -f` phase.

5. The `bsdb.protos.<proto>.disconnect_script` string will provide bash shell code that will be executed on the remote just after the `tail -f` phase terminates.

Questions:

Q1: How to gracefully stop the `tail -f` phase.
