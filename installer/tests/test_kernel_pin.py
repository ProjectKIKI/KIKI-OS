import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
MODULE_PATH = ROOT / "installer/alpine/overlay/usr/local/bin/kiki-install.py"
SPEC = importlib.util.spec_from_file_location("kiki_install_kernel", MODULE_PATH)
kiki_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kiki_install)


def config():
    return {
        "apiVersion": "kiki.io/v1alpha1",
        "kind": "KikiInstallConfig",
        "metadata": {"name": "kernel-node"},
        "spec": {
            "hostname": "kernel-node",
            "role": "compute",
            "clusterRef": {"name": "lab"},
            "os": {
                "distribution": "debian",
                "release": "bookworm",
                "mirror": "https://deb.debian.org/debian",
                "securityMirror": "https://deb.debian.org/debian-security",
                "architecture": "amd64",
                "kernelPackage": "linux-image-6.1.0-51-amd64",
                "kernelVersion": "6.1.177-1",
                "packages": ["systemd", "linux-image-amd64"],
            },
            "storage": {"disk": "/dev/sda", "wipe": True, "bootMode": "bios", "rootFs": "ext4"},
            "agent": {"registrationRequired": False},
        },
    }


class RecordingRunner:
    def __init__(self):
        self.commands = []
        self.files = {}

    def run(self, args, check=True):
        self.commands.append(args)

    def write_text(self, path, content, mode=0o644):
        self.files[str(path)] = content


class KernelPinTests(unittest.TestCase):
    def test_rejects_kernel_drift(self):
        value = config()
        value["spec"]["os"]["kernelVersion"] = "6.1.178-1"
        with self.assertRaisesRegex(kiki_install.InstallerError, "must be pinned"):
            kiki_install.validate_config(value)

    def test_installs_holds_and_verifies_exact_kernel(self):
        value = config()
        runner = RecordingRunner()
        with tempfile.TemporaryDirectory() as directory:
            kiki_install.install_and_verify_target_kernel(runner, value["spec"], directory)
        rendered = "\n".join(" ".join(command) for command in runner.commands)
        self.assertIn("linux-image-6.1.0-51-amd64=6.1.177-1", rendered)
        self.assertIn("apt-mark hold linux-image-6.1.0-51-amd64", rendered)
        self.assertIn("dpkg-query", rendered)
        self.assertTrue(any("bookworm-security" in content for content in runner.files.values()))

    def test_iso_profile_pins_alpine_lts_kernel(self):
        profile = (ROOT / "installer/alpine/iso/profiles/profile_kiki.sh").read_text(encoding="utf-8")
        self.assertIn("linux-lts=6.6.139-r0", profile)


if __name__ == "__main__":
    unittest.main()
