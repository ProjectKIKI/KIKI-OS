# AOS(KIKI Arte Operating System) Packaging System v0.0.3

This repository contains a minimal, **executable** prototype of the AOS
packaging tools:

- `bosctl`: BaseOS package manager
- `cpmctl`: Container package manager
- `bosbuild`: BOS package archive builder
- `tools/ki2build.py`: early KIKI OS recipe builder and rootfs assembler

## KIKI OS seed build system

The independent-distro work starts under `distro/` with a 40-package
systemd/glibc seed catalog and a small Python build orchestrator.

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 40
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --dry-run
python tools/ki2build.py rootfs --profile distro/profiles/bootstrap-stage1.toml --rootfs-dir dist/rootfs/bootstrap-stage1
```

Current WSL/Rocky builder smoke status: 17 real `.ki2` artifacts and a
verified pre-systemd `bootstrap-stage1` rootfs have been produced. `systemd`
now reaches compile/link and needs the next step: a real target sysroot
toolchain, so KIKI headers are not mixed with the host libc.

See `distro/README.md` for the package scope, cache model, build status, and
next bootstrap steps.

## Build

From the project root:

```bash
go mod tidy

go build -o bosctl ./cmd/bosctl
go build -o cpmctl ./cmd/cpmctl
go build -o bosbuild ./cmd/bosbuild

go test ./cmd/... ./internal/...
```

## BOS (BaseOS) local DB usage

```bash
./bosctl init
./bosctl add baseos 0.0.1 x86_64 "Base OS core" 1
./bosctl add kernel 5.15.130 x86_64 "Linux kernel" 1 --deps baseos

./bosctl list
./bosctl info baseos
./bosctl remove kernel
```

This uses a JSON DB under `${HOME}/.bosctl/bosdb.json`.

## CPM (Container packages) local DB usage

```bash
./cpmctl init
./cpmctl add nginx 1.25.0 registry.example.com/aos/nginx:1.25.0 "NGINX web server"
./cpmctl list
./cpmctl info nginx
./cpmctl remove nginx
```

DB path: `${HOME}/.cpmctl/cpmdb.json`.

## BOS package build

`bosbuild` creates a `.bos` package from a work directory containing a
top-level `manifest.yaml` file and optional `rootfs/` and `scripts/`
directories:

```bash
bosbuild -C ./workdir -o kernel-5.15.130-1.x86_64.bos
```

Example layout:

```text
workdir/
  manifest.yaml
  rootfs/
    usr/
    lib/
  scripts/
    post-install.sh
```

The builder writes to a temporary file before moving the package into place and
skips the output file when the target path is inside the source work directory.

## BOS HTTP repository index generation

`bosctl` can generate an `index.yaml` for a directory that contains `.bos`
packages. Each `.bos` file is assumed to be a `tar.gz` archive containing
a top-level `manifest.yaml` file with at least:

```yaml
name: kernel
version: "5.15.130"
release: "1"
arch: "x86_64"
summary: Linux kernel
dependencies:
  runtime:
    - baseos
  build:
    - gcc
    - make
```

Example layout:

```text
/var/www/bos-repo/
  kernel-5.15.130-1.x86_64.bos
  baseos-0.0.1-1.x86_64.bos
```

Generate `index.yaml`:

```bash
bosctl repo-index /var/www/bos-repo
```

This will create `/var/www/bos-repo/index.yaml` with SHA-256 digests
for each `.bos` file and any package dependencies declared in its manifest.

Preview the runtime dependency install order for a package:

```bash
bosctl plan /var/www/bos-repo kernel
```

## Notes

- This is an early prototype (v0.0.3) focusing on:
  - Local DB management for BOS/CPM
  - BOS package archive building
  - HTTP repo index generation for BOS (`index.yaml`)
- Actual installation of BOS packages into a real rootfs and podman/systemd
  integration for CPM are planned as later steps.
