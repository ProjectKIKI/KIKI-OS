#!/bin/sh
set -eu

RELEASE="v3.20"
ARCH="x86_64"
OUT_DIR="installer/dist/iso"
APORTS_DIR="installer/dist/iso-work/aports"
AUTOINSTALL=0

usage() {
  cat <<EOF
Usage: $0 [--release vX.Y] [--arch x86_64] [--out-dir path] [--aports-dir path]
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --release)
      RELEASE="$2"
      shift 2
      ;;
    --arch)
      ARCH="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --aports-dir)
      APORTS_DIR="$2"
      shift 2
      ;;
    --autoinstall)
      AUTOINSTALL=1
      shift
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

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)
PROFILE_DIR="$REPO_ROOT/installer/alpine/iso/profiles"
OVERLAY_TARBALL="$REPO_ROOT/installer/dist/kiki-alpine-overlay.tar.gz"

if [ ! -f "$OVERLAY_TARBALL" ]; then
  "$REPO_ROOT/installer/scripts/build-alpine-overlay.sh"
fi

if [ ! -x "$APORTS_DIR/scripts/mkimage.sh" ]; then
  mkdir -p "$(dirname "$APORTS_DIR")"
  git clone --depth 1 --branch "$RELEASE" https://gitlab.alpinelinux.org/alpine/aports.git "$APORTS_DIR"
fi

mkdir -p "$OUT_DIR"
cp "$PROFILE_DIR/profile_kiki.sh" "$APORTS_DIR/scripts/mkimg.kiki.sh"

KIKI_AUTOINSTALL="$AUTOINSTALL" KIKI_APKOVL="$OVERLAY_TARBALL" \
sh "$APORTS_DIR/scripts/mkimage.sh" \
  --tag "$RELEASE" \
  --outdir "$OUT_DIR" \
  --arch "$ARCH" \
  --profile kiki \
  --repository "https://dl-cdn.alpinelinux.org/alpine/$RELEASE/main" \
  --repository "https://dl-cdn.alpinelinux.org/alpine/$RELEASE/community"
