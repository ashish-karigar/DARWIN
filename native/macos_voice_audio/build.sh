#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
swift build --package-path "$SCRIPT_DIR" --configuration release
printf '%s\n' "Built $SCRIPT_DIR/.build/release/darwin-voice-capture"
