from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "distro/sources/kiki-kubeadm/usr/bin/kiki-kubeadm"
CRIO_TEMPLATES = Path(__file__).resolve().parents[1] / "distro/sources/kube-node-config/etc/kubernetes/kiki"
CONTAINERD_TEMPLATES = Path(__file__).resolve().parents[1] / "distro/sources/kube-node-config-containerd/etc/kubernetes/kiki"


class KikiKubeadmTests(unittest.TestCase):
    def run_tool(self, root: Path, *args: str, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if expect_ok and result.returncode != 0:
            raise AssertionError(f"command failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        if not expect_ok and result.returncode == 0:
            raise AssertionError(f"command unexpectedly succeeded\nstdout:\n{result.stdout}")
        return result

    def test_render_compute_join_requires_discovery_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CRIO_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = write_plan(root, role="compute", action="join", runtime="cri-o")

            result = self.run_tool(root, "--plan", str(plan), "render", expect_ok=False)

            self.assertIn("join requires", result.stderr)

    def test_join_dry_run_renders_config_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CONTAINERD_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = write_plan(root, role="compute", action="join", runtime="containerd")
            digest = "2" * 64

            result = self.run_tool(
                root,
                "--plan",
                str(plan),
                "join",
                "--dry-run",
                "--node-name",
                "worker-01",
                "--endpoint",
                "10.0.0.10:6443",
                "--token",
                "abcdef.0123456789abcdef",
                "--ca-cert-hash",
                digest,
            )

            rendered = (root / "etc/kubernetes/kiki/kubeadm.local.yaml").read_text(encoding="utf-8")
            state = json.loads((root / "var/lib/kiki/kubernetes/state.json").read_text(encoding="utf-8"))
            self.assertIn("dry-run: kubeadm join", result.stdout)
            self.assertIn("name: worker-01", rendered)
            self.assertIn("apiServerEndpoint: 10.0.0.10:6443", rendered)
            self.assertIn("sha256:" + digest, rendered)
            self.assertIn("criSocket: unix:///run/containerd/containerd.sock", rendered)
            self.assertEqual(state["status"], "dry-run")
            self.assertEqual(state["action"], "join")

    def test_join_token_file_is_read_without_command_line_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CRIO_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = write_plan(root, role="compute", action="join", runtime="cri-o")
            token_file = root / "run/secrets/kubeadm-token"
            token_file.parent.mkdir(parents=True)
            token_file.write_text("abcdef.0123456789abcdef\n", encoding="utf-8")

            result = self.run_tool(
                root,
                "--plan",
                str(plan),
                "join",
                "--dry-run",
                "--endpoint",
                "10.0.0.10:6443",
                "--token-file",
                "/run/secrets/kubeadm-token",
                "--ca-cert-hash",
                "4" * 64,
            )

            rendered = (root / "etc/kubernetes/kiki/kubeadm.local.yaml").read_text(encoding="utf-8")
            self.assertIn("abcdef.0123456789abcdef", rendered)
            self.assertNotIn("abcdef.0123456789abcdef", result.stdout)

    def test_init_dry_run_renders_containerd_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CONTAINERD_TEMPLATES / "kubeadm-init.yaml")
            plan = write_plan(root, role="bootstrap-control-plane", action="init", runtime="containerd")

            self.run_tool(root, "--plan", str(plan), "init", "--dry-run", "--node-name", "cp-01")

            rendered = (root / "etc/kubernetes/kiki/kubeadm.local.yaml").read_text(encoding="utf-8")
            state = json.loads((root / "var/lib/kiki/kubernetes/state.json").read_text(encoding="utf-8"))
            self.assertIn("name: cp-01", rendered)
            self.assertIn("controlPlaneEndpoint: cp-01:6443", rendered)
            self.assertIn("criSocket: unix:///run/containerd/containerd.sock", rendered)
            self.assertEqual(state["action"], "init")
            self.assertEqual(state["status"], "dry-run")

    def test_join_refuses_non_dry_run_against_target_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CRIO_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = write_plan(root, role="compute", action="join", runtime="cri-o")

            result = self.run_tool(
                root,
                "--plan",
                str(plan),
                "join",
                "--endpoint",
                "10.0.0.10:6443",
                "--token",
                "abcdef.0123456789abcdef",
                "--ca-cert-hash",
                "3" * 64,
                expect_ok=False,
            )

            self.assertIn("requires --root /", result.stderr)


def install_template(root: Path, template: Path) -> None:
    target = root / "etc/kubernetes/kiki" / template.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def write_plan(root: Path, *, role: str, action: str, runtime: str) -> Path:
    template = "/etc/kubernetes/kiki/kubeadm-init.yaml" if action == "init" else "/etc/kubernetes/kiki/kubeadm-join-compute.yaml"
    socket = "unix:///run/containerd/containerd.sock" if runtime == "containerd" else "unix:///var/run/crio/crio.sock"
    plan = root / "install-plan.yaml"
    plan.write_text(
        "\n".join(
            [
                "install_plan:",
                "  schema: kiki-install-plan-v1",
                "  identity:",
                "    hostname: localhost.localdomain",
                "  runtime:",
                f"    container_runtime: {runtime}",
                "    cgroup_driver: systemd",
                "  kubernetes:",
                f"    role: {role}",
                "    kubeadm:",
                "      config_api: kubeadm.k8s.io/v1beta4",
                f"      action: {action}",
                f"      config_template: {template}",
                "      config_output: /etc/kubernetes/kiki/kubeadm.local.yaml",
                f"      cri_socket: {socket}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return plan


if __name__ == "__main__":
    unittest.main()
