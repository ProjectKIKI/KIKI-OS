#!/usr/bin/env python3
"""Stage 2 readiness checks for KIKI OS.

This tool verifies the Kubernetes/runtime contracts that are easy to regress
while Stage 2 is still moving from placeholder payloads to source-backed
packages.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))
import ki2build  # type: ignore  # noqa: E402


class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


KUBE_COMMON = {
    "cni-plugins",
    "cri-tools",
    "kubelet",
    "kubeadm",
    "kubectl",
    "kiki-kubeadm",
    "conntrack-tools",
    "iptables",
    "nftables",
    "bridge-utils",
    "socat",
    "ethtool",
    "chrony",
}
CRIO_PACKAGES = {"cri-o", "conmon", "crun", "kube-node-config"}
CONTAINERD_PACKAGES = {"containerd", "runc", "kube-node-config-containerd"}
KUBEADM_CONFIG_API = "kubeadm.k8s.io/v1beta4"
KUBEADM_LOCAL_CONFIG = "/etc/kubernetes/kiki/kubeadm.local.yaml"
KUBEADM_TEMPLATES = (
    "/etc/kubernetes/kiki/kubeadm-init.yaml",
    "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml",
    "/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
)
KUBEADM_CONFIG_PACKAGES = ("kube-node-config", "kube-node-config-containerd")
NETWORK_USERSPACE_PACKAGES = (
    "conntrack-tools",
    "nftables",
    "iptables",
    "firewalld",
    "bridge-utils",
    "socat",
    "ethtool",
    "chrony",
    "kiki-netconfig",
)

FORBIDDEN_HOST_LDD_CORE_RUNTIME_PATHS = {
    "/lib/ld-linux-x86-64.so.2",
    "/lib/ld-linux.so.2",
    "/lib/libanl.so.1",
    "/lib/libc.so.6",
    "/lib/libc_malloc_debug.so.0",
    "/lib/libcrypt.so.1",
    "/lib/libcrypt.so.2",
    "/lib/libdl.so.2",
    "/lib/libm.so.6",
    "/lib/libmvec.so.1",
    "/lib/libnsl.so.1",
    "/lib/libpthread.so.0",
    "/lib/libresolv.so.2",
    "/lib/librt.so.1",
    "/lib/libthread_db.so.1",
    "/lib/libutil.so.1",
    "/lib64/ld-linux-x86-64.so.2",
    "/lib64/libanl.so.1",
    "/lib64/libc.so.6",
    "/lib64/libc_malloc_debug.so.0",
    "/lib64/libcrypt.so.1",
    "/lib64/libcrypt.so.2",
    "/lib64/libdl.so.2",
    "/lib64/libm.so.6",
    "/lib64/libmvec.so.1",
    "/lib64/libnsl.so.1",
    "/lib64/libpthread.so.0",
    "/lib64/libresolv.so.2",
    "/lib64/librt.so.1",
    "/lib64/libthread_db.so.1",
    "/lib64/libutil.so.1",
}

PROFILE_SPECS = [
    ("kiki-kube-bootstrap", "cri-o"),
    ("kiki-kube-control", "cri-o"),
    ("kiki-kube-compute", "cri-o"),
    ("kiki-kube-bootstrap-containerd", "containerd"),
    ("kiki-kube-control-containerd", "containerd"),
    ("kiki-kube-compute-containerd", "containerd"),
]

INSTALL_PLAN_REQUIRED_SECTIONS = {
    "schema",
    "api_version",
    "kind",
    "mode",
    "source",
    "target",
    "identity",
    "network",
    "users",
    "packages",
    "services",
    "boot",
    "runtime",
    "kubernetes",
    "firewall",
    "artifacts",
}

INSTALL_PLAN_KUBEADM_FIELDS = {
    "config_api",
    "action",
    "config_template",
    "config_output",
    "command",
    "control_plane",
    "cri_socket",
}


@dataclass(frozen=True)
class BinarySmokeCommand:
    package: str
    path: str
    args: tuple[str, ...]
    contains: tuple[str, ...]


BINARY_SMOKE_COMMANDS = (
    BinarySmokeCommand("runc", "/usr/bin/runc", ("--version",), ("runc version 1.3.0",)),
    BinarySmokeCommand("containerd", "/usr/bin/containerd", ("--version",), ("containerd", "v2.1.0")),
    BinarySmokeCommand("conmon", "/usr/bin/conmon", ("--version",), ("conmon version 2.1.13",)),
    BinarySmokeCommand("crun", "/usr/bin/crun", ("--version",), ("crun version 1.23.1",)),
    BinarySmokeCommand("cri-o", "/usr/bin/crio", ("--version",), ("crio version 1.36.0",)),
    BinarySmokeCommand("cri-tools", "/usr/bin/crictl", ("--version",), ("crictl version v1.36.0",)),
    BinarySmokeCommand("cri-tools", "/usr/bin/critest", ("--version",), ("critest version: v1.36.0",)),
    BinarySmokeCommand("kubelet", "/usr/bin/kubelet", ("--version",), ("Kubernetes v1.36.1",)),
    BinarySmokeCommand("kubeadm", "/usr/bin/kubeadm", ("version", "-o", "short"), ("v1.36.1",)),
    BinarySmokeCommand("kubectl", "/usr/bin/kubectl", ("version", "--client=true"), ("Client Version: v1.36.1",)),
)


@dataclass(frozen=True)
class PayloadRequirement:
    paths: tuple[str, ...]
    contains: dict[str, tuple[str, ...]] = field(default_factory=dict)


PAYLOAD_REQUIREMENTS: dict[str, PayloadRequirement] = {
    "containerd": PayloadRequirement(
        paths=(
            "/usr/bin/containerd",
            "/usr/bin/ctr",
            "/usr/bin/containerd-shim-runc-v2",
            "/usr/lib/systemd/system/containerd.service",
            "/etc/containerd/config.toml",
        ),
        contains={
            "/etc/containerd/config.toml": ("SystemdCgroup = true", "io.containerd.runc.v2"),
            "/usr/lib/systemd/system/containerd.service": (
                "ExecStart=/usr/bin/containerd",
            ),
        },
    ),
    "runc": PayloadRequirement(paths=("/usr/bin/runc",)),
    "cri-o": PayloadRequirement(
        paths=("/usr/bin/crio", "/usr/bin/crio-status", "/usr/lib/systemd/system/crio.service"),
        contains={
            "/usr/lib/systemd/system/crio.service": (
                "ExecStart=/usr/bin/crio",
            )
        },
    ),
    "conmon": PayloadRequirement(paths=("/usr/bin/conmon",)),
    "crun": PayloadRequirement(paths=("/usr/bin/crun",)),
    "cni-plugins": PayloadRequirement(paths=("/opt/cni/bin/bridge", "/opt/cni/bin/host-local", "/opt/cni/bin/loopback", "/etc/cni/net.d/README")),
    "cri-tools": PayloadRequirement(paths=("/usr/bin/crictl", "/usr/bin/critest")),
    "kubelet": PayloadRequirement(
        paths=("/usr/bin/kubelet", "/usr/lib/systemd/system/kubelet.service"),
        contains={
            "/usr/lib/systemd/system/kubelet.service": (
                "ExecStart=/usr/bin/kubelet",
                "crio.service containerd.service",
            )
        },
    ),
    "kubeadm": PayloadRequirement(paths=("/usr/bin/kubeadm",)),
    "kubectl": PayloadRequirement(paths=("/usr/bin/kubectl",)),
    "kube-node-config": PayloadRequirement(
        paths=(
            "/etc/crictl.yaml",
            "/etc/crio/crio.conf.d/10-kiki.conf",
            "/etc/systemd/system/kubelet.service.d/10-kiki.conf",
            "/etc/modules-load.d/kiki-kubernetes.conf",
            "/etc/sysctl.d/90-kiki-kubernetes.conf",
            "/etc/cni/net.d/README",
            *KUBEADM_TEMPLATES,
        ),
        contains={
            "/etc/crictl.yaml": ("unix:///var/run/crio/crio.sock",),
            "/etc/crio/crio.conf.d/10-kiki.conf": ("cgroup_manager = \"systemd\"", "pause_image = \"registry.k8s.io/pause:3.10\""),
            "/etc/systemd/system/kubelet.service.d/10-kiki.conf": ("--container-runtime-endpoint=unix:///var/run/crio/crio.sock", "--cgroup-driver=systemd"),
            "/etc/kubernetes/kiki/kubeadm-init.yaml": (KUBEADM_CONFIG_API, "kind: InitConfiguration", "kind: ClusterConfiguration", "criSocket: unix:///var/run/crio/crio.sock"),
            "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml": (KUBEADM_CONFIG_API, "kind: JoinConfiguration", "controlPlane:", "criSocket: unix:///var/run/crio/crio.sock"),
            "/etc/kubernetes/kiki/kubeadm-join-compute.yaml": (KUBEADM_CONFIG_API, "kind: JoinConfiguration", "criSocket: unix:///var/run/crio/crio.sock"),
        },
    ),
    "kube-node-config-containerd": PayloadRequirement(
        paths=(
            "/etc/crictl.yaml",
            "/etc/systemd/system/kubelet.service.d/10-kiki.conf",
            "/etc/modules-load.d/kiki-kubernetes.conf",
            "/etc/sysctl.d/90-kiki-kubernetes.conf",
            "/etc/cni/net.d/README",
            *KUBEADM_TEMPLATES,
        ),
        contains={
            "/etc/crictl.yaml": ("unix:///run/containerd/containerd.sock",),
            "/etc/systemd/system/kubelet.service.d/10-kiki.conf": (
                "--container-runtime-endpoint=unix:///run/containerd/containerd.sock",
                "--cgroup-driver=systemd",
            ),
            "/etc/kubernetes/kiki/kubeadm-init.yaml": (KUBEADM_CONFIG_API, "kind: InitConfiguration", "kind: ClusterConfiguration", "criSocket: unix:///run/containerd/containerd.sock"),
            "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml": (KUBEADM_CONFIG_API, "kind: JoinConfiguration", "controlPlane:", "criSocket: unix:///run/containerd/containerd.sock"),
            "/etc/kubernetes/kiki/kubeadm-join-compute.yaml": (KUBEADM_CONFIG_API, "kind: JoinConfiguration", "criSocket: unix:///run/containerd/containerd.sock"),
        },
    ),
    "kiki-kubeadm": PayloadRequirement(
        paths=("/usr/bin/kiki-kubeadm",),
        contains={
            "/usr/bin/kiki-kubeadm": (
                "kubeadm init",
                "kubeadm join",
                "join requires",
                "/var/lib/kiki/kubernetes/state.json",
            )
        },
    ),
}

NETWORK_USERSPACE_REQUIREMENTS: dict[str, PayloadRequirement] = {
    "conntrack-tools": PayloadRequirement(paths=("/usr/sbin/conntrack",)),
    "nftables": PayloadRequirement(
        paths=("/usr/sbin/nft", "/usr/lib/systemd/system/nftables.service", "/etc/nftables.conf"),
        contains={"/etc/nftables.conf": ("flush ruleset",)},
    ),
    "iptables": PayloadRequirement(paths=("/usr/sbin/iptables", "/usr/sbin/ip6tables", "/usr/sbin/iptables-save", "/usr/sbin/iptables-restore")),
    "firewalld": PayloadRequirement(paths=("/usr/sbin/firewalld", "/usr/bin/firewall-cmd", "/usr/lib/systemd/system/firewalld.service")),
    "bridge-utils": PayloadRequirement(paths=("/usr/sbin/brctl",)),
    "socat": PayloadRequirement(paths=("/usr/bin/socat",)),
    "ethtool": PayloadRequirement(paths=("/usr/sbin/ethtool",)),
    "chrony": PayloadRequirement(paths=("/usr/sbin/chronyd", "/usr/bin/chronyc", "/usr/lib/systemd/system/chronyd.service")),
    "kiki-netconfig": PayloadRequirement(
        paths=("/usr/bin/kiki-netconfig",),
        contains={"/usr/bin/kiki-netconfig": ("systemd-networkd", "render_networkd", "command_static")},
    ),
}


class Verifier:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.ok: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        if condition:
            self.ok.append(message)
        else:
            self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def flatten_package_sets(plan: dict[str, Any]) -> set[str]:
    package_sets = plan.get("package_sets", {})
    packages: set[str] = set()
    if isinstance(package_sets, dict):
        for values in package_sets.values():
            if isinstance(values, list):
                packages.update(str(value) for value in values)
    return packages


def install_plan(path: Path) -> dict[str, Any]:
    data = ki2build.read_structured_file(path)
    plan = data.get("install_plan")
    if not isinstance(plan, dict):
        raise ki2build.Ki2Error(f"{path}: expected install_plan mapping")
    return plan


def expected_runtime_packages(runtime: str) -> tuple[set[str], set[str], str, str]:
    if runtime == "containerd":
        return KUBE_COMMON | CONTAINERD_PACKAGES, CRIO_PACKAGES, "containerd.service", "crio.service"
    return KUBE_COMMON | CRIO_PACKAGES, CONTAINERD_PACKAGES, "crio.service", "containerd.service"


def expected_kubeadm_contract(profile_name: str, runtime: str) -> dict[str, Any]:
    cri_socket = "unix:///run/containerd/containerd.sock" if runtime == "containerd" else "unix:///var/run/crio/crio.sock"
    if "bootstrap" in profile_name:
        return {
            "role": "bootstrap-control-plane",
            "action": "init",
            "template": "/etc/kubernetes/kiki/kubeadm-init.yaml",
            "command": f"kubeadm init --config {KUBEADM_LOCAL_CONFIG}",
            "control_plane": True,
            "cri_socket": cri_socket,
        }
    if "control" in profile_name:
        return {
            "role": "control-plane",
            "action": "join",
            "template": "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml",
            "command": f"kubeadm join --config {KUBEADM_LOCAL_CONFIG}",
            "control_plane": True,
            "cri_socket": cri_socket,
        }
    return {
        "role": "compute",
        "action": "join",
        "template": "/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
        "command": f"kubeadm join --config {KUBEADM_LOCAL_CONFIG}",
        "control_plane": False,
        "cri_socket": cri_socket,
    }


def expected_kubeadm_contract_for_role(role: str, runtime: str) -> dict[str, Any]:
    profile_by_role = {
        "bootstrap-control-plane": "kiki-kube-bootstrap",
        "control-plane": "kiki-kube-control",
        "compute": "kiki-kube-compute",
    }
    profile = profile_by_role.get(role)
    if profile is None:
        raise ki2build.Ki2Error(f"unknown Kubernetes role {role!r}")
    if runtime == "containerd":
        profile += "-containerd"
    return expected_kubeadm_contract(profile, runtime)


def verify_stage2_install_plan(plan_path: Path, runtime: str, role: str, verifier: Verifier) -> None:
    verifier.check(plan_path.exists(), f"install plan exists: {plan_path}")
    if not plan_path.exists():
        return
    plan = install_plan(plan_path)
    expected = expected_kubeadm_contract_for_role(role, runtime)
    required, forbidden, required_service, forbidden_service = expected_runtime_packages(runtime)

    verifier.check(plan.get("schema") == "kiki-install-plan-v1", "install plan schema is kiki-install-plan-v1")
    verifier.check(plan.get("api_version") == "kiki.io/v1alpha1", "install plan API version is kiki.io/v1alpha1")
    verifier.check(plan.get("kind") == "InstallPlan", "install plan kind is InstallPlan")

    source = plan.get("source", {})
    verifier.check(isinstance(source, dict) and bool(source.get("repo_index")), "install plan source declares repository index")
    verifier.check(isinstance(source, dict) and source.get("channel") == "stage2-v2", "install plan source channel is stage2-v2")

    target = plan.get("target", {})
    filesystems = target.get("filesystems", {}) if isinstance(target, dict) else {}
    swap = filesystems.get("swap", {}) if isinstance(filesystems, dict) else {}
    verifier.check(isinstance(swap, dict) and swap.get("enabled") is False, "Kubernetes install plan disables swap by default")
    verifier.check(isinstance(swap, dict) and swap.get("policy") == "kubernetes-off", "Kubernetes install plan records Kubernetes swap policy")

    packages = plan.get("packages", {})
    selected_values = packages.get("selected", []) if isinstance(packages, dict) else []
    selected = {str(value) for value in selected_values} if isinstance(selected_values, list) else set()
    services = plan.get("services", {})
    enabled_values = services.get("enable", []) if isinstance(services, dict) else []
    enabled = {str(value) for value in enabled_values} if isinstance(enabled_values, list) else set()

    verifier.check(isinstance(packages, dict) and isinstance(packages.get("dependency_resolution"), bool), "install plan declares dependency resolution policy")
    verifier.check(required <= selected, f"install plan selected packages include {runtime} Kubernetes set")
    verifier.check(not (forbidden & selected), "install plan selected packages exclude opposite CRI set")
    verifier.check(required_service in enabled, f"install plan enables {required_service}")
    verifier.check("kubelet.service" in enabled, "install plan enables kubelet.service")
    verifier.check(forbidden_service not in enabled, f"install plan does not enable {forbidden_service}")

    runtime_plan = plan.get("runtime", {})
    verifier.check(isinstance(runtime_plan, dict) and runtime_plan.get("container_runtime") == runtime, f"install plan runtime is {runtime}")
    verifier.check(isinstance(runtime_plan, dict) and runtime_plan.get("cgroup_driver") == "systemd", "install plan uses systemd cgroup driver")
    verifier.check(isinstance(runtime_plan, dict) and runtime_plan.get("swap_policy") == "kubernetes-off", "install plan runtime keeps Kubernetes swap off")

    kubernetes = plan.get("kubernetes", {})
    kubeadm = kubernetes.get("kubeadm", {}) if isinstance(kubernetes, dict) else {}
    verifier.check(isinstance(kubernetes, dict) and kubernetes.get("role") == role, f"install plan Kubernetes role is {role}")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_api") == KUBEADM_CONFIG_API, f"install plan kubeadm config API is {KUBEADM_CONFIG_API}")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("action") == expected["action"], f"install plan kubeadm action is {expected['action']}")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_template") == expected["template"], f"install plan kubeadm template is {expected['template']}")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_output") == KUBEADM_LOCAL_CONFIG, f"install plan kubeadm local config output is {KUBEADM_LOCAL_CONFIG}")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("command") == expected["command"], "install plan kubeadm command is declared")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("control_plane") is expected["control_plane"], "install plan kubeadm control-plane flag matches role")
    verifier.check(isinstance(kubeadm, dict) and kubeadm.get("cri_socket") == expected["cri_socket"], f"install plan kubeadm CRI socket matches {runtime}")

    artifacts = plan.get("artifacts", {})
    verifier.check(isinstance(artifacts, dict) and bool(artifacts.get("runtime_plan")), "install plan records runtime plan path")
    verifier.check(isinstance(artifacts, dict) and artifacts.get("installed_plan") == "/var/lib/ki2/install-plan.yaml", "install plan records installed plan path")


def verify_install_plan_spec(repo_root: Path, verifier: Verifier) -> None:
    spec_path = repo_root / "distro" / "specs" / "kiki-install-plan-v1.yaml"
    verifier.check(spec_path.exists(), f"install plan spec exists: {spec_path.relative_to(repo_root)}")
    if not spec_path.exists():
        return
    spec = ki2build.read_structured_file(spec_path)
    required = {str(item) for item in spec.get("required", []) if item is not None}
    optional = spec.get("optional", [])
    document = spec.get("document", {})
    kubernetes = spec.get("kubernetes", {})
    kubeadm = kubernetes.get("kubeadm", {}) if isinstance(kubernetes, dict) else {}
    artifacts = spec.get("artifacts", {})
    safety = spec.get("safety", {})
    rules = safety.get("rules", []) if isinstance(safety, dict) else []
    rule_text = "\n".join(str(item) for item in rules)

    verifier.check(spec.get("status") == "stage2-v2", "install plan spec status is stage2-v2")
    verifier.check(INSTALL_PLAN_REQUIRED_SECTIONS <= required, "install plan spec requires Stage 2 sections")
    verifier.check(optional == [] or optional == {}, "install plan spec has no Stage 2 optional core sections")
    verifier.check(isinstance(document, dict) and document.get("generated_runtime_path") == "/run/kiki/install-plan.yaml", "install plan spec documents runtime plan path")
    verifier.check(isinstance(document, dict) and document.get("installed_copy_path") == "/var/lib/ki2/install-plan.yaml", "install plan spec documents installed plan path")
    verifier.check(isinstance(kubernetes, dict) and kubernetes.get("role"), "install plan spec documents Kubernetes role")
    verifier.check(isinstance(kubeadm, dict) and INSTALL_PLAN_KUBEADM_FIELDS <= set(kubeadm), "install plan spec documents kubeadm Stage 2 fields")
    verifier.check(isinstance(artifacts, dict) and "runtime_plan" in artifacts and "installed_plan" in artifacts, "install plan spec documents artifact paths")
    verifier.check("containerd.sock" in rule_text and "crio.sock" in rule_text, "install plan spec documents CRI socket safety rules")
    verifier.check("kiki.autoinstall" in rule_text and "kiki.target" in rule_text, "install plan spec documents autoinstall safety rules")


def verify_profile_contracts(repo_root: Path, verifier: Verifier) -> None:
    for name, runtime in PROFILE_SPECS:
        profile_path = repo_root / "distro" / "profiles" / f"{name}.yaml"
        plan_path = repo_root / "distro" / "install-plans" / f"{name}.yaml"
        required, forbidden, required_service, forbidden_service = expected_runtime_packages(runtime)

        verifier.check(profile_path.exists(), f"profile exists: {profile_path.relative_to(repo_root)}")
        verifier.check(plan_path.exists(), f"install plan exists: {plan_path.relative_to(repo_root)}")
        if not profile_path.exists() or not plan_path.exists():
            continue

        profile = ki2build.load_profile(profile_path)
        profile_packages = set(profile.get("packages", []))
        services = set(profile.get("services", {}).get("enable", []))
        verifier.check(required <= profile_packages, f"{name}: profile includes {runtime} Kubernetes package set")
        verifier.check(not (forbidden & profile_packages), f"{name}: profile excludes opposite CRI package set")
        verifier.check(required_service in services, f"{name}: profile enables {required_service}")
        verifier.check(forbidden_service not in services, f"{name}: profile does not enable {forbidden_service}")

        plan = install_plan(plan_path)
        plan_packages = flatten_package_sets(plan)
        plan_services = set(plan.get("post_install", {}).get("enable_services", []))
        plan_runtime = str(plan.get("runtime", {}).get("container_runtime", ""))
        kubeadm_contract = expected_kubeadm_contract(name, runtime)
        kubernetes = plan.get("kubernetes", {})
        kubeadm = kubernetes.get("kubeadm", {}) if isinstance(kubernetes, dict) else {}
        verifier.check(plan_runtime == runtime, f"{name}: install plan runtime is {runtime}")
        verifier.check(required <= plan_packages, f"{name}: install plan includes {runtime} Kubernetes package set")
        verifier.check(not (forbidden & plan_packages), f"{name}: install plan excludes opposite CRI package set")
        verifier.check(required_service in plan_services, f"{name}: install plan enables {required_service}")
        verifier.check(forbidden_service not in plan_services, f"{name}: install plan does not enable {forbidden_service}")
        verifier.check(isinstance(kubernetes, dict) and kubernetes.get("role") == kubeadm_contract["role"], f"{name}: install plan Kubernetes role is {kubeadm_contract['role']}")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_api") == KUBEADM_CONFIG_API, f"{name}: kubeadm config API is {KUBEADM_CONFIG_API}")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("action") == kubeadm_contract["action"], f"{name}: kubeadm action is {kubeadm_contract['action']}")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_template") == kubeadm_contract["template"], f"{name}: kubeadm template is {kubeadm_contract['template']}")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("config_output") == KUBEADM_LOCAL_CONFIG, f"{name}: kubeadm local config output is {KUBEADM_LOCAL_CONFIG}")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("command") == kubeadm_contract["command"], f"{name}: kubeadm command is declared")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("control_plane") is kubeadm_contract["control_plane"], f"{name}: kubeadm control-plane flag matches role")
        verifier.check(isinstance(kubeadm, dict) and kubeadm.get("cri_socket") == kubeadm_contract["cri_socket"], f"{name}: kubeadm CRI socket matches {runtime}")


def package_member_names(package: Path) -> set[str]:
    with tarfile.open(package, "r:gz") as tar:
        return {"/" + member.name.removeprefix("rootfs/") for member in tar.getmembers() if member.name.startswith("rootfs/") and member.name != "rootfs/"}


def package_member_text(package: Path, rootfs_path: str) -> str:
    member_name = "rootfs/" + rootfs_path.strip("/")
    with tarfile.open(package, "r:gz") as tar:
        try:
            member = tar.getmember(member_name)
        except KeyError as exc:
            raise ki2build.Ki2Error(f"{package}: missing {rootfs_path}") from exc
        handle = tar.extractfile(member)
        if handle is None:
            raise ki2build.Ki2Error(f"{package}: {rootfs_path} is not a regular file")
        return handle.read().decode("utf-8", errors="replace")


def package_has_stage2_placeholder_metadata(package: Path, package_name: str) -> bool:
    placeholder_metadata = f"/usr/share/kiki/stage2/{package_name}.json"
    paths = package_member_names(package)
    if placeholder_metadata not in paths:
        return False
    try:
        metadata = json.loads(package_member_text(package, placeholder_metadata))
    except (json.JSONDecodeError, ki2build.Ki2Error):
        return True
    return metadata.get("schema") == "kiki-stage2-placeholder-v1"


def latest_package(packages_dir: Path, arch: str, name: str) -> tuple[Path, dict[str, Any]] | None:
    matches: list[tuple[tuple[Any, ...], Path, dict[str, Any]]] = []
    for path in sorted((packages_dir / arch).glob(f"{name}-*.{arch}.ki2")):
        manifest = ki2build.read_package_manifest(path)
        if manifest.get("name") == name:
            matches.append((ki2build.package_latest_sort_key(manifest, path), path, manifest))
    if not matches:
        return None
    _, path, manifest = max(matches, key=lambda item: item[0])
    return path, manifest


def package_for_recipe(packages_dir: Path, arch: str, recipe: ki2build.Recipe) -> tuple[Path, dict[str, Any]] | None:
    exact = packages_dir / arch / ki2build.package_filename(recipe, arch)
    if exact.exists():
        manifest = ki2build.read_package_manifest(exact)
        if manifest.get("name") == recipe.name:
            return exact, manifest
    return latest_package(packages_dir, arch, recipe.name)


def verify_package_payloads(repo_root: Path, arch: str, verifier: Verifier, package_names: list[str] | None = None, strict_production: bool = False) -> None:
    recipes = ki2build.load_recipes(repo_root / "distro" / "recipes")
    packages_dir = repo_root / "dist" / "ki2" / "packages"
    names = package_names or list(PAYLOAD_REQUIREMENTS)

    for name in names:
        recipe = recipes.get(name)
        verifier.check(recipe is not None, f"recipe exists: {name}")
        requirement = PAYLOAD_REQUIREMENTS[name]
        result = package_for_recipe(packages_dir, arch, recipe)
        verifier.check(result is not None, f"package artifact exists: {name}")
        if recipe is None or result is None:
            continue
        package, manifest = result

        expected_version = f"{recipe.version}-{recipe.release}"
        actual_version = f"{manifest.get('version')}-{manifest.get('release')}"
        verifier.check(actual_version == expected_version, f"{name}: artifact version matches recipe {expected_version}")
        verifier.check(sorted(manifest.get("runtime_dependencies", [])) == sorted(recipe.dependencies.get("runtime", [])), f"{name}: runtime dependencies match recipe")

        paths = package_member_names(package)
        placeholder_artifact = package_has_stage2_placeholder_metadata(package, name)
        if recipe.build.get("system") == "stage2-stub" or placeholder_artifact:
            message = f"{name}: still uses stage2-stub placeholder payload"
            if strict_production:
                verifier.errors.append(message)
            else:
                verifier.warn(message)

        missing = [path for path in requirement.paths if path not in paths]
        verifier.check(not missing, f"{name}: package contains required payload paths")
        for path, needles in requirement.contains.items():
            try:
                text = package_member_text(package, path)
            except ki2build.Ki2Error as exc:
                verifier.errors.append(str(exc))
                continue
            for needle in needles:
                verifier.check(needle in text, f"{name}: {path} contains {needle!r}")


def verify_network_userspace(repo_root: Path, arch: str, verifier: Verifier, *, strict_production: bool = False) -> None:
    recipes = ki2build.load_recipes(repo_root / "distro" / "recipes")
    packages_dir = repo_root / "dist" / "ki2" / "packages"

    for name in NETWORK_USERSPACE_PACKAGES:
        recipe = recipes.get(name)
        verifier.check(recipe is not None, f"network userspace recipe exists: {name}")
        result = package_for_recipe(packages_dir, arch, recipe)
        verifier.check(result is not None, f"network userspace package artifact exists: {name}")
        if recipe is None or result is None:
            continue

        package, _manifest = result
        paths = package_member_names(package)
        requirement = NETWORK_USERSPACE_REQUIREMENTS[name]
        missing = [path for path in requirement.paths if path not in paths]
        verifier.check(not missing, f"{name}: network userspace package contains expected command/service paths")
        forbidden_core_runtime = sorted(paths & FORBIDDEN_HOST_LDD_CORE_RUNTIME_PATHS)
        verifier.check(
            not forbidden_core_runtime,
            f"{name}: network userspace package does not embed host glibc/core runtime libraries",
        )
        for path, needles in requirement.contains.items():
            try:
                text = package_member_text(package, path)
            except ki2build.Ki2Error as exc:
                verifier.errors.append(str(exc))
                continue
            for needle in needles:
                verifier.check(needle in text, f"{name}: {path} contains {needle!r}")

        placeholder_artifact = package_has_stage2_placeholder_metadata(package, name)
        if recipe.build.get("system") == "stage2-stub" or placeholder_artifact:
            message = f"{name}: network userspace still uses stage2-stub placeholder payload"
            if strict_production:
                verifier.errors.append(message)
            else:
                verifier.warn(message)


def verify_repository_metadata(repo_root: Path, arch: str, verifier: Verifier, *, require_signed: bool = False) -> None:
    metadata_path = repo_root / "dist" / "ki2" / "repo" / f"metadata.{arch}.json"
    index_path = repo_root / "dist" / "ki2" / "repo" / f"index.{arch}.json"
    verifier.check(index_path.exists(), f"repository index exists: {index_path.relative_to(repo_root)}")
    verifier.check(metadata_path.exists(), f"repository metadata exists: {metadata_path.relative_to(repo_root)}")
    if not metadata_path.exists():
        return
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    package_count = metadata.get("package_count")
    if package_count is None and isinstance(metadata.get("packages"), dict):
        package_count = metadata["packages"].get("count")
    if package_count is None and isinstance(metadata.get("index"), dict):
        package_count = metadata["index"].get("package_count")
    verifier.check(metadata.get("channel") == "stage2-v2", "repository metadata channel is stage2-v2")
    verifier.check(int(package_count or 0) >= len(PAYLOAD_REQUIREMENTS), "repository metadata includes Stage 2 packages")
    security = metadata.get("security", {})
    if require_signed:
        verifier.check(isinstance(security, dict) and security.get("signed") is True, "repository metadata is signed")
        verifier.check(isinstance(security, dict) and security.get("algorithm") == "hmac-sha256", "repository metadata uses HMAC-SHA256 signing")
        verifier.check(isinstance(security, dict) and bool(security.get("signature")), "repository metadata has a signature")


def rootfs_path(root: Path, path: str) -> Path:
    return root / path.strip("/")


def rootfs_path_exists(root: Path, path: str) -> bool:
    candidate = rootfs_path(root, path)
    return candidate.exists() or candidate.is_symlink()


def rootfs_text(root: Path, path: str) -> str:
    return rootfs_path(root, path).read_text(encoding="utf-8", errors="replace")


def read_installed_package_names(root: Path) -> set[str]:
    installed_db = root / "var/lib/ki2/installed.json"
    if installed_db.exists():
        data = json.loads(installed_db.read_text(encoding="utf-8"))
        packages = data.get("packages", {})
        if isinstance(packages, dict):
            return {str(name) for name in packages}
    installed_list = root / "var/lib/ki2/installed.list"
    if installed_list.exists():
        return {line.strip() for line in installed_list.read_text(encoding="utf-8").splitlines() if line.strip()}
    return set()


def fstab_has_active_swap(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 3 and fields[2] == "swap":
            return True
    return False


def verify_installed_rootfs(root: Path, runtime: str, verifier: Verifier) -> None:
    required, forbidden, required_service, forbidden_service = expected_runtime_packages(runtime)
    installed = read_installed_package_names(root)
    verifier.check(root.exists() and root.is_dir(), f"installed rootfs exists: {root}")
    verifier.check(bool(installed), "installed package state exists")
    verifier.check(required <= installed, f"installed rootfs includes {runtime} Kubernetes package set")
    verifier.check(not (forbidden & installed), "installed rootfs excludes opposite CRI package set")

    payload_names = sorted(required & set(PAYLOAD_REQUIREMENTS))
    for name in payload_names:
        requirement = PAYLOAD_REQUIREMENTS[name]
        missing = [path for path in requirement.paths if not rootfs_path_exists(root, path)]
        verifier.check(not missing, f"{name}: installed rootfs contains required payload paths")
        for path, needles in requirement.contains.items():
            if not rootfs_path_exists(root, path):
                continue
            text = rootfs_text(root, path)
            for needle in needles:
                verifier.check(needle in text, f"{name}: installed {path} contains {needle!r}")

    wants_dir = root / "etc/systemd/system/multi-user.target.wants"
    verifier.check(rootfs_path_exists(root, f"/etc/systemd/system/multi-user.target.wants/{required_service}"), f"installed rootfs enables {required_service}")
    verifier.check(rootfs_path_exists(root, "/etc/systemd/system/multi-user.target.wants/kubelet.service"), "installed rootfs enables kubelet.service")
    verifier.check(not rootfs_path_exists(root, f"/etc/systemd/system/multi-user.target.wants/{forbidden_service}"), f"installed rootfs does not enable {forbidden_service}")

    if runtime == "containerd":
        endpoint = "unix:///run/containerd/containerd.sock"
    else:
        endpoint = "unix:///var/run/crio/crio.sock"
    for path in ("/etc/crictl.yaml", "/etc/systemd/system/kubelet.service.d/10-kiki.conf"):
        verifier.check(rootfs_path_exists(root, path), f"installed rootfs has {path}")
        if rootfs_path_exists(root, path):
            verifier.check(endpoint in rootfs_text(root, path), f"installed {path} uses {runtime} endpoint")

    fstab = root / "etc/fstab"
    if fstab.exists():
        text = fstab.read_text(encoding="utf-8", errors="replace")
        verifier.check(not fstab_has_active_swap(text), "installed Kubernetes rootfs has swap disabled in fstab")
    verifier.check(wants_dir.exists(), "installed rootfs has multi-user target wants directory")


def verify_binary_smoke(repo_root: Path, arch: str, verifier: Verifier) -> None:
    if platform.system() != "Linux":
        verifier.errors.append("binary smoke requires a Linux runner")
        return

    packages_dir = repo_root / "dist" / "ki2" / "packages"
    package_names = sorted({command.package for command in BINARY_SMOKE_COMMANDS})
    with tempfile.TemporaryDirectory(prefix="kiki-stage2-binary-smoke-") as tmp:
        rootfs = Path(tmp) / "rootfs"
        rootfs.mkdir(parents=True, exist_ok=True)
        for name in package_names:
            result = latest_package(packages_dir, arch, name)
            verifier.check(result is not None, f"binary smoke package artifact exists: {name}")
            if result is None:
                continue
            package, _manifest = result
            ki2build.extract_package_rootfs(package, rootfs)

        env = {**os.environ, "LC_ALL": "C", "CRICTL_CONFIG": str(rootfs / "etc/crictl.yaml")}
        for command in BINARY_SMOKE_COMMANDS:
            executable = rootfs / command.path.strip("/")
            verifier.check(executable.exists(), f"binary smoke executable exists: {command.path}")
            if not executable.exists():
                continue
            try:
                proc = subprocess.run(
                    [str(executable), *command.args],
                    cwd=rootfs,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
            except OSError as exc:
                verifier.errors.append(f"binary smoke failed to execute {command.path}: {exc}")
                continue
            except subprocess.TimeoutExpired:
                verifier.errors.append(f"binary smoke timed out: {command.path} {' '.join(command.args)}")
                continue
            output = (proc.stdout or "") + (proc.stderr or "")
            verifier.check(proc.returncode == 0, f"binary smoke exits 0: {command.path} {' '.join(command.args)}")
            for needle in command.contains:
                verifier.check(needle in output, f"binary smoke output contains {needle!r}: {command.path}")

        kubeadm = rootfs / "usr/bin/kubeadm"
        if kubeadm.exists():
            for package_name in KUBEADM_CONFIG_PACKAGES:
                config_root = Path(tmp) / f"rootfs-{package_name}"
                config_root.mkdir(parents=True, exist_ok=True)
                result = latest_package(packages_dir, arch, package_name)
                verifier.check(result is not None, f"kubeadm config smoke package artifact exists: {package_name}")
                if result is None:
                    continue
                package, _manifest = result
                ki2build.extract_package_rootfs(package, config_root)
                for template in KUBEADM_TEMPLATES:
                    config_path = config_root / template.strip("/")
                    verifier.check(config_path.exists(), f"kubeadm config smoke template exists: {package_name}:{template}")
                    if not config_path.exists():
                        continue
                    output_path = Path(tmp) / f"{package_name}-{Path(template).stem}.migrated.yaml"
                    try:
                        proc = subprocess.run(
                            [str(kubeadm), "config", "migrate", "--old-config", str(config_path), "--new-config", str(output_path)],
                            cwd=rootfs,
                            env=env,
                            text=True,
                            capture_output=True,
                            timeout=20,
                            check=False,
                        )
                    except OSError as exc:
                        verifier.errors.append(f"kubeadm config smoke failed to execute for {package_name}:{template}: {exc}")
                        continue
                    except subprocess.TimeoutExpired:
                        verifier.errors.append(f"kubeadm config smoke timed out: {package_name}:{template}")
                        continue
                    output = (proc.stdout or "") + (proc.stderr or "")
                    verifier.check(proc.returncode == 0, f"kubeadm config smoke migrates: {package_name}:{template}")
                    if proc.returncode != 0 and output:
                        verifier.errors.append(f"kubeadm config smoke output for {package_name}:{template}: {output.strip()}")


def run_ki2ctl(repo_root: Path, target: Path, verifier: Verifier, *args: str) -> subprocess.CompletedProcess[str] | None:
    script = repo_root / "distro" / "sources" / "ki2ctl" / "usr" / "bin" / "ki2ctl"
    verifier.check(script.exists(), "ki2ctl script exists for repository flow")
    if not script.exists():
        return None
    command = [sys.executable, str(script), "--root", str(target), *args]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        verifier.errors.append(f"ki2ctl repository flow failed to run {' '.join(args)}: {exc}")
        return None
    verifier.check(proc.returncode == 0, f"ki2ctl repository flow succeeds: {' '.join(args)}")
    if proc.returncode != 0:
        verifier.errors.append((proc.stdout + proc.stderr).strip())
    return proc


def run_ki2ctl_failure(repo_root: Path, target: Path, verifier: Verifier, *args: str) -> subprocess.CompletedProcess[str] | None:
    script = repo_root / "distro" / "sources" / "ki2ctl" / "usr" / "bin" / "ki2ctl"
    verifier.check(script.exists(), "ki2ctl script exists for negative repository flow")
    if not script.exists():
        return None
    command = [sys.executable, str(script), "--root", str(target), *args]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        verifier.errors.append(f"ki2ctl negative repository flow failed to run {' '.join(args)}: {exc}")
        return None
    verifier.check(proc.returncode != 0, f"ki2ctl repository flow rejects: {' '.join(args)}")
    if proc.returncode == 0:
        verifier.errors.append(proc.stdout.strip())
    return proc


def verify_package_manager(repo_root: Path, verifier: Verifier) -> None:
    repo_base = repo_root / "dist" / "ki2"
    verifier.check((repo_base / "repo" / "index.x86_64.json").exists(), "ki2ctl repository flow has local index")
    verifier.check((repo_base / "packages" / "x86_64").exists(), "ki2ctl repository flow has package directory")
    if not (repo_base / "repo" / "index.x86_64.json").exists():
        return

    with tempfile.TemporaryDirectory(prefix="kiki-stage2-ki2ctl-") as tmp:
        temp = Path(tmp)
        http_root = temp / "http-target"
        local_root = temp / "local-target"
        deps_root = temp / "deps-target"

        handler = functools.partial(QuietHTTPRequestHandler, directory=str(repo_base))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        http_url = f"http://127.0.0.1:{server.server_port}"
        try:
            run_ki2ctl(repo_root, http_root, verifier, "repo", "set", http_url)
            update = run_ki2ctl(repo_root, http_root, verifier, "update")
            if update is not None:
                verifier.check("packages" in update.stdout, "ki2ctl HTTP update reads Stage 2 repository")
            install = run_ki2ctl(repo_root, http_root, verifier, "install", "base-files")
            if install is not None:
                verifier.check("installed base-files" in install.stdout, "ki2ctl HTTP install extracts a package")
            verifier.check((http_root / "var" / "lib" / "ki2" / "installed.json").exists(), "ki2ctl HTTP install writes installed DB")
        finally:
            server.shutdown()
            server.server_close()

        run_ki2ctl(repo_root, local_root, verifier, "repo", "set", str(repo_base))
        local_update = run_ki2ctl(repo_root, local_root, verifier, "update")
        if local_update is not None:
            verifier.check("packages" in local_update.stdout, "ki2ctl local mirror update reads Stage 2 repository")
        local_install = run_ki2ctl(repo_root, local_root, verifier, "install", "base-files")
        if local_install is not None:
            verifier.check("installed base-files" in local_install.stdout, "ki2ctl local mirror install extracts a package")
        local_remove = run_ki2ctl(repo_root, local_root, verifier, "repo", "remove")
        if local_remove is not None:
            verifier.check("removed repo default" in local_remove.stdout, "ki2ctl local mirror repo remove clears config")

        kube_roots = ("kubeadm", "kubectl", "kiki-kubeadm", "kube-node-config-containerd")
        index_data = json.loads((repo_base / "repo" / "index.x86_64.json").read_text(encoding="utf-8"))
        available_packages = {item.get("name") for item in index_data.get("packages", [])}
        if not set(kube_roots) <= available_packages:
            verifier.warnings.append("ki2ctl Kubernetes dependency flow skipped: repository profile does not include Kubernetes roots")
            return
        deps = run_ki2ctl(repo_root, deps_root, verifier, "--repo", str(repo_base), "install", *kube_roots, "--dry-run")
        if deps is not None:
            for name in ("containerd", "kubelet", "kubeadm", "kubectl", "kiki-kubeadm", "kube-node-config-containerd"):
                verifier.check(name in deps.stdout, f"ki2ctl dry-run resolves Kubernetes dependency: {name}")
        kube_install = run_ki2ctl(repo_root, deps_root, verifier, "--repo", str(repo_base), "install", *kube_roots)
        if kube_install is not None:
            verifier.check("installed kube-node-config-containerd" in kube_install.stdout, "ki2ctl installs Kubernetes containerd node config")
            verifier.check("installed kiki-kubeadm" in kube_install.stdout, "ki2ctl installs KIKI kubeadm executor")
            installed_db = deps_root / "var" / "lib" / "ki2" / "installed.json"
            verifier.check(installed_db.exists(), "ki2ctl Kubernetes install writes installed DB")
            if installed_db.exists():
                installed = json.loads(installed_db.read_text(encoding="utf-8")).get("packages", {})
                for name in ("containerd", "kubelet", "kubeadm", "kubectl", "kiki-kubeadm", "kube-node-config-containerd"):
                    verifier.check(name in installed, f"ki2ctl Kubernetes install records package: {name}")
        blocked_remove = run_ki2ctl_failure(repo_root, deps_root, verifier, "remove", "containerd")
        if blocked_remove is not None:
            verifier.check("reverse dependencies prevent removal" in blocked_remove.stderr, "ki2ctl blocks removing runtime with dependents")


def verify_kubeadm_renderer(repo_root: Path, verifier: Verifier) -> None:
    script = repo_root / "tools" / "ki2kubeadm.py"
    verifier.check(script.exists(), "kubeadm renderer exists")
    if not script.exists():
        return
    plan = repo_root / "distro" / "install-plans" / "kiki-kube-compute-containerd.yaml"
    template = repo_root / "distro" / "sources" / "kube-node-config-containerd" / "etc" / "kubernetes" / "kiki" / "kubeadm-join-compute.yaml"
    verifier.check(plan.exists(), "kubeadm renderer has containerd compute install plan")
    verifier.check(template.exists(), "kubeadm renderer has containerd join template")
    if not plan.exists() or not template.exists():
        return
    with tempfile.TemporaryDirectory(prefix="kiki-stage2-kubeadm-") as tmp:
        root = Path(tmp)
        target_template = root / "etc" / "kubernetes" / "kiki" / template.name
        target_template.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, target_template)
        digest = "2" * 64
        command = [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "--plan",
            str(plan),
            "--node-name",
            "stage2-worker",
            "--endpoint",
            "10.0.0.10:6443",
            "--token",
            "abcdef.0123456789abcdef",
            "--ca-cert-hash",
            digest,
        ]
        proc = subprocess.run(command, text=True, capture_output=True, timeout=60, check=False)
        verifier.check(proc.returncode == 0, "kubeadm renderer creates local compute join config")
        if proc.returncode != 0:
            verifier.errors.append((proc.stdout + proc.stderr).strip())
            return
        rendered_path = root / "etc" / "kubernetes" / "kiki" / "kubeadm.local.yaml"
        verifier.check(rendered_path.exists(), "kubeadm renderer writes kubeadm.local.yaml")
        if rendered_path.exists():
            rendered = rendered_path.read_text(encoding="utf-8")
            verifier.check("name: stage2-worker" in rendered, "kubeadm renderer writes node name")
            verifier.check("apiServerEndpoint: 10.0.0.10:6443" in rendered, "kubeadm renderer writes control-plane endpoint")
            verifier.check(f"sha256:{digest}" in rendered, "kubeadm renderer writes CA hash")
            verifier.check("criSocket: unix:///run/containerd/containerd.sock" in rendered, "kubeadm renderer writes containerd CRI socket")
            verifier.check("kiki-control-plane.local" not in rendered, "kubeadm renderer removes endpoint placeholder")


def print_report(verifier: Verifier) -> None:
    print("KIKI Stage 2 Kubernetes readiness")
    print("=================================")
    for item in verifier.ok:
        print("[OK]", item)
    for item in verifier.warnings:
        print("[WARN]", item)
    for item in verifier.errors:
        print("[FAIL]", item)
    print()
    print(f"ok={len(verifier.ok)} warnings={len(verifier.warnings)} errors={len(verifier.errors)}")


def command_verify_kubernetes(args: argparse.Namespace) -> None:
    repo_root = args.repo_root.resolve()
    verifier = Verifier()
    verify_install_plan_spec(repo_root, verifier)
    verify_profile_contracts(repo_root, verifier)
    verify_package_payloads(repo_root, args.arch, verifier, strict_production=args.strict_production)
    verify_repository_metadata(repo_root, args.arch, verifier, require_signed=args.require_signed_metadata)
    verify_kubeadm_renderer(repo_root, verifier)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def command_verify_installed_rootfs(args: argparse.Namespace) -> None:
    verifier = Verifier()
    verify_installed_rootfs(args.root.resolve(), args.runtime, verifier)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def command_verify_binary_smoke(args: argparse.Namespace) -> None:
    verifier = Verifier()
    verify_binary_smoke(args.repo_root.resolve(), args.arch, verifier)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def command_verify_package_manager(args: argparse.Namespace) -> None:
    verifier = Verifier()
    verify_package_manager(args.repo_root.resolve(), verifier)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def command_verify_network_userspace(args: argparse.Namespace) -> None:
    verifier = Verifier()
    verify_network_userspace(args.repo_root.resolve(), args.arch, verifier, strict_production=args.strict_production)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def command_verify_install_plan(args: argparse.Namespace) -> None:
    verifier = Verifier()
    verify_stage2_install_plan(args.plan.resolve(), args.runtime, args.role, verifier)
    print_report(verifier)
    raise SystemExit(1 if verifier.errors else 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KIKI Stage 2 readiness checks")
    subcommands = parser.add_subparsers(dest="command", required=True)

    verify = subcommands.add_parser("verify-kubernetes", help="verify Stage 2 Kubernetes/runtime profiles and payloads")
    verify.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    verify.add_argument("--arch", default="x86_64")
    verify.add_argument("--strict-production", action="store_true", help="fail while placeholder stage2-stub payloads remain")
    verify.add_argument("--require-signed-metadata", action="store_true", help="fail unless repository metadata is signed")
    verify.set_defaults(func=command_verify_kubernetes)

    rootfs = subcommands.add_parser("verify-installed-rootfs", help="verify an installed Stage 2 Kubernetes rootfs")
    rootfs.add_argument("--root", type=Path, required=True, help="installed target rootfs, for example /mnt/target")
    rootfs.add_argument("--runtime", choices=["cri-o", "containerd"], required=True)
    rootfs.set_defaults(func=command_verify_installed_rootfs)

    binary = subcommands.add_parser("verify-binary-smoke", help="execute Stage 2 runtime and Kubernetes package binaries")
    binary.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    binary.add_argument("--arch", default="x86_64")
    binary.set_defaults(func=command_verify_binary_smoke)

    package_manager = subcommands.add_parser("verify-package-manager", help="verify Stage 2 repository install flows with ki2ctl")
    package_manager.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    package_manager.set_defaults(func=command_verify_package_manager)

    network = subcommands.add_parser("verify-network-userspace", help="verify Stage 2 network userspace package status")
    network.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    network.add_argument("--arch", default="x86_64")
    network.add_argument("--strict-production", action="store_true", help="fail while network userspace packages still use placeholders")
    network.set_defaults(func=command_verify_network_userspace)

    plan = subcommands.add_parser("verify-install-plan", help="verify a Stage 2 Kubernetes install plan")
    plan.add_argument("--plan", type=Path, required=True)
    plan.add_argument("--runtime", choices=["cri-o", "containerd"], required=True)
    plan.add_argument("--role", choices=["bootstrap-control-plane", "control-plane", "compute"], required=True)
    plan.set_defaults(func=command_verify_install_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
