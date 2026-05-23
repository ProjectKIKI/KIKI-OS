# KIKI OS Seed Build System

This directory contains the first independent KIKI OS build plan. It is
systemd-based, glibc-based, and intentionally capped at 40 seed packages.

The goal of this pass is not full self-hosting yet. The goal is a reproducible
pipeline:

```text
recipes -> dependency plan -> cached build keys -> .ki2 packages -> repo index -> rootfs
```

## Layout

```text
distro/
  recipes/core.toml              40-package seed catalog
  profiles/bootstrap-stage1.toml validated pre-systemd package/rootfs set
  profiles/minimal-systemd.toml  bootable server-node target
  profiles/world.toml            every seed package
  builders/rocky9-wsl-deps.sh    phase-0 Rocky/WSL builder dependency setup
  sources/                       local source trees copied into packages
tools/
  ki2build.py                    build/repo/rootfs orchestrator
```

## Seed Scope

The seed catalog contains exactly 40 packages:

- kernel and base ABI: `linux`, `linux-headers`, `glibc`
- systemd runtime: `systemd`, `dbus`, `kmod`, `util-linux`, `libcap`,
  `libseccomp`, `acl`, `attr`
- shell/userland/archive tools: `bash`, `busybox`, `coreutils`, `findutils`,
  `grep`, `sed`, `gawk`, `tar`, `gzip`, `xz`, `zstd`
- networking and remote access: `iproute2`, `openssl`, `ca-certificates`,
  `openssh`, `curl`
- bootstrap build tools kept as packages for later self-hosting:
  `make`, `pkgconf`, `meson`, `ninja`, `python`, `perl`
- KIKI integration: `base-files`, `ki2ctl`, `kiki-agent`

`containerd`, `runc`, Kubernetes tools, initramfs generation, signed repo
metadata, and full self-hosting are intentionally phase 2.

## Commands

Validate the catalog and enforce the 40 package cap:

```bash
python tools/ki2build.py validate --profile distro/profiles/world.toml --max-packages 40
```

Show the runtime plan for the minimal systemd image:

```bash
python tools/ki2build.py plan --profile distro/profiles/minimal-systemd.toml
```

Show the build plan including build-time target inputs:

```bash
python tools/ki2build.py plan --profile distro/profiles/world.toml --include-build-deps
```

Dry-run the minimal build:

```bash
python tools/ki2build.py build --profile distro/profiles/minimal-systemd.toml --dry-run
```

Build packages when sources are pinned and the Linux builder environment is
ready:

```bash
python tools/ki2build.py build \
  --profile distro/profiles/minimal-systemd.toml \
  --toolchain-id x86_64-linux-gnu-v1
```

Generate a repository index:

```bash
python tools/ki2build.py repo-index
```

Assemble a rootfs from built packages:

```bash
python tools/ki2build.py rootfs \
  --profile distro/profiles/minimal-systemd.toml \
  --rootfs-dir dist/rootfs/minimal-systemd
```

Assemble the currently validated stage-1 rootfs:

```bash
python tools/ki2build.py rootfs \
  --profile distro/profiles/bootstrap-stage1.toml \
  --rootfs-dir dist/rootfs/bootstrap-stage1
```

## Build Cache Model

Each package build key is derived from:

- normalized recipe content
- architecture
- toolchain ID
- dependency build keys

If the key and package artifact match the saved build state, the package is
skipped. This is the first piece that prevents recompiling everything on every
run.

Each `.ki2` package also carries dependency metadata in `manifest.json`:

```json
"dependencies": {
  "build": ["linux-headers"],
  "runtime": ["glibc"]
}
```

The repository index preserves the same shape so a later `ki2ctl install`
command can resolve runtime dependencies without unpacking every package.

## Cross-Compile Position

This seed assumes a Linux builder container or VM supplies the phase-0 host
toolchain. The target packages are still recipe-managed, but host tools such as
`make`, `meson`, and `ninja` are captured by `--toolchain-id` during this phase.

The next step is to add explicit builder containers:

```text
builder/x86_64 -> builds x86_64 packages natively
builder/aarch64 -> builds under QEMU or native ARM runner
```

Once those are reliable, KIKI can move toward a two-stage bootstrap and later
self-hosting.

## Current Build Status

The Rocky 9 WSL builder has produced a real `.ki2` repository for the
pre-systemd stage:

- package artifacts: 17 in `dist/ki2/packages/x86_64`
- repository index: `dist/ki2/repo/index.x86_64.json`
- verified rootfs profile: `distro/profiles/bootstrap-stage1.toml`

The successful set currently includes `linux`, `glibc`, `zlib`, `expat`,
`openssl`, `attr`, `libcap`, `libseccomp`, `acl`, `util-linux`, `xz`, `zstd`,
`kmod`, `dbus`, `ca-certificates`, `base-files`, and `linux-headers`.

`systemd` configures and starts compiling, but the native Rocky builder hits a
known bootstrap boundary: KIKI's sysroot headers are newer than the host libc
used for linking, so symbols such as `__isoc23_strtoul` are referenced by the
headers but not provided by the host. The right fix is the next bootstrap
milestone: build and use a real target sysroot toolchain instead of mixing KIKI
headers with the host libc.

To reproduce the current WSL builder dependency setup:

```bash
bash distro/builders/rocky9-wsl-deps.sh
```

## Source Pinning

Some upstream source hashes are currently marked `TODO`. Real builds refuse
unpinned sources unless `--allow-unpinned` is passed. The intended workflow is:

```text
fetch upstream source
verify it manually
write sha256 into distro/recipes/core.toml
commit recipe hash update
build packages
```

This keeps the seed system honest while the recipe set is still moving quickly.
