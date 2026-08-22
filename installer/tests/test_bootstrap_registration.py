import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "alpine/overlay/usr/local/bin/kiki-install.py"
SPEC = importlib.util.spec_from_file_location("kiki_install_registration", MODULE_PATH)
kiki_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kiki_install)


def config():
    return {
        "metadata": {"name": "node-01"},
        "spec": {
            "hostname": "node-01",
            "role": "compute",
            "clusterRef": {"name": "lab"},
            "os": {"distribution": "debian", "release": "bookworm", "architecture": "amd64"},
            "storage": {"disk": "/dev/sda", "bootMode": "bios", "rootFs": "ext4"},
            "agent": {
                "managementUrl": "https://bootstrap.example",
                "callbackPath": "/api/v1/nodes/register",
                "registrationToken": "one-time-token",
            },
        },
    }


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.value).encode("utf-8")


class BootstrapRegistrationTests(unittest.TestCase):
    def test_exchanges_one_time_token_then_uses_bearer_token(self):
        requests = []

        def open_request(req, timeout):
            self.assertEqual(timeout, 10)
            requests.append(req)
            return Response({"ok": True, "node": "node-01", "nodeToken": "node-token"})

        value = config()
        with mock.patch.object(kiki_install.request, "urlopen", side_effect=open_request):
            token = kiki_install.notify_management(value, "installing", False)
            self.assertEqual(token, "node-token")
            kiki_install.notify_management(value, "installed", False, node_token=token)

        first = json.loads(requests[0].data)
        second = json.loads(requests[1].data)
        self.assertEqual(first["spec"]["registrationToken"], "one-time-token")
        self.assertNotIn("Authorization", requests[0].headers)
        self.assertNotIn("registrationToken", second["spec"])
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer node-token")

    def test_target_persists_exchanged_node_token(self):
        value = config()
        with tempfile.TemporaryDirectory() as directory:
            runner = kiki_install.Runner()
            kiki_install.configure_target(runner, value, directory, node_token="node-token")
            root = Path(directory)
            self.assertEqual((root / "etc/kiki/registration-token").read_text().strip(), "node-token")
            node_config = (root / "etc/kiki/node.yaml").read_text()
            self.assertIn("registrationPending: false", node_config)
            self.assertNotIn("one-time-token", node_config)

    def test_target_can_defer_exchange_until_first_boot(self):
        value = config()
        with tempfile.TemporaryDirectory() as directory:
            runner = kiki_install.Runner()
            kiki_install.configure_target(runner, value, directory)
            root = Path(directory)
            self.assertEqual((root / "etc/kiki/registration-token").read_text().strip(), "one-time-token")
            self.assertIn("registrationPending: true", (root / "etc/kiki/node.yaml").read_text())
            agent_script = (root / "usr/local/bin/kiki-agent").read_text()
            self.assertIn('headers["Authorization"] = "Bearer " + token', agent_script)
            self.assertIn("persist_node_token(config, token)", agent_script)


if __name__ == "__main__":
    unittest.main()
