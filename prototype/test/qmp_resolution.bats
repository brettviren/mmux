#!/usr/bin/env bats
load helpers

# ---------------------------------------------------------------------------
# QMP resolution precedence: arg > MMUXQ_PATH > walk-up > error
# ---------------------------------------------------------------------------

@test "explicit argument takes precedence over MMUXQ_PATH" {
    local explicit_q="$MMUXQ_TEST_DIR/explicit"
    "$MMUXQ" init "$explicit_q" >/dev/null
    # MMUXQ_PATH points to a different queue; explicit arg should win.
    run "$MMUXQ" producer "$explicit_q"
    [ "$status" -eq 0 ]
    [[ "$output" == "$explicit_q/producers/"* ]]
}

@test "MMUXQ_PATH is used when no explicit argument given" {
    run "$MMUXQ" producer
    [ "$status" -eq 0 ]
    [[ "$output" == "$MMUXQ_PATH/producers/"* ]]
}

@test "walk-up finds .mmuxq in parent directory" {
    local tmpdir subdir
    tmpdir="$(mktemp -d)"
    subdir="$tmpdir/a/b/c"
    mkdir -p "$subdir"
    "$MMUXQ" init "$tmpdir/.mmuxq" >/dev/null
    # Run from deep subdirectory with MMUXQ_PATH unset.
    run env -u MMUXQ_PATH bash -c "cd '$subdir' && '$MMUXQ' producer"
    [ "$status" -eq 0 ]
    [[ "$output" == "$tmpdir/.mmuxq/producers/"* ]]
    rm -rf "$tmpdir"
}

@test "walk-up stops at filesystem root and reports error" {
    run env -u MMUXQ_PATH bash -c "cd / && '$MMUXQ' producer 2>&1"
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR"* ]]
}

@test "error when no QMP can be resolved" {
    run env -u MMUXQ_PATH bash -c "cd /tmp && '$MMUXQ' producer 2>&1"
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR"* ]]
}

@test "error when explicit QMP path does not exist" {
    run "$MMUXQ" producer "$MMUXQ_TEST_DIR/nonexistent" 2>&1
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR"* ]]
}

@test "error when MMUXQ_PATH does not exist" {
    run env MMUXQ_PATH="$MMUXQ_TEST_DIR/nonexistent" "$MMUXQ" producer 2>&1
    [ "$status" -ne 0 ]
    [[ "$output" == *"ERROR"* ]]
}

@test "init with no argument does not require QMP to exist" {
    local tmpdir
    tmpdir="$(mktemp -d)"
    # init creates the queue at .mmuxq, so MMUXQ_PATH need not exist yet.
    run env -u MMUXQ_PATH bash -c "cd '$tmpdir' && '$MMUXQ' init"
    [ "$status" -eq 0 ]
    [ -d "$tmpdir/.mmuxq" ]
    rm -rf "$tmpdir"
}
