"""Non-network smoke test for optional journal remote/upload binaries."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_JOURNAL_TRANSPORT") == "1",
                     "set KIKI_TEST_JOURNAL_TRANSPORT=1 on Linux")
class JournalTransportRuntimeTests(unittest.TestCase):
    def test_target_abi_and_opt_in_units(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-journal-transport-") as tmp:
            root = Path(tmp) / "root"
            closure = ki2build.dependency_closure(recipes, ["systemd-journal-transport"], "x86_64",
                                                   include_build_deps=False)
            for name in closure:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)

            units = root / "usr/lib/systemd/system"
            self.assertIn("ListenStream=127.0.0.1:19532",
                          (units / "systemd-journal-remote.socket").read_text())
            for name in ("remote", "upload"):
                self.assertTrue((units / f"systemd-journal-{name}.service").is_file())
                self.assertTrue((root / f"usr/lib/systemd/journal-{name}.conf").is_file())
            self.assertTrue((root / "usr/lib/sysusers.d/systemd-remote.conf").is_file())
            self.assertFalse((root / "etc/systemd/system/sockets.target.wants/systemd-journal-remote.socket").exists())
            self.assertFalse((root / "etc/systemd/system/multi-user.target.wants/systemd-journal-upload.service").exists())

            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            dirs = [root / p for p in ("usr/lib/systemd", "usr/lib", "usr/lib64", "lib", "lib64")]
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, dirs))]
            environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LD_BIND_NOW": "1"}
            for name in ("remote", "upload"):
                with self.subTest(name=name):
                    binary = root / f"usr/lib/systemd/systemd-journal-{name}"
                    dynamic = subprocess.run(["readelf", "-d", str(binary)], capture_output=True, text=True, timeout=15)
                    self.assertEqual(dynamic.returncode, 0, dynamic.stderr)
                    self.assertNotRegex(dynamic.stdout, r"RPATH|RUNPATH")
                    listing = subprocess.run(loader + ["--list", str(binary)], env=environment,
                                             capture_output=True, text=True, timeout=15)
                    self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
                    resolved = re.findall(r"^\s*\S+ => (\S+) \(", listing.stdout, re.MULTILINE)
                    self.assertTrue(resolved, listing.stdout)
                    for path in resolved:
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing.stdout)
                    version = subprocess.run(loader + [str(binary), "--version"], env=environment,
                                             capture_output=True, text=True, timeout=15)
                    self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
                    self.assertIn("systemd 255", version.stdout)


if __name__ == "__main__":
    unittest.main()
