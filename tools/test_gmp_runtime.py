"""Run GMP's configured upstream make check with packaged KIKI libraries."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import ki2build


@unittest.skipUnless(sys.platform == "linux" and os.environ.get("KIKI_GMP_TEST_SOURCE"),
                     "set KIKI_GMP_TEST_SOURCE on Linux")
class GmpRuntimeTests(unittest.TestCase):
    def test_upstream_make_check(self):
        repo = Path(__file__).resolve().parents[1]
        source = Path(os.environ["KIKI_GMP_TEST_SOURCE"]).resolve()
        self.assertTrue((source / "Makefile").is_file())
        recipes = ki2build.load_recipes(repo / "distro/recipes")
        with tempfile.TemporaryDirectory(prefix="kiki-gmp-runtime-") as tmp:
            root = Path(tmp) / "root"
            for name in ki2build.dependency_closure(recipes, ["gmp"], "x86_64",
                                                    include_build_deps=False):
                package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipes[name], "x86_64")
                self.assertTrue(package.is_file(), str(package))
                ki2build.extract_package_rootfs(package, root)
            self.assertFalse((root / "usr/lib/libgmp.la").exists())
            for name in ("COPYING", "COPYING.LESSERv3", "COPYINGv2"):
                self.assertEqual((root / "usr/share/licenses/gmp" / name).read_bytes(),
                                 (source / name).read_bytes())
            dynamic = subprocess.check_output(["readelf", "-d", str(root / "usr/lib/libgmp.so.10")],
                                              text=True)
            self.assertNotRegex(dynamic, r"\((?:RPATH|RUNPATH)\)")
            loaders = [p for p in root.rglob("ld-linux-x86-64.so.2") if p.is_file() and not p.is_symlink()]
            self.assertEqual(len(loaders), 1)
            loader = [str(loaders[0]), "--inhibit-cache", "--inhibit-rpath", "", "--library-path",
                      ":".join(str(root / p) for p in ("usr/lib", "usr/lib64", "lib", "lib64"))]
            runner = Path(tmp) / "runner.py"
            # Automake invokes this for each test; reject host paths before running.
            runner.write_text("ROOT = " + repr(str(root)) + "\nLOADER = " + repr(loader) + "\n" + r"""
import os
from pathlib import Path
import re
import subprocess
import sys
binary = Path(sys.argv[1]).resolve()
if binary.read_bytes()[:4] != b'\x7fELF':
    raise SystemExit('Expected upstream ELF test: ' + str(binary))
env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}
listing = subprocess.check_output(LOADER + ['--list', str(binary)], env=env, text=True)
resolved = re.findall(r'^\s*\S+ => (\S+) \(', listing, re.MULTILINE)
if not resolved or any(not Path(p).resolve().is_relative_to(ROOT) for p in resolved):
    raise SystemExit('Non-package dependency: ' + listing)
os.execve(LOADER[0], LOADER + [str(binary)] + sys.argv[2:], env)
""")
            result = subprocess.run(["make", "-C", str(source), "-j8", "check",
                                     "LOG_COMPILER=python3 " + str(runner)],
                                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                    capture_output=True, text=True, timeout=1200)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-18000:])
            totals = re.findall(r"^# (TOTAL|PASS|SKIP|FAIL|ERROR):\s*(\d+)", result.stdout, re.MULTILINE)
            self.assertTrue(totals, result.stdout[-4000:])
            counts = {}
            for label, count in totals:
                counts[label] = counts.get(label, 0) + int(count)
            self.assertGreater(counts.get("PASS", 0), 0)
            self.assertEqual(counts.get("FAIL", 0) + counts.get("ERROR", 0), 0)
            print("GMP upstream make check summaries: " + json.dumps(counts), flush=True)


if __name__ == "__main__":
    unittest.main()
