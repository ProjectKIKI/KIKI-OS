#!/bin/sh
set -eu

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
  shift
fi

if [ "$#" -ne 1 ]; then
  echo "usage: $0 [--dry-run] installer/configs/images.example.yaml" >&2
  exit 2
fi

if [ "$DRY_RUN" = false ] && ! command -v skopeo >/dev/null 2>&1; then
  echo "skopeo is required for image mirroring" >&2
  exit 1
fi

PAIRS=$(python3 - "$1" <<'PY'
import sys

try:
    import yaml
except ImportError as exc:
    raise SystemExit("python3-yaml or PyYAML is required") from exc

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    plan = yaml.safe_load(handle)

dest = plan["spec"]["destination"].rstrip("/")
for image in plan["spec"].get("images", []):
    name = image.split("/", 1)[-1]
    print(f"{image} {dest}/{name}")
PY
)

printf '%s\n' "$PAIRS" | while read -r source destination; do
  [ -n "$source" ] || continue
  if [ "$DRY_RUN" = true ]; then
    echo "skopeo copy docker://$source docker://$destination"
  else
    skopeo copy "docker://$source" "docker://$destination"
  fi
done
