#!/bin/sh
set -eu

MODE="bios"
ISO=""
KERNEL=""
INITRD=""
APPEND="console=ttyS0"
DISK="installer/dist/qemu/kiki-test.qcow2"
DISK_SIZE="20G"
MEMORY="2048"
CPUS="2"
DRY_RUN=false
SMOKE_SECONDS=""
SERIAL_LOG=""
EXPECT=""
OVMF=""
BOOT_DISK=false

usage() {
  cat <<EOF
Usage: $0 (--iso path | --kernel path --initrd path | --boot-disk) [options]

Options:
  --iso <path>            Installer ISO boot source
  --kernel <path>         Direct kernel boot source
  --initrd <path>         Initramfs for direct kernel boot
  --append <args>         Direct kernel command line
  --boot-disk             Boot the supplied --disk without install media
  --mode <bios|uefi>       Firmware mode (default: $MODE)
  --disk <path>            QCOW2 disk path (default: $DISK)
  --disk-size <size>       Disk size for new image (default: $DISK_SIZE)
  --memory <MiB>           VM memory (default: $MEMORY)
  --cpus <n>               VM CPUs (default: $CPUS)
  --dry-run                Print commands without executing
  --smoke-seconds <n>      Stop after n seconds and verify serial output
  --serial-log <path>      Serial log used by smoke verification
  --expect <text>          Required fixed text in the serial log
  -h, --help               Show this help

UEFI mode expects OVMF firmware at /usr/share/OVMF/OVMF_CODE.fd or
/usr/share/edk2/ovmf/OVMF_CODE.fd.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --iso)
      ISO="$2"
      shift 2
      ;;
    --kernel)
      KERNEL="$2"
      shift 2
      ;;
    --initrd)
      INITRD="$2"
      shift 2
      ;;
    --append)
      APPEND="$2"
      shift 2
      ;;
    --boot-disk)
      BOOT_DISK=true
      shift
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --disk)
      DISK="$2"
      shift 2
      ;;
    --disk-size)
      DISK_SIZE="$2"
      shift 2
      ;;
    --memory)
      MEMORY="$2"
      shift 2
      ;;
    --cpus)
      CPUS="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --smoke-seconds)
      SMOKE_SECONDS="$2"
      shift 2
      ;;
    --serial-log)
      SERIAL_LOG="$2"
      shift 2
      ;;
    --expect)
      EXPECT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

source_count=0
if [ -n "$ISO" ]; then source_count=$((source_count + 1)); fi
if [ -n "$KERNEL" ] || [ -n "$INITRD" ]; then
  if [ -z "$KERNEL" ] || [ -z "$INITRD" ]; then
    echo "--kernel and --initrd must be supplied together" >&2
    exit 2
  fi
  source_count=$((source_count + 1))
fi
if [ "$BOOT_DISK" = true ]; then source_count=$((source_count + 1)); fi
if [ "$source_count" -ne 1 ]; then
  echo "provide exactly one of --iso, --kernel/--initrd, or --boot-disk" >&2
  exit 2
fi

case "$MODE" in
  bios|uefi) ;;
  *)
    echo "unsupported mode: $MODE" >&2
    exit 2
    ;;
esac

mkdir -p "$(dirname "$DISK")"

if [ -n "$SMOKE_SECONDS" ]; then
  case "$SMOKE_SECONDS" in *[!0-9]*|'') echo "invalid --smoke-seconds" >&2; exit 2;; esac
  if [ "$SMOKE_SECONDS" -lt 1 ] || [ -z "$SERIAL_LOG" ] || [ -z "$EXPECT" ]; then
    echo "smoke mode requires positive seconds, --serial-log, and --expect" >&2
    exit 2
  fi
  mkdir -p "$(dirname "$SERIAL_LOG")"
fi

