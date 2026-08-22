# KIKI Alpine Installer

This directory contains an MVP installer skeleton for bootstrapping KIKI nodes.
The intended flow is:

```text
Alpine installer boot
-> read /etc/kiki/install.yaml
-> partition and format the target disk
-> install Debian with debootstrap
-> configure hostname, network, and kiki-agent
-> install GRUB
-> reboot into a Debian controller or compute node
```

The Alpine image is only the installer runtime. The installed node OS is Debian.

## Layout

```text
installer/
  configs/
    install.example.yaml
    install.uefi.example.yaml
    images.example.yaml
    kikimachine.example.yaml
  dist/
    .gitignore
  bootstrap/
    README.md
  alpine/
    overlay/
      etc/kiki/install.yaml
      usr/local/bin/kiki-install
      usr/local/bin/kiki-install.py
    iso/
      Containerfile
      README.md
      run-mkimage.sh
      profiles/profile_kiki.sh
  scripts/
    build-alpine-iso.sh
    build-alpine-overlay.sh
    build_alpine_overlay.py
    install-debian-node.py
    mirror-images.sh
    render-install-config.py
    run-bootstrap-server.sh
    smoke-dry-run.sh
    test-qemu-install.sh
    upload-log-bundle.sh
  crds/
    kiki.io_kikiinstallconfigs.yaml
    kiki.io_kikimachines.yaml
```

## Alpine Runtime Packages

The installer runtime should include at least:

- `python3`
- `py3-yaml`
- `debootstrap`
- `parted`
- `sgdisk` from `gptfdisk`
- `e2fsprogs`
- `dosfstools`
- `util-linux`
- `grub`
- `grub-bios`
- `grub-efi`
- `efibootmgr`
- `mount`
- `openrc` or systemd-compatible tooling as required by the image build

Exact package names may vary by Alpine release and image profile.

## Build Overlay

From the repository root:

```bash
bash installer/scripts/build-alpine-overlay.sh
```

This writes:

```text
installer/dist/kiki-alpine-overlay.tar.gz
```

The tarball can be unpacked into an Alpine ISO/PXE build root.

## Build ISO

Build with Podman or Docker:

```bash
bash installer/scripts/build-alpine-iso.sh --runner podman --release v3.20
```

Preview the commands without network or package operations:

```bash
bash installer/scripts/build-alpine-iso.sh --runner podman --dry-run
```

ISO output is written under:

```text
installer/dist/iso/
```

See `installer/alpine/iso/README.md` for local Alpine build instructions.

## Pinned kernels

KIKI image builds intentionally fail instead of silently selecting a newer
kernel. The transient Alpine v3.20 ISO/PXE environment is pinned to
`linux-lts=6.6.139-r0` in `profile_kiki.sh`. Installed Debian Bookworm nodes
are pinned to `linux-image-6.1.0-51-amd64=6.1.177-1`; the installer obtains it
from the configured `bookworm-security` mirror, marks the package as held, and
verifies the installed version with `dpkg-query` before installing GRUB.

For production reproducibility, point both the Alpine repositories and Debian
`mirror`/`securityMirror` fields at version-retaining internal snapshots. A
kernel security update is an explicit release change: update the package and
version constants, rebuild and sign ISO/PXE/disk artifacts, run BIOS/UEFI and
GPU acceptance tests, then promote the artifacts through InfraOps.

## QEMU Test

After building an ISO, boot it in a BIOS VM:

```bash
bash installer/scripts/test-qemu-install.sh --iso installer/dist/iso/kiki.iso --mode bios --dry-run
```

UEFI dry-run:

```bash
bash installer/scripts/test-qemu-install.sh --iso installer/dist/iso/kiki.iso --mode uefi --dry-run
```

## Dry Run

Use dry-run first. It prints the commands that would be executed without
changing disks:

```bash
installer/scripts/install-debian-node.py --config installer/configs/install.example.yaml --dry-run
```

Inside the Alpine installer environment:

```bash
kiki-install --dry-run
```

Run the BIOS and UEFI dry-run matrix:

```bash
bash installer/scripts/smoke-dry-run.sh
```

## Real Install

Real installation is destructive and requires `--yes`:

```bash
kiki-install --yes
```

By default the installer reads:

```text
/etc/kiki/install.yaml
```

## Current MVP Scope

Implemented in this skeleton:

