# KIKI deployment boundaries

`kubernetes/base` deploys the Pod-oriented normal-node plane: InfraOps, its
model Pod reconciler, and the read-only inventory DaemonSet. Replace every
`registry.invalid` digest with a verified release digest before applying and
create `kiki-infraops-auth` with distinct `admin-token`, `agent-token`, and
`factory-token` keys. Reusing one value defeats the API role boundary.
Add a distinct `build-token` key for trusted supply-chain result reporters.

Before deployment, replace the example Git/source-archive/registry allowlists, proxy URL and
CIDR, BuildKit address and CIDR, and every zero digest. Provide an externally
managed rootless BuildKit endpoint plus `kiki-registry-auth`,
`kiki-artifact-signing`, and the `build-artifacts` PVC in `kiki-build`. These
environment-specific resources are intentionally not created with placeholder
credentials or an assumed storage class.

The digest-pinned `bos-builder` image is a build profile rather than a generic
shell image. It must contain `/usr/local/bin/bosbuild`,
`/usr/local/bin/kiki-bos-recipe`, and `/usr/local/bin/kiki-bos-deps`. Its
`/etc/kiki/bos-build-capabilities.json` lists the build dependencies already
present in that immutable image. A Recipe request fails when `build_requires`
asks for a capability outside that list; dependencies are never installed from
an unapproved repository during a build.

The web UI creates one `.bos` artifact per Recipe request. Recipe source input
is a credential-free HTTPS `tar.gz` URL plus an exact SHA-256. The builder
rejects path traversal, links, undeclared output files, source hash mismatches,
and source hosts outside `-allowed-source-hosts`. Existing Git package trees
remain available as an advanced build mode.

The `kiki-system` namespace is privileged only because the inventory DaemonSet
uses host PID visibility and a read-only machine-id mount. Model runtime Pods
belong in the Restricted `kiki-models` namespace. User workloads must not be
scheduled into `kiki-system`.

`image-factory/kiki-image-factory.service` is intentionally not a normal-node
Pod. Install it only inside a disposable VM or on a dedicated host with KVM,
Podman, xorriso, QEMU/OVMF, Syft, Grype, and Cosign. The host must not join the
general workload pool. Its factory token has only Image Factory claim/result
permissions; the signing key and token remain separate root-managed files.

InfraOps is a ClusterIP service. Expose it through your authenticated TLS
Gateway/Ingress and label only the gateway namespace
`kiki.io/infraops-client=true`; the NetworkPolicy otherwise limits port 8090
to the system plane and node agents.

Example secret creation (supply real random values through your secret
manager, not shell history):

```sh
kubectl -n kiki-system create secret generic kiki-infraops-auth \
  --from-file=admin-token=/secure/admin-token \
  --from-file=agent-token=/secure/agent-token \
  --from-file=factory-token=/secure/factory-token \
  --from-file=build-token=/secure/build-token
kubectl -n kiki-build create secret generic kiki-build-reporter \
  --from-file=build-token=/secure/build-token
```
