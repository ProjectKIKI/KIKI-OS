#!/bin/sh
set -eu

NODE_NAME=""
SERVER_URL="http://127.0.0.1:8088"
OUT_DIR="/tmp"
TOKEN_FILE="/etc/kiki/registration-token"

usage() {
  cat <<EOF
Usage: $0 --node <name> [--server http://bootstrap:8088] [--token-file /etc/kiki/registration-token] [--out-dir /tmp]

Collect installer diagnostics into a tar.gz bundle and upload it to bootstrapd.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --node)
      NODE_NAME="$2"
      shift 2
      ;;
    --server)
      SERVER_URL="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --token-file)
      TOKEN_FILE="$2"
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

if [ -z "$NODE_NAME" ]; then
  echo "--node is required" >&2
  exit 2
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

if [ ! -r "$TOKEN_FILE" ]; then
  echo "node token file is not readable: $TOKEN_FILE" >&2
  exit 1
fi
NODE_TOKEN=$(tr -d '\r\n' <"$TOKEN_FILE")
if [ -z "$NODE_TOKEN" ]; then
  echo "node token file is empty: $TOKEN_FILE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
WORK_DIR=$(mktemp -d "$OUT_DIR/kiki-log-bundle.XXXXXX")
AUTH_HEADER=$(mktemp "$OUT_DIR/.kiki-auth.XXXXXX")
trap 'rm -rf "$WORK_DIR"; rm -f "$AUTH_HEADER"' EXIT
umask 077
printf 'Authorization: Bearer %s\n' "$NODE_TOKEN" >"$AUTH_HEADER"

collect_cmd() {
  name="$1"
  shift
  if "$@" >"$WORK_DIR/$name" 2>&1; then
    :
  else
    echo "command failed: $*" >>"$WORK_DIR/$name"
  fi
}

collect_cmd lsblk.txt lsblk -f
collect_cmd ip-addr.txt ip addr
collect_cmd ip-route.txt ip route
collect_cmd mount.txt mount
collect_cmd dmesg.txt dmesg

if command -v journalctl >/dev/null 2>&1; then
  collect_cmd journal-kiki.txt journalctl -u kiki-agent.service -u kiki-prepull-images.service --no-pager -n 300
fi

for path in \
  /var/log/kiki-install.log \
  /tmp/kiki-install.log \
  /etc/kiki/install.yaml \
  /etc/kiki/node.yaml
do
  if [ -e "$path" ]; then
    cp "$path" "$WORK_DIR/$(basename "$path")"
  fi
done

BUNDLE="$OUT_DIR/${NODE_NAME}-kiki-logs-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C "$WORK_DIR" -czf "$BUNDLE" .

curl -fsS \
  -H "@$AUTH_HEADER" \
  -F "nodeName=$NODE_NAME" \
  -F "bundle=@$BUNDLE" \
  "$SERVER_URL/api/v1/nodes/log-bundles"

echo "uploaded $BUNDLE"
