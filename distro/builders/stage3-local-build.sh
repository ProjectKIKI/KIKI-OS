#!/usr/bin/env bash
# Rocky 9 (including WSL2) Stage 3 build entry point. Run from any directory.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
plan="distro/build-plans/stage3-server-core.yaml"
mode="${1:-check}"
jobs="${KIKI_BUILD_JOBS:-$(nproc)}"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "Stage 3 local builder requires x86_64" >&2
  exit 2
fi
if ! command -v python3 >/dev/null; then
  echo "python3 is required; see distro/builders/rocky9-wsl-deps.sh" >&2
  exit 2
fi
if [[ ! -f "$repo_root/$plan" ]]; then
  echo "Missing Stage 3 build plan: $repo_root/$plan" >&2
  exit 2
fi
cd "$repo_root"
case "$mode" in
  deps)
    exec bash distro/builders/rocky9-wsl-deps.sh
    ;;
  check)
    python3 tools/ki2build.py validate --profile distro/profiles/server-core.toml --max-packages 72
    exec python3 tools/ki2osbuild.py plan --build-plan "$plan" --jobs "$jobs"
    ;;
  build)
    exec python3 tools/ki2osbuild.py run --build-plan "$plan" --jobs "$jobs"
    ;;
  iso)
    exec python3 tools/ki2osbuild.py run --build-plan "$plan" --jobs "$jobs" --iso
    ;;
  *)
    echo "Usage: $0 {check|deps|build|iso}" >&2
    exit 2
    ;;
esac
