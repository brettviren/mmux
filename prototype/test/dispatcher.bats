#!/usr/bin/env bats
load helpers

# ---------------------------------------------------------------------------
# Foreground dispatcher lifecycle
# ---------------------------------------------------------------------------

@test "dispatcher writes pid file on start" {
    start_dispatcher
    [ -f "$MMUXQ_PATH/dispatcher.pid" ]
    stop_dispatcher
}

@test "dispatcher pid file contains a valid PID" {
    start_dispatcher
    local pid
    pid="$(< "$MMUXQ_PATH/dispatcher.pid")"
    kill -0 "$pid"
    stop_dispatcher
}

@test "dispatcher removes pid file on clean exit" {
    start_dispatcher
    stop_dispatcher
    [ ! -f "$MMUXQ_PATH/dispatcher.pid" ]
}

@test "second dispatcher exits with warning if one is running" {
    start_dispatcher
    run "$MMUXQ" dispatcher "$MMUXQ_PATH"
    [ "$status" -ne 0 ]
    [[ "$output" == *"already running"* ]]
    stop_dispatcher
}

# ---------------------------------------------------------------------------
# Background start / stop / status
# ---------------------------------------------------------------------------

@test "start launches background dispatcher" {
    run "$MMUXQ" start
    [ "$status" -eq 0 ]
    [[ "$output" == *"started"* ]]
    [ -f "$MMUXQ_PATH/dispatcher.pid" ]
    "$MMUXQ" stop >/dev/null
}

@test "start is idempotent when dispatcher is already running" {
    "$MMUXQ" start >/dev/null
    run "$MMUXQ" start
    [ "$status" -eq 0 ]
    [[ "$output" == *"already running"* ]]
    "$MMUXQ" stop >/dev/null
}

@test "stop terminates the dispatcher" {
    "$MMUXQ" start >/dev/null
    local pid
    pid="$(< "$MMUXQ_PATH/dispatcher.pid")"
    run "$MMUXQ" stop
    [ "$status" -eq 0 ]
    ! kill -0 "$pid" 2>/dev/null
}

@test "stop reports when dispatcher is not running" {
    run "$MMUXQ" stop
    [ "$status" -eq 0 ]
    [[ "$output" == *"not running"* ]]
}

@test "status reports running when dispatcher is alive" {
    "$MMUXQ" start >/dev/null
    run "$MMUXQ" status
    [ "$status" -eq 0 ]
    [[ "$output" == *"running"* ]]
    "$MMUXQ" stop >/dev/null
}

@test "status reports not running when dispatcher is stopped" {
    run "$MMUXQ" status
    [ "$status" -eq 0 ]
    [[ "$output" == *"not running"* ]]
}

@test "status includes pending message count" {
    local pmp
    pmp="$("$MMUXQ" producer)"
    touch "$pmp/msg001" "$pmp/msg002"
    run "$MMUXQ" status
    [ "$status" -eq 0 ]
    [[ "$output" == *"pending messages: 2"* ]]
}

# ---------------------------------------------------------------------------
# Dispatcher dispatches messages via inotify
# ---------------------------------------------------------------------------

@test "dispatcher dispatches new PMF to consumers via inotify" {
    local pmp cmp
    pmp="$("$MMUXQ" producer)"
    cmp="$("$MMUXQ" consumer)"
    start_dispatcher
    echo "hello" > "$pmp/msg_inotify"
    wait_for_file "$cmp/msg_inotify" 30
    [ -f "$cmp/msg_inotify" ]
    stop_dispatcher
}

@test "dispatcher dispatches pre-existing PMFs on startup" {
    local pmp cmp
    pmp="$("$MMUXQ" producer)"
    cmp="$("$MMUXQ" consumer)"
    # Write PMF before starting dispatcher.
    echo "pre-existing" > "$pmp/msg_pre"
    start_dispatcher
    wait_for_file "$cmp/msg_pre" 30
    [ -f "$cmp/msg_pre" ]
    stop_dispatcher
}

@test "dispatcher handles new producer registered after start" {
    local cmp
    cmp="$("$MMUXQ" consumer)"
    start_dispatcher
    sleep 0.2
    # Register producer AFTER dispatcher started.
    local pmp
    pmp="$("$MMUXQ" producer)"
    sleep 0.2
    echo "late producer" > "$pmp/msg_late"
    wait_for_file "$cmp/msg_late" 40
    [ -f "$cmp/msg_late" ]
    stop_dispatcher
}

@test "dispatcher runs CMH on new messages" {
    local pmp cmp
    pmp="$("$MMUXQ" producer)"
    cmp="$("$MMUXQ" consumer --hook 'cp "$MMUXQ_CMF" "${MMUXQ_CMF}.done"')"
    start_dispatcher
    echo "hook test" > "$pmp/msg_hook"
    wait_for_file "$cmp/msg_hook.done" 30
    [ -f "$cmp/msg_hook.done" ]
    [ ! -f "$cmp/msg_hook" ]
    stop_dispatcher
}
