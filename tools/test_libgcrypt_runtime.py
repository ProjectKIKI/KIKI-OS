"""Opt-in upstream crypto checks against the packaged KIKI runtime.

Set KIKI_LIBGCRYPT_TEST_SOURCE to the matching configured source directory.
No host library search path or installed host libgcrypt is used.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_LIBGCRYPT_TEST_SOURCE"),
                     "set KIKI_LIBGCRYPT_TEST_SOURCE on Linux")
class LibgcryptRuntimeTests(unittest.TestCase):
    def test_upstream_crypto_with_packaged_runtime(self):
        repo = Path(__file__).resolve().parents[1]
        source = Path(os.environ["KIKI_LIBGCRYPT_TEST_SOURCE"]).resolve()
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        names = ki2build.dependency_closure(recipes, ["libgcrypt"], "x86_64",
                                           include_build_deps=False)
        with tempfile.TemporaryDirectory(prefix="kiki-libgcrypt-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in names:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(command, cwd=None):
                result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                         "GCRYPT_IN_REGRESSION_TEST": "1", "srcdir": str(source / "tests")},
                    timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            for name in ("COPYING", "COPYING.LIB", "LICENSES", "AUTHORS"):
                self.assertEqual((root / "usr/share/licenses/libgcrypt" / name).read_bytes(),
                                 (source / name).read_bytes())
            self.assertFalse((root / "usr/lib/libgcrypt.la").exists())
            self.assertTrue((root / "usr/include/gcrypt.h").is_file())
            self.assertTrue((root / "usr/lib/pkgconfig/libgcrypt.pc").is_file())
            self.assertNotRegex(run(["readelf", "-d", str(root / "usr/lib/libgcrypt.so.20")]),
                                r"\((?:RPATH|RUNPATH)\)")
            directories = [root / p for p in ("usr/lib", "usr/lib64", "lib", "lib64")]
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            # Upstream -no-install test ELFs carry an RPATH to src/.libs.
            # Suppress it, then assert every resolution is in the package root.
            loader = [str(loaders[0]), "--inhibit-cache", "--inhibit-rpath", "", "--library-path",
                      ":".join(map(str, directories))]
            for name in ("version", "basic", "hmac", "t-kdf", "mpitests", "t-sexp", "aeswrap", "keygrip"):
                with self.subTest(upstream=name):
                    binary = source / "tests" / name
                    self.assertEqual(binary.read_bytes()[:4], b"\x7fELF")
                    listing = run(loader + ["--list", str(binary)])
                    resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
                    for library in ("libgcrypt.so.20", "libgpg-error.so.0", "libc.so.6"):
                        self.assertIn(library, resolved)
                    for path in resolved.values():
                        self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
                    run(loader + [str(binary)], cwd=source / "tests")
                    print("KIKI packaged libgcrypt upstream check passed: " + name, flush=True)


if __name__ == "__main__":
    unittest.main()
