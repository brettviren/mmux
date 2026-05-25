#!/usr/bin/env bash
# Shared helpers for mmuxq bats test suite.

BATS_TEST_TIMEOUT=30

MMUXQ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mmuxq"

setup() {
    MMUXQ_TEST_DIR="$(mktemp -d)"
    export MMUXQ_PATH="$MMUXQ_TEST_DIR/q"
    "$MMUXQ" init "$MMUXQ_PATH" >/dev/null
    _dispatcher_pid=""
}

teardown() {
    # Kill any dispatcher started during the test.
    if [[ -n "${_dispatcher_pid:-}" ]]; then
        kill "$_dispatcher_pid" 2>/dev/null || true
        wait "$_dispatcher_pid" 2>/dev/null || true
    fi
    # Also kill any leftover dispatcher for this test's QMP.
    local pidfile="$MMUXQ_PATH/dispatcher.pid"
    if [[ -f "$pidfile" ]]; then
        kill "$(< "$pidfile")" 2>/dev/null || true
    fi
    rm -rf "$MMUXQ_TEST_DIR"
}

# Start the dispatcher in background; store PID in _dispatcher_pid.
start_dispatcher() {
    "$MMUXQ" dispatcher "$MMUXQ_PATH" &
    _dispatcher_pid=$!
    # Wait for pid file to appear.
    local waited=0
    while [[ ! -f "$MMUXQ_PATH/dispatcher.pid" ]] && (( waited < 20 )); do
        sleep 0.1
        waited=$(( waited + 1 ))
    done
}

# Stop the background dispatcher and wait for it to exit.
stop_dispatcher() {
    if [[ -f "$MMUXQ_PATH/dispatcher.pid" ]]; then
        kill "$(< "$MMUXQ_PATH/dispatcher.pid")" 2>/dev/null || true
    fi
    wait "$_dispatcher_pid" 2>/dev/null || true
    _dispatcher_pid=""
}

# Wait up to N*0.1s for a file to appear.
wait_for_file() {
    local file="$1" attempts="${2:-30}"
    local waited=0
    while [[ ! -f "$file" ]] && (( waited < attempts )); do
        sleep 0.1
        waited=$(( waited + 1 ))
    done
    [[ -f "$file" ]]
}
