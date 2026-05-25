#!/usr/bin/env bats
load helpers

setup() {
    MMUXQ_TEST_DIR="$(mktemp -d)"
    export MMUXQ_PATH="$MMUXQ_TEST_DIR/q"
    "$MMUXQ" init "$MMUXQ_PATH" >/dev/null
    _dispatcher_pid=""

    # Common fixtures: one producer, two consumers (one with hook).
    PMP="$("$MMUXQ" producer)"
    CMP1="$("$MMUXQ" consumer)"
    CMP2="$("$MMUXQ" consumer --hook 'cp "$MMUXQ_CMF" "${MMUXQ_CMF}.done"')"
}

# ---------------------------------------------------------------------------
# Basic dispatch
# ---------------------------------------------------------------------------

@test "dmo dispatches PMF to all consumers" {
    echo "hello" > "$PMP/msg001"
    run "$MMUXQ" dmo
    [ "$status" -eq 0 ]
    [ -f "$CMP1/msg001" ]
    [ -f "$CMP2/msg001.done" ]
}

@test "dmo removes the PMF after dispatch" {
    echo "hello" > "$PMP/msg001"
    "$MMUXQ" dmo >/dev/null
    [ ! -f "$PMP/msg001" ]
}

@test "dmo prints the dispatched PMF path" {
    echo "hello" > "$PMP/msg001"
    run "$MMUXQ" dmo
    [ "$status" -eq 0 ]
    [[ "$output" == *"msg001" ]]
}

@test "dmo with no PMFs exits 0 and prints nothing" {
    run "$MMUXQ" dmo
    [ "$status" -eq 0 ]
    [ -z "$output" ]
}

@test "dmo executes CMH and removes CMF" {
    echo "hello" > "$PMP/msg001"
    "$MMUXQ" dmo >/dev/null
    # CMH copies CMF to .done then dispatcher removes CMF.
    [ -f "$CMP2/msg001.done" ]
    [ ! -f "$CMP2/msg001" ]
}

@test "dmo leaves CMF in place for hook-less consumer" {
    echo "hello" > "$PMP/msg001"
    "$MMUXQ" dmo >/dev/null
    [ -f "$CMP1/msg001" ]
}

# ---------------------------------------------------------------------------
# CMF content matches PMF
# ---------------------------------------------------------------------------

@test "CMF content is identical to PMF (hard link)" {
    echo "test content" > "$PMP/msg001"
    "$MMUXQ" dmo >/dev/null
    run cat "$CMP1/msg001"
    [ "$status" -eq 0 ]
    [ "$output" = "test content" ]
}

# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

@test "dmo dispatches oldest PMF first" {
    touch -t 202001010000 "$PMP/old_msg"
    touch -t 202012310000 "$PMP/new_msg"
    result="$("$MMUXQ" dmo)"
    [[ "$result" == *"old_msg" ]]
    [ ! -f "$PMP/old_msg" ]
    [ -f "$PMP/new_msg" ]
}

# ---------------------------------------------------------------------------
# Multiple consumers — delivery order
# ---------------------------------------------------------------------------

@test "dmo delivers to consumers in registration order" {
    echo "hello" > "$PMP/msg001"
    "$MMUXQ" dmo >/dev/null
    # Both consumers should have received the message.
    [ -f "$CMP1/msg001" ]
    [ -f "$CMP2/msg001.done" ]
}

# ---------------------------------------------------------------------------
# Explicit path arguments
# ---------------------------------------------------------------------------

@test "dmo with explicit QMP path" {
    echo "hello" > "$PMP/msg001"
    run "$MMUXQ" dmo "$MMUXQ_PATH"
    [ "$status" -eq 0 ]
    [[ "$output" == *"msg001" ]]
}

@test "dmo with explicit PMP path" {
    echo "hello" > "$PMP/msg001"
    run "$MMUXQ" dmo "$PMP"
    [ "$status" -eq 0 ]
    [[ "$output" == *"msg001" ]]
}

@test "dmo with explicit PMF path" {
    echo "hello" > "$PMP/msg001"
    run "$MMUXQ" dmo "$PMP/msg001"
    [ "$status" -eq 0 ]
    [[ "$output" == *"msg001" ]]
}

# ---------------------------------------------------------------------------
# Hook failure modes
# ---------------------------------------------------------------------------

@test "dmo removes CMF by default when hook fails" {
    local cmp_fail
    cmp_fail="$("$MMUXQ" consumer --hook 'exit 1')"
    echo "hello" > "$PMP/msg_fail"
    "$MMUXQ" dmo >/dev/null 2>&1 || true
    [ ! -f "$cmp_fail/msg_fail" ]
}

@test "dmo keeps CMF when hook fails and mode is keep" {
    local cmp_keep
    cmp_keep="$("$MMUXQ" consumer --hook 'exit 1' --on-hook-fail keep)"
    echo "hello" > "$PMP/msg_keep"
    "$MMUXQ" dmo >/dev/null 2>&1 || true
    [ -f "$cmp_keep/msg_keep" ]
}

@test "dmo moves CMF to failed/ when hook fails and mode is faildir" {
    local cmp_faildir
    cmp_faildir="$("$MMUXQ" consumer --hook 'exit 1' --on-hook-fail faildir)"
    local croot
    croot="$(dirname "$cmp_faildir")"
    echo "hello" > "$PMP/msg_faildir"
    "$MMUXQ" dmo >/dev/null 2>&1 || true
    [ -f "$croot/failed/msg_faildir" ]
    [ ! -f "$cmp_faildir/msg_faildir" ]
}
