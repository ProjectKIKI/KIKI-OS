#!/usr/bin/env python3
"""Run the KIKI Stage 3 kubeadm validation matrix on provisioned VMs."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("python3-yaml or PyYAML is required") from exc


SCHEMA = "kiki-stage3-vm-matrix-v1"
TOKEN_RE = re.compile(r"^[a-z0-9]{6}\.[a-z0-9]{16}$")
CA_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class MatrixError(RuntimeError):
    pass


@dataclass(frozen=True)
class Node:
    name: str
    role: str
    host: str
    user: str
    port: int
    control_plane_certificates_ready: bool = False


@dataclass(frozen=True)
class MatrixConfig:
    endpoint: str
    identity_file: Path
    known_hosts: Path
    connect_timeout: int
    node_timeout: int
    require_ready: bool
    nodes: tuple[Node, ...]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise MatrixError(message)


def load_config(path: Path) -> MatrixConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(raw, dict), "matrix configuration must be a YAML map")
    require(raw.get("schema") == SCHEMA, f"matrix schema must be {SCHEMA}")
    cluster = raw.get("cluster") or {}
    ssh = raw.get("ssh") or {}
    require(isinstance(cluster, dict) and isinstance(ssh, dict), "cluster and ssh must be maps")
    endpoint = str(cluster.get("control_plane_endpoint") or "").strip()
    require(bool(re.fullmatch(r"[^\s:]+:\d{1,5}", endpoint)), "control_plane_endpoint must be host:port")
    identity_file = Path(str(ssh.get("identity_file") or "")).expanduser()
    known_hosts = Path(str(ssh.get("known_hosts") or "")).expanduser()
    require(str(identity_file) not in ("", "."), "ssh.identity_file is required")
    require(str(known_hosts) not in ("", "."), "ssh.known_hosts is required")
    default_user = str(ssh.get("user") or "root")
    default_port = int(ssh.get("port") or 22)
    connect_timeout = int(ssh.get("connect_timeout") or 10)
    node_timeout = int(cluster.get("node_timeout") or 600)
    require(1 <= default_port <= 65535, "ssh.port is invalid")
    require(1 <= connect_timeout <= 120, "ssh.connect_timeout must be between 1 and 120")
    require(30 <= node_timeout <= 3600, "cluster.node_timeout must be between 30 and 3600")

    nodes_raw = raw.get("nodes")
    require(isinstance(nodes_raw, list) and nodes_raw, "nodes must be a non-empty list")
    nodes: list[Node] = []
    for item in nodes_raw:
        require(isinstance(item, dict), "each node must be a map")
        node = Node(
            name=str(item.get("name") or "").strip(),
            role=str(item.get("role") or "").strip(),
            host=str(item.get("host") or "").strip(),
            user=str(item.get("user") or default_user).strip(),
            port=int(item.get("port") or default_port),
            control_plane_certificates_ready=item.get("control_plane_certificates_ready") is True,
        )
        require(bool(re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", node.name)), f"invalid node name: {node.name}")
        require(node.role in {"bootstrap", "control", "compute"}, f"invalid role for {node.name}: {node.role}")
        require(bool(node.host) and not any(char.isspace() for char in node.host), f"invalid host for {node.name}")
        require(bool(node.user) and not any(char.isspace() for char in node.user), f"invalid SSH user for {node.name}")
        require(1 <= node.port <= 65535, f"invalid SSH port for {node.name}")
        if node.role == "control":
            require(
                node.control_plane_certificates_ready,
                f"{node.name}: control-plane certificates must be distributed and acknowledged",
            )
        nodes.append(node)
    require(len({node.name for node in nodes}) == len(nodes), "node names must be unique")
    require(len({(node.host, node.port) for node in nodes}) == len(nodes), "node endpoints must be unique")
    require(sum(node.role == "bootstrap" for node in nodes) == 1, "exactly one bootstrap node is required")
    require(sum(node.role == "control" for node in nodes) <= 1, "at most one control node is supported")
    require(sum(node.role == "compute" for node in nodes) <= 1, "at most one compute node is supported")
    return MatrixConfig(
        endpoint=endpoint,
        identity_file=identity_file,
        known_hosts=known_hosts,
        connect_timeout=connect_timeout,
        node_timeout=node_timeout,
        require_ready=cluster.get("require_ready") is not False,
        nodes=tuple(nodes),
    )


def select_nodes(config: MatrixConfig, size: int) -> tuple[Node, ...]:
    require(size in (1, 2, 3), "matrix size must be 1, 2, or 3")
    by_role = {node.role: node for node in config.nodes}
    required_roles = {1: ("bootstrap",), 2: ("bootstrap", "compute"), 3: ("bootstrap", "control", "compute")}[size]
    missing = [role for role in required_roles if role not in by_role]
    require(not missing, f"matrix size {size} requires roles: {', '.join(missing)}")
    return tuple(by_role[role] for role in required_roles)


class SSHRunner:
    def __init__(self, config: MatrixConfig, *, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run

    def base_command(self, node: Node) -> list[str]:
        return [
            "ssh",
            "-p",
            str(node.port),
            "-i",
            str(self.config.identity_file),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts}",
            "-o",
            f"ConnectTimeout={self.config.connect_timeout}",
            f"{node.user}@{node.host}",
            "--",
        ]

    def run(self, node: Node, arguments: list[str], *, input_text: str | None = None) -> str:
        remote = shlex.join(arguments)
        command = [*self.base_command(node), remote]
        print(f"[{node.name}] {remote}")
        if self.dry_run:
            return ""
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.config.node_timeout,
        )
        if result.returncode != 0:
            raise MatrixError(
                f"{node.name}: remote command failed ({result.returncode}): {remote}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result.stdout.strip()


def validate_firewall_runtime(runner: SSHRunner, node: Node) -> None:
    """Prove that the packaged D-Bus/firewalld/nftables stack is live on a VM."""
    runner.run(node, ["sudo", "-n", "test", "-x", "/usr/bin/firewall-cmd"])
    runner.run(node, ["sudo", "-n", "test", "-x", "/usr/sbin/nft"])
    runner.run(node, ["sudo", "-n", "systemctl", "is-active", "dbus.service"])
    runner.run(node, ["sudo", "-n", "systemctl", "is-active", "firewalld.service"])
    runner.run(node, ["sudo", "-n", "/usr/bin/firewall-cmd", "--state"])
    runner.run(node, ["sudo", "-n", "/usr/sbin/nft", "list", "ruleset"])


def reconcile_arguments(node: Node, config: MatrixConfig, *, join: bool) -> list[str]:
    arguments = [
        "sudo",
        "-n",
        "/usr/bin/kiki-agent",
        "kube",
        "reconcile",
        "--profile",
        node.role,
        "--node-name",
        node.name,
    ]
    if join:
        arguments.extend(
            [
                "--token-file",
                "/run/secrets/kiki/kubeadm-token",
                "--endpoint",
                config.endpoint,
                "--ca-cert-hash",
                "__CA_CERT_HASH__",
            ]
        )
    return arguments


def derive_ca_hash(runner: SSHRunner, bootstrap: Node) -> str:
    output = runner.run(
        bootstrap,
        [
            "sudo",
            "-n",
            "sh",
            "-c",
            "openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | "
            "openssl pkey -pubin -outform DER | openssl dgst -sha256 -hex",
        ],
    )
    match = re.search(r"([0-9a-fA-F]{64})$", output)
    require(match is not None, "could not derive kubeadm CA public-key hash")
    return "sha256:" + match.group(1).lower()


def wait_for_nodes(runner: SSHRunner, bootstrap: Node, expected_names: set[str], timeout: int, require_ready: bool) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        output = runner.run(
            bootstrap,
            ["sudo", "-n", "kubectl", "--kubeconfig", "/etc/kubernetes/admin.conf", "get", "nodes", "-o", "json"],
        )
        try:
            last = json.loads(output)
        except json.JSONDecodeError:
            last = {}
        items = last.get("items", []) if isinstance(last, dict) else []
        observed = {str(item.get("metadata", {}).get("name") or "") for item in items if isinstance(item, dict)}
        ready = {
            str(item.get("metadata", {}).get("name") or "")
            for item in items
            if isinstance(item, dict)
            and any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in item.get("status", {}).get("conditions", [])
                if isinstance(condition, dict)
            )
        }
        if expected_names <= observed and (not require_ready or expected_names <= ready):
            return {"observed": sorted(observed), "ready": sorted(ready)}
        time.sleep(5)
    raise MatrixError(f"nodes did not reach the required state: expected={sorted(expected_names)} last={last}")


def validate_local_inputs(config: MatrixConfig) -> None:
    require(config.identity_file.is_file(), f"SSH identity file not found: {config.identity_file}")
    require(config.known_hosts.is_file(), f"SSH known_hosts file not found: {config.known_hosts}")


def run_matrix(config: MatrixConfig, size: int, *, dry_run: bool = False) -> dict[str, Any]:
    nodes = select_nodes(config, size)
    if not dry_run:
        validate_local_inputs(config)
    runner = SSHRunner(config, dry_run=dry_run)
    bootstrap = nodes[0]
    for node in nodes:
        runner.run(node, ["sudo", "-n", "test", "-x", "/usr/bin/kiki-agent"])
        runner.run(node, ["sudo", "-n", "test", "-S", "/var/run/crio/crio.sock", "-o", "-S", "/run/containerd/containerd.sock"])
        validate_firewall_runtime(runner, node)

    bootstrap_output = runner.run(bootstrap, reconcile_arguments(bootstrap, config, join=False))
    if dry_run:
        for node in nodes[1:]:
            runner.run(node, reconcile_arguments(node, config, join=True))
        return {"size": size, "nodes": [node.name for node in nodes], "dry_run": True, "firewall_runtime": True}

    token = runner.run(bootstrap, ["sudo", "-n", "kubeadm", "token", "create", "--ttl", "30m"])
    require(TOKEN_RE.fullmatch(token) is not None, "kubeadm returned an invalid bootstrap token")
    ca_hash = derive_ca_hash(runner, bootstrap)
    require(CA_HASH_RE.fullmatch(ca_hash) is not None, "derived CA hash is invalid")
    for node in nodes[1:]:
        runner.run(
            node,
            ["sudo", "-n", "install", "-d", "-m", "0700", "/run/secrets/kiki"],
        )
        runner.run(
            node,
            ["sudo", "-n", "install", "-m", "0600", "/dev/stdin", "/run/secrets/kiki/kubeadm-token"],
            input_text=token + "\n",
        )
        arguments = [ca_hash if value == "__CA_CERT_HASH__" else value for value in reconcile_arguments(node, config, join=True)]
        runner.run(node, arguments)

    state = wait_for_nodes(runner, bootstrap, {node.name for node in nodes}, config.node_timeout, config.require_ready)
    for node in nodes:
        runner.run(node, ["sudo", "-n", "systemctl", "is-active", "kubelet.service"])
        rerun = runner.run(
            node,
            [ca_hash if value == "__CA_CERT_HASH__" else value for value in reconcile_arguments(node, config, join=node.role != "bootstrap")],
        )
        require("kubeadm_skipped=true" in rerun, f"{node.name}: reconcile rerun was not idempotent")
    return {
        "size": size,
        "nodes": [node.name for node in nodes],
        "bootstrap_initialized": "kubeadm_skipped=false" in bootstrap_output,
        "firewall_runtime": True,
        "idempotent": True,
        **state,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 3 kubeadm validation on 1/2/3 provisioned VMs")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--dry-run", action="store_true", help="print the SSH matrix without connecting")
    parser.add_argument("command", choices=("validate", "run"), nargs="?", default="run")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config.resolve())
        if args.command == "validate":
            select_nodes(config, args.size)
            validate_local_inputs(config)
            result = {"schema": SCHEMA, "size": args.size, "valid": True}
        else:
            result = run_matrix(config, args.size, dry_run=args.dry_run)
    except (OSError, MatrixError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
