# kiki-agent Stage 3 commands

The Go `kiki-agent` keeps the existing inventory and InfraOps reporting commands
and adds the guarded Stage 3 configuration path. The distribution package
installs it as `/usr/libexec/kiki-agent-stage3`; the compatible Python
`/usr/bin/kiki-agent` delegates the Stage 3 subcommands to that binary.

## Merge and reconcile

Configuration layers are merged in this order:

1. `/usr/share/kiki/defaults/*.yaml`
2. `/usr/share/kiki/profiles/<role>.yaml`
3. `/var/lib/ki2/install-plan.yaml`
4. `/etc/kiki/overrides/*.yaml`
5. one-shot command flags

Maps merge by key, ordinary lists replace earlier lists, and a list can append
explicitly with `{merge_strategy: append, items: [...]}`. The merged plan is
written with mode `0600`; plaintext token/password/private-key fields are
redacted while secret references remain.

```bash
kiki-agent kube reconcile --dry-run \
  --token-file /run/secrets/kubeadm-token \
  --endpoint 10.0.0.10:6443 \
  --ca-cert-hash sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

Join refuses missing endpoints, token references, invalid CA hashes, and
control-plane joins without an explicit certificate policy. CRI socket
preflight is enabled by default. `--skip-preflight` is reserved for image and
target-rootfs validation.

CNI is disabled by default. When explicitly enabled, only providers in the
configured allowlist can run and a manifest URL, manifest path, or package must
be supplied. Dry-run reports the CNI command without applying it.

## Remote install plan

The remote plan is downloaded to a quarantine path and promoted only after its
SHA-256 digest or Ed25519 signature verifies:

```bash
kiki-agent plan fetch \
  --url https://repo.example/kiki/install-plan.yaml \
  --sha256 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

For signature-based bootstrapping, sign the exact YAML bytes and install only
the public key on the target:

```bash
kiki-agent plan fetch \
  --url https://repo.example/kiki/install-plan.yaml \
  --signature https://repo.example/kiki/install-plan.yaml.sig \
  --public-key /etc/kiki/trust/install-plan.ed25519.pub
```

The signature value may also be `base64:<signature>`, `@/path/to/plan.sig`, or
a `file://` URL. If both SHA-256 and a signature are supplied, both checks must
pass. The private key never belongs on an installed node.

With no `--url`, the command reads `kiki.plan.url`, `kiki.plan.sha256`, and
`kiki.plan.signature` from `/proc/cmdline`. Unverified plans are rejected unless
the operator passes the explicit `--allow-unverified` safety override.
