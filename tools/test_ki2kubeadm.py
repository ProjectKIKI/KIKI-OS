import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools/ki2kubeadm.py"
CRIO_TEMPLATES = Path(__file__).resolve().parents[1] / "distro/sources/kube-node-config/etc/kubernetes/kiki"
CONTAINERD_TEMPLATES = Path(__file__).resolve().parents[1] / "distro/sources/kube-node-config-containerd/etc/kubernetes/kiki"


class Ki2KubeadmTests(unittest.TestCase):
    def run_render(self, *args, expect_ok=True):
        command = [sys.executable, str(SCRIPT), *args]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if expect_ok and result.returncode != 0:
            raise AssertionError(
                f"command failed: {' '.join(command)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        if not expect_ok and result.returncode == 0:
            raise AssertionError(f"command unexpectedly succeeded: {' '.join(command)}\nstdout:\n{result.stdout}")
        return result

    def test_compute_join_requires_cluster_join_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CRIO_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = root / "plan.yaml"
            write_plan(plan, role="compute", action="join", runtime="cri-o")

            result = self.run_render("--root", str(root), "--plan", str(plan), expect_ok=False)
            self.assertIn("join rendering requires", result.stderr)

    def test_compute_join_renders_runtime_and_discovery_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CRIO_TEMPLATES / "kubeadm-join-compute.yaml")
            plan = root / "plan.yaml"
            write_plan(plan, role="compute", action="join", runtime="cri-o")

            digest = "1" * 64
            self.run_render(
                "--root",
                str(root),
                "--plan",
                str(plan),
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
            self.assertIn("name: worker-01", rendered)
            self.assertIn("apiServerEndpoint: 10.0.0.10:6443", rendered)
            self.assertIn("sha256:" + digest, rendered)
            self.assertIn("criSocket: unix:///var/run/crio/crio.sock", rendered)
            self.assertNotIn("kiki-control-plane.local", rendered)
            self.assertNotIn("0000000000000000000000000000000000000000000000000000000000000000", rendered)

    def test_bootstrap_init_renders_containerd_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install_template(root, CONTAINERD_TEMPLATES / "kubeadm-init.yaml")
            plan = root / "plan.yaml"
            write_plan(plan, role="bootstrap-control-plane", action="init", runtime="containerd")

            self.run_render("--root", str(root), "--plan", str(plan), "--node-name", "cp-01")
            rendered = (root / "etc/kubernetes/kiki/kubeadm.local.yaml").read_text(encoding="utf-8")
            self.assertIn("name: cp-01", rendered)
            self.assertIn("controlPlaneEndpoint: cp-01:6443", rendered)
            self.assertIn("criSocket: unix:///run/containerd/containerd.sock", rendered)
            self.assertIn("podSubnet: 10.244.0.0/16", rendered)


def install_template(root: Path, template: Path) -> None:
    target = root / "etc/kubernetes/kiki" / template.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")


def write_plan(path: Path, *, role: str, action: str, runtime: str) -> None:
    template = {
        "init": "/etc/kubernetes/kiki/kubeadm-init.yaml",
        "join-control": "/etc/kubernetes/kiki/kubeadm-join-control-plane.yaml",
        "join": "/etc/kubernetes/kiki/kubeadm-join-compute.yaml",
    }["init" if action == "init" else "join"]
    socket = "unix:///run/containerd/containerd.sock" if runtime == "containerd" else "unix:///var/run/crio/crio.sock"
    path.write_text(
        "\n".join(
            [
                "schema: kiki-install-plan-v1",
                "api_version: kiki.io/v1alpha1",
                "kind: InstallPlan",
                "identity:",
                "  hostname: localhost.localdomain",
                "runtime:",
                f"  container_runtime: {runtime}",
                "  cgroup_driver: systemd",
                "  swap_policy: kubernetes-off",
                "kubernetes:",
                f"  role: {role}",
                "  kubeadm:",
                "    config_api: kubeadm.k8s.io/v1beta4",
                f"    action: {action}",
                f"    config_template: {template}",
                "    config_output: /etc/kubernetes/kiki/kubeadm.local.yaml",
                f"    cri_socket: {socket}",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
