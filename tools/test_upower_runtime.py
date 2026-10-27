"""Read-only target ELF smoke test; never start the UPower daemon."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_UPOWER") == "1",
                     "set KIKI_TEST_UPOWER=1 on Linux")
class UPowerRuntimeTests(unittest.TestCase):
    def test_target_linkage_and_service_payload(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-upower-runtime-") as tmp:
            root = Path(tmp) / "root"
            closure = ki2build.dependency_closure(recipes, ["upower"], "x86_64", include_build_deps=False)
            for name in closure:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)

            for relative in (
                "usr/lib/systemd/system/upower.service",
                "usr/share/dbus-1/system-services/org.freedesktop.UPower.service",
                "usr/share/polkit-1/actions/org.freedesktop.upower.policy",
                "usr/share/licenses/upower/COPYING",
            ):
                self.assertTrue((root / relative).is_file(), relative)

            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            library_dirs = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", ":".join(map(str, library_dirs))]
            for relative in ("usr/bin/upower", "usr/libexec/upowerd", "usr/lib/libupower-glib.so.3.1.2"):
                binary = root / relative
                with self.subTest(binary=relative):
                    listing = subprocess.run(loader + ["--list", str(binary)], capture_output=True, text=True, timeout=15)
                    self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
                    resolved = re.findall(r"^\s*\S+ => (\S+) \(", listing.stdout, re.MULTILINE)
                    self.assertTrue(resolved, listing.stdout)
                    for path in resolved:
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing.stdout)
                    dynamic = subprocess.run(["readelf", "-d", str(binary)], capture_output=True, text=True, timeout=15)
                    self.assertEqual(dynamic.returncode, 0, dynamic.stderr)
                    self.assertNotRegex(dynamic.stdout, r"RPATH|RUNPATH")


if __name__ == "__main__":
    unittest.main()
