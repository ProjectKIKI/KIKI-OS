"""Opt-in libtasn1 upstream C checks against packaged KIKI libraries."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_LIBTASN1_TEST_SOURCE"),
                     "set KIKI_LIBTASN1_TEST_SOURCE on Linux")
class Libtasn1RuntimeTests(unittest.TestCase):
    def test_upstream_c_checks(self):
        repo = Path(__file__).resolve().parents[1]
        source = Path(os.environ["KIKI_LIBTASN1_TEST_SOURCE"]).resolve()
        suite = source / "tests"
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        with tempfile.TemporaryDirectory(prefix="kiki-libtasn1-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["libtasn1"], "x86_64",
                                                    include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            for name in ("COPYING", "COPYING.LESSERv2", "README.md"):
                self.assertEqual((root / "usr/share/licenses/libtasn1" / name).read_bytes(),
                                 (source / name).read_bytes())
            self.assertFalse((root / "usr/lib/libtasn1.la").exists())
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--inhibit-rpath", "", "--library-path",
                      ":".join(str(root / p) for p in ("usr/lib", "usr/lib64", "lib", "lib64"))]
            runner = Path(tmp) / "runner.py"
            runner.write_text("ROOT = " + repr(str(root)) + "\nLOADER = " + repr(loader) + "\n" + r"""
import os
from pathlib import Path
import re
import subprocess
import sys
binary = Path(sys.argv[1]).resolve()
if binary.read_bytes()[:4] != b'\x7fELF':
    raise SystemExit('Expected ELF: ' + str(binary))
env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
env.update({k:v for k,v in os.environ.items() if k.startswith('ASN1') or k == 'srcdir'})
listing = subprocess.check_output(LOADER + ['--list', str(binary)], env=env, text=True)
resolved = dict(re.findall(r'^\s*(\S+) => (\S+) \(', listing, re.MULTILINE))
if 'libtasn1.so.6' not in resolved or any(not Path(p).resolve().is_relative_to(ROOT) for p in resolved.values()):
    raise SystemExit('Non-package dependency: ' + listing)
os.execve(LOADER[0], LOADER + [str(binary)] + sys.argv[2:], env)
""")
            # Generate upstream fixture headers using the packaged CLI, not host execution.
            for number in (1, 2):
                name = "CVE-2018-1000654-" + str(number)
                result = subprocess.run(["python3", str(runner), str(root / "usr/bin/asn1Parser"),
                                         str(suite / (name + ".asn")), "-o",
                                         str(suite / (name + "_asn1_tab.h"))],
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run(["make", "-C", str(suite), "-j8", "check",
                                     "TESTS=$(ctests)", "LOG_COMPILER=python3 " + str(runner)],
                                    env=env, capture_output=True, text=True, timeout=600)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-14000:])
            summary = re.findall(r"^# (TOTAL|PASS|SKIP|FAIL|ERROR):\s*(\d+)", result.stdout, re.MULTILINE)
            self.assertTrue(summary, result.stdout[-4000:])
            counts = dict((k, int(v)) for k,v in summary)
            self.assertGreater(counts.get("PASS", 0), 0)
            self.assertEqual(counts.get("FAIL", 0) + counts.get("ERROR", 0), 0)
            print("KIKI libtasn1 upstream C summary: " + repr(counts), flush=True)


if __name__ == "__main__":
    unittest.main()
