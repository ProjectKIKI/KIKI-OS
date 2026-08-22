#!/usr/bin/env bash
set -euo pipefail

cd "${KIKI_WORKDIR:-/work}"

jobs="${KIKI_JOBS:-$(nproc)}"
port="${KIKI_PORT:-8090}"
toolchain_id="${KIKI_TOOLCHAIN_ID:-container-rocky9-stage0-gcc11-v1}"
artifact_root="${KIKI_ARTIFACT_ROOT:-/work/build/ki2ci}"
publish_dir="${KIKI_PUBLISH_DIR:-/work/dist/publish}"

if [[ "${1:-serve}" == "serve" ]]; then
  exec python3 tools/ki2ci.py serve \
    --host 0.0.0.0 \
    --port "${port}" \
    --artifact-root "${artifact_root}" \
    --publish-dir "${publish_dir}" \
    --jobs "${jobs}" \
    --toolchain-id "${toolchain_id}"
fi

if [[ "${1:-}" == "run" ]]; then
  shift
  exec python3 tools/ki2ci.py run \
    --artifact-root "${artifact_root}" \
    --publish-dir "${publish_dir}" \
    --jobs "${jobs}" \
    --toolchain-id "${toolchain_id}" \
    "$@"
fi

if [[ "${1:-}" == "shell" ]]; then
  exec /bin/bash
fi

exec "$@"
