#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

python3 "$SCRIPT_DIR/install-debian-node.py" \
  --config "$INSTALLER_DIR/configs/install.example.yaml" \
  --dry-run >/tmp/kiki-install-bios-dry-run.log

python3 "$SCRIPT_DIR/install-debian-node.py" \
  --config "$INSTALLER_DIR/configs/install.uefi.example.yaml" \
  --dry-run >/tmp/kiki-install-uefi-dry-run.log

echo "wrote /tmp/kiki-install-bios-dry-run.log"
echo "wrote /tmp/kiki-install-uefi-dry-run.log"
