# AOS(KIKI Arte Operating System) Packaging System v0.0.3

This repository contains a minimal, **executable** prototype of the AOS
packaging tools:

- `bosctl`: BaseOS package manager
- `cpmctl`: Container package manager

## Build

From the project root:

```bash
go mod tidy

go build -o bosctl ./cmd/bosctl
go build -o cpmctl ./cmd/cpmctl
```

## BOS (BaseOS) local DB usage

```bash
./bosctl init
./bosctl add baseos 0.0.1 x86_64 "Base OS core" 1
./bosctl add kernel 6.1.177 x86_64 "Linux kernel example (not the image pin)" 1

./bosctl list
./bosctl info baseos
```

This uses a JSON DB under `${HOME}/.bosctl/bosdb.json`.

## CPM (Container packages) local DB usage

```bash
./cpmctl init
./cpmctl add nginx 1.25.0 registry.example.com/aos/nginx:1.25.0 "NGINX web server"
./cpmctl list
./cpmctl info nginx
```

DB path: `${HOME}/.cpmctl/cpmdb.json`.

## BOS HTTP repository index generation

`bosctl` can generate an `index.yaml` for a directory that contains `.bos`
packages. Each `.bos` file is assumed to be a `tar.gz` archive containing
a top-level `manifest.yaml` file with at least:

```yaml
name: kernel
version: "5.15.130"
release: "1"
arch: "x86_64"
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
for each `.bos` file.

## Notes

- This is an early prototype (v0.0.3) focusing on:
  - Local DB management for BOS/CPM
  - HTTP repo index generation for BOS (`index.yaml`)
- Actual installation of BOS packages into a real rootfs and podman/systemd
  integration for CPM are planned as later steps.
