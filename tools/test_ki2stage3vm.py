from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent / "ki2stage3vm.py"
SPEC = importlib.util.spec_from_file_location("ki2stage3vm", SCRIPT)
ki2stage3vm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ki2stage3vm
SPEC.loader.exec_module(ki2stage3vm)


class Ki2Stage3VMTests(unittest.TestCase):
    def test_loads_and_selects_one_two_three_node_matrices(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp))
            config = ki2stage3vm.load_config(config_path)
            self.assertEqual([node.role for node in ki2stage3vm.select_nodes(config, 1)], ["bootstrap"])
            self.assertEqual(
                [node.role for node in ki2stage3vm.select_nodes(config, 2)],
                ["bootstrap", "compute"],
            )
            self.assertEqual(
                [node.role for node in ki2stage3vm.select_nodes(config, 3)],
                ["bootstrap", "control", "compute"],
            )

    def test_requires_manual_control_plane_certificate_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), certificates_ready=False)
            with self.assertRaisesRegex(ki2stage3vm.MatrixError, "certificates must be distributed"):
                ki2stage3vm.load_config(config_path)

    def test_ssh_command_enforces_pinned_host_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ki2stage3vm.load_config(write_config(Path(tmp)))
            command = ki2stage3vm.SSHRunner(config).base_command(config.nodes[0])
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn(f"UserKnownHostsFile={config.known_hosts}", command)
            self.assertIn("BatchMode=yes", command)

    def test_dry_run_builds_full_matrix_without_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ki2stage3vm.load_config(write_config(Path(tmp)))
            result = ki2stage3vm.run_matrix(config, 3, dry_run=True)
            self.assertEqual(result["nodes"], ["bootstrap-1", "control-1", "compute-1"])
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["firewall_runtime"])

    def test_firewall_runtime_gate_checks_services_and_nft_backend(self):
        class RecordingRunner:
            def __init__(self):
                self.commands = []

            def run(self, node, arguments, *, input_text=None):
                self.commands.append(arguments)
                return ""

        runner = RecordingRunner()
        node = ki2stage3vm.Node("bootstrap-1", "bootstrap", "10.20.0.10", "admin", 22)
        ki2stage3vm.validate_firewall_runtime(runner, node)
        self.assertIn(["sudo", "-n", "systemctl", "is-active", "dbus.service"], runner.commands)
        self.assertIn(["sudo", "-n", "systemctl", "is-active", "firewalld.service"], runner.commands)
        self.assertIn(["sudo", "-n", "/usr/bin/firewall-cmd", "--state"], runner.commands)
        self.assertIn(["sudo", "-n", "/usr/sbin/nft", "list", "ruleset"], runner.commands)


def write_config(directory: Path, *, certificates_ready: bool = True) -> Path:
    path = directory / "matrix.yaml"
    path.write_text(
        f"""schema: kiki-stage3-vm-matrix-v1
cluster:
  control_plane_endpoint: 10.20.0.10:6443
  node_timeout: 60
  require_ready: true
ssh:
  user: admin
  identity_file: {directory / 'identity'}
  known_hosts: {directory / 'known_hosts'}
nodes:
  - name: bootstrap-1
    role: bootstrap
    host: 10.20.0.10
  - name: control-1
    role: control
    host: 10.20.0.11
    control_plane_certificates_ready: {str(certificates_ready).lower()}
  - name: compute-1
    role: compute
    host: 10.20.0.12
""",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
