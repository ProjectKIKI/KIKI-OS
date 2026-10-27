"""Root-only disposable chroot Info index test; no mounts or host changes."""
import bz2
import gzip
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import ki2build

@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_TEST_INSTALL_INFO") == "1",
                     "set KIKI_TEST_INSTALL_INFO=1 as Linux root")
class InstallInfoRuntimeTests(unittest.TestCase):
    def test_plain_and_compressed_manuals(self):
        self.assertEqual(os.geteuid(), 0)
        repo = Path(__file__).resolve().parents[1]
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-install-info-runtime-") as tmp:
            root = Path(tmp) / "root"
            # Runtime closure must supply /bin/sh and bzip2 without test extras.
            for name in ki2build.dependency_closure(recipes, ["install-info"],
                                                   "x86_64", include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            def run(arguments):
                result = subprocess.run(["chroot", str(root)] + arguments,
                                        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"},
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout
            # gnulib opens /dev/null while sanitizing standard descriptors.
            # An empty fixture file is sufficient for these captured-I/O cases;
            # do not mount host /dev or create device nodes.
            (root / "dev").mkdir(exist_ok=True)
            (root / "dev/null").write_bytes(b"")
            run(["/sbin/ldconfig", "/usr/lib", "/usr/lib64", "/lib", "/lib64"])
            self.assertIn("7.2", run(["/usr/bin/install-info", "--version"]))
            docs = root / "usr/share/info"
            docs.mkdir(parents=True, exist_ok=True)
            index = docs / "dir"
            for name, suffix, compress in (("plain", "", lambda x: x), ("gzip", ".gz", gzip.compress),
                                            ("xz", ".xz", lzma.compress), ("bzip", ".bz2", bz2.compress)):
                content = ("INFO-DIR-SECTION Runtime test\nSTART-INFO-DIR-ENTRY\n"
                           f"* {name}: ({name}). Test manual.\nEND-INFO-DIR-ENTRY\n"
                           f"\x1f\nFile: {name}.info, Node: Top\nTest.\n").encode()
                filename = name + ".info" + suffix
                (docs / filename).write_bytes(compress(content))
                run(["/usr/bin/install-info", "/usr/share/info/" + filename, "/usr/share/info/dir"])
                self.assertIn("* " + name + ":", index.read_text())
            before = index.read_bytes()
            run(["/usr/bin/install-info", "/usr/share/info/plain.info", "/usr/share/info/dir"])
            self.assertEqual(index.read_bytes(), before)
            run(["/usr/bin/install-info", "--delete", "/usr/share/info/gzip.info.gz", "/usr/share/info/dir"])
            self.assertNotIn("* gzip:", index.read_text())
            for name in ("plain", "xz", "bzip"):
                self.assertIn("* " + name + ":", index.read_text())
            print("KIKI install-info: plain/gzip/xz/bzip2 insert, idempotence and compressed deletion passed")

if __name__ == "__main__":
    unittest.main()
