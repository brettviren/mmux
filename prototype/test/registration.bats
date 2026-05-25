#!/usr/bin/env bats
load helpers

# ---------------------------------------------------------------------------
# Producer registration
# ---------------------------------------------------------------------------

@test "producer creates a queue directory and prints its path" {
    run "$MMUXQ" producer
    [ "$status" -eq 0 ]
    [ -d "$output" ]
    [[ "$output" == */producers/*/queue ]]
}

@test "producer directories are sequentially numbered" {
    local pmp1 pmp2
    pmp1="$("$MMUXQ" producer)"
    pmp2="$("$MMUXQ" producer)"
    [[ "$(basename "$(dirname "$pmp1")")" == "0001" ]]
    [[ "$(basename "$(dirname "$pmp2")")" == "0002" ]]
}

@test "producer accepts explicit QMP argument" {
    local q="$MMUXQ_TEST_DIR/explicit"
    "$MMUXQ" init "$q" >/dev/null
    run "$MMUXQ" producer "$q"
    [ "$status" -eq 0 ]
    [[ "$output" == "$q/producers/"* ]]
}

# ---------------------------------------------------------------------------
# Consumer registration
# ---------------------------------------------------------------------------

@test "consumer creates a queue directory and prints its path" {
    run "$MMUXQ" consumer
    [ "$status" -eq 0 ]
    [ -d "$output" ]
    [[ "$output" == */consumers/*/queue ]]
}

@test "consumer directories are sequentially numbered" {
    local cmp1 cmp2
    cmp1="$("$MMUXQ" consumer)"
    cmp2="$("$MMUXQ" consumer)"
    [[ "$(basename "$(dirname "$cmp1")")" == "0001" ]]
    [[ "$(basename "$(dirname "$cmp2")")" == "0002" ]]
}

@test "consumer IDs are independent of producer IDs" {
    "$MMUXQ" producer >/dev/null
    "$MMUXQ" producer >/dev/null
    local cmp
    cmp="$("$MMUXQ" consumer)"
    [[ "$(basename "$(dirname "$cmp")")" == "0001" ]]
}

@test "consumer with --hook writes consumer-hook file" {
    local cmp
    cmp="$("$MMUXQ" consumer --hook 'echo hello')"
    local cdir
    cdir="$(dirname "$cmp")"
    [ -f "$cdir/consumer-hook" ]
    grep -q 'echo hello' "$cdir/consumer-hook"
}

@test "consumer with --hook prints CMP regardless" {
    run "$MMUXQ" consumer --hook 'echo hello'
    [ "$status" -eq 0 ]
    [[ "$output" == */consumers/*/queue ]]
}

@test "consumer with --on-hook-fail writes consumer-hook-fail file" {
    local cmp
    cmp="$("$MMUXQ" consumer --hook 'true' --on-hook-fail keep)"
    local cdir
    cdir="$(dirname "$cmp")"
    [ -f "$cdir/consumer-hook-fail" ]
    grep -q 'keep' "$cdir/consumer-hook-fail"
}

@test "consumer without --hook has no consumer-hook file" {
    local cmp
    cmp="$("$MMUXQ" consumer)"
    local cdir
    cdir="$(dirname "$cmp")"
    [ ! -f "$cdir/consumer-hook" ]
}

# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

@test "remove deregisters a producer" {
    local pmp
    pmp="$("$MMUXQ" producer)"
    local proot
    proot="$(dirname "$pmp")"
    run "$MMUXQ" remove "$proot"
    [ "$status" -eq 0 ]
    [ ! -d "$proot" ]
}

@test "remove deregisters a consumer" {
    local cmp
    cmp="$("$MMUXQ" consumer)"
    local croot
    croot="$(dirname "$cmp")"
    run "$MMUXQ" remove "$croot"
    [ "$status" -eq 0 ]
    [ ! -d "$croot" ]
}

@test "remove warns about pending messages" {
    local pmp
    pmp="$("$MMUXQ" producer)"
    touch "$pmp/msg001"
    local proot
    proot="$(dirname "$pmp")"
    run "$MMUXQ" remove "$proot" 2>&1
    [[ "$output" == *"WARNING"* ]]
    [[ "$output" == *"1 pending"* ]]
}
