import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "alpine/overlay/usr/local/bin/kiki-install.py"
SPEC = importlib.util.spec_from_file_location("kiki_install", MODULE_PATH)
kiki_install = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kiki_install)


def config():
    return {
        "apiVersion": "kiki.io/v1alpha1",
        "kind": "KikiInstallConfig",
        "metadata": {"name": "gpu-node"},
        "spec": {
            "hostname": "gpu-node",
            "role": "compute",
            "clusterRef": {"name": "lab"},
            "os": {"distribution": "debian", "release": "bookworm", "mirror": "https://deb.debian.org/debian", "securityMirror": "https://deb.debian.org/debian-security", "architecture": "amd64", "kernelPackage": "linux-image-6.1.0-51-amd64", "kernelVersion": "6.1.177-1"},
            "storage": {"disk": "/dev/sda", "wipe": True, "bootMode": "bios", "rootFs": "ext4"},
            "agent": {"managementUrl": "https://infraops.example", "registrationToken": "test"},
            "accelerators": {
                "nvidia": {
                    "enabled": True,
                    "repository": "https://packages.example/nvidia",
                    "keyURL": "https://packages.example/nvidia/key.pub",
                    "keySHA256": "a" * 64,
                    "driverPackage": "cuda-drivers",
                    "driverVersion": "550.54.15-1",
                    "toolkitPackage": "nvidia-container-toolkit",
                    "toolkitVersion": "1.17.8-1",
                    "devicePluginImage": "registry.example/plugin@sha256:" + "b" * 64,
                }
            },
        },
    }


class GPUConfigTests(unittest.TestCase):
    def test_generic_disk_image_contains_no_registration_secret(self):
        value = config()
        value["spec"]["agent"] = {"registrationRequired": False}
        kiki_install.validate_config(value)
        with tempfile.TemporaryDirectory() as directory:
            runner = kiki_install.Runner()
            kiki_install.configure_target(runner, value, directory)
            root = Path(directory)
            self.assertTrue((root / "etc/kiki/provisioning-required").exists())
            self.assertFalse((root / "etc/kiki/registration-token").exists())
            node_config = (root / "etc/kiki/node.yaml").read_text()
            self.assertIn("registrationRequired: false", node_config)
    def test_validates_and_renders_pinned_nvidia_configuration(self):
        value = config()
        kiki_install.validate_config(value)
        nvidia = value["spec"]["accelerators"]["nvidia"]
        script = kiki_install.render_nvidia_setup(nvidia)
        self.assertIn("cuda-drivers=550.54.15-1", script)
        self.assertIn("nvidia-container-toolkit=1.17.8-1", script)
        self.assertIn("sha256sum -c -", script)
        self.assertIn("nvidia-ctk runtime configure --runtime=containerd", script)
        self.assertNotIn("curl |", script)

        manifest = kiki_install.render_nvidia_device_plugin(nvidia)
        self.assertIn("registry.example/plugin@sha256:" + "b" * 64, manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("kiki.io/accelerator: nvidia", manifest)

    def test_rejects_mutable_device_plugin_image(self):
        value = config()
        value["spec"]["accelerators"]["nvidia"]["devicePluginImage"] = "registry.example/plugin:latest"
        with self.assertRaisesRegex(kiki_install.InstallerError, "digest pinned"):
            kiki_install.validate_config(value)

    def test_writes_gpu_units_and_manifest(self):
        value = config()
        with tempfile.TemporaryDirectory() as directory:
            runner = kiki_install.Runner()
            kiki_install.configure_accelerators(runner, value["spec"], directory)
            root = Path(directory)
            self.assertTrue((root / "usr/local/sbin/kiki-configure-nvidia").exists())
            unit = (root / "etc/systemd/system/kiki-configure-nvidia.service").read_text()
            self.assertIn("Before=kubelet.service", unit)
            self.assertTrue((root / "etc/kiki/manifests/nvidia-device-plugin.yaml").exists())
            kubelet = (root / "etc/default/kubelet").read_text()
            self.assertIn("kiki.io/accelerator=nvidia", kubelet)
            self.assertIn("kiki.io/runtime-vllm=true", kubelet)


if __name__ == "__main__":
    unittest.main()
