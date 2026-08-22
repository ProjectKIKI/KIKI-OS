# kiki-infraopsd

`kiki-infraopsd` is the authenticated KIKI InfraOps management API and minimal
web console. It stores prototype state atomically in a mode `0600` JSON file.

## Run

All runtime and builder images are immutable digest references. Builds require
an allow-listed Git host and a controlled egress proxy whose CIDR is rendered
into the per-build NetworkPolicy.

```bash
kiki-infraopsd \
  -host 0.0.0.0 \
  -port 8090 \
  -state /var/lib/kiki/infraops-state.json \
  -token-file /run/secrets/kiki/infraops-token \
  -llama-image registry.local/kiki/llama@sha256:<digest> \
  -vllm-image registry.local/kiki/vllm@sha256:<digest> \
  -git-image registry.local/kiki/git@sha256:<digest> \
  -bos-builder-image registry.local/kiki/bos-builder@sha256:<digest> \
  -buildctl-image registry.local/kiki/buildctl@sha256:<digest> \
  -supply-chain-image registry.local/kiki/supply-chain@sha256:<digest> \
  -allowed-git-hosts git.example.com \
  -allowed-registries registry.example.com \
  -build-egress-proxy http://egress-proxy.kiki-system.svc:8080 \
  -build-egress-proxy-cidr 10.20.0.10/32 \
  -buildkit-address tcp://buildkitd.kiki-build.svc:1234 \
  -buildkit-cidr 10.30.0.20/32 \
  -buildkit-port 1234 \
  -registry-auth-secret registry-auth \
  -signing-secret artifact-signing
```

API requests require both headers:

```text
Authorization: Bearer <token>
X-Kiki-Actor: <audited principal>
```

## API

- `PUT /api/v1/nodes/{name}/inventory`
- `GET /api/v1/nodes`
- `POST|GET /api/v1/models`
- `POST|GET /api/v1/model-deployments`
- `POST|GET /api/v1/builds`
- `PUT /api/v1/builds/{id}/result`
- `GET /api/v1/artifacts`
- `GET /api/v1/audit`

The BOS and OCI/CPM build lifecycle is strictly ordered from `Queued` through fetching,
validation, build, test, scan, signing, and publishing. A successful result is
accepted only when the artifact, SBOM, provenance, and signature all have
SHA-256 digests.

OCI/CPM builds use a restricted `buildctl` client Pod and a separately managed
BuildKit service. The Pod has no Docker socket or host mount. Its NetworkPolicy
permits DNS, the configured egress proxy, and the configured BuildKit CIDR only.
The `kiki-supplychain` finalizer runs Syft, Grype, and Cosign without a shell,
creates SLSA v1 provenance, and reports digests for every evidence file.
