#!/usr/bin/env bash
set -euo pipefail

sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --set-enabled crb

sudo dnf install -y \
  gcc gcc-c++ make cmake meson ninja-build pkgconf-pkg-config \
  golang perl python3 python3-devel python3-pip python3-tomli python3-jinja2 \
  curl tar gzip xz bzip2 patch diffutils findutils file git \
  openssl-devel zlib-devel expat-devel libcap-devel libseccomp-devel \
  libacl-devel libattr-devel bison flex gawk gettext gperf \
  bc elfutils-libelf-devel ncurses-devel rsync

echo "Rocky 9 WSL builder dependencies are installed."
