#!/usr/bin/env python3
"""Render kubeadm local configuration from a KIKI Stage 2 install plan."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import ki2build


PLACEHOLDER_CA_HASH = "sha256:" + ("0" * 64)
DEFAULT_POD_CIDR = "10.244.0.0/16"
DEFAULT_SERVICE_CIDR = "10.96.0.0/12"


class KubeadmRenderError(RuntimeError):
    pass


def load_plan(path: Path) -> dict[str, Any]:
    data = ki2build.read_structured_file(path)
    plan = data.get("install_plan", data)
    if not isinstance(plan, dict):
        raise KubeadmRenderError(f"{path}: expected install plan mapping")
    return plan


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def string_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "null":
        return ""
    return text


def prompt_default(plan: dict[str, Any], name: str) -> str:
    return string_value(nested(plan, "prompts", name, "default"))


def first_text(*values: Any) -> str:
    for value in values:
        text = string_value(value)
        if text:
            return text
    return ""


def rooted_path(root: Path, value: str) -> Path:
    if value.startswith(("/", "\\")):
        return root / value.lstrip("/\\")
    path = Path(value)
    if path.is_absolute():
        return root / str(path).lstrip("/")
    return root / path


def default_node_name(role: str) -> str:
    if role == "bootstrap-control-plane":
        return "kiki-bootstrap"
    if role == "control-plane":
        return "kiki-control"
    if role == "compute":
        return "kiki-compute"
    return "localhost.localdomain"


def normalize_ca_hash(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if re.fullmatch(r"[A-Fa-f0-9]{64}", text):
        return "sha256:" + text.lower()
    if re.fullmatch(r"sha256:[A-Fa-f0-9]{64}", text):
        return "sha256:" + text.split(":", 1)[1].lower()
    raise KubeadmRenderError("CA certificate hash must be sha256:<64 hex> or a 64 hex digest")


def sed_safe_replace(text: str, old: str, new: str) -> str:
    if not old:
        return text
    return text.replace(old, new)


def render_config(plan: dict[str, Any], template_text: str, args: argparse.Namespace) -> tuple[str, str]:
    kubernetes = plan.get("kubernetes", {})
    kubeadm = kubernetes.get("kubeadm", {}) if isinstance(kubernetes, dict) else {}
    role = first_text(args.role, kubernetes.get("role") if isinstance(kubernetes, dict) else "", "none")
    action = first_text(args.action, kubeadm.get("action"), "none")
    cri_socket = first_text(args.cri_socket, kubeadm.get("cri_socket"))
    if not cri_socket and first_text(nested(plan, "runtime", "container_runtime")) == "containerd":
        cri_socket = "unix:///run/containerd/containerd.sock"
    if not cri_socket:
        cri_socket = "unix:///var/run/crio/crio.sock"

    node_name = first_text(
        args.node_name,
        prompt_default(plan, "node_name"),
        nested(plan, "identity", "hostname"),
        default_node_name(role),
    )
    endpoint = first_text(
        args.endpoint,
        nested(plan, "kubernetes", "cluster", "control_plane_endpoint"),
        prompt_default(plan, "control_plane_endpoint"),
        prompt_default(plan, "bootstrap_endpoint"),
    )
    if action == "init" and not endpoint:
        endpoint = f"{node_name}:6443"

    token = first_text(args.token, nested(plan, "kubernetes", "join", "token"))
    ca_hash = first_text(args.ca_cert_hash, nested(plan, "kubernetes", "join", "ca_cert_hash"))
    if ca_hash:
        ca_hash = normalize_ca_hash(ca_hash)

    if action == "join" and not args.allow_placeholders:
        missing = []
        if not endpoint:
            missing.append("--endpoint")
        if not token:
            missing.append("--token")
        if not ca_hash:
            missing.append("--ca-cert-hash")
        if missing:
            raise KubeadmRenderError("join rendering requires " + ", ".join(missing))

    pod_cidr = first_text(args.pod_cidr, prompt_default(plan, "pod_cidr"), DEFAULT_POD_CIDR)
    service_cidr = first_text(args.service_cidr, prompt_default(plan, "service_cidr"), DEFAULT_SERVICE_CIDR)
    advertise_address = first_text(args.advertise_address, nested(plan, "kubernetes", "local_api", "advertise_address"), "0.0.0.0")

    output = template_text
    output = sed_safe_replace(output, "kiki-control-plane.local:6443", endpoint or "kiki-control-plane.local:6443")
    for old in ("kiki-bootstrap", "kiki-control", "kiki-compute"):
        output = sed_safe_replace(output, old, node_name)
    output = sed_safe_replace(output, "abcdef.0123456789abcdef", token or "abcdef.0123456789abcdef")
    output = sed_safe_replace(output, PLACEHOLDER_CA_HASH, ca_hash or PLACEHOLDER_CA_HASH)
    output = sed_safe_replace(output, "unix:///var/run/crio/crio.sock", cri_socket)
    output = sed_safe_replace(output, "unix:///run/containerd/containerd.sock", cri_socket)
    output = sed_safe_replace(output, "10.244.0.0/16", pod_cidr)
    output = sed_safe_replace(output, "10.96.0.0/12", service_cidr)
    output = sed_safe_replace(output, "advertiseAddress: 0.0.0.0", f"advertiseAddress: {advertise_address}")
    return output, action


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render KIKI kubeadm.local.yaml from an install plan")
    parser.add_argument("--plan", type=Path, required=True, help="KIKI install plan YAML")
    parser.add_argument("--root", type=Path, default=Path("/"), help="target root for absolute template/output paths")
    parser.add_argument("--template", default="", help="override kubeadm template path")
    parser.add_argument("--output", default="", help="override output path")
    parser.add_argument("--role", default="", help="override Kubernetes role")
    parser.add_argument("--action", choices=["", "init", "join", "none"], default="", help="override kubeadm action")
    parser.add_argument("--node-name", default="", help="nodeRegistration.name")
    parser.add_argument("--endpoint", default="", help="control-plane endpoint host:port")
    parser.add_argument("--token", default="", help="kubeadm bootstrap token for join")
    parser.add_argument("--ca-cert-hash", default="", help="discovery token CA cert hash")
    parser.add_argument("--cri-socket", default="", help="CRI socket endpoint")
    parser.add_argument("--pod-cidr", default="", help="pod subnet for kubeadm init")
    parser.add_argument("--service-cidr", default="", help="service subnet for kubeadm init")
    parser.add_argument("--advertise-address", default="", help="control-plane local advertise address")
    parser.add_argument("--allow-placeholders", action="store_true", help="allow join template placeholders to remain")
    return parser


def command_render(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    kubeadm = nested(plan, "kubernetes", "kubeadm")
    if not isinstance(kubeadm, dict):
        raise KubeadmRenderError("install plan does not contain kubernetes.kubeadm")
    template_value = first_text(args.template, kubeadm.get("config_template"))
    output_value = first_text(args.output, kubeadm.get("config_output"))
    if not template_value:
        raise KubeadmRenderError("kubeadm config_template is missing")
    if not output_value:
        raise KubeadmRenderError("kubeadm config_output is missing")

    root = args.root.resolve()
    template_path = rooted_path(root, template_value)
    output_path = rooted_path(root, output_value)
    template_text = template_path.read_text(encoding="utf-8")
    rendered, action = render_config(plan, template_text, args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"rendered kubeadm {action} config -> {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command_render(args)
    except (KubeadmRenderError, OSError, ki2build.Ki2Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
