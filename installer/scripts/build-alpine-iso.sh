#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALLER_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(CDPATH= cd -- "$INSTALLER_DIR/.." && pwd)

ALPINE_RELEASE="v3.20"
ARCH="x86_64"
RUNNER="local"
APORTS_DIR=""
WORK_DIR="$INSTALLER_DIR/dist/iso-work"
OUT_DIR="$INSTALLER_DIR/dist/iso"
DRY_RUN=false
AUTOINSTALL=false

usage() {
  cat <<EOF
Usage: $0 [options]

Build a KIKI Alpine installer ISO using Alpine aports mkimage.sh.

Options:
  --release <vX.Y>       Alpine release branch/tag (default: $ALPINE_RELEASE)
  --arch <arch>          Target arch (default: $ARCH)
  --runner <local|docker|podman>
                         Build runner (default: $RUNNER)
  --aports-dir <path>    Existing Alpine aports checkout
  --work-dir <path>      Work directory (default: $WORK_DIR)
  --out-dir <path>       ISO output directory (default: $OUT_DIR)
  --dry-run              Print the build command without running it
  --autoinstall          Add destructive factory-only autoinstall kernel flag
  -h, --help             Show this help

Notes:
  local runner must be executed on Alpine with alpine-sdk, syslinux, xorriso,
  squashfs-tools, mtools, dosfstools, grub, and grub-efi installed.

  docker/podman runner uses installer/alpine/iso/Containerfile and requires
  network access to fetch Alpine packages and clone aports if --aports-dir is
  not supplied.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --release)
      ALPINE_RELEASE="$2"
      shift 2
      ;;
    --arch)
      ARCH="$2"
      shift 2
      ;;
    --runner)
      RUNNER="$2"
      shift 2
      ;;
    --aports-dir)
      APORTS_DIR="$2"
      shift 2
      ;;
    --work-dir)
      WORK_DIR="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --autoinstall)
      AUTOINSTALL=true
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

case "$RUNNER" in
  local|docker|podman) ;;
  *)
    echo "unsupported runner: $RUNNER" >&2
    exit 2
    ;;
esac

"$SCRIPT_DIR/build-alpine-overlay.sh"

PROFILE_DIR="$INSTALLER_DIR/alpine/iso/profiles"
PROFILE_FILE="$PROFILE_DIR/profile_kiki.sh"
OVERLAY_TARBALL="$INSTALLER_DIR/dist/kiki-alpine-overlay.tar.gz"
AUTOINSTALL_VALUE=0
if [ "$AUTOINSTALL" = true ]; then
  AUTOINSTALL_VALUE=1
fi

if [ ! -f "$PROFILE_FILE" ]; then
  echo "profile not found: $PROFILE_FILE" >&2
  exit 1
fi
if [ ! -f "$OVERLAY_TARBALL" ]; then
  echo "overlay tarball not found: $OVERLAY_TARBALL" >&2
  exit 1
fi

mkdir -p "$WORK_DIR" "$OUT_DIR"

if [ "$RUNNER" = "local" ]; then
  if [ -z "$APORTS_DIR" ]; then
    APORTS_DIR="$WORK_DIR/aports"
  fi
  COMMAND="cp '$PROFILE_FILE' '$APORTS_DIR/scripts/mkimg.kiki.sh' && KIKI_AUTOINSTALL='$AUTOINSTALL_VALUE' KIKI_APKOVL='$OVERLAY_TARBALL' sh '$APORTS_DIR/scripts/mkimage.sh' --tag '$ALPINE_RELEASE' --outdir '$OUT_DIR' --arch '$ARCH' --profile kiki --repository 'https://dl-cdn.alpinelinux.org/alpine/$ALPINE_RELEASE/main' --repository 'https://dl-cdn.alpinelinux.org/alpine/$ALPINE_RELEASE/community'"
  if [ "$DRY_RUN" = true ]; then
    if [ ! -x "$APORTS_DIR/scripts/mkimage.sh" ]; then
      echo "# missing Alpine aports mkimage.sh: $APORTS_DIR/scripts/mkimage.sh"
      echo "# clone it first, for example:"
      echo "# git clone --branch $ALPINE_RELEASE https://gitlab.alpinelinux.org/alpine/aports.git $APORTS_DIR"
    fi
    echo "$COMMAND"
    exit 0
  fi
  if [ ! -x "$APORTS_DIR/scripts/mkimage.sh" ]; then
    echo "missing Alpine aports mkimage.sh: $APORTS_DIR/scripts/mkimage.sh" >&2
    echo "clone it first, for example:" >&2
    echo "  git clone --branch $ALPINE_RELEASE https://gitlab.alpinelinux.org/alpine/aports.git $APORTS_DIR" >&2
    exit 1
  fi
  cp "$PROFILE_FILE" "$APORTS_DIR/scripts/mkimg.kiki.sh"

  KIKI_AUTOINSTALL="$AUTOINSTALL_VALUE" KIKI_APKOVL="$OVERLAY_TARBALL" sh "$APORTS_DIR/scripts/mkimage.sh" \
    --tag "$ALPINE_RELEASE" \
    --outdir "$OUT_DIR" \
    --arch "$ARCH" \
    --profile kiki \
    --repository "https://dl-cdn.alpinelinux.org/alpine/$ALPINE_RELEASE/main" \
    --repository "https://dl-cdn.alpinelinux.org/alpine/$ALPINE_RELEASE/community"
  exit 0
fi

CONTAINER_TOOL="$RUNNER"
IMAGE_TAG="kiki-alpine-iso-builder:$ALPINE_RELEASE"
CONTAINERFILE="$INSTALLER_DIR/alpine/iso/Containerfile"
ALPINE_VERSION=${ALPINE_RELEASE#v}

if [ ! -f "$CONTAINERFILE" ]; then
  echo "containerfile not found: $CONTAINERFILE" >&2
  exit 1
fi

BUILD_CMD="$CONTAINER_TOOL build --build-arg ALPINE_VERSION=$ALPINE_VERSION -t $IMAGE_TAG -f '$CONTAINERFILE' '$REPO_ROOT'"
AUTOINSTALL_ARG=""
if [ "$AUTOINSTALL" = true ]; then
  AUTOINSTALL_ARG="--autoinstall"
fi
RUN_CMD="$CONTAINER_TOOL run --rm -v '$REPO_ROOT:/work' -w /work $IMAGE_TAG sh installer/alpine/iso/run-mkimage.sh --release '$ALPINE_RELEASE' --arch '$ARCH' --out-dir '$OUT_DIR' $AUTOINSTALL_ARG"

if [ "$DRY_RUN" = true ]; then
  echo "$BUILD_CMD"
  echo "$RUN_CMD"
  exit 0
fi

"$CONTAINER_TOOL" build --build-arg "ALPINE_VERSION=$ALPINE_VERSION" -t "$IMAGE_TAG" -f "$CONTAINERFILE" "$REPO_ROOT"
if [ "$AUTOINSTALL" = true ]; then
  "$CONTAINER_TOOL" run --rm -v "$REPO_ROOT:/work" -w /work "$IMAGE_TAG" sh installer/alpine/iso/run-mkimage.sh --release "$ALPINE_RELEASE" --arch "$ARCH" --out-dir "$OUT_DIR" --autoinstall
else
  "$CONTAINER_TOOL" run --rm -v "$REPO_ROOT:/work" -w /work "$IMAGE_TAG" sh installer/alpine/iso/run-mkimage.sh --release "$ALPINE_RELEASE" --arch "$ARCH" --out-dir "$OUT_DIR"
fi