- YAML config loading and required-field validation
- dry-run mode
- explicit `--yes` guard for destructive installation
- BIOS and UEFI partition plans
- ext4 root filesystem creation
- Debian rootfs installation with debootstrap
- hostname and hosts file generation
- systemd-networkd DHCP configuration
- `/etc/kiki/node.yaml` generation
- boot-time `kiki-agent` registration and heartbeat script
- `kiki-agent.service` systemd unit
- optional Kubernetes package bootstrap unit
- installer-time management API status callback
- `KikiInstallConfig` and `KikiMachine` CRD manifests
- SSH and kiki-agent enablement
- GRUB installation
- cleanup and unmount handling

Still needed:

- Production kiki-agent binary or package
- UEFI and BIOS VM install tests
- Controller reconciliation for `KikiMachine` and `KikiInstallConfig`

## Management API Contract

Run the Go bootstrap management API and dashboard:

```bash
go run ./cmd/kiki-bootstrapd \
  -host 0.0.0.0 \
  -port 8088 \
  -require-token \
  -admin-token-file /run/secrets/kiki/bootstrap-admin-token
```

During install, the Alpine installer sends best-effort JSON callbacks to:

```text
{spec.agent.managementUrl}{spec.agent.callbackPath}
```

The default path is:

```text
/api/v1/nodes/register
```

The installed Debian node then runs `kiki-agent.service`, which posts a booted
registration event and optional heartbeats. Callback failures are warnings so a
temporary management API outage does not brick the install.

The first successful callback exchanges the one-time registration token for a
node-bound bearer token. The installer writes only that node token to the
installed system. If the management API is temporarily unavailable, the first
boot agent performs the exchange and atomically replaces the one-time token.
Subsequent registrations, heartbeats, logs, and log bundles use the node token
in the HTTP `Authorization` header.

For production deployments, prefer `spec.agent.registrationTokenFile` over a
literal token in YAML.

## Kubernetes Bootstrap

Set:

```yaml
spec:
  bootstrap:
    installKubernetesTools: true
    kubernetesVersion: "1.30"
    joinCommand: "kubeadm join ..."
```

The installer writes `kiki-bootstrap-kubernetes.service` into the target Debian
system. It installs `kubelet`, `kubeadm`, and `kubectl`, then optionally runs the
provided join command.

For the current bootstrap-node-only path, leave `installKubernetesTools: false`.
The installer can still configure containerd registry mirrors and pre-pull
bootstrap images.

## NVIDIA GPU Nodes

Set `spec.accelerators.nvidia.enabled: true` only on NVIDIA compute nodes. The
installer then requires an HTTPS repository and key URL, the expected key
SHA-256, exact driver/toolkit package versions, and a digest-pinned device
plugin image. It writes a first-boot unit that installs the pinned packages,
configures containerd with `nvidia-ctk`, restarts containerd, and verifies the
result with `nvidia-smi` before creating its completion marker.

The node is labeled `kiki.io/accelerator=nvidia` and
`kiki.io/runtime-vllm=true` through kubelet configuration. The generated device
plugin DaemonSet selects only those nodes. Its manifest is stored at:

```text
/etc/kiki/manifests/nvidia-device-plugin.yaml
```

Apply that manifest from the InfraOps/controller trust boundary. Compute nodes
do not receive cluster-admin credentials merely to install the plugin.

## Image Mirrors

Configure pull-through mirrors in `install.yaml`:

```yaml
spec:
  images:
    mirrors:
      - registry: registry.k8s.io
        endpoint: https://registry-mirror.local/registry.k8s.io
    prePull:
      - registry.k8s.io/pause:3.9
```

This writes containerd `hosts.toml` mirror config under:

```text
/etc/containerd/certs.d/<registry>/hosts.toml
```

If `prePull` is set, the installed node enables `kiki-prepull-images.service`.

Mirror a plan with `skopeo`:

```bash
bash installer/scripts/mirror-images.sh --dry-run installer/configs/images.example.yaml
```

## Render Node Configs

Generate per-node configs from the example template:

```bash
python3 installer/scripts/render-install-config.py \
  --hostname kiki-node-002 \
  --role compute \
  --boot-mode uefi \
  --management-url http://bootstrap.local:8088 \
  --output installer/dist/kiki-node-002.install.yaml
```

## Dashboard And Diagnostics

The dashboard shows nodes, phases, heartbeats, events, image plans, and
artifact indexes, uploaded log bundles, and diagnostic summaries. Diagnostics are rule-based by default. If
`KIKI_LLM_COMMAND` is set, the server sends a read-only prompt to that command
and stores its text response as a diagnostic note.

## Log Bundles

Upload an installer/node diagnostic bundle to bootstrapd:

```bash
bash installer/scripts/upload-log-bundle.sh \
  --node kiki-node-001 \
  --server http://bootstrap.local:8088 \
  --token-file /etc/kiki/registration-token
```
