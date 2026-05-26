#!/usr/bin/env bash
# Run the mmuxq test suite via bats.
set -euo pipefail

BATS="${BATS:-$HOME/dev/bats-core/bin/bats}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$BATS" ]]; then
    echo "ERROR: bats not found at $BATS" >&2
    echo "Set BATS=/path/to/bats to override." >&2
    exit 1
fi

exec "$BATS" "$@" "$SCRIPT_DIR"/*.bats
