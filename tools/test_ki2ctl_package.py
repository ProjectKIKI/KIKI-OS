"""Run transaction/hook regression suites against the built package's CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import ki2build

@unittest.skipUnless(os.environ.get("KIKI_TEST_KI2CTL_PACKAGE") == "1",
                     "set KIKI_TEST_KI2CTL_PACKAGE=1")
class Ki2CtlPackageTests(unittest.TestCase):
    def test_packaged_cli_transactions_and_hooks(self):
        repo = Path(__file__).resolve().parents[1]
        recipe = ki2build.load_recipes(repo / "distro/recipes")["ki2ctl"]
        package = repo / "dist/ki2/packages/x86_64" / ki2build.package_filename(recipe, "x86_64")
        with tarfile.open(package, "r:gz") as archive:
            manifest = json.load(archive.extractfile("manifest.json"))
            self.assertIn("install-info", manifest["runtime_dependencies"])
            member = archive.getmember("rootfs/usr/bin/ki2ctl")
            self.assertEqual(member.mode, 0o755)
            self.assertEqual((member.uid, member.gid), (0, 0))
            source = archive.extractfile(member).read()
        self.assertEqual(source, (repo / "distro/sources/ki2ctl/usr/bin/ki2ctl").read_bytes())
        with tempfile.TemporaryDirectory(prefix="kiki-packaged-cli-") as tmp:
            script = Path(tmp) / "ki2ctl"
            script.write_bytes(source)
            environment = os.environ.copy()
            environment["KIKI_TEST_KI2CTL_SCRIPT"] = str(script)
            environment["PYTHONPATH"] = str(repo / "tools")
            result = subprocess.run([sys.executable, "-B", "-m", "unittest",
                                     "test_ki2ctl", "test_ki2ctl_hooks", "-v"],
                                    cwd=repo, env=environment, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout + result.stderr)
            print("Packaged CLI tested with host Python; not a booted target-system validation")

if __name__ == "__main__":
    unittest.main()
