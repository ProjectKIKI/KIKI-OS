# ADR 0001: KIKI InfraOps, model runtime, and build architecture

- Status: Accepted
- Date: 2026-07-31

## Context

KIKI-OS must support ordinary Kubernetes nodes, CPU and GPU LLM inference,
declarative infrastructure operations, and web-triggered artifact builds. These
features have different privilege and availability requirements. Treating the
bootstrap API, node runtime, and build system as one daemon would give routine
workloads unnecessary host access and make recovery depend on the component
being recovered.

## Decision

KIKI uses four planes with explicit trust boundaries.

### Host plane

The host contains only what is required before Pods can run or when Kubernetes
is unavailable:

- kernel, systemd, networking, storage mounts, and device drivers;
- containerd and kubelet;
- vendor GPU container-runtime integration;
- a minimal bootstrap and recovery agent.

The recovery agent does not execute arbitrary remote shell commands. It accepts
only versioned, allow-listed operations with an idempotency key and expiry.

### Node workload plane

Ordinary node services run as Pods:

- the operational part of `kiki-agent` as a DaemonSet;
- metrics and log collectors;
- `kiki-modeld`, llama.cpp, vLLM, and the inference gateway;
- user workloads and unprivileged build workers.

User namespaces enforce the Kubernetes Restricted Pod Security profile. Trusted
system workloads use a separate namespace and narrowly scoped service accounts.

### InfraOps control plane

`kiki-bootstrapd` remains responsible for installation and initial registration.
The long-lived InfraOps API owns inventory, desired state, tasks, approvals,
audit records, model deployments, build records, and artifact promotion.
Controllers reconcile desired state; API handlers do not directly mutate hosts.

### Build plane

Builds are immutable jobs. Rootless workers build BOS and OCI artifacts. ISO,
PXE, and disk images run on tainted, dedicated image-factory nodes or disposable
VMs because they may require mounts, loop devices, bootloader installation, or
QEMU/KVM. Build workers cannot schedule ordinary workloads.

Every published artifact is addressed by digest. Release promotion requires a
successful policy result and records source revision, builder identity, logs,
test results, SBOM, provenance, and signature references.

## Resource identity

- `Machine` is a desired physical or virtual machine.
- `Node` is an observed KIKI-OS instance registered by the agent.
- `Machine.status.nodeRef` associates the desired machine with an observed node.
- `Task` is a finite, typed, idempotent operation assigned to a node.
- `Model` identifies immutable model content and its license/format metadata.
- `ModelDeployment` declares placement, runtime, resources, and endpoint policy.
- `Build` is one immutable build attempt from a pinned source revision.
- `Artifact` is immutable content; channels such as `development` and `release`
  are mutable references to approved artifact digests.

## Runtime selection

Runtime selection is deterministic and explainable:

1. A compatible GPU with sufficient memory selects a supported vLLM profile.
2. A GPU unsupported by vLLM may select a llama.cpp offload profile.
3. A CPU with sufficient RAM selects a llama.cpp GGUF profile.
4. Insufficient or incompatible resources leave the deployment Pending with a
   machine-readable condition. The controller never silently selects a model
   with a different identity or quantization.

All inference runtimes are exposed through an internal OpenAI-compatible
gateway. InfraOps diagnostics are read-only consumers and retain the existing
rule-based fallback.

## Task safety invariants

Every node task has:

- an immutable UUID and idempotency key;
- a typed action and schema-validated parameters;
- target node, creator, creation time, and expiry;
- required approval class;
- desired, observed, and terminal state;
- bounded execution time and output size;
- an append-only audit trail.

The protocol has no generic `shell`, `command`, or executable-script action.
Destructive operations require explicit approval and cannot be generated or
approved by the same principal.

## Consequences

Kubernetes failure does not remove the minimal recovery path. Most functionality
can still be upgraded as Pods. Privileged image builds are isolated from general
nodes. The separation introduces more APIs, but those APIs provide stable
boundaries for the web portal, CLI, controllers, and future storage backends.