CREATE_DISK="qemu-img create -f qcow2 '$DISK' '$DISK_SIZE'"
QEMU_BASE="qemu-system-x86_64 -m '$MEMORY' -smp '$CPUS' -enable-kvm -serial mon:stdio -drive file='$DISK',format=qcow2,if=virtio"
if [ -n "$ISO" ]; then
  QEMU_BASE="$QEMU_BASE -cdrom '$ISO' -boot d"
elif [ -n "$KERNEL" ]; then
  QEMU_BASE="$QEMU_BASE -kernel '$KERNEL' -initrd '$INITRD' -append '$APPEND'"
fi

if [ "$MODE" = "uefi" ]; then
  for candidate in /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd; do
    if [ -f "$candidate" ]; then
      OVMF="$candidate"
      break
    fi
  done
  if [ -z "$OVMF" ]; then
    echo "OVMF firmware not found" >&2
    echo "install ovmf/edk2-ovmf package or run with --dry-run" >&2
    if [ "$DRY_RUN" = false ]; then
      exit 1
    fi
    OVMF="/usr/share/OVMF/OVMF_CODE.fd"
  fi
  QEMU_BASE="$QEMU_BASE -drive if=pflash,format=raw,readonly=on,file='$OVMF'"
fi

if [ "$DRY_RUN" = true ]; then
  echo "$CREATE_DISK"
  echo "$QEMU_BASE"
  exit 0
fi

if [ ! -f "$DISK" ]; then
  qemu-img create -f qcow2 "$DISK" "$DISK_SIZE"
fi

run_qemu() {
  if [ -n "$ISO" ] && [ -n "$OVMF" ]; then
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -cdrom "$ISO" -boot d -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF"
  elif [ -n "$ISO" ]; then
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -cdrom "$ISO" -boot d -no-reboot
  elif [ -n "$KERNEL" ] && [ -n "$OVMF" ]; then
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -kernel "$KERNEL" -initrd "$INITRD" -append "$APPEND" -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF"
  elif [ -n "$KERNEL" ]; then
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -kernel "$KERNEL" -initrd "$INITRD" -append "$APPEND" -no-reboot
  elif [ -n "$OVMF" ]; then
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" -boot c -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF"
  else
    qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" -boot c -no-reboot
  fi
}

if [ -n "$SMOKE_SECONDS" ]; then
  set +e
  if [ -n "$ISO" ] && [ -n "$OVMF" ]; then
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -cdrom "$ISO" -boot d -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF" 2>/dev/null
  elif [ -n "$ISO" ]; then
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -cdrom "$ISO" -boot d -no-reboot 2>/dev/null
  elif [ -n "$KERNEL" ] && [ -n "$OVMF" ]; then
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -kernel "$KERNEL" -initrd "$INITRD" -append "$APPEND" -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF" 2>/dev/null
  elif [ -n "$KERNEL" ]; then
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" \
      -kernel "$KERNEL" -initrd "$INITRD" -append "$APPEND" -no-reboot 2>/dev/null
  elif [ -n "$OVMF" ]; then
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" -boot c -no-reboot \
      -drive "if=pflash,format=raw,readonly=on,file=$OVMF" 2>/dev/null
  else
    timeout "$SMOKE_SECONDS" qemu-system-x86_64 -m "$MEMORY" -smp "$CPUS" -enable-kvm -display none \
      -serial "file:$SERIAL_LOG" -drive "file=$DISK,format=qcow2,if=virtio" -boot c -no-reboot 2>/dev/null
  fi
  status=$?
  set -e
  if [ "$status" -ne 0 ] && [ "$status" -ne 124 ]; then
    echo "QEMU smoke boot failed with status $status" >&2
    exit "$status"
  fi
  if ! grep -F -- "$EXPECT" "$SERIAL_LOG" >/dev/null; then
    echo "serial log does not contain expected marker: $EXPECT" >&2
    exit 1
  fi
  exit 0
fi

SERIAL_LOG=/dev/stdout
run_qemu
