"""Opt-in packaged CLI checks; does not discover, pair or modify devices."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_IMOBILE") == "1",
                     "set KIKI_TEST_IMOBILE=1 on Linux")
class MobileRuntimeTests(unittest.TestCase):
    def test_tools_and_gnutls_linkage(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-imobile-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["libimobiledevice"], "x86_64",
                                                    include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command):
                result = subprocess.run(command, env={"PATH":"/usr/bin:/bin", "LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            paths = ":".join(str(root / p) for p in ("usr/lib", "usr/lib64", "lib", "lib64"))
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path", paths]
            library = root / "usr/lib/libimobiledevice-1.0.so.6"
            dynamic = run(["readelf", "-d", str(library)])
            self.assertIn("[libgnutls.so.30]", dynamic)
            self.assertIn("[libgcrypt.so.20]", dynamic)
            self.assertNotRegex(dynamic, r"Shared library: \[lib(?:ssl|crypto)\.")
            self.assertNotRegex(dynamic, r"\((?:RPATH|RUNPATH)\)")
            self.assertFalse((root / "usr/lib/libimobiledevice-1.0.la").exists())
            binaries = sorted((root / "usr/bin").glob("idevice*"))
            self.assertGreaterEqual(len(binaries), 20)
            for binary in binaries:
                with self.subTest(tool=binary.name):
                    self.assertNotRegex(run(["readelf", "-d", str(binary)]), r"\((?:RPATH|RUNPATH)\)")
                    listing = run(loader + ["--list", str(binary)])
                    resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
                    self.assertIn("libimobiledevice-1.0.so.6", resolved)
                    for path in resolved.values():
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
                    self.assertIn("1.4.0", run(loader + [str(binary), "--version"]))
                    self.assertIn("Usage:", run(loader + [str(binary), "--help"]))
            print("KIKI libimobiledevice: %d CLI help/version checks and target-only linkage passed" % len(binaries))

if __name__ == "__main__":
    unittest.main()
