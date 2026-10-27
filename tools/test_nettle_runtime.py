"""Opt-in upstream C tests using packaged KIKI Nettle/Hogweed/GMP."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_NETTLE_TEST_SOURCE"),
                     "set KIKI_NETTLE_TEST_SOURCE on Linux")
class NettleRuntimeTests(unittest.TestCase):
    def test_upstream_c_tests(self):
        repo = Path(__file__).resolve().parents[1]
        source = Path(os.environ["KIKI_NETTLE_TEST_SOURCE"]).resolve()
        suite = source / "testsuite"
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "srcdir": str(suite)}
        def run(command, timeout=120):
            result = subprocess.run(command, cwd=suite, env=env, capture_output=True,
                                    text=True, timeout=timeout)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-14000:])
            return result.stdout
        targets = run(["make", "--no-print-directory", "--eval",
                       "ki2-test-list:;@echo $(TS_C)", "ki2-test-list"]).split()
        self.assertGreater(len(targets), 30)
        self.assertTrue(all(re.fullmatch(r"[a-zA-Z0-9_-]+", t) for t in targets))
        run(["make", "-j8"] + targets, timeout=600)
        with tempfile.TemporaryDirectory(prefix="kiki-nettle-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["nettle"], "x86_64",
                                                    include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            for name in ("COPYINGv2", "COPYINGv3", "COPYING.LESSERv3", "AUTHORS"):
                self.assertEqual((root / "usr/share/licenses/nettle" / name).read_bytes(),
                                 (source / name).read_bytes())
            for name in ("libnettle.so.8", "libhogweed.so.6"):
                self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib" / name)]),
                                    r"\((?:RPATH|RUNPATH)\)")
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--inhibit-rpath", "", "--library-path",
                      ":".join(str(root / p) for p in ("usr/lib", "usr/lib64", "lib", "lib64"))]
            observed = set()
            passed = []
            skipped = []
            for target in targets:
                with self.subTest(upstream=target):
                    binary = suite / target
                    self.assertEqual(binary.read_bytes()[:4], b"\x7fELF")
                    listing = run(loader + ["--list", str(binary)])
                    resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
                    self.assertTrue(resolved, listing)
                    observed.update(resolved)
                    for path in resolved.values():
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
                    result = subprocess.run(loader + [str(binary)], cwd=suite, env=env,
                                            capture_output=True, text=True, timeout=120)
                    self.assertIn(result.returncode, (0, 77), result.stdout + result.stderr)
                    (skipped if result.returncode == 77 else passed).append(target)
            self.assertTrue({"libnettle.so.8", "libhogweed.so.6", "libgmp.so.10", "libc.so.6"} <= observed)
            self.assertEqual(len(passed) + len(skipped), len(targets))
            self.assertGreater(len(passed), 0)
            print("KIKI packaged Nettle upstream C tests: "
                  + str(len(passed)) + " passed; skipped: " + repr(skipped), flush=True)


if __name__ == "__main__":
    unittest.main()
