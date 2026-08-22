#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
OVERLAY_DIR="$INSTALLER_DIR/alpine/overlay"
DIST_DIR="$INSTALLER_DIR/dist"
OUTPUT="$DIST_DIR/kiki-alpine-overlay.tar.gz"

mkdir -p "$DIST_DIR"

if [ ! -d "$OVERLAY_DIR" ]; then
  echo "overlay directory not found: $OVERLAY_DIR" >&2
  exit 1
fi

python3 "$SCRIPT_DIR/build_alpine_overlay.py" "$OVERLAY_DIR" "$OUTPUT"
echo "wrote $OUTPUT"
