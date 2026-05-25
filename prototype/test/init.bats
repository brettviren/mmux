#!/usr/bin/env bats
load helpers

@test "init creates producers and consumers directories" {
    local q="$MMUXQ_TEST_DIR/newq"
    run "$MMUXQ" init "$q"
    [ "$status" -eq 0 ]
    [ -d "$q/producers" ]
    [ -d "$q/consumers" ]
}

@test "init prints the initialized path" {
    local q="$MMUXQ_TEST_DIR/newq"
    run "$MMUXQ" init "$q"
    [ "$status" -eq 0 ]
    [[ "$output" == *"$q"* ]]
}

@test "init is idempotent on existing queue" {
    run "$MMUXQ" init "$MMUXQ_PATH"
    [ "$status" -eq 0 ]
    [ -d "$MMUXQ_PATH/producers" ]
    [ -d "$MMUXQ_PATH/consumers" ]
}

@test "init with no argument creates .mmuxq in current directory" {
    local tmpdir
    tmpdir="$(mktemp -d)"
    cd "$tmpdir"
    run "$MMUXQ" init
    [ "$status" -eq 0 ]
    [ -d "$tmpdir/.mmuxq/producers" ]
    [ -d "$tmpdir/.mmuxq/consumers" ]
    rm -rf "$tmpdir"
}

@test "init with explicit path does not require MMUXQ_PATH" {
    local q="$MMUXQ_TEST_DIR/explicit"
    run env -u MMUXQ_PATH "$MMUXQ" init "$q"
    [ "$status" -eq 0 ]
    [ -d "$q/producers" ]
}
