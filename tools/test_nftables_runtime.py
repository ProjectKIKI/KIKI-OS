"""Opt-in nft --version test using only packaged KIKI dependencies."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_NFTABLES_RUNTIME") == "1",
                     "set KIKI_TEST_NFTABLES_RUNTIME=1 after building nftables")
class NftablesRuntimeTests(unittest.TestCase):
    def test_version_resolves_gmp_and_libc_from_target_packages(self):
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-nftables-runtime-") as tmp:
            root = Path(tmp) / "root"
            ordered = ki2build.dependency_closure(recipes, ["nftables"], "x86_64", include_build_deps=False)
            for name in ordered:
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            binary = root / "usr/sbin/nft"
            loader = [str(loaders[0]), "--inhibit-cache", "--library-path",
                      ":".join(str(root / path) for path in ("usr/lib", "usr/lib64", "lib", "lib64"))]

            def run(command):
                result = subprocess.run(command, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            listing = run(loader + ["--list", str(binary)])
            resolved = dict(re.findall(r"^\s*(\S+) => (\S+) \(", listing, re.MULTILINE))
            for library in ("libc.so.6", "libgmp.so.10"):
                self.assertIn(library, resolved, listing)
            for path in resolved.values():
                self.assertTrue(Path(path).resolve().is_relative_to(root), listing)
            # No netlink calls or firewall changes: version output tests runtime linking.
            output = run(loader + [str(binary), "--version"])
            self.assertIn(f"v{recipes['nftables'].version}", output)
            print("KIKI packaged nftables: version and target GMP/libc resolution passed")


if __name__ == "__main__":
    unittest.main()
