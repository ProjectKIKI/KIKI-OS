"""Opt-in host-side ABI smoke test for the experimental Podman KI2.

This does not replace a booted KIKI OS container/Quadlet test.
"""

import os
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_PODMAN") == "1",
                     "set KIKI_TEST_PODMAN=1 on Linux")
class PodmanBootstrapRuntimeTests(unittest.TestCase):
    def test_target_glibc_loader_and_private_libraries(self):
        repo = Path(__file__).resolve().parents[1]
        packages = repo / "dist/ki2/packages/x86_64"
        package = packages / "kiki-podman-bootstrap-5.8.2-5.x86_64.ki2"
        manifest = ki2build.read_package_manifest(package)
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertFalse(any(path.startswith(("/lib64/", "/usr/lib64/")) for path in paths))
        self.assertIn("/usr/lib/kiki-podman/lib/libsqlite3.so.0", paths)
        self.assertFalse(any(int(entry["mode"], 8) & 0o6000 for entry in manifest["files"]))
        self.assertEqual(manifest["dependencies"]["runtime"][:2], ["glibc", "libseccomp"])
        self.assertIn("bash", manifest["dependencies"]["runtime"])
        bash = next(packages.glob("bash-*.x86_64.ki2"))
        bash_paths = {entry["path"] for entry in ki2build.read_package_manifest(bash)["files"]}
        self.assertIn("/usr/bin/bash", bash_paths)
        with tempfile.TemporaryDirectory(prefix="kiki-podman-") as tmp:
            root = Path(tmp) / "root"
            for name in ("glibc-2.39-1", "kiki-podman-bootstrap-5.8.2-5"):
                package = packages / f"{name}.x86_64.ki2"
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)

            loader = root / "lib64/ld-linux-x86-64.so.2"
            binary = root / "usr/libexec/kiki-podman/bin/podman"
            library_dir = root / "usr/lib/kiki-podman/lib"
            self.assertTrue(loader.is_file())
            self.assertTrue(binary.is_file())
            self.assertTrue((root / "usr/lib/systemd/system-generators/podman-system-generator").is_file())
            self.assertTrue((root / "usr/libexec/podman/netavark").is_file())
            self.assertTrue((root / "usr/libexec/podman/aardvark-dns").is_file())
            self.assertTrue((root / "usr/share/licenses/kiki-podman-bootstrap/podman/LICENSE").is_file())
            self.assertTrue((root / "usr/bin/podman").read_text().startswith("#!/usr/bin/bash\n"))
            self.assertTrue((root / "usr/bin/kiki-podman-check").read_text().startswith("#!/usr/bin/bash\n"))
            policy = json.loads((root / "etc/containers/policy.json").read_text())
            self.assertEqual(policy["default"], [{"type": "reject"}])

            args = [str(loader), "--inhibit-cache", "--library-path",
                    f"{library_dir}:{root / 'lib64'}"]
            environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LD_BIND_NOW": "1"}
            listing = subprocess.run(args + ["--list", str(binary)], env=environment,
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            for path in re.findall(r"^\s*\S+ => (\S+) \(", listing.stdout, re.MULTILINE):
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing.stdout)
            version = subprocess.run(args + [str(binary), "--version"], env=environment,
                                     capture_output=True, text=True, timeout=20)
            self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
            self.assertIn("podman version 5.8.2", version.stdout)


if __name__ == "__main__":
    unittest.main()
