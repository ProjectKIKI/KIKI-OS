"""Opt-in chroot check of packaged p11-kit trust and CA export.

Uses Linux root only to enter a disposable package root; no mounts or network.
"""
import base64
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_P11_TRUST") == "1",
                     "set KIKI_TEST_P11_TRUST=1 as Linux root")
class P11TrustRuntimeTests(unittest.TestCase):
    def test_packaged_ca_module_export(self):
        self.assertEqual(os.geteuid(), 0, "chroot requires Linux root")
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-p11-trust-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["p11-kit"], "x86_64",
                                                    include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            (root / "tmp").mkdir(mode=0o1777, exist_ok=True)
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = "/" + str(loaders[0].relative_to(root))
            def run(args):
                result = subprocess.run(["chroot", str(root), loader, "--inhibit-cache",
                                         "--library-path", "/usr/lib:/usr/lib64:/lib:/lib64"] + args,
                                        env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            def certs(data):
                blocks = re.findall(rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
                                    data, re.DOTALL)
                return {base64.b64decode(re.sub(rb"\s", b"", block), validate=True) for block in blocks}
            original = certs((root / "etc/ssl/certs/ca-certificates.crt").read_bytes())
            self.assertGreater(len(original), 0)
            modules = run(["/usr/bin/p11-kit", "list-modules"])
            self.assertIn("p11-kit-trust", modules)
            listing = run(["/usr/bin/trust", "list", "--filter=ca-anchors"])
            self.assertIn("certificate", listing)
            run(["/usr/bin/trust", "extract", "--format=pem-bundle", "--filter=ca-anchors",
                 "/tmp/exported-ca.pem"])
            exported = certs((root / "tmp/exported-ca.pem").read_bytes())
            self.assertEqual(exported, original)
            print("KIKI p11-kit trust: module discovery and " + str(len(exported))
                  + " CA certificates exported with exact DER set equality", flush=True)

if __name__ == "__main__":
    unittest.main()
